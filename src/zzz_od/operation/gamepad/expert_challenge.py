"""专业挑战室普通材料单场，复用原编队、战斗与结算。"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from one_dragon.utils import debug_utils
from zzz_od.operation.gamepad.area_patrol import GamepadChargeBackToWorld
from zzz_od.operation.gamepad.charge_transport import (
    charge_mission_names,
    match_charge_mission,
)
from zzz_od.operation.gamepad.combat_simulation import GamepadCombatSimulation
from zzz_od.operation.gamepad.focus import has_filled_highlight
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation
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
        return title is not None and any(match_charge_mission(text, '专业挑战室') == self.plan.mission_type_name for text in title[1])

    @operation_node(name='检查手柄计划', is_start_node=True)
    def check_plan(self) -> OperationRoundResult:
        """只接受原数据中的普通专业挑战室副本，不将特训目标当普通关卡。"""
        if self.plan.tab_name != '训练' or self.plan.category_name != '专业挑战室' or self.plan.mission_type_name not in charge_mission_names('专业挑战室'):
            return self.round_fail('专业挑战室目标不在已支持的原副本数据中')
        if self.plan.level != '默认等级' or self.plan.predefined_team_idx not in range(-1, 20):
            return self.round_fail('专业挑战室暂支持默认等级与当前编队或二十个预备编队')
        if self.plan.plan_times <= 0 or self.plan.run_times < 0 or self.plan.run_times >= self.plan.plan_times:
            return self.round_fail('计划次数无效或已完成')
        return self.round_success()

    @node_from(from_name='加载既有自动战斗')
    @operation_node(name='配置挑战卡片', node_max_retry_times=8, timeout_seconds=60)
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
            return self.round_by_op_result(GamepadDisableBurnout(self.ctx, self.plan.mission_type_name).execute())
        return self.round_retry('等待专业挑战室详情', wait=1)

    def move_to_battle(self) -> None:
        """沿用原专业挑战室的一秒前移，在已有战斗输入保护内执行。"""
        self.ctx.controller.move_w(press=True, press_time=1, release=True)

    @node_from(from_name='确认结算返回')
    @operation_node(name='手柄返回大世界', screenshot_before_round=False, timeout_seconds=90)
    def back_to_world(self) -> OperationRoundResult:
        """复用同一已建档退出操作，用于完成与资源不足。"""
        return self.round_by_op_result(GamepadChargeBackToWorld(self.ctx, '专业挑战室').execute())



class GamepadInspectExpertLevels(GamepadOperation):
    """读取专业挑战室已有难度选项，不确认等级或进入战斗。"""

    def __init__(self, ctx: ZContext, target: str) -> None:
        super().__init__(ctx, op_name='手柄查看专业挑战室等级', timeout_seconds=20)
        self.target: str = target
        self._opened: bool = False

    def handle_init(self) -> None:
        self._opened = False

    @operation_node(name='读取专业挑战室等级', is_start_node=True, node_max_retry_times=8)
    def inspect(self) -> OperationRoundResult:
        if self.last_screenshot is None:
            return self.round_retry('等待截图', wait=0.8)
        title = read_preset_area(self.ctx, self.last_screenshot, '手柄-副本标题', '专业挑战室')
        if title is None or not any(match_charge_mission(text, '专业挑战室') == self.target for text in title[1]):
            return self.round_fail('专业挑战室目标未确认')
        words = self.ctx.ocr.run_ocr(self.last_screenshot)
        levels = sorted({int(match[1]) for text in words for match in re.finditer(r'(?:Lv|LV|lv)[.．]?\s*(\d+)', text)})
        if len(levels) > 1:
            name = self.save_screenshot(prefix='macos_expert_levels')
            self.ctx.controller.btn_tap('east')
            return self.round_success('等级已读取并关闭列表，未更改等级', wait=1, data={
                'levels': levels, 'screenshot': debug_utils.get_debug_image_path(name),
            })
        if not self._opened and self.round_by_find_area(self.last_screenshot, '专业挑战室', '手柄-挑战等级').is_success:
            self.ctx.controller.btn_tap('left_stick_click')
            self._opened = True
        return self.round_retry('等待读取等级列表', wait=0.8)



class GamepadDisableBurnout(GamepadOperation):
    """关闭已明确开启的燃竭模式，保留普通四十电量挑战语义。"""

    def __init__(self, ctx: ZContext, target: str) -> None:
        super().__init__(ctx, op_name='手柄关闭燃竭模式', timeout_seconds=30)
        self.target: str = target
        self._sent: bool = False
        self._confirmed: bool = False

    def handle_init(self) -> None:
        self._sent = False
        self._confirmed = False

    @operation_node(name='核对燃竭关闭状态', is_start_node=True, node_max_retry_times=10)
    def disable(self) -> OperationRoundResult:
        """只有可见RS提示才切换；可恢复明确的退出确认，未知弹窗不确认。"""
        if self.last_screenshot is None:
            return self.round_retry('等待模式截图', wait=0.8)
        words = self.ctx.ocr.run_ocr(self.last_screenshot)
        text = ''.join(words).replace(' ', '')
        exit_prompt = all(part in text for part in (
            '是否退出', '燃竭模式', '恢复电量消耗和奖励产出至正常水平',
        ))
        if exit_prompt:
            confirms = [match for word, matches in words.items() if word.replace(' ', '') == '确认'
                        for match in matches if has_filled_highlight(self.last_screenshot, match.rect, 'yellow')]
            if len(confirms) == 1 and not self._confirmed:
                self.ctx.controller.btn_tap('south')
                self._sent = True
                self._confirmed = True
            return self.round_retry('等待关闭模式确认返回', wait=1)
        title = read_preset_area(self.ctx, self.last_screenshot, '手柄-副本标题', '专业挑战室')
        if title is None or not any(match_charge_mission(word, '专业挑战室') == self.target for word in title[1]):
            return self.round_retry('等待指定专业挑战室详情', wait=0.8)
        mode = read_preset_area(self.ctx, self.last_screenshot, '手柄-燃竭开关', '专业挑战室')
        if mode is None:
            return self.round_retry('无法读取燃竭状态区域', wait=0.8)
        text = ' '.join(word.replace(' ', '') for word in mode[1])
        if '燃竭' not in text:
            if self._sent:
                return self.round_retry('切换后未确认OFF，不推断关闭成功', wait=0.8)
            return self.round_success('普通详情无燃竭开关，继续核对实际消耗')
        on = re.search(r'(?<![A-Za-z])ON(?![A-Za-z])', text) is not None
        off = re.search(r'(?<![A-Za-z])OFF(?![A-Za-z])', text) is not None
        if off and not on:
            return self.round_success('燃竭模式已关闭')
        if on and not off:
            if re.search(r'(?<![A-Za-z])RS(?![A-Za-z])', text) is None:
                return self.round_fail('燃竭已开启但未识别对应RS提示，未猜测按键')
            if not self._sent:
                self.ctx.controller.btn_tap('right_stick_click')
                self._sent = True
            return self.round_retry('等待燃竭OFF或关闭确认', wait=1)
        return self.round_retry('燃竭状态无法唯一确认', wait=0.8)
