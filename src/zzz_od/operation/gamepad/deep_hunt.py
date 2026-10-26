"""体力计划的深度追猎模式，区分周期奖励与消耗电量。"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from one_dragon.base.operation.application import application_const
from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from zzz_od.application.charge_plan import charge_plan_const
from zzz_od.operation.gamepad.charge_transport import (
    charge_mission_names,
    match_charge_mission,
)
from zzz_od.operation.gamepad.focus import has_filled_highlight
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation
from zzz_od.operation.gamepad.notorious_hunt import (
    GamepadHuntBackToWorld,
    GamepadHuntPrepare,
    GamepadHuntResultExit,
    GamepadNotoriousHunt,
)
from zzz_od.operation.gamepad.simulation_preset import (
    read_preset_area,
    read_preset_charge,
)

if TYPE_CHECKING:
    from cv2.typing import MatLike

    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.application.charge_plan.charge_plan_config import (
        ChargePlanConfig,
        ChargePlanItem,
    )
    from zzz_od.context.zzz_context import ZContext


class GamepadEnableDeepHunt(GamepadOperation):
    """仅在免费次数用完且目标已确认时切换模式，不发送出战。"""

    def __init__(self, ctx: ZContext, mission_type_name: str) -> None:
        super().__init__(ctx, op_name='手柄开启深度追猎', timeout_seconds=30)
        self.target: str = mission_type_name
        self._sent: bool = False
        self._confirmed: bool = False

    def handle_init(self) -> None:
        self._sent = False
        self._confirmed = False

    @operation_node(name='确认深度追猎模式', is_start_node=True, node_max_retry_times=8)
    def enable(self) -> OperationRoundResult:
        """按实拍RS切换，免费机会存在时不擅自消耗周期奖励。"""
        area = read_preset_area(self.ctx, self.last_screenshot, '手柄-页面文字', '恶名狩猎')
        if area is None:
            return self.round_retry('等待挑战入口', wait=1)
        text = ''.join(area[1]).replace(' ', '')
        if all(value in text for value in ('本周免费挑战次数已用尽', '是否开启', '深度追猎', '额外消耗电量继续挑战')):
            confirm = [match for word, matches in area[1].items() if word.replace(' ', '') == '确认' for match in matches]
            if len(confirm) == 1 and has_filled_highlight(area[0], confirm[0].rect, 'yellow'):
                if not self._confirmed:
                    self.ctx.controller.btn_tap('south')
                    self._confirmed = True
                return self.round_retry('确认开启，等待实际电量显示', wait=1)
            return self.round_retry('等待模式确认按钮高亮', wait=1)
        if not hunt_title_selected(self.ctx, self.last_screenshot, self.target) or '挑战等级' not in text:
            self.save_screenshot(prefix='macos_deep_mode_unknown')
            return self.round_retry('等待已确认的深度追猎页面', wait=1)
        left = re.search(r'剩余奖励次数[:：]?([0-3])/3', text)
        if left and int(left[1]) > 0:
            return self.round_fail('周期挑战有剩余次数，本次跳过深度追猎')
        if deep_hunt_enabled(self.ctx, self.last_screenshot) and '电量消耗' in text:
            return self.round_success('深度追猎已开启')
        if left and int(left[1]) == 0 and '深度追猎' in text and 'OFF' in text and '无报酬模式' in text:
            if not self._sent:
                self.ctx.controller.btn_tap('right_stick_click')
                self._sent = True
            return self.round_retry('等待深度追猎开关或确认弹窗', wait=1)
        self.save_screenshot(prefix='macos_deep_mode_pending')
        return self.round_retry('等待深度追猎状态明确', wait=1)


def deep_hunt_enabled(ctx: ZContext, screen: MatLike | None) -> bool:
    """独立开关区域识别ON，不从敌人介绍中的英文推断模式。"""
    area = read_preset_area(ctx, screen, '手柄-深度开关', '恶名狩猎')
    if area is None:
        return False
    words = {text.replace(' ', '') for text in area[1]}
    return 'ON' in words and any('深度追猎' in word for word in words)


def hunt_title_selected(ctx: ZContext, screen: MatLike | None, target: str) -> bool:
    """目标标题通过原数据及其明确别名确认。"""
    title = read_preset_area(ctx, screen, '手柄-副本标题', '恶名狩猎')
    return title is not None and any(match_charge_mission(text, '恶名狩猎') == target for text in title[1])


def deep_target_selected(ctx: ZContext, screen: MatLike | None, target: str) -> bool:
    """目标与ON模式同时成立才允许体力挑战。"""
    return hunt_title_selected(ctx, screen, target) and deep_hunt_enabled(ctx, screen)


class GamepadDeepHuntPrepare(GamepadHuntPrepare):
    """沿用编队与难度导航，替换免费次数检查为实际电量检查。"""

    @operation_node(name='核对挑战目标', is_start_node=True, node_max_retry_times=4)
    def check_target(self) -> OperationRoundResult:
        """未确认目标及模式不进入编队。"""
        if self.plan.predefined_team_idx not in range(-1, 6):
            return self.round_fail('暂支持当前编队或前六个预备编队')
        if not deep_target_selected(self.ctx, self.last_screenshot, self.plan.mission_type_name):
            return self.round_fail('深度追猎目标或模式与计划不一致')
        charge = read_preset_charge(self.ctx, self.last_screenshot)
        if charge is None or charge[1] != 60:
            return self.round_retry('等待深度追猎实际60电量', wait=1)
        if charge[0] < charge[1]:
            return self.round_fail('电量不足')
        return self.round_success()

    @node_from(from_name='核对挑战目标')
    @operation_node(name='选择计划难度', node_max_retry_times=10, timeout_seconds=20)
    def choose_level(self) -> OperationRoundResult:
        """体力计划默认等级沿用游戏当前值，显式等级复用已验证导航。"""
        if self.plan.level == '默认等级':
            return self.round_success()
        return super().choose_level()

    @node_from(from_name='选择计划难度')
    @operation_node(name='进入当前编队', node_max_retry_times=10, timeout_seconds=75)
    def prepare_deployment(self) -> OperationRoundResult:
        """出战页再次读取真实60消耗，不靠预估跳过检查。"""
        charge = read_preset_charge(self.ctx, self.last_screenshot)
        if charge is None or charge[1] != 60:
            return self.round_retry('等待深度追猎电量核对', wait=1)
        if charge[0] < charge[1]:
            return self.round_fail('电量不足')
        return super().prepare_deployment()


class GamepadDeepHuntResultExit(GamepadHuntResultExit):
    """保留明确胜负与退出动作，返回后读取电量而非免费次数。"""

    @node_from(from_name='退出结算')
    @operation_node(name='等待挑战入口', node_max_retry_times=25, timeout_seconds=40)
    def wait_entry(self) -> OperationRoundResult:
        charge = read_preset_charge(self.ctx, self.last_screenshot)
        if deep_hunt_enabled(self.ctx, self.last_screenshot) and charge is not None and charge[1] == 60:
            return self.round_success(data={'won': self.won, 'charge': charge[0]})
        return self.round_retry('等待深度追猎入口电量', wait=1)


class GamepadDeepHunt(GamepadNotoriousHunt):
    """复用恶名狩猎单场编排，胜利只累计原体力计划。"""

    def __init__(self, ctx: ZContext, plan: ChargePlanItem, config: ChargePlanConfig | None = None, prepare_only: bool = False) -> None:
        super().__init__(ctx, plan)
        self.op_name = '手柄深度追猎体力挑战'
        self.config: ChargePlanConfig = config if config is not None else ctx.run_context.get_config(
            app_id=charge_plan_const.APP_ID, instance_idx=ctx.current_instance_idx, group_id=application_const.DEFAULT_GROUP_ID,
        )
        self.prepare_only: bool = prepare_only
        self._charge_before: int | None = None

    @property
    def expected_charge(self) -> int:
        return 60

    def read_charge(self) -> tuple[int, int] | None:
        return read_preset_charge(self.ctx, self.last_screenshot)

    def _preset_selected(self) -> bool:
        return deep_target_selected(self.ctx, self.last_screenshot, self.plan.mission_type_name)

    @operation_node(name='准备挑战', is_start_node=True, screenshot_before_round=False, timeout_seconds=180)
    def prepare(self) -> OperationRoundResult:
        if self.plan.tab_name != '训练' or self.plan.category_name != '恶名狩猎' or self.plan.mission_type_name not in charge_mission_names('恶名狩猎'):
            return self.round_fail('深度追猎目标不在原数据中')
        if self.plan.plan_times <= self.plan.run_times or self.plan.run_times < 0:
            return self.round_fail('计划次数无效或已完成')
        mode = GamepadEnableDeepHunt(self.ctx, self.plan.mission_type_name).execute()
        if not mode.success:
            return self.round_by_op_result(mode)
        self.ctx.lost_void.init_lost_void_det_model()
        result = GamepadDeepHuntPrepare(self.ctx, self.plan).execute()
        if not result.success:
            return self.round_by_op_result(result)
        charge = read_preset_charge(self.ctx, self.ctx.controller.get_screenshot())
        if charge is None or charge[1] != 60 or charge[0] < 60:
            return self.round_fail('出战前实际电量未能确认')
        self._charge_before = charge[0]
        return self.round_success('准备完成，尚未出战' if self.prepare_only else '恶名狩猎当前编队准备就绪')

    @node_from(from_name='战斗')
    @operation_node(name='结算返回', screenshot_before_round=False, timeout_seconds=90)
    def finish(self) -> OperationRoundResult:
        result = GamepadDeepHuntResultExit(self.ctx).execute()
        if not result.success:
            return self.round_by_op_result(result)
        if not self._won or result.data['won'] is not True:
            return self.round_fail('深度追猎失败，未增加体力计划次数')
        # 胜利且实际扣电接近60才计数；预留十点自然恢复容差。
        if self._charge_before is None or not 50 <= self._charge_before - result.data['charge'] <= 60:
            return self.round_fail('深度追猎胜利后电量变化不符，未累计次数')
        self.config.add_plan_run_times(self.plan)
        result = GamepadHuntBackToWorld(self.ctx).execute()
        return self.round_by_op_result(result)
