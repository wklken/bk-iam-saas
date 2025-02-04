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
import time

from django.utils.translation import gettext as _
from drf_yasg.openapi import Response as yasg_response
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from backend.apps.role.models import RoleUser
from backend.biz.role import RoleBiz
from backend.common.error_codes import error_codes
from backend.common.swagger import ResponseSwaggerAutoSchema

from .role_auth import ROLE_SESSION_KEY
from .serializers import AccountRoleSLZ, AccountRoleSwitchSLZ, AccountUserSLZ


class UserViewSet(GenericViewSet):
    @swagger_auto_schema(
        operation_description="用户信息",
        auto_schema=ResponseSwaggerAutoSchema,
        responses={status.HTTP_200_OK: AccountUserSLZ(label="用户信息")},
        tags=["account"],
    )
    def retrieve(self, request, *args, **kwargs):
        user = request.user
        role = request.role
        timestamp = int(time.time())
        return Response(
            {
                "timestamp": timestamp,
                "username": user.username,
                "role": {"type": role.type, "id": role.id, "name": role.name},
            }
        )


class RoleViewSet(GenericViewSet):

    paginator = None  # 去掉swagger中的limit offset参数

    role_biz = RoleBiz()

    @swagger_auto_schema(
        operation_description="用户角色列表",
        auto_schema=ResponseSwaggerAutoSchema,
        responses={status.HTTP_200_OK: AccountRoleSLZ(label="角色信息", many=True)},
        tags=["account"],
    )
    def list(self, request, *args, **kwargs):
        data = self.role_biz.list_user_role(request.user.username)
        return Response([one.dict() for one in data])

    @swagger_auto_schema(
        operation_description="用户角色切换",
        request_body=AccountRoleSwitchSLZ(label="角色切换"),
        auto_schema=ResponseSwaggerAutoSchema,
        responses={status.HTTP_200_OK: yasg_response({})},
        tags=["account"],
    )
    def create(self, request, *args, **kwargs):
        serializer = AccountRoleSwitchSLZ(data=request.data)
        serializer.is_valid(raise_exception=True)
        role_id = serializer.validated_data["id"]

        # 切换为管理员时, 如果不存在对应的关系, 越权
        if role_id != 0 and not RoleUser.objects.user_role_exists(request.user.username, role_id):
            raise error_codes.FORBIDDEN.format(_("您没有该角色权限，无法切换到该角色"), True)

        # 修改session
        request.session[ROLE_SESSION_KEY] = role_id

        return Response({})
