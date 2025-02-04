# -*- coding: utf-8 -*-
"""
TencentBlueKing is pleased to support the open source community by making 蓝鲸智云-权限中心(BlueKing-IAM) available.
Copyright (C) 2017-2021 THL A29 Limited, a Tencent company. All rights reserved.
Licensed under the MIT License (the "License"); you may not use this file except in compliance with the License.
You may obtain a copy of the License at http://opensource.org/licenses/MIT
Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.
"""
import json
import logging
import re
import traceback
from abc import ABCMeta, abstractmethod
from copy import deepcopy
from typing import Any, Dict, List

from aenum import LowerStrEnum, auto
from django.conf import settings
from django.core.cache import DEFAULT_CACHE_ALIAS
from django.utils import timezone
from django_redis import get_redis_connection

from backend.common.local import Singleton, get_local
from backend.util.json import json_dumps

__all__ = ["RedisStorage", "http_trace", "log_api_error_trace", "log_task_error_trace"]

logger = logging.getLogger("app")


class TraceType(LowerStrEnum):
    HTTP = auto()
    API = auto()
    TASK = auto()


class DebugStack:
    key = "debug_stack"

    def push(self, item):
        local = get_local()
        if not hasattr(local, self.key):
            setattr(local, self.key, [])

        getattr(local, self.key).append(item)

    def pop_all(self):
        local = get_local()
        items = getattr(local, self.key, [])
        setattr(local, self.key, [])
        return items


stack = DebugStack()


def http_trace(**kwargs):
    info = {"type": TraceType.HTTP.value}
    info.update(kwargs)
    try:
        stack.push(info)
    except IndexError:
        pass


class DebugObserver(metaclass=ABCMeta):
    @abstractmethod
    def update(self, data: Dict[str, Any]):
        pass


class DebugReceiver(Singleton):
    """
    调试信息
    """

    def __init__(self):
        # 观察者模式
        self._observers: List[DebugObserver] = [RedisObserver()]
        self._cleaner = SensitiveCleaner()

    def register(self, ob):
        self._observers.append(ob)

    def remove(self, ob):
        self._observers.remove(ob)

    def notify(self, data: Dict[str, Any]):
        for ob in self._observers:
            try:
                ob.update(data)
            except Exception:  # pylint: disable=broad-except
                logger.exception(f"{ob.__class__.__name__} debug update fail")


class RedisObserver(DebugObserver):
    def __init__(self) -> None:
        self.storage = RedisStorage()

    def update(self, data: Dict[str, Any]):
        _type = data["type"]
        if _type == TraceType.API.value:
            self.storage.set_api_data(data)
        elif _type == TraceType.TASK.value:
            self.storage.set_task_data(data)


class RedisStorage:
    ttl = settings.MAX_DEBUG_TRACE_TTL
    queue_key = "iam:debug:queue"
    queue_size = settings.MAX_DEBUG_TRACE_COUNT

    def __init__(self) -> None:
        self.cli = get_redis_connection(DEFAULT_CACHE_ALIAS)
        self.cleaner = SensitiveCleaner()

    def get(self, key):
        value = self.cli.get(self._gen_redis_key(key))
        return json.loads(value) if value else value

    def list_task_debug(self, day):
        task_key = f"iam:debug:task:{day}"
        keys = self.cli.lrange(task_key, 0, -1)

        if not keys:
            return []

        with self.cli.pipeline(transaction=False) as pipe:
            for raw_key in keys:
                pipe.get(self._gen_redis_key(str(raw_key, encoding="utf-8")))
            results = pipe.execute()

        return [json.loads(one) for one in results if one]

    def set_api_data(self, data: Dict[str, Any]):
        self._set(data)

    def set_task_data(self, data: Dict[str, Any]):
        self._set(data)

        # 如果是task产生的数据, 建立时间的索引
        self._append_task(data["id"])

    def _set(self, data):
        key = data["id"]
        clean_data = self.cleaner.clean(data)
        self.cli.set(self._gen_redis_key(key), json_dumps(clean_data), ex=self.ttl)

        # 保持队列长度
        self._fixed_size(key)

    def _gen_redis_key(self, key):
        return f"iam:debug:{key}"

    def _gen_task_key(self):
        day = timezone.now().strftime("%Y%m%d")
        return f"iam:debug:task:{day}"

    def _fixed_size(self, key):
        """
        保持定长队列长度
        """
        cnt = self.cli.lpush(self.queue_key, key)
        if cnt <= self.queue_size:
            return

        # 保持队列长度, 删除多余的key
        with self.cli.pipeline() as pipe:
            pipe.lrange(self.queue_key, self.queue_size, -1)
            pipe.ltrim(self.queue_key, 0, self.queue_size - 1)
            del_keys = pipe.execute()[0]

        if not del_keys:
            return

        with self.cli.pipeline(transaction=False) as pipe:
            for raw_key in del_keys:
                pipe.delete(self._gen_redis_key(str(raw_key, encoding="utf-8")))
            pipe.execute()

    def _append_task(self, _id):
        key = self._gen_task_key()
        self.cli.lpush(key, _id)
        self.cli.expire(key, self.ttl)


class SensitiveCleaner:
    """
    处理敏感信息
    """

    ip_pattern = re.compile(r"(?<![\.\d])(?:\d{1,3}\.){3}\d{1,3}(?![\.\d])")

    def __init__(self):
        self.sensitive_keys = ["app_secret"]
        self.sensitive_key_func = {"url": lambda value: re.sub(self.ip_pattern, "ip", value)}

    def clean(self, data: Dict[str, Any]) -> Dict[str, Any]:
        data = deepcopy(data)
        self._clean(data)
        return data

    def _clean(self, data: Dict[str, Any]):
        for key in data.keys():
            value = data[key]

            if isinstance(value, dict):
                self._clean(value)
            elif isinstance(value, list):
                for one in value:
                    if isinstance(one, dict):
                        self._clean(one)
            elif isinstance(value, str):
                for sk in self.sensitive_keys:
                    if key.endswith(sk):
                        data[key] = "***"

                if key in self.sensitive_key_func:
                    data[key] = self.sensitive_key_func[key](value)


receiver = DebugReceiver()


def log_api_error_trace(request, force=False):
    """
    记录api的错误跟踪信息
    """
    chain = stack.pop_all()
    if chain or force:
        data = {
            "id": request.request_id,
            "type": TraceType.API.value,
            "path": request.path,
            "method": request.method,
            "data": getattr(request, request.method, None),
            "exc": traceback.format_exc(),
            "stack": chain,
        }
        receiver.notify(data)


def log_task_error_trace(task, force=False):
    """
    记录task的错误跟踪信息
    """
    chain = stack.pop_all()
    if chain or force:
        data = {
            "id": task.request.id,
            "type": TraceType.TASK.value,
            "name": task.name,
            "exc": traceback.format_exc(),
            "stack": chain,
        }
        receiver.notify(data)
