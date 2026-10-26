"""迷失之地以太活性按实际勾选与总值调整，默认保持游戏设置。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from one_dragon.base.operation.operation_node import operation_node
from zzz_od.operation.gamepad.focus import find_yellow_frames, text_inside_frame
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation
from zzz_od.operation.gamepad.transport_by_compendium import (
    GamepadTransportByCompendium,
)

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class GamepadLostVoidSetActivity(GamepadOperation):
    """每次只改变一个已确认选项，读到预期总值变化后才能继续。"""

    def __init__(self, ctx: ZContext, target: int = -1) -> None:
        super().__init__(ctx, op_name='手柄设置以太活性', timeout_seconds=90)
        self.target: int = target
        self.navigation: GamepadTransportByCompendium = GamepadTransportByCompendium(ctx, '作战', '周期征讨')
        self._pending: int | None = None
        self._moved: bool = False
        self._opened: bool = False
        self._previous: str | None = None
        self._unchanged: int = 0
        self._reversed: bool = False
        self._direction: str = 'dpad_down'
        self._changed: set[str] = set()
        self._pending_waits: int = 0

    def read_activity(self) -> tuple[int, int] | None:
        """只解析活性专属栏的分数，不能把悬赏进度当成活性。"""
        nav = self.navigation
        nav.last_screenshot = self.last_screenshot
        area = nav._read_area('迷失之地-战线肃清', '手柄-活性数值')
        if area is None or nav._text_rect(area[1], '以太活性') is None:
            return None
        values = [re.search(r'(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})(?!\d)', text) for text in area[1]]
        parsed = {(int(match[1]), int(match[2])) for match in values if match is not None}
        return next(iter(parsed)) if len(parsed) == 1 else None

    @operation_node(name='设置并核对活性', is_start_node=True, node_max_retry_times=45)
    def set_activity(self) -> OperationRoundResult:
        """维持默认时不输入；目标范围以当帧显示的上限为准。"""
        if type(self.target) is not int or self.target < -1:
            return self.round_fail('以太活性必须为维持游戏设置或非负整数')
        if self.last_screenshot is None:
            return self.round_retry('等待有效游戏截图', wait=1)
        if not self.round_by_find_area(self.last_screenshot, '迷失之地-战线肃清', '标题-战线肃清').is_success:
            return self.round_retry('等待战线肃清准备页', wait=1)
        value = self.read_activity()
        if value is None:
            return self.round_retry('未能读取以太活性实际值', wait=1)
        current, maximum = value
        if not 0 <= current <= maximum or maximum > 12 or self.target > maximum:
            return self.round_fail(f'以太活性配置或画面数值无效：目标{self.target}，当前{current}/{maximum}')
        if self._pending is not None:
            if current != self._pending:
                self._pending_waits += 1
                if self._pending_waits >= 3:
                    return self.round_fail('活性选项操作未产生预期数值变化，已停止')
                return self.round_retry('等待单个活性选项改变后的实际值', wait=1)
            self._pending = None
            self._pending_waits = 0
            if current != self.target:
                self.ctx.controller.btn_tap(self._direction)
                return self.round_retry('等待下一活性选项', wait=1)
        if self.target == -1 or current == self.target:
            self.save_screenshot(prefix='macos_lost_void_activity_verified')
            return self.round_success('以太活性已核对', data={'activity': current, 'maximum': maximum})
        nav = self.navigation
        panel = nav._read_area('迷失之地-战线肃清', '手柄-以太活性')
        if panel is None:
            return self.round_retry('等待活性面板', wait=1)
        if nav._text_rect(panel[1], '选择周期增益') is not None:
            # B 先退出周期增益的子焦点，不能将增益单选框当作活性开关。
            if not self._moved:
                self.ctx.controller.btn_tap('east')
                self._moved = True
                return self.round_retry('退出周期增益行焦点', wait=1)
            import cv2

            from zzz_od.operation.gamepad.focus import highlight_mask

            contours, _ = cv2.findContours(highlight_mask(panel[0], 'yellow'), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            boxes = [cv2.boundingRect(c) for c in contours]
            summary = nav._text_rect(panel[1], '以太活性')
            if summary and any(x < summary.x1 < summary.x2 < x + w and y < summary.y1 < summary.y2 < y + h
                               for x, y, w, h in boxes if w > 700 and 50 < h < 120):
                if not self._opened:
                    self.ctx.controller.btn_tap('south')
                    self._opened = True
            else:
                self.ctx.controller.btn_tap('dpad_down')
            return self.round_retry('打开以太活性选项面板', wait=1)
        area = nav._read_area('迷失之地-战线肃清', '手柄-活性选项')
        if area is None:
            return self.round_retry('等待活性选项', wait=1)
        image, words = area
        frames = find_yellow_frames(image)
        selected = [frame for frame in frames if frame.height < 160]
        if len(selected) != 1:
            # 收起态只在周期增益外框已确认时移动到下方活性栏。
            panel = nav._read_area('迷失之地-战线肃清', '手柄-以太活性')
            if panel is not None:
                summary = nav._text_rect(panel[1], '以太活性')
                panel_frames = find_yellow_frames(panel[0])
                if summary and text_inside_frame(summary, panel_frames) and not self._opened:
                    self.ctx.controller.btn_tap('south')
                    self._opened = True
                elif summary and not self._moved:
                    self.ctx.controller.btn_tap('dpad_down')
                    self._moved = True
            return self.round_retry('等待活性选项焦点', wait=1)
        frame = selected[0]
        labels = [text for text, matches in words.items() if matches.max is not None
                  and matches.max.center.x < 700 and text_inside_frame(matches.max.rect, [frame])]
        name = ''.join(labels)
        if not name:
            return self.round_retry('未读取到焦点活性说明', wait=1)
        if name == self._previous:
            self._unchanged += 1
            if self._unchanged >= 2 and not self._reversed:
                self._direction = 'dpad_up'
                self._reversed = True
                self._unchanged = 0
                self.ctx.controller.btn_tap(self._direction)
            elif self._unchanged >= 3:
                return self.round_fail('活性选项焦点未响应或已遍历，停止调整')
            return self.round_retry('等待活性焦点移动', wait=1)
        self._previous = name
        self._unchanged = 0
        row = image[frame.y1:frame.y2, max(frame.x1, frame.x2 - 90):frame.x2]
        checked = self.ctx.tm.match_template(row, 'ios_gamepad', 'lost_void_activity_checked', threshold=0.9).max is not None
        unchecked = self.ctx.tm.match_template(row, 'ios_gamepad', 'lost_void_activity_unchecked', threshold=0.9).max is not None
        if checked == unchecked:
            return self.round_fail('活性选项勾选状态不明确，未切换')
        if name not in self._changed and (checked and current > self.target or unchecked and current < self.target):
            self.ctx.controller.btn_tap('south')
            self._pending = current - 1 if checked else current + 1
            self._changed.add(name)
        else:
            self.ctx.controller.btn_tap(self._direction)
        return self.round_retry('等待单项活性调整确认', wait=1)
