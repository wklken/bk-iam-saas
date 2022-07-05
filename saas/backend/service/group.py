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
from typing import List, Tuple

from django.db import transaction
from django.db.models import F
from pydantic import BaseModel, parse_obj_as

from backend.apps.group.models import Group
from backend.apps.organization.models import Department, DepartmentMember, User
from backend.component import iam

from .constants import SubjectType
from .models import Subject


class SubjectGroup(BaseModel):
    """
    后端返回的Subject的Group
    """

    type: str
    id: str
    policy_expired_at: int
    created_at: str  # 后端json返回的格式化时间

    # 从部门继承的信息
    department_id: int = 0
    department_name: str = ""


class GroupCreate(BaseModel):
    name: str
    description: str


class GroupMemberExpiredAt(Subject):
    policy_expired_at: int


class GroupService:
    def create(self, name: str, description: str, creator: str) -> Group:
        """
        创建用户组
        """
        group = Group(name=name, description=description, creator=creator)
        group.save(force_insert=True)

        # 创建后端的用户组
        iam.create_subjects([{"type": SubjectType.GROUP.value, "id": str(group.id), "name": name}])

        return group

    def batch_create(self, infos: List[GroupCreate], creator: str) -> List[Group]:
        """
        批量创建用户组
        """
        groups = [Group(name=one.name, description=one.description, creator=creator) for one in infos]
        with transaction.atomic():
            # 为了获取返回的insert id, 不能使用bulk_create
            for group in groups:
                group.save()
            iam.create_subjects([{"type": SubjectType.GROUP.value, "id": str(g.id), "name": g.name} for g in groups])

        return groups

    def update(self, group: Group, name: str, description: str, updater: str) -> Group:
        """
        更新用户组信息
        """
        group.name = name
        group.description = description
        group.updater = updater

        with transaction.atomic():
            group.save()
            iam.update_subjects([{"type": SubjectType.GROUP.value, "id": str(group.id), "name": name}])

        return group

    def delete(self, group_id: int):
        """
        删除用户组
        """
        Group.objects.filter(id=group_id).delete()
        iam.delete_subjects([{"type": SubjectType.GROUP.value, "id": str(group_id)}])

    def add_members(self, group_id: int, members: List[Subject], expired_at: int):
        """
        用户组添加成员
        """
        type_count = iam.add_subject_members(
            SubjectType.GROUP.value, str(group_id), expired_at, [m.dict() for m in members]
        )
        Group.objects.filter(id=group_id).update(
            user_count=F("user_count") + type_count[SubjectType.USER.value],
            department_count=F("department_count") + type_count[SubjectType.DEPARTMENT.value],
        )

    def remove_members(self, group_id: str, subjects: List[Subject]):
        """
        用户组删除成员
        """
        type_count = iam.delete_subject_members(SubjectType.GROUP.value, group_id, [one.dict() for one in subjects])
        Group.objects.filter(id=group_id).update(
            user_count=F("user_count") - type_count[SubjectType.USER.value],
            department_count=F("department_count") - type_count[SubjectType.DEPARTMENT.value],
        )

    def list_subject_group(self, subject: Subject, is_recursive: bool = False) -> List[SubjectGroup]:
        """
        查询Subject的Group关系列表

        is_recursive: 是否递归查找user的部门所属的Group
        """
        iam_data = iam.get_subject_relation(subject.type, subject.id)
        relations = parse_obj_as(List[SubjectGroup], iam_data)

        if subject.type == SubjectType.USER.value and is_recursive:
            # 查询用户有的部门
            dep_relations = self._list_user_department_group(subject.id)
            relations.extend(dep_relations)

        return relations

    def _list_user_department_group(self, user_id: str) -> List[SubjectGroup]:
        """
        查询user的部门递归的Group
        """
        relations = []
        user = User.objects.get(username=user_id)
        # 查询用户直接加入的部门
        department_ids = DepartmentMember.objects.filter(user_id=user.id).values_list("department_id", flat=True)
        department_set = set()
        for department in Department.objects.filter(id__in=department_ids):
            # 查询部门继承的所有部门
            for ancestor in department.get_ancestors(include_self=True):
                if ancestor.id in department_set:
                    continue
                department_set.add(ancestor.id)
                iam_data = iam.get_subject_relation("department", str(ancestor.id))
                dep_relations = [
                    SubjectGroup(department_id=ancestor.id, department_name=ancestor.name, **one) for one in iam_data
                ]
                relations.extend(dep_relations)
        return relations

    def list_subject_group_before_expired_at(self, subject: Subject, expired_at: int) -> List[SubjectGroup]:
        """
        查询subject在指定过期时间之前的相关Group
        """
        iam_data = iam.get_subject_relation(subject.type, subject.id, expired_at=expired_at)
        relations = parse_obj_as(List[SubjectGroup], iam_data)
        return relations

    def get_member_count_before_expired_at(self, group_id: int, expired_at: int) -> int:
        """
        获取过期的成员数量
        """
        data = iam.list_subject_member_before_expired_at(SubjectType.GROUP.value, str(group_id), expired_at, 0, 0)
        return data["count"]

    def list_paging_members_before_expired_at(
        self, group_id: int, expired_at: int, limit: int = 10, offset: int = 0
    ) -> Tuple[int, List[SubjectGroup]]:
        """
        分页查询用户组过期的成员
        """
        data = iam.list_subject_member_before_expired_at(
            SubjectType.GROUP.value, str(group_id), expired_at, limit, offset
        )
        return data["count"], parse_obj_as(List[SubjectGroup], data["results"])

    def list_exist_groups_before_expired_at(self, group_ids: List[int], expired_at: int) -> List[int]:
        """
        筛选出存在的即将过期的用户组id
        """
        subjects = [{"type": SubjectType.GROUP.value, "id": str(_id)} for _id in group_ids]

        exist_group_ids = []
        for i in range(0, len(subjects), 500):
            part_subjects = subjects[i : i + 500]
            data = iam.list_exist_subjects_before_expired_at(part_subjects, expired_at)
            exist_group_ids.extend([int(m["id"]) for m in data])

        return exist_group_ids

    def update_subject_groups_expired_at(self, subject_expired_at: GroupMemberExpiredAt, group_ids: List[int]):
        """
        subject group 续期
        """
        for group_id in group_ids:
            iam.update_subject_members_expired_at(
                SubjectType.GROUP.value,
                str(group_id),
                [subject_expired_at.dict()],
            )

    def update_members_expired_at(self, group_id: int, members: List[GroupMemberExpiredAt]):
        """
        更新用户组成员的过期时间
        """
        iam.update_subject_members_expired_at(
            SubjectType.GROUP.value,
            str(group_id),
            [one.dict() for one in members],
        )

    def list_paging_group_member(self, group_id: int, limit: int, offset: int) -> Tuple[int, List[SubjectGroup]]:
        """分页查询用户组成员"""
        data = iam.list_subject_member(SubjectType.GROUP.value, str(group_id), limit, offset)
        return data["count"], parse_obj_as(List[SubjectGroup], data["results"])
