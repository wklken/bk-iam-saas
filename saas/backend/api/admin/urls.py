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
from django.urls import path

from backend.apps.system.views import SystemViewSet

from . import views

urlpatterns = [
    # 用户组
    path("groups/", views.AdminGroupViewSet.as_view({"get": "list"}), name="open.admin.group"),
    # 用户组成员
    path(
        "groups/<int:id>/members/",
        views.AdminGroupMemberViewSet.as_view({"get": "list"}),
        name="open.admin.group_member",
    ),
    # Subject
    path(
        "subjects/<str:subject_type>/<str:subject_id>/groups/",
        views.AdminSubjectGroupViewSet.as_view({"get": "list"}),
        name="open.admin.subject_group",
    ),
    # 系统列表 list(不分页, 或者分页, page_size不传默认100?)
    path(
        "systems/",
        SystemViewSet.as_view({"get": "list"}),
        name="open.admin.system",
    ),
    # 超级管理员成员列表  get
    path(
        "roles/super_managers/members/",
        views.SuperManagerMemberViewSet.as_view({"get": "retrieve"}),
        name="open.admin.super_manager.members",
    ),
    # 系统管理员成员列表 get
    path(
        "roles/system_managers/systems/<slug:system_id>/members/",
        views.SystemManagerMemberViewSet.as_view({"get": "retrieve"}),
        name="open.admin.system_manager.members",
    ),
    # 用户的角色列表, list分页 (可以filter=super/system/grade来过滤是否分级管理员)
    path(
        "subjects/<str:subject_type>/<str:subject_id>/roles/",
        views.SubjectRoleViewSet.as_view({"get": "list"}),
        name="open.admin.subject.roles",
    ),
    # TODO: 冻结, 解冻接口
]
