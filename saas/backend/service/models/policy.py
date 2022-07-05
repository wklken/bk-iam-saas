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
from collections import namedtuple
from typing import Any, Dict, List, Optional, Tuple, Type, Union

from pydantic import BaseModel, Field

from backend.apps.policy.models import Policy as PolicyModel
from backend.apps.temporary_policy.models import TemporaryPolicy
from backend.common.time import PERMANENT_SECONDS
from backend.service.constants import ANY_ID, DEAULT_RESOURCE_GROUP_ID, AbacPolicyChangeType, AuthTypeEnum
from backend.service.utils.translate import ResourceExpressionTranslator
from backend.util.model import ListModel
from backend.util.uuid import gen_uuid

from .action import Action, InstanceSelection
from .instance_selection import PathResourceType
from .subject import Subject


class PathNode(BaseModel):
    id: str
    name: str
    system_id: str = ""  # NOTE 兼容一下, 早期的policy数据中可能没有system_id
    type: str

    def __hash__(self):
        return hash((self.system_id, self.type, self.id))

    def __eq__(self, other):
        return self.system_id == other.system_id and self.type == other.type and self.id == other.id

    def to_path_resource_type(self) -> PathResourceType:
        return PathResourceType(system_id=self.system_id, id=self.type)

    def match_resource_type(self, resource_system_id: str, resource_type_id: str) -> bool:
        """
        是否匹配资源类型
        """
        return self.system_id == resource_system_id and self.type == resource_type_id


class PathNodeList(ListModel):
    __root__: List[PathNode]

    def match_selection(self, resource_system_id: str, resource_type_id: str, selection: InstanceSelection) -> bool:
        """
        检查是否匹配实例视图
        """
        # 链路只有一层, 并且与资源类型匹配
        if len(self.__root__) == 1 and self.__root__[0].match_resource_type(resource_system_id, resource_type_id):
            return True

        return selection.match_path(self._to_path_resource_types())

    def _to_path_resource_types(self) -> List[PathResourceType]:
        return [one.to_path_resource_type() for one in self.__root__]

    def ignore_path(self, selection: InstanceSelection) -> "PathNodeList":
        """
        根据实例视图, 返回忽略路径后的链路
        """
        if (
            selection.ignore_iam_path
            and len(self.__root__) == len(selection.resource_type_chain)
            and self.__root__[-1].id != ANY_ID
        ):
            return PathNodeList(__root__=[self.__root__[-1]])

        return self

    def get_last_node_without_any(self):
        """获取路径里最后一个非任意的节点"""
        if len(self.__root__) >= 2 and self.__root__[-1].id == ANY_ID:
            return self.__root__[-2]

        assert len(self.__root__) >= 1
        assert self.__root__[-1].id != ANY_ID

        return self.__root__[-1]

    def is_all_ignore_path_of_matched_selection(self) -> bool:
        """所有匹配到的实例视图是否都为忽略路径"""
        # FIXME: 对每条路径都进行实例视图匹配，只有所有匹配到的实例视图都是忽略路径的，则可转换为ABAC策略
        # NOTE: 第一期由于限制了当Action的AuthType为rbac时，其所有实例视图只能是ignore_path=True，
        # 所以这里可以直接认为只能是RBAC策略，暂时不进行实例视图匹配的分析
        return True


class Instance(BaseModel):
    type: str
    path: List[PathNodeList]

    def ignore_path(self, resource_system_id: str, resource_type_id: str, selections: List[InstanceSelection]):
        """
        检查实例视图
        """
        for i in range(len(self.path)):
            node_list = self.path[i]
            for selection in selections:
                if node_list.match_selection(resource_system_id, resource_type_id, selection):
                    self.path[i] = node_list.ignore_path(selection)
                    break


class Value(BaseModel):
    id: Any
    name: str


class Attribute(BaseModel):
    id: str
    name: str
    values: List[Value]

    def sort_values(self):
        self.values.sort(key=lambda value: value.id)

    def trim(self) -> Tuple:
        return self.id, tuple([value.id for value in self.values])


class Condition(BaseModel):
    instances: List[Instance]
    attributes: List[Attribute]
    id: str

    def __init__(self, **data: Any) -> None:
        if "id" not in data:
            data["id"] = gen_uuid()
        super().__init__(**data)

    def sort_attributes(self):
        for a in self.attributes:
            a.sort_values()
        self.attributes.sort(key=lambda attribute: attribute.id)

    def hash_attributes(self):
        self.sort_attributes()
        return hash(tuple([attribute.trim() for attribute in self.attributes]))

    def has_no_attributes(self) -> bool:
        return len(self.attributes) == 0

    def has_no_instances(self) -> bool:
        return len(self.instances) == 0


class RelatedResource(BaseModel):
    system_id: str
    type: str
    condition: List[Condition]

    def ignore_path(self, selections: List[InstanceSelection]):
        """
        校验条件中的实例拓扑是否满足实例视图
        """
        for c in self.condition:
            if c.has_no_instances():
                continue

            for instance in c.instances:
                instance.ignore_path(self.system_id, self.type, selections)


class EnvValue(BaseModel):
    name: str = ""
    value: Any


class EnvCondition(BaseModel):
    type: str
    values: List[EnvValue]

    def trim_for_hash(self) -> Tuple[str, Any]:
        return self.type, tuple(sorted([v.value for v in self.values]))


class Environment(BaseModel):
    type: str
    condition: List[EnvCondition]

    def trim_for_hash(self) -> Tuple[str, Any]:
        return self.type, tuple(sorted([c.trim_for_hash() for c in self.condition], key=lambda c: c[0]))


class ResourceGroup(BaseModel):
    id: str = ""
    related_resource_types: List[RelatedResource]
    environments: List[Environment] = []

    def hash_environments(self) -> int:
        """
        计算环境属性hash值
        """
        return hash(tuple(sorted([e.trim_for_hash() for e in self.environments], key=lambda e: e[0])))

    def ignore_path(self, action: Action):
        for rrt in self.related_resource_types:
            resource_type = action.get_related_resource_type(rrt.system_id, rrt.type)
            if not resource_type:
                continue
            rrt.ignore_path(resource_type.instance_selections)


ThinResourceType = namedtuple("ThinResourceType", ["system_id", "type"])


class ResourceGroupList(ListModel):
    __root__: List[ResourceGroup]

    def get_thin_resource_types(self) -> List[ThinResourceType]:
        """
        获取资源类型列表
        """
        if len(self) == 0:
            return []

        return [ThinResourceType(rrt.system_id, rrt.type) for rrt in self[0].related_resource_types]


class Policy(BaseModel):
    action_id: str = Field(alias="id")
    policy_id: int
    expired_at: int
    resource_groups: ResourceGroupList

    class Config:
        allow_population_by_field_name = True  # 支持alias字段同时传 action_id 与 id

    def __init__(self, **data: Any):
        # NOTE 兼容 role, group授权信息的旧版结构
        if "resource_groups" not in data and "related_resource_types" in data:
            if not data["related_resource_types"]:
                data["resource_groups"] = []
            else:
                data["resource_groups"] = [
                    # NOTE: 固定resource_group_id方便删除逻辑
                    {
                        "id": DEAULT_RESOURCE_GROUP_ID,
                        "related_resource_types": data.pop("related_resource_types"),
                    }
                ]

        super().__init__(**data)

    @staticmethod
    def _is_old_structure(resources: List[Dict[str, Any]]) -> bool:
        """
        是否是老的policy结构
        """
        for r in resources:
            if "condition" in r and "system_id" in r and "type" in r:
                return True
        return False

    @classmethod
    def from_db_model(cls, policy: Union[PolicyModel, TemporaryPolicy], expired_at: int) -> "Policy":
        # 兼容新老结构
        resource_groups = policy.resources
        if cls._is_old_structure(policy.resources):
            # NOTE: 固定resource_group_id, 方便删除逻辑
            resource_groups = [ResourceGroup(id=DEAULT_RESOURCE_GROUP_ID, related_resource_types=policy.resources)]

        return cls(
            action_id=policy.action_id,
            policy_id=policy.policy_id,
            expired_at=expired_at,
            resource_groups=ResourceGroupList.parse_obj(resource_groups),
        )

    def to_db_model(
        self, system_id: str, subject: Subject, model: Union[Type[PolicyModel], Type[TemporaryPolicy]] = PolicyModel
    ) -> Union[PolicyModel, TemporaryPolicy]:
        p = model(
            subject_type=subject.type,
            subject_id=subject.id,
            system_id=system_id,
            action_type="",
            action_id=self.action_id,
        )
        p.resources = self.resource_groups.dict()

        if isinstance(p, TemporaryPolicy):
            p.expired_at = self.expired_at

        return p

    def to_backend_dict(self, system_id: str):
        translator = ResourceExpressionTranslator()
        return {
            "action_id": self.action_id,
            "resource_expression": translator.translate(system_id, self.resource_groups.dict()),
            "environment": "{}",
            "expired_at": self.expired_at,
            "id": self.policy_id,
        }

    def list_thin_resource_type(self) -> List[ThinResourceType]:
        """
        获取权限关联的资源类型列表
        """
        return self.resource_groups.get_thin_resource_types()

    def ignore_path(self, action: Action):
        """
        检查资源的实例视图是否匹配
        """
        for rg in self.resource_groups:
            rg.ignore_path(action)


class BackendThinPolicy(BaseModel):
    id: int
    system: str
    action_id: str
    expired_at: int


class SystemCounter(BaseModel):
    id: str
    count: int


class PolicyIDExpiredAt(BaseModel):
    id: int
    expired_at: int


class AbacPolicyChangeContent(BaseModel):
    change_type: AbacPolicyChangeType = AbacPolicyChangeType.NONE.value
    id: int = 0
    resource_expression: str = ""
    environment: str = "{}"
    expired_at = PERMANENT_SECONDS


class RbacPolicyChangeContent(BaseModel):
    created: List[PathNode] = []
    deleted: List[PathNode] = []


class UniversalPolicyChangedContent(BaseModel):
    action_id: str
    # 策略变更后的策略类型
    auth_type: AuthTypeEnum = AuthTypeEnum.ABAC.value
    # ABAC策略变更
    abac: Optional[AbacPolicyChangeContent]
    # RBAC策略变更
    rbac: Optional[RbacPolicyChangeContent]


class UniversalPolicy(Policy):
    """
    通用Policy，支持处理RBAC和ABAC策略，原Policy只支持处理ABAC
    """

    expression_resource_groups: ResourceGroupList = ResourceGroupList(__root__=[])
    instances: List[PathNode] = []

    auth_type: AuthTypeEnum = AuthTypeEnum.ABAC.value

    @classmethod
    def from_policy(cls, policy: Policy) -> "UniversalPolicy":
        p = cls(
            action_id=policy.action_id,
            policy_id=policy.policy_id,
            expired_at=policy.expired_at,
            resource_groups=policy.resource_groups,
        )
        # 主要是初始化expression_resource_groups、instances、auth_type 这3个与RBAC和ABAC相关的数据
        p._init_abac_and_rbac_data(policy.resource_groups)
        return p

    @staticmethod
    def _is_absolute_abac(resource_groups: ResourceGroupList) -> bool:
        """
        对于策略，某些情况下可以立马判断为ABAC策略
        """
        # TODO: 写单元测试时，顺便添加一些debug日志, 排查问题时能精确知道在哪个分支被return, 降低成本
        resource_group_count = len(resource_groups)
        # 1. 与资源实例无关
        # Note: 对于有关联资源实例的权限，resource_groups有数据，即使是任意，其也是有一个resource_group，且resource_group里Condition为空列表
        if resource_group_count == 0:
            return True

        # 2. 关联多种资源类型
        # Note: 对于只关联一种资源类型的情况，多个resource_group一定会被合并为一个resource_group
        #  所以这里多个resource_group，则一定是关联了多种资源类型
        if resource_group_count > 1:
            return True

        # 3. 只有一组的情况，进一步判断
        resource_group = resource_groups[0]
        # 3.1 关联多个资源类型
        related_resource_type_count = len(resource_group.related_resource_types)
        if related_resource_type_count != 1:
            return True

        # 只有一组，且只关联一种资源类型，进一步判断
        # 3.2 包含环境属性
        if resource_group.environments:
            return True

        # 3.3 Any策略
        rrt = resource_group.related_resource_types[0]
        if len(rrt.condition) == 0:
            return True

        return False

    @staticmethod
    def _parse_abac_and_rbac(rrt: RelatedResource) -> Tuple[ResourceGroupList, List[PathNode]]:
        """将关联的资源类型的权限进行拆分，并设置在对应rbac和abac数据里"""

        abac_conditions = []  # 存储ABAC策略数据
        rbac_instances = []  # 存储RBAC策略数据

        # 遍历原始策略的每个Condition，将ABAC策略和RBAC策略数据拆分出来
        for c in rrt.condition:
            # 包含属性，则只能是ABAC策略
            if not c.has_no_attributes():
                abac_conditions.append(c)
                continue

            # 接下来分析只包含资源实例范围的情况
            abac_instances: List[Instance] = []
            for inst in c.instances:
                # 无法命中RBAC策略规则的路径
                abac_paths = []
                for path in inst.path:
                    if not path.is_all_ignore_path_of_matched_selection():
                        abac_paths.append(path)
                        continue
                    # 只添加最后一个节点，其他忽略
                    rbac_instances.append(path.get_last_node_without_any())

                # 存在abac路径，则需要对应实例
                if len(abac_paths) > 0:
                    abac_instances.append(Instance(type=inst.type, path=abac_paths))

            # 存在abac实例，则构造对应Condition
            if len(abac_instances) > 0:
                abac_conditions.append(Condition(instances=abac_instances, attributes=[]))

        # 如果拆分后，存储ABAC策略的Condition有数据，则构造ABAC策略数据结构
        expression_resource_groups = ResourceGroupList(__root__=[])
        if len(abac_conditions) > 0:
            expression_resource_groups = ResourceGroupList(
                __root__=[
                    ResourceGroup(
                        related_resource_types=[
                            RelatedResource(system_id=rrt.system_id, type=rrt.type, condition=abac_conditions)
                        ]
                    )
                ]
            )

        return expression_resource_groups, list(set(rbac_instances))

    @staticmethod
    def _calculate_auth_type(has_abac: bool, has_rbac: bool) -> AuthTypeEnum:
        """计算auth_type"""
        # 1 abac和rbac都有
        if has_abac and has_rbac:
            return AuthTypeEnum.ALL.value

        # 2 有abac，无rbac
        if has_abac and not has_rbac:
            return AuthTypeEnum.ABAC.value

        # 3 无abac，有rbac
        if not has_abac and has_rbac:
            return AuthTypeEnum.RBAC.value

        return AuthTypeEnum.NONE.value

    def _init_abac_and_rbac_data(self, resource_groups: ResourceGroupList):
        """
        拆分出RBAC和ABAC权限
        并填充到expression_resource_groups和instances_resource_groups字段里
        同时计算出策略类型auth_type
        """
        # 1. 绝对是ABAC策略的情况，则无需进行策略的分析拆分
        if self._is_absolute_abac(resource_groups):
            self.expression_resource_groups = resource_groups
            return

        # 2. 分析拆分出RBAC和ABAC策略并设置
        # Note: 由于_is_absolute_abac方法里已经判断了多组和空组的情况为abac策略，提前返回了，所以下面只分析一组且只关联一种资源类型的情况
        rrt = resource_groups[0].related_resource_types[0]
        expression_resource_groups, instances = self._parse_abac_and_rbac(rrt)
        # 根据解析出的rabc和abac策略数据进行设置
        self.expression_resource_groups = expression_resource_groups
        self.instances = instances

        # 3. 计算出策略类型auth_type并设置
        has_abac = len(expression_resource_groups) > 0
        has_rbac = len(instances) > 0
        auth_type = self._calculate_auth_type(has_abac, has_rbac)
        self.auth_type = auth_type

    def calculate_pre_changed_content(self, system_id: str, old: "UniversalPolicy") -> UniversalPolicyChangedContent:
        """
        用于策略变化时，预先计算出策略要变化的abac和rbac内容
        """
        policy_changed_content = UniversalPolicyChangedContent(action_id=self.action_id, auth_type=self.auth_type)

        # ABAC
        self_has_abac = len(self.expression_resource_groups) > 0
        old_has_abac = len(old.expression_resource_groups) > 0
        # 新老策略都有ABAC策略，则最终是使用新策略直接覆盖
        if self_has_abac and old_has_abac:
            policy_changed_content.abac = AbacPolicyChangeContent(
                change_type=AbacPolicyChangeType.UPDATED.value,
                id=old.policy_id,
                resource_expression=self.to_resource_expression(system_id),
            )
        # 新策略无ABAC策略，但老策略有ABAC策略，则需要将老的ABAC策略删除
        elif not self_has_abac and old_has_abac:
            policy_changed_content.abac = AbacPolicyChangeContent(
                change_type=AbacPolicyChangeType.DELETED.value,
                id=old.policy_id,
            )
        # 新策略由ABAC策略，但老策略无ABAC策略，则需要创建ABAC策略
        elif self_has_abac and old_has_abac:
            policy_changed_content.abac = AbacPolicyChangeContent(
                change_type=AbacPolicyChangeType.CREATED.value,
                resource_expression=self.to_resource_expression(system_id),
            )

        # RBAC
        # TODO：需要策略1万个实例的情况下的性能
        created_instances = list(set(self.instances) - set(old.instances))
        deleted_instances = list(set(old.instances) - set(self.instances))
        if created_instances or deleted_instances:
            policy_changed_content.rbac = RbacPolicyChangeContent(created=created_instances, deleted=deleted_instances)

        return policy_changed_content

    def to_resource_expression(self, system_id: str) -> str:
        """将ABAC权限翻译为后台所需表达式"""
        assert len(self.expression_resource_groups) > 0
        translator = ResourceExpressionTranslator()
        return translator.translate(system_id, self.expression_resource_groups.dict())
