"""手柄结果分别核对道中完成关卡与最终胜利标识、真实奖励增量。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from one_dragon.base.operation.operation_node import operation_node
from zzz_od.application.hollow_zero.lost_void.lost_void_challenge_config import (
    LostVoidRegionType,
)
from zzz_od.application.hollow_zero.lost_void.operation.lost_void_run_level import (
    LostVoidRunLevel,
)
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation
from zzz_od.operation.gamepad.transport_by_compendium import (
    GamepadTransportByCompendium,
)

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class GamepadLostVoidBattleResult(GamepadOperation):
    """通过完成关卡和底栏按键确认实际胜利，X失败页不累计通关。"""

    def __init__(self, ctx: ZContext, investigation_completed: bool = False) -> None:
        super().__init__(ctx, op_name='手柄迷失之地挑战结果', timeout_seconds=25)
        self.navigation: GamepadTransportByCompendium = GamepadTransportByCompendium(
            ctx, '作战', '周期征讨'
        )
        self._sent: bool = False
        self._status: str | None = None
        self._next_region: str | None = None
        self.investigation_completed: bool = investigation_completed

    @operation_node(
        name='确认胜利与结果去向', is_start_node=True, node_max_retry_times=15
    )
    def confirm(self) -> OperationRoundResult:
        if self.last_screenshot is None:
            return self.round_retry('等待结果截图', wait=1)
        title = self.round_by_find_area(
            self.last_screenshot, '迷失之地-挑战结果', '标题-挑战结果'
        ).is_success
        if self._sent:
            if not title:
                self.save_screenshot(prefix='macos_lost_void_result_confirmed')
                return self.round_success(self._status, data=self._next_region)
            return self.round_retry('等待已确认的挑战结果关闭', wait=1)
        if not title:
            return self.round_retry('等待挑战结果标题', wait=1)
        nav = self.navigation
        nav.last_screenshot = self.last_screenshot
        objective = nav._read_area('迷失之地-挑战结果', '手柄-完成关卡')
        actions = nav._read_area('迷失之地-挑战结果', '手柄-结果底栏')
        completed = (
            nav._text_rect(objective[1], '完成关卡') if objective is not None else None
        )
        ratios = (
            [
                match
                for text, matches in objective[1].items()
                if re.search(r'1\s*/\s*1', text)
                for match in matches
            ]
            if objective is not None
            else []
        )
        won = completed is not None and any(
            abs(match.center.y - completed.center.y) < 30 for match in ratios
        )
        if actions is None:
            return self.round_retry('等待结果底栏', wait=1)
        if all(nav._text_rect(actions[1], word) is not None for word in ('A', '确定')):
            if not won:
                return self._wait_victory_evidence()
            key = 'south'
            self._status = LostVoidRunLevel.STATUS_NEXT_LEVEL
            self._next_region = LostVoidRegionType.FRIENDLY_TALK.value.value
        elif all(
            nav._text_rect(actions[1], word) is not None for word in ('B', '完成')
        ):
            if not won:
                gain = nav._read_area('迷失之地-挑战结果', '手柄-最终结晶')
                values = (
                    [
                        int(match[1])
                        for text in gain[1]
                        if (match := re.search(r'[+＋]\s*(\d+)', text))
                    ]
                    if gain
                    else []
                )
                final_grade = (
                    self.investigation_completed
                    or self.round_by_find_area(
                        self.last_screenshot,
                        '迷失之地-挑战结果',
                        '手柄-最终S评级',
                    ).is_success
                )
                if not final_grade or not values or max(values) <= 0:
                    return self._wait_victory_evidence()
            key = 'east'
            self._status = LostVoidRunLevel.STATUS_COMPLETE
            self._next_region = LostVoidRegionType.ENTRY.value.value
        else:
            return self.round_retry('未确认结果操作按键', wait=1)
        self.save_screenshot(prefix='macos_lost_void_result_won')
        self.ctx.controller.btn_tap(key)
        self._sent = True
        return self.round_retry('等待挑战结果确认生效', wait=1)

    def _wait_victory_evidence(self) -> OperationRoundResult:
        """中途须完成关卡，最终须调查完成或S评级及实际结晶增量。"""
        if self.node_retry_times >= 4:
            self.save_screenshot(prefix='macos_lost_void_result_not_won')
            return self.round_fail('未确认实际胜利，不累计通关')
        return self.round_retry('等待实际完成关卡证据', wait=1)
