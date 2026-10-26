"""区域巡防单场挑战，复用模拟室的编队、战斗保护与结算计数。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from zzz_od.operation.gamepad.charge_transport import charge_mission_names
from zzz_od.operation.gamepad.combat_simulation import GamepadCombatSimulation
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation
from zzz_od.operation.gamepad.simulation_preset import (
    read_focused_choice,
    read_preset_area,
)

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.application.charge_plan.charge_plan_config import (
        ChargePlanConfig,
        ChargePlanItem,
    )
    from zzz_od.context.zzz_context import ZContext


class GamepadChargeBackToWorld(GamepadOperation):
    """从已识别的副本准备或出战页返回，不在未知页面连续按 B。"""

    def __init__(self, ctx: ZContext, category_name: str) -> None:
        super().__init__(ctx, op_name=f'手柄退出{category_name}', timeout_seconds=75)
        self.category_name: str = category_name
        self._deployment_back_sent: bool = False
        self._detail_back_sent: bool = False
        self._list_back_sent: bool = False

    def handle_init(self) -> None:
        self._deployment_back_sent = False
        self._detail_back_sent = False
        self._list_back_sent = False

    @operation_node(name='返回副本大世界', is_start_node=True, node_max_retry_times=30)
    def back(self) -> OperationRoundResult:
        """每个已确认页面只发送一次返回，并等待下一页。"""
        if self.category_name not in ('实战模拟室', '区域巡防', '专业挑战室'):
            return self.round_fail('未适配的副本返回分类')
        if self.last_screenshot is None:
            return self.round_retry('等待截图', wait=1)
        if self.round_by_find_area(self.last_screenshot, '大世界-普通', '快捷手册').is_success:
            return self.round_success('已返回大世界')
        if all(self.round_by_find_area(self.last_screenshot, '实战模拟室', name).is_success for name in ('手柄-出战', '手柄-预备编队')):
            if not self._deployment_back_sent:
                self.ctx.controller.btn_tap('east')
                self._deployment_back_sent = True
            return self.round_retry('等待副本详情', wait=1)
        if all(self.round_by_find_area(self.last_screenshot, self.category_name, name).is_success for name in ('手柄-挑战等级', '手柄-下一步')):
            if not self._detail_back_sent:
                self.ctx.controller.btn_tap('east')
                self._detail_back_sent = True
            return self.round_retry('等待大世界', wait=1)
        if self.category_name == '实战模拟室' and all(
            self.round_by_find_area(self.last_screenshot, '实战模拟室', name).is_success
            for name in ('手柄-基础材料分类', '手柄-代理人晋升分类')
        ):
            if not self._list_back_sent:
                self.ctx.controller.btn_tap('east')
                self._list_back_sent = True
            return self.round_retry('等待模拟室分类页退出', wait=1)
        if self.category_name == '专业挑战室':
            selected, _ = read_focused_choice(self.ctx, self.last_screenshot, '手柄-副本列表', charge_mission_names('专业挑战室'), '专业挑战室')
            if selected is not None:
                if not self._list_back_sent:
                    self.ctx.controller.btn_tap('east')
                    self._list_back_sent = True
                return self.round_retry('等待专业挑战室列表退出', wait=1)
        if self.node_retry_times >= 15:
            self.save_screenshot(prefix='macos_charge_exit_pending')
        return self.round_retry('等待已建档的副本返回画面', wait=1)


class GamepadAreaPatrol(GamepadCombatSimulation):
    """每场核对指定驱动盘副本及六十电量，再复用既有战斗闭环。"""

    def __init__(self, ctx: ZContext, plan: ChargePlanItem, prepare_only: bool = False, config: ChargePlanConfig | None = None) -> None:
        super().__init__(ctx, plan, prepare_only=prepare_only, config=config)
        self.op_name = '手柄区域巡防单次挑战'
        self.timeout_seconds = 600

    @property
    def expected_charge(self) -> int:
        """只用于比对，是否足够仍读取实际画面。"""
        return 60

    def _found(self, area_name: str) -> bool:
        """区域巡防有独立的等级位置，编队页继续共用已验证区域。"""
        if area_name in ('手柄-挑战等级', '手柄-下一步'):
            return self.last_screenshot is not None and self.round_by_find_area(self.last_screenshot, '区域巡防', area_name).is_success
        return super()._found(area_name)

    def _preset_selected(self) -> bool:
        """详情标题和列表黄框必须同时指向配置副本。"""
        title = read_preset_area(self.ctx, self.last_screenshot, '手柄-副本标题', '区域巡防')
        if title is None or not any(text.replace(' ', '') == self.plan.mission_type_name for text in title[1]):
            return False
        selected, _ = read_focused_choice(self.ctx, self.last_screenshot, '手柄-副本列表', charge_mission_names('区域巡防'), '区域巡防', border_gap=35)
        return selected == self.plan.mission_type_name

    @operation_node(name='检查手柄计划', is_start_node=True)
    def check_plan(self) -> OperationRoundResult:
        """只接受原数据中的普通巡防副本，不将特训目标当普通关卡。"""
        if self.plan.tab_name != '训练' or self.plan.category_name != '区域巡防' or self.plan.mission_type_name not in charge_mission_names('区域巡防'):
            return self.round_fail('区域巡防目标不在已支持的原副本数据中')
        if self.plan.level != '默认等级' or self.plan.predefined_team_idx not in range(-1, 20):
            return self.round_fail('区域巡防暂支持默认等级与当前编队或二十个预备编队')
        if self.plan.plan_times <= 0 or self.plan.run_times < 0 or self.plan.run_times >= self.plan.plan_times:
            return self.round_fail('计划次数无效或已完成')
        return self.round_success()

    @node_from(from_name='加载既有自动战斗')
    @operation_node(name='配置挑战卡片', node_max_retry_times=8, timeout_seconds=20)
    def prepare_cards(self) -> OperationRoundResult:
        """巡防不编辑模拟室卡片，必须重新确认目标详情。"""
        if self._deployment_visible():
            if not self._return_to_preset_sent:
                self.ctx.controller.btn_tap('east')
                self._return_to_preset_sent = True
            return self.round_retry('返回详情重新确认驱动盘副本', wait=1)
        if self._found('手柄-挑战等级') and self._found('手柄-下一步'):
            if not self._preset_selected():
                self.save_screenshot(prefix='macos_patrol_wrong_target')
                return self.round_fail(f'当前详情并非计划副本{self.plan.mission_type_name}')
            return self.round_success('驱动盘副本已确认')
        return self.round_retry('等待区域巡防详情', wait=1)

    def move_to_battle(self) -> None:
        """沿用原区域巡防的一秒前移，在已有战斗输入保护内执行。"""
        self.ctx.controller.move_w(press=True, press_time=1, release=True)

    @node_from(from_name='确认结算返回')
    @operation_node(name='手柄返回大世界', screenshot_before_round=False, timeout_seconds=90)
    def back_to_world(self) -> OperationRoundResult:
        """复用同一已建档退出操作，用于完成与资源不足。"""
        return self.round_by_op_result(GamepadChargeBackToWorld(self.ctx, '区域巡防').execute())
