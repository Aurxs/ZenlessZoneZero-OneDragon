"""专业挑战室普通材料单场，复用原编队、战斗与结算。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from zzz_od.operation.gamepad.area_patrol import GamepadChargeBackToWorld
from zzz_od.operation.gamepad.charge_transport import charge_mission_names
from zzz_od.operation.gamepad.combat_simulation import GamepadCombatSimulation
from zzz_od.operation.gamepad.simulation_preset import read_preset_area

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.application.charge_plan.charge_plan_config import (
        ChargePlanConfig,
        ChargePlanItem,
    )
    from zzz_od.context.zzz_context import ZContext


class GamepadExpertChallenge(GamepadCombatSimulation):
    """每场核对指定专业挑战室副本及四十电量，再复用既有战斗闭环。"""

    def __init__(self, ctx: ZContext, plan: ChargePlanItem, prepare_only: bool = False, config: ChargePlanConfig | None = None) -> None:
        super().__init__(ctx, plan, prepare_only=prepare_only, config=config)
        self.op_name = '手柄专业挑战室单次挑战'
        self.timeout_seconds = 600

    @property
    def expected_charge(self) -> int:
        """只用于比对，是否足够仍读取实际画面。"""
        return 40

    def _found(self, area_name: str) -> bool:
        """专业挑战室有独立的等级位置，编队页继续共用已验证区域。"""
        if area_name in ('手柄-挑战等级', '手柄-下一步'):
            return self.last_screenshot is not None and self.round_by_find_area(self.last_screenshot, '专业挑战室', area_name).is_success
        return super()._found(area_name)

    def _preset_selected(self) -> bool:
        """单目标详情标题必须与配置中的完整副本名一致。"""
        title = read_preset_area(self.ctx, self.last_screenshot, '手柄-副本标题', '专业挑战室')
        return title is not None and any(text.replace(' ', '') == self.plan.mission_type_name for text in title[1])

    @operation_node(name='检查手柄计划', is_start_node=True)
    def check_plan(self) -> OperationRoundResult:
        """只接受原数据中的普通专业挑战室副本，不将特训目标当普通关卡。"""
        if self.plan.tab_name != '训练' or self.plan.category_name != '专业挑战室' or self.plan.mission_type_name not in charge_mission_names('专业挑战室'):
            return self.round_fail('专业挑战室目标不在已支持的原副本数据中')
        if self.plan.level != '默认等级' or self.plan.predefined_team_idx not in range(-1, 6):
            return self.round_fail('专业挑战室暂支持默认等级与当前编队或前六个预备编队')
        if self.plan.plan_times <= 0 or self.plan.run_times < 0 or self.plan.run_times >= self.plan.plan_times:
            return self.round_fail('计划次数无效或已完成')
        return self.round_success()

    @node_from(from_name='加载既有自动战斗')
    @operation_node(name='配置挑战卡片', node_max_retry_times=8, timeout_seconds=20)
    def prepare_cards(self) -> OperationRoundResult:
        """专业挑战室不编辑模拟室卡片，必须重新确认目标详情。"""
        if self._deployment_visible():
            if not self._return_to_preset_sent:
                self.ctx.controller.btn_tap('east')
                self._return_to_preset_sent = True
            return self.round_retry('返回详情重新确认专业挑战室副本', wait=1)
        if self._found('手柄-挑战等级') and self._found('手柄-下一步'):
            if not self._preset_selected():
                self.save_screenshot(prefix='macos_expert_wrong_target')
                return self.round_fail(f'当前详情并非计划副本{self.plan.mission_type_name}')
            mode = read_preset_area(self.ctx, self.last_screenshot, '手柄-底部模式', '专业挑战室')
            text = ''.join(mode[1]).replace(' ', '') if mode else ''
            if '燃竭' in text:
                return self.round_fail('检测到燃竭模式，需要确认关闭状态后再出战')
            return self.round_success('专业挑战室目标已确认')
        return self.round_retry('等待专业挑战室详情', wait=1)

    def move_to_battle(self) -> None:
        """沿用原专业挑战室的一秒前移，在已有战斗输入保护内执行。"""
        self.ctx.controller.move_w(press=True, press_time=1, release=True)

    @node_from(from_name='确认结算返回')
    @operation_node(name='手柄返回大世界', screenshot_before_round=False, timeout_seconds=90)
    def back_to_world(self) -> OperationRoundResult:
        """复用同一已建档退出操作，用于完成与资源不足。"""
        return self.round_by_op_result(GamepadChargeBackToWorld(self.ctx, '专业挑战室').execute())
