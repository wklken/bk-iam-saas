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
from typing import List, Optional

from backend.component import iam
from backend.component.iam import get_system
from backend.util.cache import region

from .models import System


class SystemList:
    def __init__(self, systems: List[System]) -> None:
        self.systems = systems
        self._system_dict = {one.id: one for one in systems}

    def get(self, system_id: str) -> Optional[System]:
        return self._system_dict.get(system_id, None)


class SystemService:
    def list(self) -> List[System]:
        """获取所有系统"""
        systems = iam.list_system()
        # 组装为返回结构
        return [System(**i) for i in systems]

    def get(self, system_id: str) -> System:
        system = iam.get_system(system_id)
        return System(**system)

    @region.cache_on_arguments(expiration_time=5 * 60)  # 5分钟过期
    def list_client(self, system_id: str) -> List[str]:
        """
        查询可访问系统的clients
        """
        system = iam.get_system(system_id, fields="clients")
        return system["clients"].split(",")

    def new_system_list(self) -> SystemList:
        return SystemList(self.list())

    def get_system_name(self, system_id: str) -> str:
        """
        根据系统ID获取系统名称
        """
        system_name = get_system(system_id)["name"]
        return system_name
