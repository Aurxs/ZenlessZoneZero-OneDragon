"""手柄模式的可选战斗引导，供各 Boss 操作共用。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.operation.zzz_operation import ZOperation


class GamepadBattleGuide:
    """识别引导后逐页阅读；未出现时不发送任何输入。"""

    def __init__(self) -> None:
        self._page: tuple[int, int] | None = None
        self._attempts: int = 0
        self._unreadable: int = 0

    def handle(self, operation: ZOperation) -> OperationRoundResult | None:
        """返回 None 表示没有引导，由调用者继续原流程。"""
        image = operation.last_screenshot
        if image is None:
            return operation.round_retry('等待战斗引导识别画面', wait=1)
        if not operation.round_by_find_area(image, '画面-通用', '手柄-战斗引导标题').is_success:
            self._page = None
            self._attempts = 0
            self._unreadable = 0
            return None
        ctx = operation.ctx
        area = ctx.screen_loader.get_area('画面-通用', '手柄-战斗引导页码')
        words = ctx.ocr.crop_and_run_ocr(image, area.rect)
        pages = [re.fullmatch(r'\s*(\d+)\s*/\s*(\d+)\s*', text) for text in words]
        page = next(((int(match[1]), int(match[2])) for match in pages
                     if match is not None and 1 <= int(match[1]) <= int(match[2])), None)
        if page is None or not operation.round_by_find_area(
            image, '画面-通用', '手柄-战斗引导返回',
        ).is_success:
            self._unreadable += 1
            if self._unreadable >= 3:
                return operation.round_fail('战斗引导页码或返回提示不清晰，已停止输入')
            return operation.round_retry('等待战斗引导页码和返回提示', wait=1)
        self._unreadable = 0
        if page != self._page:
            self._page = page
            self._attempts = 0
        if self._attempts >= 3:
            return operation.round_fail('战斗引导未响应操作，已停止输入')
        key = 'dpad_right' if page[0] < page[1] else 'east'
        ctx.controller.btn_press(key, press_time=0.2)
        ctx.controller.btn_release(key)
        self._attempts += 1
        return operation.round_retry(
            '等待战斗引导下一页' if key == 'dpad_right' else '等待战斗引导关闭', wait=1,
        )
