"""大世界功能导览的手柄网格导航。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from one_dragon.base.operation.operation_node import operation_node
from zzz_od.operation.gamepad.rewards import _GamepadRewardOperation
from zzz_od.operation.gamepad.transport import find_yellow_focus_frames

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class GamepadOpenFunction(_GamepadRewardOperation):
    """按功能名与唯一黄色框移焦，调用方继续确认目的页面。"""

    def __init__(self, ctx: ZContext, target: str) -> None:
        super().__init__(ctx, op_name=f'手柄功能导览 {target}', timeout_seconds=35)
        self.target: str = target
        self._opened: bool = False
        self._entered: bool = False

    def handle_init(self) -> None:
        """重新执行时清理本次输入标记。"""
        self.evidence_paths.clear()
        self._opened = False
        self._entered = False

    @operation_node(name='选择功能入口', is_start_node=True, node_max_retry_times=18)
    def select_function(self) -> OperationRoundResult:
        """LT 与菜单键同时保持打开导览，每次移焦后重新读图。"""
        visible = self.round_by_find_area(self.last_screenshot, '功能导览', '标题').is_success
        if self._entered:
            if not visible:
                return self.round_success('功能入口已选择')
            return self.round_retry('等待功能入口切换', wait=1)
        if visible:
            area = self._read_area('功能导览', '手柄-卡片')
            if area is None:
                return self.round_retry('等待功能卡片', wait=0.6)
            image, words = area
            frames = find_yellow_focus_frames(image, 100, 175, 100, 180)
            target = self._text_rect(words, self.target)
            if len(frames) != 1 or target is None:
                return self._pending_evidence('function_focus', f'未识别{self.target}或唯一功能焦点')
            focus = frames[0]
            if focus.x1 <= target.center.x <= focus.x2 and focus.y1 <= target.center.y <= focus.y2:
                self._save_evidence('function_selected')
                self.ctx.controller.btn_tap('south')
                self._entered = True
            elif target.center.y > focus.y2:
                self.ctx.controller.btn_tap('dpad_down')
            elif target.center.y < focus.y1:
                self.ctx.controller.btn_tap('dpad_up')
            else:
                self.ctx.controller.btn_tap('dpad_right' if target.center.x > focus.center.x else 'dpad_left')
            return self.round_retry('等待功能焦点或页面切换', wait=0.7)
        if self.round_by_find_area(self.last_screenshot, '菜单-更多功能', '标题-更多功能').is_success:
            self.ctx.controller.btn_tap('east')
            return self.round_retry('从更多功能返回菜单', wait=1)
        menu = self._read_area('菜单', '手柄-底部应用')
        if menu is not None and all(self._text_rect(menu[1], name) is not None for name in ('代理人', '更多')):
            self.ctx.controller.btn_tap('east')
            return self.round_retry('从菜单返回大世界', wait=1)
        if self.round_by_find_area(self.last_screenshot, '大世界-普通', '快捷手册').is_success:
            if not self._opened:
                self.ctx.controller.gamepad.tap_combo(['left_trigger', 'start'])
                self._opened = True
            return self.round_retry('等待功能导览', wait=1)
        return self._pending_evidence('function_entry', '未识别功能导览入口')
