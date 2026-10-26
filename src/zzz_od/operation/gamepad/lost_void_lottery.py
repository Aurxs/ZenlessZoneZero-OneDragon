"""抽奖机沿用剩余次数、原奖励选择和返回大世界的流程。"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

from one_dragon.base.operation.operation_node import operation_node
from zzz_od.operation.gamepad.focus import has_filled_highlight
from zzz_od.operation.gamepad.lost_void_common import GamepadLostVoidChooseCommon
from zzz_od.operation.gamepad.rewards import _GamepadRewardOperation

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class GamepadLostVoidLottery(_GamepadRewardOperation):
    """只操作明确的 1/1 次数，不将分母或其他数字当成剩余机会。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄迷失之地抽奖机', timeout_seconds=120)
        self._started: bool = False
        self._started_at: float = 0
        self._back_sent: bool = False
        self._reward_confirmed: bool = False

    @operation_node(name='使用剩余次数并返回', is_start_node=True, node_max_retry_times=25)
    def use_remaining(self) -> OperationRoundResult:
        """开始只确认一次，获得提示交给原奖励流程，次数归零后返回。"""
        if self.last_screenshot is None:
            return self.round_retry('等待抽奖机截图', wait=1)
        if self.ctx.lost_void.in_normal_world(self.last_screenshot):
            return self.round_success('抽奖机已返回大世界') if self._back_sent else self.round_fail('未确认抽奖机返回来源')
        if self._started:
            common = GamepadLostVoidChooseCommon(self.ctx)
            common.last_screenshot = self.last_screenshot
            if common.can_handle():
                result = common.execute()
                return self.round_retry('抽奖机奖励已确认', wait=1) if result.success else self.round_by_op_result(result)
            if self._known_reward_visible():
                if not self._reward_confirmed:
                    self.ctx.controller.btn_tap('south')
                    self._reward_confirmed = True
                return self.round_retry('等待抽奖机获得弹窗关闭', wait=1)
        current = self.check_and_update_current_screen(self.last_screenshot, screen_name_list=['迷失之地-抽奖机'])
        if current is None:
            return self.round_retry('等待抽奖动画或明确的奖励画面', wait=1)
        if self._back_sent:
            return self.round_retry('等待抽奖机返回', wait=1)
        footer = self._read_area('迷失之地-抽奖机', '手柄-开始提示')
        if footer is None:
            return self.round_retry('等待抽奖机剩余次数', wait=1)
        image, words = footer
        counts = [(re.fullmatch(r'开始([01])/1', ''.join(text.split())), matches.max) for text, matches in words.items()]
        counts = [(match, position) for match, position in counts if match is not None and position is not None]
        if len(counts) != 1:
            return self.round_fail('抽奖机次数或按钮不明确，未发送输入')
        count, position = counts[0]
        if count.group(1) == '0':
            self.ctx.controller.btn_tap('east')
            self._back_sent = True
            return self.round_retry('抽奖机次数已用完，等待返回', wait=1)
        if self._started:
            if time.monotonic() - self._started_at > 8:
                return self.round_fail('抽奖机开始后次数未变化，不重复确认')
            return self.round_retry('等待抽奖机次数变化', wait=1)
        prompts = [matches.max for text, matches in words.items() if text.strip().upper() == 'A' and matches.max is not None]
        if not prompts:
            prompts = list(self.ctx.tm.match_template(image, 'ios_gamepad', 'dialog_a', threshold=0.8))
        if not has_filled_highlight(image, position.rect, 'yellow') or not any(
            prompt.x + prompt.w < position.x and abs(prompt.center.y - position.center.y) <= 40 for prompt in prompts
        ):
            return self.round_retry('等待抽奖机开始按钮和同排A提示', wait=1)
        self.ctx.controller.btn_tap('south')
        self._started = True
        self._started_at = time.monotonic()
        return self.round_retry('等待抽奖机动画', wait=4)
