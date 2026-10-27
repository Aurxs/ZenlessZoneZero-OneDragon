"""任务失败后从有返回标识的手柄页面退回主界面。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from one_dragon.base.operation.operation_node import operation_node
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class GamepadBackToNormalWorld(GamepadOperation):
    """只发送有限的返回键，不确认未知弹窗或领取奖励。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='任务失败后手柄返回主界面', timeout_seconds=30)
        self._back_count: int = 0
        self._last_action_frame_time: float = -1

    def handle_init(self) -> None:
        """清理失败任务留下的按键，再逐帧检查返回路径。"""
        self._back_count = 0
        self._last_action_frame_time = -1
        self.ctx.controller.gamepad.reset()

    @operation_node(name='返回主界面', is_start_node=True, node_max_retry_times=12)
    def back(self) -> OperationRoundResult:
        """确认大世界才成功；仅在通用返回模板出现时按 B。"""
        if self.last_screenshot is None or self.last_screenshot_time <= self._last_action_frame_time:
            return self.round_retry('等待返回后的新截图', wait=1)
        if self.round_by_find_area(self.last_screenshot, '大世界-普通', '快捷手册').is_success:
            return self.round_success('已返回游戏主界面')
        if self._back_count >= 6:
            self.save_screenshot(prefix='macos_task_recovery_limit')
            return self.round_fail('返回次数已达上限，未进入下一任务')
        if self.round_by_find_area(self.last_screenshot, '画面-通用', '返回').is_success:
            self.ctx.controller.btn_tap('east')
            self._last_action_frame_time = self.last_screenshot_time
            self._back_count += 1
            return self.round_retry('等待返回游戏主界面', wait=1)
        if self.node_retry_times >= 3:
            self.save_screenshot(prefix='macos_task_recovery_unknown')
            return self.round_fail('未识别到可返回页面，未进入下一任务')
        return self.round_retry('等待可返回页面稳定', wait=1)
