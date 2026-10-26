"""沿用原武备解析和优先级，通过原生手柄逐个预览选择。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import cv2

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.operation.operation_node import operation_node
from zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_artifact_pos import (
    LostVoidArtifactPos,
)
from zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_choose_gear import (
    LostVoidChooseGear,
)
from zzz_od.operation.gamepad.focus import has_filled_highlight, highlight_mask
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation
from zzz_od.operation.gamepad.transport_by_compendium import (
    GamepadTransportByCompendium,
)

if TYPE_CHECKING:
    from cv2.typing import MatLike

    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class GamepadLostVoidChooseGear(GamepadOperation):
    """扫描实际焦点下的武备名称，复用原追新和优先级决策。"""

    def __init__(
        self, ctx: ZContext, completed_name_list: list[str] | None = None
    ) -> None:
        super().__init__(ctx, op_name='手柄迷失之地武备选择', timeout_seconds=120)
        self.completed_name_list: list[str] | None = completed_name_list
        self.parser: LostVoidChooseGear = LostVoidChooseGear(ctx, completed_name_list)
        self.navigation: GamepadTransportByCompendium = GamepadTransportByCompendium(
            ctx, '作战', '周期征讨'
        )
        self._candidates: list[LostVoidArtifactPos] = []
        self._unlocked: list[LostVoidArtifactPos] = []
        self._previous: str | None = None
        self._target: str | None = None
        self._equipped: bool = False
        self._equip_requested: bool = False
        self._repeated: bool = False
        self._first_name: str | None = None
        self._confirmed: bool = False
        self._back_sent: bool = False
        self._at_first: bool = False
        self._home_steps: int = 0

    def handle_init(self) -> None:
        """重新执行时清除预览和确认状态，保留调用方共享的已完成名单。"""
        self._candidates.clear()
        self._unlocked.clear()
        self._previous = None
        self._target = None
        self._equipped = False
        self._equip_requested = False
        self._repeated = False
        self._first_name = None
        self._confirmed = False
        self._back_sent = False
        self._at_first = False
        self._home_steps = 0

    def equipped_at_focus(self, image: MatLike, box: tuple[int, int, int, int]) -> bool:
        """绿色勾须位于该槽右上方，不能把其他槽已携带当成本槽状态。"""
        x, y, width, _ = box
        marks = self.ctx.tm.match_template(
            image, 'ios_gamepad', 'lost_void_gear_equipped', threshold=0.85
        )
        return any(
            x + width / 2 < match.center.x < x + width
            and y - 45 < match.center.y < y + 45
            for match in marks
        )

    def focus_frames(self, image: MatLike) -> list[tuple[int, int, int, int]]:
        """完整黄环优先；没有黄环时只接受带已携带勾的半绿环。"""
        contours, _ = cv2.findContours(
            highlight_mask(image, 'yellow'), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        boxes = [cv2.boundingRect(contour) for contour in contours]
        full = [box for box in boxes if 125 <= box[2] <= 165 and 120 <= box[3] <= 170]
        if full:
            return full
        return [
            box
            for box in boxes
            if 125 <= box[2] <= 165
            and 90 <= box[3] < 120
            and self.equipped_at_focus(image, box)
        ]

    @operation_node(name='预览并携带武备', is_start_node=True, node_max_retry_times=40)
    def choose(self) -> OperationRoundResult:
        """一个焦点一份名称，确认携带后必须回到局内才记入已完成名单。"""
        if self.last_screenshot is None:
            return self.round_retry('等待武备截图', wait=1)
        if self.ctx.lost_void.in_normal_world(self.last_screenshot):
            if not self._equipped and not self._repeated:
                return self.round_fail('未确认武备选择')
            if (
                self.completed_name_list is not None
                and self._first_name is not None
                and not self._repeated
            ):
                if self._first_name not in self.completed_name_list:
                    self.completed_name_list.append(self._first_name)
            self.ctx.lost_void.priority_updated = False
            return self.round_success(
                LostVoidChooseGear.STATUS_REPEATED if self._repeated else '武备已携带'
            )
        nav = self.navigation
        nav.last_screenshot = self.last_screenshot
        confirmation = nav._read_area('迷失之地-武备选择', '手柄-初始武备确认')
        if confirmation:
            title = ''.join(confirmation[1])
            parsed = re.search(
                r'确认选择([\[【].+?[\]】].+?)作为初始武备', title.replace(' ', '')
            )
            if parsed:
                pending = parsed[1].replace('【', '[').replace('】', ']')
                if self._target is not None and self._target != pending:
                    return self.round_fail('初始武备确认与选择目标不一致')
                self._target = pending
                buttons = {
                    text: matches
                    for text, matches in confirmation[1].items()
                    if text.strip() == '确认'
                }
                button = nav._text_rect(buttons, '确认')
                if button is not None and has_filled_highlight(
                    confirmation[0], button, 'yellow'
                ):
                    if not self._confirmed:
                        self.ctx.controller.btn_tap('south')
                        self._confirmed = True
                        self._equipped = True
                    return self.round_retry('等待初始武备确认关闭', wait=1)
                return self.round_retry('等待初始武备确认焦点', wait=1)
        if self._equipped or self._repeated:
            if (
                self._equipped
                and not self._back_sent
                and self.round_by_find_area(
                    self.last_screenshot,
                    '迷失之地-武备选择',
                    '文本-详情',
                ).is_success
            ):
                self.ctx.controller.btn_tap('east')
                self._back_sent = True
            return self.round_retry('等待武备选择返回', wait=1)
        if self._equip_requested:
            return self.round_retry('等待可确认的武备携带结果', wait=1)
        if not all(
            self.round_by_find_area(
                self.last_screenshot, '迷失之地-武备选择', key
            ).is_success
            for key in ('按钮-携带', '文本-详情')
        ):
            words = self.ctx.ocr.run_ocr(self.last_screenshot)
            if any('服务器连接超时' in text for text in words):
                from zzz_od.operation.gamepad.dialog import GamepadReconnect

                result = GamepadReconnect(self.ctx).execute()
                return (
                    self.round_retry('等待连接恢复后的武备页', wait=1)
                    if result.success
                    else self.round_by_op_result(result)
                )
            self.save_screenshot(prefix='macos_lost_void_gear_pending')
            return self.round_retry('等待武备页面恢复，未发送输入', wait=1)
        listing = nav._read_area('迷失之地-武备选择', '武备列表')
        name_area = nav._read_area('迷失之地-武备选择', '武备名称')
        if listing is None or name_area is None:
            return self.round_fail('武备区域缺失')
        focus = self.focus_frames(listing[0])
        if len(focus) != 1:
            return self.round_retry('等待唯一武备圆环焦点', wait=1)
        tokens = sorted(
            [
                (m.center.x, text)
                for text, matches in name_area[1].items()
                for m in matches
            ]
        )
        name = ''.join(text for _, text in tokens)
        art, primary = self.parser._build_artifact_from_ocr_name(name)
        if art is None:
            return self.round_retry('等待完整武备分类与名称', wait=1)
        name = art.display_name
        if not self._at_first:
            self.parser.last_screenshot = self.last_screenshot
            _, geometry = self.parser._find_gears_with_status()
            slots = sorted(
                geometry.get_absolute_rect_pairs(), key=lambda item: item[1][0]
            )
            source = self.ctx.screen_loader.get_area(
                '迷失之地-武备选择', '武备列表'
            ).rect
            current_x = source.x1 + focus[0][0] + focus[0][2] / 2
            if not slots:
                return self.round_retry('等待可见武备槽位', wait=1)
            first = slots[0][1]
            if abs(current_x - (first[0] + first[2]) / 2) < 55:
                self._at_first = True
            else:
                if self._home_steps >= 12:
                    return self.round_fail('武备列表起点定位失败')
                self._home_steps += 1
                self.ctx.controller.btn_tap('dpad_left')
                return self.round_retry('核对武备列表起点', wait=0.7)
        if self._first_name is None:
            self._first_name = name
            if self.completed_name_list is not None and (
                name in self.completed_name_list or len(self.completed_name_list) >= 2
            ):
                self.ctx.controller.btn_tap('east')
                self._repeated = True
                return self.round_retry('退出重复武备选择', wait=1)
        if self._target is not None:
            if name == self._target:
                if self.equipped_at_focus(listing[0], focus[0]):
                    self._equipped = True
                    return self.round_retry('目标武备已携带，等待返回', wait=0.7)
                self.ctx.controller.btn_tap('south')
                self._equip_requested = True
                return self.round_retry('等待携带结果', wait=1)
            self.ctx.controller.btn_tap('dpad_left')
            return self.round_retry('定位优先级武备', wait=0.7)
        if any(item.artifact.display_name == name for item in self._candidates):
            if name == self._previous or name == self._first_name:
                pool = (
                    self._unlocked
                    if self.ctx.lost_void.challenge_config.chase_new_mode
                    and self._unlocked
                    else self._candidates
                )
                chosen = self.ctx.lost_void.get_artifact_by_priority(pool, 1)
                target = chosen[0] if chosen else pool[0]
                self._target = target.artifact.display_name
                if (
                    target.artifact.category
                    not in self.ctx.lost_void.challenge_config.artifact_priority_in_battle
                ):
                    self.ctx.lost_void.challenge_config.artifact_priority_in_battle.append(
                        target.artifact.category
                    )
                return self.round_retry('已按原优先级选定武备', wait=0.5)
            return self.round_fail('武备预览出现重复名称，无法确定焦点')
        x, y, width, height = focus[0]
        source = self.ctx.screen_loader.get_area('迷失之地-武备选择', '武备列表').rect
        rect = Rect(
            source.x1 + x, source.y1 + y, source.x1 + x + width, source.y1 + y + height
        )
        candidate = LostVoidArtifactPos(art, rect, name, primary)
        self._candidates.append(candidate)
        self.parser.last_screenshot = self.last_screenshot
        gears, pipeline = self.parser._find_gears_with_status()
        positions = sorted(
            pipeline.get_absolute_rect_pairs(), key=lambda item: item[1][0]
        )
        index = next(
            (
                i
                for i, (_, box) in enumerate(positions)
                if box[0] <= rect.center.x <= box[2]
            ),
            None,
        )
        if index is not None and index < len(gears) and not gears[index][1]:
            self._unlocked.append(candidate)
        self._previous = name
        self.ctx.controller.btn_tap('dpad_right')
        return self.round_retry(f'已预览武备：{name}', wait=0.7)
