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
from rest_framework import serializers

from backend.apps.group.constants import SubjectRelationType
from backend.common.time import PERMANENT_SECONDS


class UserRelationSLZ(serializers.Serializer):
    type = serializers.ChoiceField(label="类型", choices=SubjectRelationType.get_choices())
    id = serializers.CharField(label="id")


class SubjectGroupSLZ(serializers.Serializer):
    id = serializers.CharField(label="用户组ID")
    name = serializers.CharField(label="用户组名称")
    expired_at = serializers.IntegerField(label="过期时间", max_value=PERMANENT_SECONDS)
    expired_at_display = serializers.CharField(label="过期时间显示")
    created_time = serializers.CharField(label="加入时间")
    description = serializers.CharField(label="描述", allow_blank=True)
    department_id = serializers.IntegerField(label="部门ID", help_text="0则为个人，其他为继承的部门ID")
    department_name = serializers.CharField(label="部门名称")


class SubjectDepartmentSLZ(serializers.Serializer):
    id = serializers.CharField(label="部门ID")
    name = serializers.CharField(label="部门名称")
    full_name = serializers.CharField(label="部门路径名称")
