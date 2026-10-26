"""恶名狩猎周期奖励的手柄领取，复用通用获得弹窗。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from one_dragon.base.operation.operation_node import operation_node
from zzz_od.operation.gamepad.rewards import _GamepadRewardOperation

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class GamepadHuntRewards(_GamepadRewardOperation):
    """只领取当前已完成奖励，不以领奖替代挑战进度。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄恶名狩猎周期领奖', timeout_seconds=45)
        self._opened: bool = False
        self._claim_sent: bool = False
        self._closed: bool = False
        self._empty_frames: int = 0

    @operation_node(name='周期领奖', is_start_node=True, node_max_retry_times=30)
    def claim(self) -> OperationRoundResult:
        """明确标题后才按 X，全领按钮置灰后关闭。"""
        if self._known_reward_visible():
            self.ctx.controller.btn_tap('south')
            return self.round_retry('确认周期奖励获得弹窗', wait=1)
        visible = self.round_by_find_area(
            self.last_screenshot, '恶名狩猎', '手柄-周期挑战标题',
        ).is_success
        if visible:
            self._opened = True
            if self._yellow_text('恶名狩猎', '手柄-周期全部领取', '全部领取'):
                self._empty_frames = 0
                if not self._claim_sent:
                    self._save_evidence('hunt_before_claim')
                    self.ctx.controller.btn_tap('west')
                    self._claim_sent = True
                return self.round_retry('等待周期奖励领取响应', wait=1)
            if not self._has_text('恶名狩猎', '手柄-周期全部领取', '全部领取'):
                return self.round_retry('等待周期奖励按钮', wait=1)
            self._empty_frames += 1
            if self._empty_frames >= 2 and not self._closed:
                self._save_evidence('hunt_after_claim')
                self.ctx.controller.btn_tap('east')
                self._closed = True
            return self.round_retry('等待周期奖励关闭', wait=1)
        if self._has_text('恶名狩猎', '手柄-页面文字', '挑战等级'):
            if self._closed:
                return self.round_success('周期可领取奖励已处理，已回到入口')
            if not self._opened:
                from zzz_od.operation.gamepad.notorious_hunt import (
                    GamepadHuntOpenRewards,
                )

                result = GamepadHuntOpenRewards(self.ctx).execute()
                if not result.success:
                    return self.round_by_op_result(result)
                self._opened = True
            return self.round_retry('等待周期奖励页面', wait=1)
        if self.node_retry_times >= 25:
            self._save_evidence('hunt_rewards_pending')
        return self.round_retry('等待已建档的周期奖励画面', wait=1)
