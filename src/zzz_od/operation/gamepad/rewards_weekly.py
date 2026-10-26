"""丽都周纪手柄领取九宫格积分与已达到的积分特赏。"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import numpy as np

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from zzz_od.operation.gamepad.rewards import (
    GamepadOpenRiduWeekly,
    _GamepadRewardOperation,
)
from zzz_od.operation.gamepad.transport import find_yellow_focus_frames

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class GamepadRiduWeekly(_GamepadRewardOperation):
    """按当前九宫格焦点领取已完成任务，再领取当前特赏。"""

    def __init__(self, ctx: ZContext) -> None:
        """保持原周纪应用只领奖、不完成周任务的范围。"""
        super().__init__(ctx, op_name='手柄丽都周纪奖励', timeout_seconds=90)
        self._claim_sent: bool = False
        self._confirmation_sent: bool = False
        self._weekly_back_sent: bool = False
        self._daily_back_sent: bool = False
        self._result_status: str = ''
        self._pending_task: int | None = None
        self._pending_waits: int = 0
        self._claimed_tasks: list[int] = []
        self._navigation_steps: int = 0

    def handle_init(self) -> None:
        """每次运行重新读取任务和可领取提示，不沿用旧帧判断。"""
        self.evidence_paths.clear()
        self._claim_sent = False
        self._confirmation_sent = False
        self._weekly_back_sent = False
        self._daily_back_sent = False
        self._result_status = ''
        self._pending_task = None
        self._pending_waits = 0
        self._claimed_tasks = []
        self._navigation_steps = 0

    def focused_task(self) -> int | None:
        """从九宫格黄色外框取行列，不把任务名或变化的积分当焦点。"""
        if self.last_screenshot is None:
            return None
        area = self.ctx.screen_loader.get_area('丽都周纪', '手柄-九宫格')
        if area is None:
            return None
        rect = area.rect
        image = self.last_screenshot[rect.y1:rect.y2, rect.x1:rect.x2]
        frames = find_yellow_focus_frames(image, 260, 350, 180, 260)
        if len(frames) != 1:
            return None
        center = frames[0].center
        return min(2, int(center.y * 3 / image.shape[0])) * 3 + min(2, int(center.x * 3 / image.shape[1])) + 1

    def _weekly_visible(self) -> bool:
        """积分特赏和累计积分同时出现，才确认处于周纪页面。"""
        area = self._read_area('丽都周纪', '手柄-页面文字')
        return area is not None and all(
            self._text_rect(area[1], text) is not None for text in ('积分特赏', '累计获取积分')
        )

    def grid_state(self) -> tuple[list[int], list[int], list[int], list[int]]:
        """按从左到右、从上到下的 1～9 格区分已领、未完成、可领及未知。"""
        area = self._read_area('丽都周纪', '手柄-九宫格')
        if area is None:
            return [], [], [], list(range(1, 10))
        image, results = area
        words: list[list[str]] = [[] for _ in range(9)]
        for text, matches in results.items():
            for match in matches:
                row = min(2, int(match.center.y * 3 / image.shape[0]))
                column = min(2, int(match.center.x * 3 / image.shape[1]))
                words[row * 3 + column].append(text.replace(' ', ''))
        completed: list[int] = []
        unfinished: list[int] = []
        claimable: list[int] = []
        unknown: list[int] = []
        for index, texts in enumerate(words, start=1):
            if any(text == '完成' or 'BINGO' in text.upper().replace('0', 'O') for text in texts):
                completed.append(index)
                continue
            progress = [re.search(r'(\d+)\s*/\s*(\d+)', text) for text in texts]
            values = {(int(match[1]), int(match[2])) for match in progress if match is not None}
            if len(values) != 1:
                unknown.append(index)
                continue
            current, target = next(iter(values))
            if target <= 0:
                unknown.append(index)
            elif current < target:
                unfinished.append(index)
            else:
                claimable.append(index)
        return completed, unfinished, claimable, unknown

    def claim_available(self) -> bool:
        """X 提示启用时文字亮白，灰色提示不能触发输入。"""
        area = self._read_area('丽都周纪', '手柄-底部提示')
        if area is None:
            return False
        image, words = area
        rect = self._text_rect(words, '领取积分特赏')
        if rect is None:
            return False
        crop = image[rect.y1:rect.y2, rect.x1:rect.x2]
        return bool(crop.size and np.mean(np.all(crop > 190, axis=2)) >= 0.15)

    @operation_node(name='检查周纪起点', is_start_node=True)
    def check_entry(self) -> OperationRoundResult:
        """已在周纪时直接识别，不重复打开手册。"""
        if self._weekly_visible():
            return self.round_success('已在周纪')
        if self._known_reward_visible():
            return self._pending_evidence('weekly_unrelated_reward', '未确认已有获得弹窗属于本次周纪领取')
        return self.round_success()

    @node_from(from_name='检查周纪起点')
    @operation_node(name='打开周纪')
    def open_weekly(self) -> OperationRoundResult:
        """复用已验证的日常入口和周纪焦点导航。"""
        return self.round_by_op_result(GamepadOpenRiduWeekly(self.ctx).execute())

    @node_from(from_name='检查周纪起点', status='已在周纪')
    @node_from(from_name='打开周纪')
    @operation_node(name='检查周纪任务积分', node_max_retry_times=30, timeout_seconds=60)
    def check_score_tasks(self) -> OperationRoundResult:
        """按已完成任务选择焦点，领取后核对完成或 BINGO 常态文字。"""
        if not self._weekly_visible():
            return self.round_retry('等待周纪稳定页面', wait=0.8)
        if not self._save_evidence('weekly_before'):
            return self.round_fail('周纪领取前截图保存失败')
        completed, _, claimable, unknown = self.grid_state()
        if self._pending_task is not None:
            if self._pending_task in completed:
                self._claimed_tasks.append(self._pending_task)
                self._pending_task = None
                self._pending_waits = 0
                self._save_evidence('weekly_scores_after')
            else:
                self._pending_waits += 1
                if self._pending_waits > 6:
                    return self._pending_evidence('weekly_score_unchanged', '领取后任务未出现完成标记')
                return self.round_retry('等待周纪积分领取完成', wait=0.5)
        if claimable:
            focused = self.focused_task()
            if focused is None:
                return self.round_retry('等待九宫格焦点', wait=0.5)
            target = focused if focused in claimable else claimable[0]
            if focused != target:
                if self._navigation_steps >= 36:
                    return self._pending_evidence('weekly_navigation_limit', '九宫格焦点移动超限')
                row, col = divmod(focused - 1, 3)
                target_row, target_col = divmod(target - 1, 3)
                key = ('dpad_down' if row < target_row else 'dpad_up') if row != target_row else (
                    'dpad_right' if col < target_col else 'dpad_left'
                )
                self.ctx.controller.btn_tap(key)
                self._navigation_steps += 1
                return self.round_retry('等待周纪目标格焦点', wait=0.5)
            if not self._yellow_text('丽都周纪', '手柄-任务领取', '领取'):
                return self.round_retry('等待任务详情的领取提示', wait=0.5)
            self._save_evidence(f'weekly_task_{target}_before')
            self.ctx.controller.btn_tap('south')
            self._pending_task = target
            return self.round_retry('等待周纪积分领取完成', wait=1)
        if unknown:
            return self._pending_evidence('weekly_unknown_tasks', f'周纪第 {unknown} 格状态未知')
        return self.round_success()

    @node_from(from_name='检查周纪任务积分')
    @operation_node(name='领取周纪特赏', node_max_retry_times=4, timeout_seconds=8)
    def claim_special_reward(self) -> OperationRoundResult:
        """可领特赏时只按一次 X；当前灰色提示正常跳过。"""
        if not self._weekly_visible():
            return self.round_retry('等待周纪页面', wait=0.8)
        if self._claim_sent:
            return self.round_success()
        if self.claim_available():
            self.ctx.controller.btn_tap('west')
            self._claim_sent = True
            return self.round_success(wait=1)
        if self._has_text('丽都周纪', '手柄-底部提示', '领取积分特赏'):
            self._result_status = '周纪任务积分领取完成，暂无可领特赏' if self._claimed_tasks else '周纪当前无可领取积分或特赏'
            return self.round_success('无可领取特赏')
        return self._pending_evidence('weekly_unknown_prompt', '周纪特赏领取提示未知')

    @node_from(from_name='领取周纪特赏')
    @operation_node(name='确认周纪特赏', node_max_retry_times=6, timeout_seconds=12)
    def confirm_special_reward(self) -> OperationRoundResult:
        """只确认本组件发起的已知获得弹窗，其他结果保留现场。"""
        if self._claim_sent and self._known_reward_visible():
            if not self._save_evidence('weekly_before_confirm'):
                return self.round_fail('周纪确认前截图保存失败')
            if not self._confirmation_sent:
                self.ctx.controller.btn_tap('south')
                self._confirmation_sent = True
            return self.round_retry('等待周纪奖励确认返回', wait=0.8)
        if self._confirmation_sent and self._weekly_visible() and not self.claim_available():
            self._save_evidence('weekly_after_confirm')
            self._result_status = '周纪当前特赏领取完成'
            return self.round_success()
        return self._pending_evidence('weekly_unknown_result', '周纪领奖结果尚未建档')

    @node_from(from_name='领取周纪特赏', status='无可领取特赏')
    @node_from(from_name='确认周纪特赏')
    @operation_node(name='周纪返回大世界', node_max_retry_times=10, timeout_seconds=15)
    def back_to_world(self) -> OperationRoundResult:
        """逐帧确认周纪、日常和大世界，每个页面只按一次 B。"""
        if self.last_screenshot is not None and self.round_by_find_area(
            self.last_screenshot, '大世界-普通', '快捷手册'
        ).is_success:
            self._save_evidence('weekly_world')
            return self.round_success(self._result_status, data={
                'evidence_paths': self.evidence_paths,
                'claimed_by_operation': self._claim_sent,
                'claimed_tasks': list(self._claimed_tasks),
            })
        if self._weekly_visible():
            self._save_evidence('weekly_result')
            if not self._weekly_back_sent:
                self.ctx.controller.btn_tap('east')
                self._weekly_back_sent = True
            return self.round_retry('等待周纪返回日常', wait=0.8)
        if self._daily_visible():
            if not self._daily_back_sent:
                self.ctx.controller.btn_tap('east')
                self._daily_back_sent = True
            return self.round_retry('等待周纪返回大世界', wait=0.8)
        return self._pending_evidence('weekly_unknown_return', '周纪返回画面尚未建档')
