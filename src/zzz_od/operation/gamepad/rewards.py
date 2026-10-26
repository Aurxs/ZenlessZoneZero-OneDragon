"""每日及周期奖励的原生手柄操作。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from one_dragon.utils import debug_utils
from zzz_od.operation.gamepad.focus import has_filled_highlight, highlight_mask
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation

if TYPE_CHECKING:
    from cv2.typing import MatLike

    from one_dragon.base.geometry.rectangle import Rect
    from one_dragon.base.matcher.match_result import MatchResultList
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class _GamepadRewardOperation(GamepadOperation):
    """只在已建档的局部区域读取提示和焦点。"""

    def __init__(self, ctx: ZContext, op_name: str, timeout_seconds: float = -1) -> None:
        """每次领取都保存前后证据，未知页面返回待补证据。"""
        super().__init__(ctx, op_name=op_name, timeout_seconds=timeout_seconds)
        self.evidence_paths: dict[str, str] = {}

    def _save_evidence(self, phase: str) -> str:
        """同一阶段只保存一次；领取前无法保存时不继续输入。"""
        if phase not in self.evidence_paths:
            image_name = self.save_screenshot(prefix=f'macos_rewards_{phase}')
            if image_name:
                self.evidence_paths[phase] = debug_utils.get_debug_image_path(image_name)
        return self.evidence_paths.get(phase, '')

    def _pending_evidence(self, phase: str, reason: str) -> OperationRoundResult:
        """保存现场并结束本次执行，外部观察期间不占用运行线程。"""
        path = self._save_evidence(phase)
        return self.round_fail(
            f'待补画面证据：{reason}，截图：{path}',
            data={'pending': True, 'evidence_paths': self.evidence_paths},
        )

    def _read_area(
        self, screen_name: str, area_name: str
    ) -> tuple[MatLike, dict[str, MatchResultList]] | None:
        """缺少资源或有效截图时不推断当前页面。"""
        area = self.ctx.screen_loader.get_area(screen_name, area_name)
        if area is None or self.last_screenshot is None:
            return None
        rect = area.rect
        image = self.last_screenshot[rect.y1:rect.y2, rect.x1:rect.x2]
        if not image.size:
            return None
        return image, self.ctx.ocr.crop_and_run_ocr(self.last_screenshot, rect)

    @staticmethod
    def _text_rect(results: dict[str, MatchResultList], target: str) -> Rect | None:
        """只接受完整目标文字，忽略 OCR 插入的空格。"""
        for text, matches in results.items():
            if target in text.replace(' ', '') and matches.max is not None:
                return matches.max.rect
        return None

    def _has_text(self, screen_name: str, area_name: str, text: str) -> bool:
        """目标文字必须位于对应画面区域内。"""
        area = self._read_area(screen_name, area_name)
        return area is not None and self._text_rect(area[1], text) is not None

    def _yellow_text(self, screen_name: str, area_name: str, text: str) -> bool:
        """只接受提示文字自身的黄色启用颜色。"""
        area = self._read_area(screen_name, area_name)
        if area is None:
            return False
        image, results = area
        rect = self._text_rect(results, text)
        if rect is None:
            return False
        text_image = image[rect.y1:rect.y2, rect.x1:rect.x2]
        if not text_image.size:
            return False
        mask = highlight_mask(text_image, 'yellow')
        return bool(np.count_nonzero(mask) / mask.size >= 0.15)

    def _daily_visible(self) -> bool:
        """日常文字周围的黄色标签填充是页面判断依据。"""
        area = self._read_area('快捷手册', '手柄-顶部标签')
        if area is None:
            return False
        image, results = area
        rect = self._text_rect(results, '日常')
        return rect is not None and has_filled_highlight(image, rect, 'yellow')

    def _known_reward_visible(self) -> bool:
        """复用实拍获得弹窗的标题、黄确认及按钮下方 A 选择提示。"""
        title = self._read_area('道具处理-获得', '标题-获得')
        if title is None or not any(text.replace(' ', '') == '获得' for text in title[1]):
            return False
        if not self._has_text('道具处理-获得', '手柄-奖励选择提示', '选择'):
            return False
        area = self._read_area('道具处理-获得', '手柄-奖励确认')
        if area is None:
            return False
        image, results = area
        rect = self._text_rect(results, '确认')
        return rect is not None and has_filled_highlight(image, rect, 'yellow')


class GamepadEngagementReward(_GamepadRewardOperation):
    """领取当前可领的活跃度奖励，再沿用原应用的最高档检查。"""

    def __init__(self, ctx: ZContext, resume_from_reward: bool = False) -> None:
        """未知奖励页结束并保留第一次领取后的现场。"""
        super().__init__(ctx, op_name='手柄活跃度奖励', timeout_seconds=90)
        self.resume_from_reward: bool = resume_from_reward
        self._claim_sent: bool = False
        self._confirmation_sent: bool = False
        self._back_sent: bool = False
        self._full_engagement: bool = False
        self._result_status: str = ''
        self._recovered_result: bool = False
        self._completion_wait_rounds: int = 0

    def handle_init(self) -> None:
        """仅新执行重置；暂停和恢复不会重新发送领取键。"""
        self.evidence_paths.clear()
        self._claim_sent = False
        self._confirmation_sent = False
        self._back_sent = False
        self._full_engagement = False
        self._result_status = ''
        self._recovered_result = False
        self._completion_wait_rounds = 0

    def claim_available(self) -> bool:
        """底部领取文字必须有已观察到的黄色启用颜色。"""
        return self._yellow_text('快捷手册-日常', '手柄-领奖提示', '领取奖励')

    def reward_confirmation_key(self) -> str | None:
        """本次已发起领取或明确恢复时，才确认已知获得弹窗。"""
        if not (self._claim_sent or self.resume_from_reward):
            return None
        return 'south' if self._known_reward_visible() else None

    def _reward_complete(self) -> bool:
        """复用原 PC 业务对 400 档绿色完成标记的识别。"""
        return self.last_screenshot is not None and self.round_by_find_area(
            self.last_screenshot, '快捷手册', '活跃度奖励-4'
        ).is_success

    @operation_node(name='检查初始奖励页', is_start_node=True)
    def check_initial_reward(self) -> OperationRoundResult:
        """已知奖励页从结果节点继续，不将遗留页面算作本次领取。"""
        if self._known_reward_visible():
            if not self.resume_from_reward:
                return self._pending_evidence('engagement_unrelated_reward', '已有获得弹窗，未确认来源为本次活跃度领取')
            self._recovered_result = True
            self._claim_sent = True
            self._save_evidence('engagement_recovered_result')
            return self.round_success('恢复奖励结果')
        if self.resume_from_reward:
            return self._pending_evidence('engagement_invalid_recovery', '指定恢复奖励页，但当前画面尚未建档')
        return self.round_success()

    @node_from(from_name='检查初始奖励页')
    @operation_node(name='打开日常')
    def open_daily(self) -> OperationRoundResult:
        """从已确认的大世界或手册页面进入日常。"""
        return self.round_by_op_result(GamepadOpenDailyCompendium(self.ctx).execute())

    @node_from(from_name='打开日常')
    @operation_node(name='领取当前奖励', node_max_retry_times=4, timeout_seconds=8)
    def claim_rewards(self) -> OperationRoundResult:
        """先留图再只按一次 X；未满仍领取当前可领档位。"""
        if not self._daily_visible():
            return self.round_retry('等待日常页面', wait=0.8)
        if not self._save_evidence('engagement_before'):
            return self.round_fail('领取前截图保存失败')
        if self._claim_sent:
            return self.round_success()
        if self.claim_available():
            self.ctx.controller.btn_tap('west')
            self._claim_sent = True
            return self.round_success(wait=1)
        self._full_engagement = self._reward_complete()
        self._result_status = '日常奖励已领取' if self._full_engagement else '活跃度未满，当前无可领取奖励'
        return self.round_success('无可领取奖励')

    @node_from(from_name='领取当前奖励')
    @node_from(from_name='检查初始奖励页', status='恢复奖励结果')
    @operation_node(name='确认奖励结果', node_max_retry_times=6)
    def confirm_reward(self) -> OperationRoundResult:
        """领取后首先保存新帧；未知弹窗结束，不猜确认键。"""
        if self.last_screenshot is None:
            return self.round_retry('等待领取后的有效截图', wait=0.8)
        self._save_evidence('engagement_after_claim')
        key = self.reward_confirmation_key()
        if key is not None:
            if not self._confirmation_sent:
                if not self._save_evidence('engagement_before_confirm'):
                    return self.round_fail('确认前截图保存失败')
                self.ctx.controller.btn_tap(key)
                self._confirmation_sent = True
            return self.round_retry('等待奖励确认返回日常', wait=0.8)
        # 未知弹窗可能仍露出日常标签，不能仅凭背后的标签按返回。
        if self._confirmation_sent and self._daily_visible():
            self._save_evidence('engagement_after_confirm')
            self._full_engagement = self._reward_complete()
            if not self._full_engagement and self._completion_wait_rounds < 3:
                # 奖励确认后会短暂发光遮住完成勾，必须换新帧再判断未满。
                self._completion_wait_rounds += 1
                return self.round_retry('等待活跃度完成标记稳定', wait=0.5)
            if self.claim_available() and self._claim_sent:
                return self._pending_evidence('engagement_still_claimable', '领取后仍显示可领取，请核对本次结果')
            if self._recovered_result:
                self._result_status = '已有奖励页已确认' if self._full_engagement else '已有奖励页已确认，活跃度未满'
            else:
                self._result_status = '日常奖励领取成功' if self._full_engagement else '已领取当前奖励，活跃度未满'
            return self.round_success(self._result_status)
        return self._pending_evidence('engagement_unknown_result', '未知活跃度奖励画面')

    @node_from(from_name='领取当前奖励', status='无可领取奖励')
    @node_from(from_name='确认奖励结果')
    @operation_node(name='返回大世界', node_max_retry_times=8, timeout_seconds=12)
    def back_to_world(self) -> OperationRoundResult:
        """只在已确认的日常页发 B；大世界新帧到达后才给最终结果。"""
        if self.last_screenshot is None:
            return self.round_retry('等待返回画面', wait=0.8)
        if self.round_by_find_area(self.last_screenshot, '大世界-普通', '快捷手册').is_success:
            self._save_evidence('engagement_world')
            result = self.round_success if self._full_engagement else self.round_fail
            return result(self._result_status, data={
                'evidence_paths': self.evidence_paths,
                'claimed_by_operation': self._claim_sent and not self._recovered_result,
                'recovered_reward_page': self._recovered_result,
            })
        if self._daily_visible():
            if not self._back_sent:
                self._save_evidence('engagement_result')
                self.ctx.controller.btn_tap('east')
                self._back_sent = True
            return self.round_retry('等待返回大世界', wait=0.8)
        return self._pending_evidence('engagement_unknown_return', '未知活跃度奖励返回画面')


class GamepadOpenDailyCompendium(_GamepadRewardOperation):
    """复用已确认的手册组合键及标签高亮，打开日常页面。"""

    TABS: tuple[str, ...] = ('目标', '日常', '训练', '作战', '战术')

    def __init__(self, ctx: ZContext) -> None:
        """只负责导航，领取动作由各奖励操作处理。"""
        super().__init__(ctx, op_name='手柄打开快捷手册日常', timeout_seconds=20)
        self._opened: bool = False

    def handle_init(self) -> None:
        """每次执行都允许重新从大世界打开一次。"""
        self._opened = False

    def selected_tab(self) -> str | None:
        """文字及周围黄色填充同时命中才确认当前标签。"""
        area = self._read_area('快捷手册', '手柄-顶部标签')
        if area is None:
            return None
        image, results = area
        selected: list[str] = []
        for text, matches in results.items():
            normalized = text.replace(' ', '').replace('？', '').replace('?', '')
            if matches.max is None:
                continue
            for tab in self.TABS:
                if tab in normalized and has_filled_highlight(image, matches.max.rect, 'yellow'):
                    selected.append(tab)
        return selected[0] if len(selected) == 1 else None

    @operation_node(name='打开快捷手册', is_start_node=True, node_max_retry_times=5, timeout_seconds=8)
    def open_compendium(self) -> OperationRoundResult:
        """只在确认大世界时发送打开组合键，不反复开关菜单。"""
        if self.selected_tab() is not None:
            return self.round_success()
        if self.last_screenshot is not None and not self._opened and self.round_by_find_area(
            self.last_screenshot, '大世界-普通', '快捷手册'
        ).is_success:
            self.ctx.controller.click(gamepad_key='compendium')
            self._opened = True
        return self.round_retry('等待手柄快捷手册', wait=0.8)

    @node_from(from_name='打开快捷手册')
    @operation_node(name='选择日常', node_max_retry_times=6, timeout_seconds=10)
    def choose_daily(self) -> OperationRoundResult:
        """根据当帧高亮选择方向，未知标签不发送输入。"""
        selected = self.selected_tab()
        if selected == '日常':
            return self.round_success('已打开快捷手册日常')
        if selected is not None:
            key = 'right_shoulder' if self.TABS.index(selected) < 1 else 'left_shoulder'
            self.ctx.controller.btn_tap(key)
        return self.round_retry('等待日常标签高亮', wait=0.8)


class GamepadOpenRiduWeekly(_GamepadRewardOperation):
    """从日常页上已有黄色焦点的丽都周纪入口进入。"""

    def __init__(self, ctx: ZContext) -> None:
        """不假设初始焦点，也不移动到未建档的卡片。"""
        super().__init__(ctx, op_name='手柄打开丽都周纪', timeout_seconds=35)
        self._entered: bool = False

    def handle_init(self) -> None:
        """重新执行时清除一次性确认记录。"""
        self._entered = False

    def weekly_focused(self) -> bool:
        """周纪入口的文字周围必须有黄色按钮填充。"""
        area = self._read_area('快捷手册-日常', '手柄-周纪入口')
        if area is None:
            return False
        image, results = area
        rect = self._text_rect(results, '丽都周纪')
        return rect is not None and has_filled_highlight(image, rect, 'yellow')

    @operation_node(name='打开日常', is_start_node=True)
    def open_daily(self) -> OperationRoundResult:
        """复用标签导航，保持现有手册入口语义。"""
        return self.round_by_op_result(GamepadOpenDailyCompendium(self.ctx).execute())

    @node_from(from_name='打开日常')
    @operation_node(name='进入丽都周纪', node_max_retry_times=4, timeout_seconds=8)
    def enter_weekly(self) -> OperationRoundResult:
        """只在有周纪焦点时确认一次，以周纪双锚点确认到达。"""
        if self._has_text('丽都周纪', '手柄-页面文字', '积分特赏') and self._has_text(
            '丽都周纪', '手柄-页面文字', '累计获取积分'
        ):
            return self.round_success('已打开丽都周纪')
        if not self._entered and self.weekly_focused():
            self.ctx.controller.btn_tap('south')
            self._entered = True
        return self.round_retry('等待丽都周纪入口焦点或页面切换', wait=0.8)
