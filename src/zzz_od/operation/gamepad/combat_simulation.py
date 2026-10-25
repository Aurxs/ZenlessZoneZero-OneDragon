"""复用体力计划与自动战斗的手柄实战模拟室单次挑战。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, ClassVar

import cv2

from one_dragon.base.operation.application import application_const
from one_dragon.base.operation.operation import Operation
from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from zzz_od.application.charge_plan import charge_plan_const
from zzz_od.application.charge_plan.charge_plan_config import CardNumEnum
from zzz_od.operation.gamepad.focus import highlight_mask
from zzz_od.operation.zzz_operation import ZOperation

if TYPE_CHECKING:
    from cv2.typing import MatLike

    from one_dragon.base.operation.operation_base import OperationResult
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.application.charge_plan.charge_plan_config import (
        ChargePlanConfig,
        ChargePlanItem,
    )
    from zzz_od.context.zzz_context import ZContext


class GamepadCombatSimulation(ZOperation):
    """只运行已验证的调查专项默认五卡，不变更队伍和电量来源。"""

    STATUS_CHARGE_NOT_ENOUGH: ClassVar[str] = '电量不足'
    STATUS_DEPLOYMENT_READY: ClassVar[str] = '出战准备就绪'
    STATUS_PREPARED: ClassVar[str] = '准备完成，尚未出战'

    def __init__(
        self, ctx: ZContext, plan: ChargePlanItem, prepare_only: bool = False,
        config: ChargePlanConfig | None = None,
    ) -> None:
        """传送后挑战一次，保留原计划和自动战斗配置。"""
        super().__init__(ctx, op_name='手柄实战模拟室单次挑战', timeout_seconds=300)
        self.plan: ChargePlanItem = plan
        self.prepare_only: bool = prepare_only
        self.config: ChargePlanConfig = config if config is not None else self.ctx.run_context.get_config(
            app_id=charge_plan_const.APP_ID,
            instance_idx=self.ctx.current_instance_idx,
            group_id=application_const.DEFAULT_GROUP_ID,
        )
        self._next_sent: bool = False
        self._deploy_sent: bool = False
        self._battle_active: bool = False
        self._recorded: bool = False
        self._gate_active: bool = False
        self._finish_sent: bool = False
        self._preset_back_sent: bool = False
        self._category_back_sent: bool = False
        self._battle_result: str | None = None

    def handle_init(self) -> None:
        """重新执行时清除一次性输入和战斗记录。"""
        self._next_sent = False
        self._deploy_sent = False
        self._battle_active = False
        self._recorded = False
        self._gate_active = False
        self._finish_sent = False
        self._preset_back_sent = False
        self._category_back_sent = False
        self._battle_result = None

    def execute(self) -> OperationResult:
        """正常、失败和异常退出都停止自动战斗。"""
        try:
            return super().execute()
        finally:
            self._stop_battle()

    def _stop_battle(self) -> None:
        """先停策略再结束输入保护，避免迟到的战斗动作获得菜单权限。"""
        self.ctx.auto_battle_context.stop_auto_battle()
        self._battle_active = False
        if self._gate_active:
            self.ctx.controller.end_battle_input_scope()
            self._gate_active = False

    def _found(self, area_name: str) -> bool:
        """只查当前截图，不产生按键。"""
        return self.last_screenshot is not None and self.round_by_find_area(
            self.last_screenshot, '实战模拟室', area_name
        ).is_success

    def _read_area(self, area_name: str) -> tuple[MatLike, dict] | None:
        """从平台区域读取局部图与 OCR，区域缺失时不输入。"""
        area = self.ctx.screen_loader.get_area('实战模拟室', area_name)
        if area is None or self.last_screenshot is None:
            return None
        rect = area.rect
        image = self.last_screenshot[rect.y1:rect.y2, rect.x1:rect.x2]
        if not image.size:
            return None
        return image, self.ctx.ocr.crop_and_run_ocr(self.last_screenshot, rect)

    def read_charge(self) -> tuple[int, int] | None:
        """读取画面实际消耗，不能用默认数量的二十电量预估替代。"""
        area = self._read_area('手柄-电量')
        if area is None:
            return None
        values: set[tuple[int, int]] = set()
        for text in area[1]:
            match = re.fullmatch(r'\s*(\d{1,4})\s*/\s*(\d{1,3})\s*', text)
            if match is not None:
                values.add((int(match[1]), int(match[2])))
        return next(iter(values)) if len(values) == 1 else None

    def _charge(self) -> tuple[int, int] | None:
        """兼容已有单次挑战调用，计划调度可直接读取实际电量。"""
        return self.read_charge()

    def _survey_selected(self) -> bool:
        """调查专项文字须被完整黄色卡片边框包住。"""
        area = self._read_area('手柄-预设列表')
        if area is None:
            return False
        image, results = area
        target = next((matches.max for text, matches in results.items()
                       if '调查专项' in text and matches.max is not None), None)
        if target is None:
            return False
        contours, _ = cv2.findContours(
            highlight_mask(image, 'yellow'), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            if width < 200 or height < 100:
                continue
            if cv2.contourArea(contour) / (width * height) < 0.75:
                continue
            if x < target.x < target.x + target.w < x + width and y < target.y < target.y + target.h < y + height:
                return True
        return False

    def _deployment_visible(self) -> bool:
        """出战与预备编队同时出现才确认编队页。"""
        return self._found('手柄-出战') and self._found('手柄-预备编队')

    def _result_visible(self) -> bool:
        """直接查结果标题与完成按钮，不受原结束检查间隔限制。"""
        if self.last_screenshot is None:
            return False
        return all(self.round_by_find_area(
            self.last_screenshot, '战斗画面', area
        ).is_success for area in ('手柄-挑战结果', '手柄-完成'))

    @operation_node(name='检查手柄计划', is_start_node=True)
    def check_plan(self) -> OperationRoundResult:
        """只接受本次已有画面与输入证据的计划。"""
        if (
            self.plan.tab_name != '训练'
            or self.plan.category_name != '实战模拟室'
            or self.plan.mission_type_name != '基础材料'
            or self.plan.mission_name != '调查专项'
            or self.plan.level != '默认等级'
            or self.plan.card_num not in (CardNumEnum.DEFAULT.value.value, '5')
            or self.plan.predefined_team_idx != -1
        ):
            return self.round_fail('手柄实战模拟室暂仅支持调查专项默认五卡、默认等级与当前编队')
        if self.plan.run_times >= self.plan.plan_times:
            return self.round_fail('当前计划已完成')
        return self.round_success()

    @node_from(from_name='检查手柄计划')
    @operation_node(name='加载既有自动战斗')
    def prepare_auto_battle(self) -> OperationRoundResult:
        """出战前加载原策略，保留尚未校准的自动转向限制。"""
        if self.prepare_only:
            return self.round_success()
        battle = self.ctx.auto_battle_context
        battle.init_auto_op(op_name=self.plan.auto_battle_config, sub_dir='auto_battle')
        if battle.auto_op is None or battle.auto_op.auto_turn_interval != 0:
            return self.round_fail('Mac 自动战斗策略须关闭尚未校准的自动转向')
        return self.round_success()

    @node_from(from_name='加载既有自动战斗')
    @operation_node(name='准备当前编队', node_max_retry_times=10, timeout_seconds=15)
    def prepare_deployment(self) -> OperationRoundResult:
        """核对实际预设后只按一次 Start，后续轮次等待编队画面。"""
        if self._deployment_visible():
            return self.round_success(
                self.STATUS_PREPARED if self.prepare_only else self.STATUS_DEPLOYMENT_READY
            )
        if not (self._found('手柄-挑战等级') and self._found('手柄-下一步')):
            return self.round_retry('等待实战模拟室预设或出战页', wait=1)
        if not self._survey_selected():
            return self.round_fail('当前未选中调查专项，手柄切换预设尚未验证')
        charge = self._charge()
        if charge is None:
            return self.round_retry('未能确认实际电量消耗', wait=1)
        current, required = charge
        if required != 100:
            return self.round_fail(f'当前预设消耗 {required} 电量，尚未验证该卡片数量')
        if current < required:
            return self.round_fail(self.STATUS_CHARGE_NOT_ENOUGH)
        if not self._next_sent:
            self.ctx.controller.btn_tap('start')
            self._next_sent = True
        return self.round_retry('等待出战准备页', wait=1)

    @node_from(from_name='准备当前编队', status=STATUS_DEPLOYMENT_READY)
    @operation_node(name='手柄出战', node_max_retry_times=10, timeout_seconds=15)
    def deploy(self) -> OperationRoundResult:
        """两处编队文字和实际电量都可识别时只按一次 Start。"""
        if self._deploy_sent:
            return self.round_success()
        if not self._deployment_visible():
            return self.round_retry('等待出战准备页', wait=1)
        charge = self._charge()
        if charge is None:
            return self.round_retry('未能确认出战电量', wait=1)
        current, required = charge
        if required != 100:
            return self.round_fail(f'出战消耗 {required} 电量，尚未验证该卡片数量')
        if current < required:
            return self.round_fail(self.STATUS_CHARGE_NOT_ENOUGH)
        self.ctx.controller.btn_tap('start')
        self._deploy_sent = True
        return self.round_success(wait=1)

    @node_from(from_name='手柄出战')
    @operation_node(name='等待手柄战斗', node_max_retry_times=30, timeout_seconds=40)
    def wait_for_battle(self) -> OperationRoundResult:
        """复用已核对的普通攻击按钮识别，不在加载期间发送动作。"""
        if self.last_screenshot is not None and self.ctx.auto_battle_context.is_normal_attack_btn_available(self.last_screenshot):
            return self.round_success()
        return self.round_retry('等待手柄战斗画面', wait=1)

    @node_from(from_name='等待手柄战斗')
    @operation_node(name='启动既有自动战斗')
    def start_auto_battle(self) -> OperationRoundResult:
        """先启用逐帧输入保护，再启动原自动战斗执行器。"""
        from zzz_od.controller.macos_battle_input_guard import MacBattleHudGuard

        battle = self.ctx.auto_battle_context
        self.ctx.controller.begin_battle_input_scope(MacBattleHudGuard(battle))
        self._gate_active = True
        battle.start_auto_battle()
        self._battle_active = True
        return self.round_success()

    @node_from(from_name='启动既有自动战斗')
    @operation_node(name='自动战斗', mute=True, timeout_seconds=180)
    def auto_battle(self) -> OperationRoundResult:
        """结果出现或输入保护阻断时立即停策略，禁止结算页残留 X。"""
        battle = self.ctx.auto_battle_context
        if self.last_screenshot is None:
            return self.round_fail('战斗截图无效')
        if self.ctx.controller.battle_input_blocked:
            if self._battle_active:
                battle.stop_auto_battle()
                self._battle_active = False
            # 输入监测先以模板阻断，再对候选帧做 OCR，正常战斗不重复 OCR。
            if self._result_visible():
                self._stop_battle()
                return self.round_success('等待结算确认')
            # 终结技过场也会隐藏 HUD，保留保护范围，只在新帧重新确认后恢复。
            if self.ctx.controller.refresh_battle_input_scope():
                battle.resume_auto_battle()
                self._battle_active = True
            return self.round_wait(wait=self.ctx.battle_assistant_config.screenshot_interval)
        battle.check_battle_state(
            self.last_screenshot, self.last_screenshot_time,
            check_battle_end_normal_result=True, sync=True,
        )
        if battle.last_check_end_result is not None:
            self._battle_result = battle.last_check_end_result
            self._stop_battle()
            return self.round_success(self._battle_result)
        return self.round_wait(wait=self.ctx.battle_assistant_config.screenshot_interval)

    @node_from(from_name='自动战斗', success=False, status=Operation.STATUS_TIMEOUT)
    @operation_node(name='战斗超时停止')
    def battle_timeout(self) -> OperationRoundResult:
        """超时只停止，未建档的战斗菜单不盲目返回。"""
        self._stop_battle()
        return self.round_fail('战斗超时，已停止自动战斗')

    @node_from(from_name='自动战斗')
    @operation_node(name='确认战斗结果', node_max_retry_times=12, timeout_seconds=15)
    def wait_for_result(self) -> OperationRoundResult:
        """输入已暂停，只有结算双锚点命中才能确认胜利。"""
        if self._battle_result == '普通战斗-撤退':
            return self.round_fail('普通战斗-撤退')
        if self._result_visible():
            self._battle_result = '普通战斗-完成'
            return self.round_success()
        return self.round_retry('战斗输入已停止，等待结算画面', wait=1)

    @node_from(from_name='确认战斗结果')
    @operation_node(name='记录单次战斗')
    def record_battle(self) -> OperationRoundResult:
        """胜利才累计一次，临时联调计划不写入用户配置。"""
        if self._battle_result != '普通战斗-完成':
            return self.round_fail(self._battle_result or '战斗结果未确认')
        if not self._recorded:
            saved = next((item for item in self.config.plan_list
                          if item.plan_id == self.plan.plan_id), None)
            if saved is None:
                self.plan.run_times += 1
            else:
                self.config.add_plan_run_times(self.plan)
                self.plan.run_times = saved.run_times
            self._recorded = True
        return self.round_success()

    @node_from(from_name='记录单次战斗')
    @operation_node(name='处理手柄结算', node_max_retry_times=5, timeout_seconds=8)
    def finish_result(self) -> OperationRoundResult:
        """确认结果后只发 B 完成；停止旧策略后才恢复菜单输入。"""
        if self._finish_sent:
            return self.round_success()
        if not self._result_visible():
            return self.round_retry('等待结算完成按钮', wait=1)
        self._stop_battle()
        self.ctx.controller.resume_input()
        self.ctx.controller.btn_tap('east')
        self._finish_sent = True
        return self.round_success(wait=1)

    @node_from(from_name='处理手柄结算')
    @operation_node(name='确认结算返回', node_max_retry_times=10, timeout_seconds=15)
    def wait_for_return(self) -> OperationRoundResult:
        """完成后先确认回到预设，过渡帧不再发 B。"""
        if self._found('手柄-挑战等级') and self._found('手柄-下一步'):
            return self.round_success()
        return self.round_retry('等待结算返回预设页', wait=1)

    @node_from(from_name='确认结算返回')
    @operation_node(name='手柄返回大世界', node_max_retry_times=15, timeout_seconds=20)
    def back_to_world(self) -> OperationRoundResult:
        """逐帧区分预设、材料分类与大世界，每个返回动作只发一次。"""
        if self.last_screenshot is None:
            return self.round_retry('截图无效', wait=1)
        if self.round_by_find_area(
            self.last_screenshot, '大世界-普通', '快捷手册'
        ).is_success:
            return self.round_success('实战模拟室单次挑战完成，已返回大世界')
        if self._found('手柄-挑战等级') and self._found('手柄-下一步'):
            if not self._preset_back_sent:
                self.ctx.controller.btn_tap('east')
                self._preset_back_sent = True
            return self.round_retry('等待材料分类页', wait=1)
        if self._found('手柄-基础材料分类') and self._found('手柄-代理人晋升分类'):
            if not self._category_back_sent:
                self.ctx.controller.btn_tap('east')
                self._category_back_sent = True
            return self.round_retry('等待大世界', wait=1)
        return self.round_retry('等待已建档的返回画面', wait=1)

    def handle_pause(self) -> None:
        """暂停沿用原自动战斗停止逻辑。"""
        self.ctx.auto_battle_context.stop_auto_battle()

    def handle_resume(self) -> None:
        """仅在自动战斗节点恢复策略，不重放导航按键。"""
        if self._battle_active and not self.ctx.controller.battle_input_blocked and self.current_node.node is not None and self.current_node.node.cn == '自动战斗':
            self.ctx.auto_battle_context.resume_auto_battle()
