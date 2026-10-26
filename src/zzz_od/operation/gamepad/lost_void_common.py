"""手柄鸣徽与卡牌选择，复用原标题、候选识别和优先级。"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

import cv2
import numpy as np

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.operation.operation_node import operation_node
from zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_choose_common import (
    LostVoidChooseCommon,
)
from zzz_od.operation.gamepad.focus import has_filled_highlight, highlight_mask
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation
from zzz_od.operation.gamepad.transport_by_compendium import (
    GamepadTransportByCompendium,
)

if TYPE_CHECKING:
    from cv2.typing import MatLike

    from one_dragon.base.matcher.match_result import MatchResultList
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_artifact_pos import (
        LostVoidArtifactPos,
    )
    from zzz_od.context.zzz_context import ZContext


class GamepadLostVoidChooseCommon(GamepadOperation):
    """按实际焦点和计数选择，连续获得提示逐项核对后交回父流程。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄迷失之地通用选择', timeout_seconds=60)
        self.parser: LostVoidChooseCommon = LostVoidChooseCommon(ctx)
        self.navigation: GamepadTransportByCompendium = GamepadTransportByCompendium(
            ctx, '作战', '周期征讨'
        )
        self._confirmed: bool = False
        self._signature: tuple[str, ...] | None = None
        self._target: str | None = None
        self._gain_notice: bool = False
        self._multi_expected_count: int | None = None
        self._multi_expected_index: int | None = None
        self._multi_pending_waits: int = 0
        self._multi_focus_saved: bool = False
        self._multi_slot_count: int | None = None
        self._gear_layout: bool = False
        self._multi_verified_selected: set[int] = set()
        self._gain_identity: tuple[str, ...] | None = None
        self._gain_probe: tuple[str, ...] | None = None
        self._gain_attempts: int = 0
        self._gain_sent_at: float = 0
        self._gain_frame_time: float = -1

    def gained_item_identity(self, title: str) -> tuple[str, ...] | None:
        """按名称与等级区分连续获得提示，不用动态背景像素判断换页。"""
        names = set()
        for rect in self.name_rects():
            words = self.ctx.ocr.crop_and_run_ocr(self.last_screenshot, rect)
            names.update(
                ''.join(text.split()) for text in words if len(text.strip()) >= 2
            )
        if not names:
            return None
        area = self.navigation._read_area('迷失之地-通用选择', '手柄-名称栏搜索')
        levels = (
            [
                int(value)
                for text in area[1]
                for value in re.findall(r'等级\s*(\d+)', text)
            ]
            if area
            else []
        )
        return (
            ''.join(title.split()),
            *sorted(names),
            f'等级{max(levels)}' if levels else '',
        )

    def confirm_gain(self, title: str) -> OperationRoundResult:
        """新提示交回父流程；同一提示只在新帧仍明确时有限重试。"""
        identity = self.gained_item_identity(title)
        if (
            self._confirmed
            and identity is not None
            and self._gain_identity is not None
            and identity != self._gain_identity
        ):
            if identity == self._gain_probe:
                self.ctx.lost_void.priority_updated = False
                return self.round_success('本次获得已确认，新的获得提示交回父流程')
            self._gain_probe = identity
            return self.round_retry('核对连续获得提示的名称或等级变化', wait=0.6)
        self._gain_probe = None
        now = time.monotonic()
        if self._confirmed:
            if (
                now - self._gain_sent_at < 2
                or self.last_screenshot_time <= self._gain_frame_time
            ):
                return self.round_retry('等待获得提示关闭', wait=0.6)
            if self._gain_attempts >= 3:
                self.save_screenshot(prefix='macos_lost_void_gain_confirm_pending')
                return self.round_fail('同一获得提示确认三次未响应，已停止')
        footer = self.navigation._read_area('迷失之地-通用选择', '手柄-确认底栏')
        if not self.has_a_confirmation(footer):
            return self.round_retry('等待获得提示的A确定', wait=1)
        self._gain_identity = identity
        self.ctx.controller.btn_tap('south')
        self._confirmed = True
        self._gain_attempts += 1
        self._gain_sent_at = now
        self._gain_frame_time = self.last_screenshot_time
        return self.round_retry('等待获得提示关闭', wait=1)

    def has_a_confirmation(self, footer: tuple[MatLike, dict[str, MatchResultList]] | None) -> bool:
        """确定文字存在时，以同排左侧的实拍图标补足 OCR 漏掉的 A。"""
        if footer is None:
            return False
        image, words = footer
        button = self.navigation._text_rect(words, '确定')
        if button is None:
            return False
        if any(text.strip().upper() == 'A' and matches.max is not None for text, matches in words.items()):
            return True
        return any(
            prompt.x + prompt.w < button.x1 and abs(prompt.center.y - button.center.y) <= 40
            for prompt in self.ctx.tm.match_template(image, 'ios_gamepad', 'dialog_a', threshold=0.8)
        )

    def name_rects(self) -> list[Rect]:
        """从黑色名称栏定位每卡正文，兼容一张奖励卡和多张鸣徽的位置差异。"""
        area = self.ctx.screen_loader.get_area('迷失之地-通用选择', '手柄-名称栏搜索')
        if area is None or self.last_screenshot is None:
            return []
        rect = area.rect
        image = self.last_screenshot[rect.y1 : rect.y2, rect.x1 : rect.x2]
        contours, _ = cv2.findContours(
            cv2.inRange(image, (0, 0, 0), (25, 25, 25)),
            cv2.RETR_LIST,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        result = [
            Rect(
                rect.x1 + x - 4,
                rect.y1 + y - 4,
                rect.x1 + x + w + 4,
                rect.y1 + y + h + 4,
            )
            for contour in contours
            for x, y, w, h in [cv2.boundingRect(contour)]
            if 200 <= w <= 420
            and 20 <= h <= 70
            and cv2.contourArea(contour) / (w * h) > 0.65
        ]
        self._gear_layout = False
        if result:
            return sorted(result, key=lambda item: item.center.x)
        if self.round_by_find_area(
            self.last_screenshot, '迷失之地-通用选择', '区域-武备标识'
        ).is_success:
            gear = self.ctx.screen_loader.get_area('迷失之地-通用选择', '区域-武备名称')
            if gear is not None:
                self._gear_layout = True
                return [gear.rect]
        return []

    def can_handle(self) -> bool:
        """标题语义与确认按钮共同出现，不依赖PC的TAB模板。"""
        if (
            self.last_screenshot is None
            or self.ctx.screen_loader.get_area('迷失之地-通用选择', '按钮-确定') is None
        ):
            return False
        self.navigation.last_screenshot = self.last_screenshot
        area = self.navigation._read_area('迷失之地-通用选择', '区域-标题')
        title = ''.join(area[1]).replace(' ', '') if area is not None else ''
        self._gain_notice = False
        if not self.round_by_find_area(
            self.last_screenshot, '迷失之地-通用选择', '按钮-确定'
        ).is_success:
            return False
        if any(
            word in title for word in ('请选择', '获得武备', '武备已升级', '获得战利品')
        ):
            return True
        # 单张卡牌获得提示没有标题或已选择标记，只有黄色确认按钮。
        selected = self.navigation._read_area('迷失之地-通用选择', '区域-藏品已选择')
        if selected and self.navigation._text_rect(selected[1], '已选择') is not None:
            return False
        confirm = self.navigation._read_area('迷失之地-通用选择', '按钮-确定')
        button = (
            self.navigation._text_rect(confirm[1], '确定')
            if confirm is not None
            else None
        )
        self._gain_notice = bool(
            len(self.name_rects()) == 1
            and confirm is not None
            and button is not None
            and has_filled_highlight(confirm[0], button, 'yellow')
        )
        return self._gain_notice

    def _focused_candidates(
        self, candidates: list[LostVoidArtifactPos]
    ) -> list[LostVoidArtifactPos]:
        """按实际整卡高亮框关联名称，不把卡牌品质A/B当成按键。"""
        mask = cv2.morphologyEx(
            highlight_mask(self.last_screenshot, 'yellow'),
            cv2.MORPH_CLOSE,
            np.ones((7, 7), np.uint8),
        )
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        frames = [
            Rect(x, y, x + w, y + h)
            for contour in contours
            for x, y, w, h in [cv2.boundingRect(contour)]
            if 200 <= w <= 650
            and 300 <= h <= 750
            and cv2.contourArea(contour) / (w * h) > 0.4
        ]
        return [
            item
            for item in candidates
            if any(
                frame.x1 < item.rect.center.x < frame.x2
                and frame.y1 < item.rect.center.y < frame.y2
                for frame in frames
            )
        ]

    def _multi_selected_indices(
        self, candidates: list[LostVoidArtifactPos]
    ) -> set[int] | None:
        """只读取真正的已选择标记，同流派武备提示不能算作本次已选。"""
        area = self.ctx.screen_loader.get_area('迷失之地-通用选择', '区域-藏品已选择')
        selected = self.navigation._read_area('迷失之地-通用选择', '区域-藏品已选择')
        if area is None or selected is None:
            return None
        result = set()
        for text, matches in selected[1].items():
            if '已选择' not in text.replace(' ', ''):
                continue
            for match in matches:
                x = area.rect.x1 + match.center.x
                index = min(
                    range(len(candidates)),
                    key=lambda i: abs(candidates[i].rect.center.x - x),
                )
                if abs(candidates[index].rect.center.x - x) <= max(
                    70, candidates[index].rect.width / 2
                ):
                    result.add(index)
        return result

    def _choose_multiple(self, count: int) -> OperationRoundResult:
        """A选择一枚后必须读到计数加一，选满后才按画面提示X确认。"""
        actual = self.parser._get_chosen_count_from_confirm_button(
            self.last_screenshot, count
        )
        if actual is None:
            return self.round_retry('等待多选的实际计数', wait=1)
        if not 0 <= actual <= count:
            return self.round_fail('多选实际计数无效')
        area = self.ctx.screen_loader.get_area('迷失之地-通用选择', '手柄-四候选名称')
        if area is None:
            return self.round_retry('等待多选名称栏', wait=1)
        # 四候选的黑色卡片名称条可能与正文连成一块，不能只数黑色轮廓。
        rect = area.rect
        rects = [
            Rect(
                rect.x1 + rect.width * index / 4,
                rect.y1,
                rect.x1 + rect.width * (index + 1) / 4,
                rect.y2,
            )
            for index in range(4)
        ]
        candidates = sorted(
            self.ctx.lost_void.get_artifact_pos(
                self.last_screenshot,
                to_choose_gear_branch=self.parser.to_choose_gear_branch,
                screen_name='迷失之地-通用选择',
                name_rects=rects,
            ),
            key=lambda item: item.rect.center.x,
        )
        if len(candidates) < count:
            return self.round_retry('等待完整多选候选', wait=1)
        if len(candidates) != len(rects):
            return self.round_retry('等待全部多选名称识别', wait=1)
        if not self._confirmed:
            if self._multi_slot_count is None:
                self._multi_slot_count = len(candidates)
            elif len(candidates) != self._multi_slot_count:
                return self.round_retry('等待多选候选恢复完整', wait=1)
        signature = tuple(item.artifact.display_name for item in candidates)
        if self._confirmed:
            if signature != self._signature or actual < count:
                self.ctx.lost_void.priority_updated = False
                return self.round_success('本次多选已确认，后续选择交由下一次识别')
            return self.round_retry('等待多选确认生效', wait=1)
        selected = self._multi_selected_indices(candidates)
        if selected is None:
            return self.round_retry('等待已选择标记与实际计数一致', wait=1)
        highlighted = {
            candidates.index(item) for item in self._focused_candidates(candidates)
        }
        selected |= self._multi_verified_selected
        # 同流派提示会覆盖已选择文字。所有已选卡仍保留黄框；焦点在已选卡上时，
        # 黄框数与实际计数一致才能重建整组选中项，绝不单凭同流派文字放行。
        if actual > 0 and len(highlighted) == actual:
            selected |= highlighted
        if (
            self._multi_expected_count == actual
            and self._multi_expected_index in highlighted
        ):
            selected.add(self._multi_expected_index)
        if len(selected) != actual:
            return self.round_retry('等待已选边框与实际计数一致', wait=1)
        self._multi_verified_selected = selected.copy()
        if self._multi_expected_count is not None:
            if actual != self._multi_expected_count:
                self._multi_pending_waits += 1
                if self._multi_pending_waits >= 3:
                    return self.round_fail('多选输入未产生预期计数变化，已停止')
                return self.round_retry('等待单枚选择后的实际计数', wait=1)
            if self._multi_expected_index not in selected:
                return self.round_fail('新增已选择标记与原目标不一致')
            self._multi_expected_count = None
            self._multi_expected_index = None
            self._multi_pending_waits = 0
        self._signature = signature
        if actual == count:
            confirm = self.navigation._read_area('迷失之地-通用选择', '按钮-确定')
            controls = (
                {text.upper(): matches for text, matches in confirm[1].items()}
                if confirm is not None
                else {}
            )
            if not all(
                self.navigation._text_rect(controls, word) is not None
                for word in ('X', '确定')
            ):
                return self.round_retry('等待多选的X确认提示', wait=1)
            self.save_screenshot(prefix='macos_lost_void_multi_selected_verified')
            self.ctx.controller.btn_tap('west')
            self._confirmed = True
            return self.round_retry('等待选满后的确认关闭', wait=1)
        available = [
            item for index, item in enumerate(candidates) if index not in selected
        ]
        ordered = self.ctx.lost_void.get_artifact_by_priority(
            available,
            1,
            consider_priority_new=self.ctx.lost_void.challenge_config.artifact_priority_new,
        )
        target = ordered[0] if ordered else available[0]
        target_index = min(
            range(len(candidates)),
            key=lambda i: abs(candidates[i].rect.center.x - target.rect.center.x),
        )
        focused = self._focused_candidates(candidates)
        unselected = [
            item for item in focused if candidates.index(item) not in selected
        ]
        if len(unselected) == 1:
            current = unselected[0]
        elif len(focused) == 1:
            current = focused[0]
        else:
            if not self._multi_focus_saved:
                self.save_screenshot(prefix='macos_lost_void_multi_focus_pending')
                self._multi_focus_saved = True
            return self.round_retry('等待唯一多选焦点', wait=1)
        if current is not candidates[target_index]:
            self.ctx.controller.btn_tap(
                'dpad_right'
                if target.rect.center.x > current.rect.center.x
                else 'dpad_left'
            )
            return self.round_retry('等待原优先级多选目标进入焦点', wait=0.7)
        self.ctx.controller.btn_tap('south')
        self._multi_expected_count = actual + 1
        self._multi_expected_index = target_index
        return self.round_retry('等待新增一枚已选择标记', wait=0.7)

    @operation_node(name='选择并确认藏品', is_start_node=True, node_max_retry_times=25)
    def choose(self) -> OperationRoundResult:
        """每轮重新识别高亮和实际已选择项，A只用于已核对目标的确认。"""
        if self.last_screenshot is None:
            return self.round_retry('等待藏品选择截图', wait=1)
        if self.ctx.lost_void.in_normal_world(self.last_screenshot):
            if self._confirmed:
                self.ctx.lost_void.priority_updated = False
                return self.round_success('藏品选择已确认并返回')
            return self.round_fail('未确认藏品选择')
        if not self.can_handle():
            if self._confirmed:
                known = self.check_and_update_current_screen(
                    self.last_screenshot,
                    screen_name_list=[
                        '迷失之地-武备选择',
                        '迷失之地-挑战结果',
                        '迷失之地-战斗失败',
                        '迷失之地-邦布商店',
                        '迷失之地-抽奖机',
                    ],
                )
                if (
                    known is not None
                    or self.round_by_find_area(
                        self.last_screenshot,
                        '迷失之地-大世界',
                        '手柄-对话推进',
                    ).is_success
                ):
                    self.ctx.lost_void.priority_updated = False
                    return self.round_success('本次藏品已确认，后续交互交由父流程')
                return self.round_retry('等待藏品选择返回', wait=1)
            self.save_screenshot(prefix='macos_lost_void_common_pending')
            return self.round_fail('未确认手柄藏品选择页')
        self.parser.last_screenshot = self.last_screenshot
        self.parser.check_choose_title(self.last_screenshot)
        count = 0 if self._gain_notice else self.parser.to_choose_num
        if count > 1:
            return self._choose_multiple(count)
        if count == 0:
            if self._confirmed and self._signature is not None:
                self.ctx.lost_void.priority_updated = False
                return self.round_success('本次选择已确认，后续获得提示交由下一次识别')
            title_area = self.navigation._read_area('迷失之地-通用选择', '区域-标题')
            title = ''.join(title_area[1]) if title_area is not None else ''
            if not self._gain_notice and not any(
                word in title for word in ('获得武备', '武备已升级', '获得战利品')
            ):
                return self.round_fail('未识别藏品选择数量，未确认')
            return self.confirm_gain(title)
        rects = self.name_rects()
        if not rects:
            return self.round_retry('等待实际卡片名称栏', wait=1)
        all_candidates = self.ctx.lost_void.get_artifact_pos(
            self.last_screenshot,
            to_choose_gear_branch=self.parser.to_choose_gear_branch,
            screen_name='迷失之地-通用选择',
            name_rects=rects,
        )
        available = [item for item in all_candidates if item.can_choose]
        chosen = [item for item in all_candidates if item.chosen]
        candidates = sorted(available + chosen, key=lambda item: item.rect.center.x)
        signature = tuple(item.artifact.display_name for item in candidates)
        if not candidates:
            return self.round_retry('等待原藏品名称识别', wait=1)
        if self._confirmed:
            if self._signature != signature:
                self.ctx.lost_void.priority_updated = False
                return self.round_success('本次选择已关闭，后续藏品交由下一次识别')
            return self.round_retry('等待本次藏品确认生效', wait=1)
        self._signature = signature
        ordered = self.ctx.lost_void.get_artifact_by_priority(
            candidates,
            1,
            consider_priority_new=self.ctx.lost_void.challenge_config.artifact_priority_new,
        )
        target = ordered[0] if ordered else candidates[0]
        self._target = target.artifact.display_name
        focused = self._focused_candidates(candidates)
        if len(focused) != 1:
            return self.round_retry('等待唯一藏品高亮框', wait=1)
        current = focused[0]
        if current.artifact.display_name != self._target:
            self.ctx.controller.btn_tap(
                'dpad_right'
                if target.rect.center.x > current.rect.center.x
                else 'dpad_left'
            )
            return self.round_retry('等待原优先级藏品进入焦点', wait=0.7)
        if self._gear_layout:
            footer = self.navigation._read_area('迷失之地-通用选择', '手柄-确认底栏')
            if not self.has_a_confirmation(footer):
                return self.round_retry('等待武备单选的A确认提示', wait=1)
        elif not any(item.artifact.display_name == self._target for item in chosen):
            return self.round_retry('等待目标藏品已选择标记', wait=0.7)
        self.ctx.controller.btn_tap('south')
        self._confirmed = True
        return self.round_retry('等待藏品确认后返回', wait=1)
