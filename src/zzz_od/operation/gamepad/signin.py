"""原生手柄每日签到，沿用每日签到应用的三选一配置。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, ClassVar

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from one_dragon.utils import debug_utils
from zzz_od.operation.gamepad.focus import has_filled_highlight
from zzz_od.operation.zzz_operation import ZOperation

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_base import OperationResult
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class GamepadDailySignIn(ZOperation):
    """只运行用户选择的卦象集录，不额外消耗其他签到次数。"""

    STATUS_AT_TRIGRAMS: ClassVar[str] = '已在卦象界面'
    RIGHT_STICK_DIRECTIONS: ClassVar[tuple[str, ...]] = (
        'right_stick_right', 'right_stick_down', 'right_stick_left', 'right_stick_up',
    )
    ROTATION_SEGMENTS: ClassVar[int] = 12
    MAX_ROTATION_ROUNDS: ClassVar[int] = 3

    def __init__(
        self, ctx: ZContext, selected_sign: str, resume_from_reward: bool = False,
    ) -> None:
        """保留原配置选项，不静默替换签到地点。"""
        super().__init__(ctx, op_name='手柄每日签到', timeout_seconds=120)
        self.selected_sign: str = selected_sign
        self.resume_from_reward: bool = resume_from_reward
        self.evidence: dict[str, str] = {}
        self._interact_sent: bool = False
        self._start_sent: bool = False
        self._gesture_count: int = 0
        self._rotation_rounds: int = 0
        self._active_gesture_key: str | None = None
        self._last_progress: int | None = None
        self._stagnant_rounds: int = 0
        self._last_action_frame_time: float = -1
        self._reward_confirm_sent: bool = False
        self._result_confirm_sent: bool = False
        self._back_sent: bool = False
        self._unknown_rounds: int = 0
        self._return_unknown_rounds: int = 0
        self._already_completed: bool = False

    def handle_init(self) -> None:
        """保留游戏实际状态，从本次截图恢复，清除旧运行输入记录。"""
        self._release_right_stick()
        self.evidence = {}
        self._interact_sent = False
        self._start_sent = False
        self._gesture_count = 0
        self._rotation_rounds = 0
        self._last_progress = None
        self._stagnant_rounds = 0
        self._last_action_frame_time = -1
        self._reward_confirm_sent = False
        self._result_confirm_sent = False
        self._back_sent = False
        self._unknown_rounds = 0
        self._return_unknown_rounds = 0
        self._already_completed = False

    def execute(self) -> OperationResult:
        """完成、停止与异常退出都释放仍在保持的右摇杆方向。"""
        try:
            return super().execute()
        finally:
            self._release_right_stick()

    def handle_pause(self) -> None:
        """暂停回调可重复触发，释放当前方向后不再发送新的动作。"""
        self._release_right_stick()

    def _release_right_stick(self) -> None:
        """只释放本操作正在保持的方向，复用控制器的暂停与断线处理。"""
        key = self._active_gesture_key
        if key is not None:
            try:
                self.ctx.controller.btn_release(key)
            finally:
                self._active_gesture_key = None

    def _rotate_right_stick(self) -> bool:
        """右下左上分段旋转约三秒，动作中不识别画面，每段可暂停或停止。"""
        for index in range(self.ROTATION_SEGMENTS):
            if self.ctx.run_context.is_context_stop or self.ctx.run_context.is_context_pause:
                return False
            if self._gesture_count >= self.ROTATION_SEGMENTS * self.MAX_ROTATION_ROUNDS:
                return False
            key = self.RIGHT_STICK_DIRECTIONS[index % len(self.RIGHT_STICK_DIRECTIONS)]
            self._active_gesture_key = key
            try:
                self.ctx.controller.btn_press(key, press_time=0.25)
            finally:
                self._release_right_stick()
            self._gesture_count += 1
        return True

    def _found(self, area_name: str) -> bool:
        """只查实拍建档的卦象区域，不产生输入。"""
        return self.last_screenshot is not None and self.round_by_find_area(
            self.last_screenshot, '卦象集录', area_name
        ).is_success

    def _main_visible(self) -> bool:
        """主界面文字保留在已完成态，不能仅凭占卜提示判断可领取。"""
        return self._found('手柄-标题') and self._found('手柄-占卜提示')

    def _main_state(self) -> str | None:
        """用中央開/闭封面模板区分可占卜和已完成，不重复开始。"""
        if not self._main_visible():
            return None
        available = self._found('手柄-可占卜封面')
        completed = self._found('手柄-已完成封面')
        if available == completed:
            return None
        return 'completed' if completed else 'available'

    def _save_evidence(self, state: str) -> None:
        """第一次出现的起点、进度和未建档结果保存原始 PNG。"""
        if state not in self.evidence and self.last_screenshot is not None:
            image_name = self.save_screenshot(prefix=f'macos_signin_{state}')
            self.evidence[state] = debug_utils.get_debug_image_path(image_name)

    def _progress(self) -> int | None:
        """进度必须是单一百分数，文字缺失或数值冲突不继续摇杆。"""
        area = self.ctx.screen_loader.get_area('卦象集录', '手柄-占卜进度')
        if area is None or self.last_screenshot is None:
            return None
        values: set[int] = set()
        for text in self.ctx.ocr.crop_and_run_ocr(self.last_screenshot, area.rect):
            match = re.fullmatch(r'\s*(\d{1,3})\s*[%％]\s*', text)
            if match is not None and int(match[1]) <= 100:
                values.add(int(match[1]))
        return next(iter(values)) if len(values) == 1 else None

    def _reward_visible(self) -> bool:
        """奖励标题、选择提示与确认黄填充同时存在，才识别已建档奖励页。"""
        if not (self._found('手柄-奖励标题') and self._found('手柄-奖励选择提示')):
            return False
        area = self.ctx.screen_loader.get_area('卦象集录', '手柄-奖励确认')
        if area is None or self.last_screenshot is None:
            return False
        rect = area.rect
        image = self.last_screenshot[rect.y1:rect.y2, rect.x1:rect.x2]
        results = self.ctx.ocr.crop_and_run_ocr(self.last_screenshot, rect)
        return bool(image.size) and any(
            text.replace(' ', '') == '确认' and matches.max is not None
            and has_filled_highlight(image, matches.max.rect, 'yellow')
            for text, matches in results.items()
        )

    def _result_visible(self) -> bool:
        """结果页需同时有确认、解卦和娱乐说明，卦象文字本身会变化。"""
        return all(self._found(area) for area in (
            '手柄-结果确认', '手柄-结果解卦', '手柄-娱乐说明',
        ))

    def _result_data(self) -> dict:
        """输出本次实际执行范围，奖励恢复不能充当完整占卜证据。"""
        return {
            'evidence': dict(self.evidence),
            'resumed_from_reward': self.resume_from_reward,
            'started_from_world': 'world_before' in self.evidence,
            'right_stick_segments': self._gesture_count,
            'right_stick_rotation_rounds': self._rotation_rounds,
            'already_completed': self._already_completed,
        }

    def _unmodeled_result(self, reason: str) -> OperationRoundResult:
        """保留现场供补档，不尝试未确认的领奖或返回按键。"""
        self._save_evidence('result_pending')
        return self.round_fail(reason, data=self._result_data())

    @operation_node(name='检查签到配置', is_start_node=True, screenshot_before_round=False)
    def check_config(self) -> OperationRoundResult:
        """未建档的签到玩法不进入 PC 点击或拖动流程。"""
        if self.selected_sign != 'trigrams_collection':
            return self.round_fail(f'Mac 每日签到尚未支持所选项目“{self.selected_sign}”')
        return self.round_success()

    @node_from(from_name='检查签到配置')
    @operation_node(name='确认签到起点')
    def check_entry(self) -> OperationRoundResult:
        """支持从已打开的主界面或占卜进度恢复，不重复传送或开始。"""
        if self._main_visible() or self._found('手柄-摇杆提示'):
            self._save_evidence('entry')
            return self.round_success(self.STATUS_AT_TRIGRAMS)
        if self.resume_from_reward and (self._reward_visible() or self._result_visible()):
            self._save_evidence('reward_resume_before')
            return self.round_success(self.STATUS_AT_TRIGRAMS)
        if self.last_screenshot is not None and self.round_by_find_area(
            self.last_screenshot, '大世界-普通', '快捷手册'
        ).is_success:
            self._save_evidence('world_before')
            return self.round_success()
        return self._unmodeled_result('签到起点未建档，已保存截图')

    @node_from(from_name='确认签到起点')
    @operation_node(name='传送至阿朔', screenshot_before_round=False)
    def transport(self) -> OperationRoundResult:
        """复用公共地图传送，传送后不追加没有依据的移动。"""
        from zzz_od.operation.gamepad.transport import GamepadTransport

        return self.round_by_op_result(
            GamepadTransport(self.ctx, '澄辉坪', '阿朔').execute(), wait=1
        )

    @node_from(from_name='传送至阿朔')
    @operation_node(name='与阿朔交互', node_max_retry_times=8, timeout_seconds=15)
    def interact(self) -> OperationRoundResult:
        """沿用原应用：传送成功并等待后直接交互，以功能页确认进入。"""
        if self._main_visible() or self._found('手柄-摇杆提示'):
            return self.round_success()
        if not self._interact_sent:
            self._save_evidence('npc_before')
            self.ctx.controller.interact(press=True, press_time=0.2, release=True)
            self._interact_sent = True
        if self.node_retry_times >= 6:
            self._save_evidence('npc_interaction_pending')
        return self.round_retry('等待阿朔卦象界面', wait=1)

    @node_from(from_name='确认签到起点', status=STATUS_AT_TRIGRAMS)
    @node_from(from_name='与阿朔交互')
    @operation_node(name='领取卦象', node_max_retry_times=60, timeout_seconds=50)
    def collect(self) -> OperationRoundResult:
        """每轮先旋转右摇杆三秒，再由下一帧核对结果或进度。"""
        if self.last_screenshot is None:
            return self.round_retry('截图无效', wait=0.5)
        if self._reward_visible():
            self._unknown_rounds = 0
            if self._gesture_count == 0 and not self.resume_from_reward:
                return self._unmodeled_result('未确认奖励来源为本次占卜，已保存截图')
            self._save_evidence('reward_before')
            if not self._reward_confirm_sent:
                self.ctx.controller.btn_tap('south')
                self._reward_confirm_sent = True
                # 结果页可能先于奖励弹窗出现；关闭弹窗后需再次确认结果。
                self._result_confirm_sent = False
            return self.round_retry('等待卦象奖励确认结束', wait=0.8)
        if self._result_visible():
            if not (self._gesture_count > 0 or self._reward_confirm_sent or self.resume_from_reward):
                return self._unmodeled_result('未确认卦象结果来源，已保存截图')
            self._unknown_rounds = 0
            self._save_evidence('trigram_result_before')
            if not self._result_confirm_sent:
                self.ctx.controller.btn_tap('south')
                self._result_confirm_sent = True
            return self.round_retry('等待卦象结果确认结束', wait=0.8)
        if self._found('手柄-摇杆提示'):
            self._unknown_rounds = 0
            progress = self._progress()
            self._save_evidence('rotation_prompt' if progress is None else f'progress_{progress}')
            if progress == 100:
                return self.round_retry('卦象进度已满，等待结果页', wait=0.5)
            if self.last_screenshot_time <= self._last_action_frame_time:
                return self.round_retry('等待占卜动作后的新帧', wait=0.3)
            if progress is not None and self._last_progress is not None:
                if progress < self._last_progress:
                    return self._unmodeled_result('卦象进度倒退，已停止并保存截图')
                self._stagnant_rounds = self._stagnant_rounds + 1 if progress == self._last_progress else 0
            if (
                self._stagnant_rounds >= 3
                or self._rotation_rounds >= self.MAX_ROTATION_ROUNDS
                or self._gesture_count >= self.ROTATION_SEGMENTS * self.MAX_ROTATION_ROUNDS
            ):
                return self._unmodeled_result('卦象进度未按预期增加，已停止并保存截图')
            self._last_progress = progress
            self._last_action_frame_time = self.last_screenshot_time
            if self._rotate_right_stick():
                self._rotation_rounds += 1
            return self.round_retry('等待三秒右摇杆旋转后的新帧', wait=0.3)
        main_state = self._main_state()
        if main_state == 'completed':
            self._unknown_rounds = 0
            self._already_completed = not (
                self._reward_confirm_sent or self._result_confirm_sent or self._gesture_count > 0
            )
            self._save_evidence('main_completed')
            return self.round_success()
        if main_state == 'available' and (self._reward_confirm_sent or self._result_confirm_sent):
            self._unknown_rounds = 0
            self._save_evidence('main_after')
            return self.round_success()
        if main_state == 'available' and self._gesture_count == 0:
            self._unknown_rounds = 0
            self._save_evidence('main_before')
            if not self._start_sent:
                self.ctx.controller.btn_tap('south')
                self._start_sent = True
            return self.round_retry('等待右摇杆占卜提示', wait=0.8)
        if self._interact_sent or self._start_sent or self._gesture_count > 0 or self._reward_confirm_sent or self._result_confirm_sent:
            self._unknown_rounds += 1
            if self._unknown_rounds <= 3:
                return self.round_retry('等待卦象动作后的稳定画面，未发送输入', wait=0.5)
        return self._unmodeled_result('卦象结果或提示尚未建档，已保存截图，未发送确认')

    @node_from(from_name='领取卦象')
    @operation_node(name='签到后返回大世界', node_max_retry_times=10, timeout_seconds=15)
    def return_to_world(self) -> OperationRoundResult:
        """奖励确认后只在已知卦象主界面返回，最终截图确认大世界。"""
        if self.last_screenshot is not None and self.round_by_find_area(
            self.last_screenshot, '大世界-普通', '快捷手册'
        ).is_success:
            self._save_evidence('world_after')
            return self.round_success(
                '奖励恢复确认完成' if self.resume_from_reward
                else ('今日已领取' if self._already_completed else '领取成功'),
                data=self._result_data(),
            )
        if self._main_state() is not None:
            self._return_unknown_rounds = 0
            if not self._back_sent:
                self.ctx.controller.btn_tap('east')
                self._back_sent = True
            return self.round_retry('等待签到后返回大世界', wait=0.8)
        self._return_unknown_rounds += 1
        if self._return_unknown_rounds <= 3:
            return self.round_retry('等待签到返回后的稳定画面，未发送输入', wait=0.8)
        return self._unmodeled_result('签到返回画面尚未建档，已保存截图')
