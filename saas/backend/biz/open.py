# -*- coding: utf-8 -*-
from typing import Dict, List

from django.core.cache import cache
from django.utils.translation import gettext as _
from pydantic.tools import parse_obj_as

from backend.common.error_codes import error_codes
from backend.util.uuid import gen_uuid

from .policy import PolicyBean, PolicyBeanList


# TODO: 后续继承backend.utils里的cache基本模块，避免cache的前缀乱用，整个项目的cache需要统一重构，命名等统一规范
# TODO: [重构]key namespace bk_iam需要在统一的地方维护; 并且, 可能需要带上版本号(可能存在不能向前兼容的情况)
class ApplicationPolicyListCache:
    """接入系统操作申请缓存：用于是临时缓存无权限跳转申请内容"""

    timeout = 10 * 60  # 十分钟
    key_prefix = "bk_iam:application"

    def _gen_key(self, cache_id: str) -> str:
        return f"{self.key_prefix}:{cache_id}"

    def _get(self, cache_id: str) -> Dict:
        key = self._gen_key(cache_id)
        return cache.get(key)

    def _set(self, cache_id: str, data: Dict):
        key = self._gen_key(cache_id)
        return cache.set(key, data, timeout=self.timeout)

    def get(self, cache_id: str) -> PolicyBeanList:
        """获取缓存里申请的策略"""
        data = self._get(cache_id)
        if data is None:
            raise error_codes.INVALID_ARGS.format(_("申请数据已过期或不存在"))

        system_id, policies = data["system_id"], data["policies"]

        return PolicyBeanList(system_id=system_id, policies=parse_obj_as(List[PolicyBean], policies))

    def set(self, policy_list: PolicyBeanList) -> str:
        """缓存申请的策略"""
        # 生成唯一的缓存ID
        cache_id = gen_uuid()
        # 转为Dict进行缓存
        data = {"system_id": policy_list.system_id, "policies": [p.dict() for p in policy_list.policies]}
        # 设置缓存
        self._set(cache_id, data)

        return cache_id
