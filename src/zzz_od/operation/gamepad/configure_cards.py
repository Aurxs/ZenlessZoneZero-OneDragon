"""只配置调查专项卡片数量，不进入编队、不出战也不恢复电量。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, ClassVar

import cv2

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from one_dragon.utils import debug_utils
from zzz_od.operation.gamepad.focus import has_filled_highlight, highlight_mask
from zzz_od.operation.gamepad.transport_by_compendium import (
    GamepadTransportByCompendium,
)
from zzz_od.operation.zzz_operation import ZOperation

if TYPE_CHECKING:
    from cv2.typing import MatLike

    from one_dragon.base.matcher.match_result import MatchResultList
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


def read_preset_area(
    ctx: ZContext, screen: MatLike | None, area_name: str,
) -> tuple[MatLike, dict[str, MatchResultList]] | None:
    """读取平台模拟室区域，缺少截图或配置时不产生输入。"""
    area = ctx.screen_loader.get_area('实战模拟室', area_name)
    if area is None or screen is None:
        return None
    rect = area.rect
    image = screen[rect.y1:rect.y2, rect.x1:rect.x2]
    if not image.size:
        return None
    return image, ctx.ocr.crop_and_run_ocr(screen, rect)


def read_preset_charge(ctx: ZContext, screen: MatLike | None) -> tuple[int, int] | None:
    """读取实际电量与所需消耗，不用卡片预估代替画面。"""
    area = read_preset_area(ctx, screen, '手柄-电量')
    if area is None:
        return None
    values: set[tuple[int, int]] = set()
    for text in area[1]:
        match = re.fullmatch(r'\s*(\d{1,4})\s*/\s*(\d{1,3})\s*', text)
        if match is not None:
            values.add((int(match[1]), int(match[2])))
    return next(iter(values)) if len(values) == 1 else None


def survey_preset_focused(ctx: ZContext, screen: MatLike | None) -> bool:
    """调查专项文字须被完整黄色卡片边框包住。"""
    area = read_preset_area(ctx, screen, '手柄-预设列表')
    if area is None:
        return False
    image, results = area
    target = next((matches.max for text, matches in results.items()
                   if '调查专项' in text and matches.max is not None), None)
    if target is None:
        return False
    contours, _ = cv2.findContours(
        highlight_mask(image, 'yellow'), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
    )
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if width < 200 or height < 100 or cv2.contourArea(contour) / (width * height) < 0.75:
            continue
        if x < target.x < target.x + target.w < x + width and y < target.y < target.y + target.h < y + height:
            return True
    return False


class GamepadConfigureCards(ZOperation):
    """复用已通过导航，只配置一张或五张调查专项卡片。"""

    STATUS_AT_PRESET: ClassVar[str] = '已在模拟室预设'

    def __init__(self, ctx: ZContext, num_cards: int) -> None:
        """保留明确目标数量，不自动把一张计划当作五张。"""
        super().__init__(ctx, op_name=f'手柄配置调查专项 {num_cards} 张卡片', timeout_seconds=90)
        self.num_cards: int = num_cards
        self._edit_sent: bool = False
        self._menu_confirm_sent: bool = False
        self._last_menu_focus: str | None = None
        self._expected_required: int | None = None
        self._save_sent: bool = False
        self._unchanged_rounds: int = 0
        self._edit_steps: int = 0
        self._unknown_rounds: int = 0
        self.evidence: dict[str, str] = {}

    def handle_init(self) -> None:
        """重复运行从当前画面恢复，不保留上次编辑按键标记。"""
        self._edit_sent = False
        self._menu_confirm_sent = False
        self._last_menu_focus = None
        self._expected_required = None
        self._save_sent = False
        self._unchanged_rounds = 0
        self._edit_steps = 0
        self._unknown_rounds = 0
        self.evidence = {}

    def _found(self, area_name: str) -> bool:
        """只读取已建档的模拟室区域。"""
        return self.last_screenshot is not None and self.round_by_find_area(
            self.last_screenshot, '实战模拟室', area_name,
        ).is_success

    def _preset_visible(self) -> bool:
        """挑战等级与下一步同时出现才算外层预设。"""
        return self._found('手柄-挑战等级') and self._found('手柄-下一步')

    def _preset_menu(self) -> tuple[bool, str | None]:
        """菜单默认开始战斗，必须识别唯一黄色焦点，不能沿用外层 A。"""
        area = read_preset_area(self.ctx, self.last_screenshot, '手柄-预设操作菜单')
        if area is None:
            return False, None
        image, results = area
        names = ('开始战斗', '编辑', '重命名')
        if not all(any(name == text.replace(' ', '') for text in results) for name in names):
            return False, None
        selected = [
            name for name in names for text, matches in results.items()
            if name == text.replace(' ', '') and matches.max is not None
            and has_filled_highlight(image, matches.max.rect, 'yellow')
        ]
        return True, selected[0] if len(selected) == 1 else None

    def _editor_charge(self) -> tuple[int, int] | None:
        """用随机卡焦点、编辑提示和实际消耗确认编辑页。"""
        footer = read_preset_area(self.ctx, self.last_screenshot, '手柄-卡片编辑信息')
        card = read_preset_area(self.ctx, self.last_screenshot, '手柄-编辑随机卡')
        if footer is None or card is None:
            return None
        words = ''.join(footer[1]).replace(' ', '')
        if '保存方案' not in words or '取消选中' not in words:
            return None
        if not any('随机怪物卡' in text for text in card[1]):
            return None
        mask = highlight_mask(card[0], 'yellow')
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not any(
            200 <= cv2.boundingRect(contour)[2] <= 290
            and cv2.boundingRect(contour)[3] >= 350
            for contour in contours
        ):
            return None
        pairs = {
            (int(match[1]), int(match[2]))
            for text in footer[1]
            if (match := re.fullmatch(r'\s*(\d{1,4})\s*/\s*(\d{1,3})\s*', text))
            and int(match[2]) in (20, 40, 60, 80, 100)
        }
        return next(iter(pairs)) if len(pairs) == 1 else None

    def _save(self, state: str) -> None:
        """首次编辑前后保留 PNG，返回可直接读取的绝对路径。"""
        if state not in self.evidence and self.last_screenshot is not None:
            name = self.save_screenshot(prefix=f'macos_cards_{state}')
            self.evidence[state] = debug_utils.get_debug_image_path(name)

    @operation_node(name='核对卡片目标和起点', is_start_node=True)
    def check_entry(self) -> OperationRoundResult:
        """只支持一张和五张，从预设或已确认大世界进入。"""
        if self.num_cards not in (1, 5):
            return self.round_fail('Mac 卡片配置目前仅支持1张或5张')
        if self._preset_visible() or self._editor_charge() is not None:
            return self.round_success(self.STATUS_AT_PRESET)
        if self.last_screenshot is not None and self.round_by_find_area(
            self.last_screenshot, '大世界-普通', '快捷手册',
        ).is_success:
            return self.round_success()
        self._save('unknown_entry')
        return self.round_fail('卡片配置起点尚未建档，未发送输入', data={'evidence': dict(self.evidence)})

    @node_from(from_name='核对卡片目标和起点')
    @operation_node(name='传送至卡片预设', screenshot_before_round=False)
    def transport(self) -> OperationRoundResult:
        """复用已经通过的基础材料手册传送。"""
        return self.round_by_op_result(GamepadTransportByCompendium(
            self.ctx, '训练', '实战模拟室', '基础材料',
        ).execute())

    @node_from(from_name='核对卡片目标和起点', status=STATUS_AT_PRESET)
    @node_from(from_name='传送至卡片预设')
    @operation_node(name='配置调查专项卡片', node_max_retry_times=20, timeout_seconds=30)
    def configure(self) -> OperationRoundResult:
        """预设 A 只打开菜单，只有编辑项已高亮才再 A，不触发开始战斗。"""
        editor = self._editor_charge()
        if editor is not None:
            self._save('editor_before')
            _, required = editor
            if self._save_sent:
                self._unchanged_rounds += 1
                if self._unchanged_rounds > 4:
                    return self.round_fail('保存后仍停留在编辑页，未重复保存')
                return self.round_retry('等待卡片保存返回预设', wait=0.6)
            if self._expected_required is not None and required != self._expected_required:
                self._unchanged_rounds += 1
                if self._unchanged_rounds > 3:
                    self._save('count_unchanged')
                    return self.round_fail('卡片数量未按预期变化，已停止输入')
                return self.round_retry('等待卡片数量变化', wait=0.4)
            self._expected_required = None
            self._unchanged_rounds = 0
            if required == self.num_cards * 20:
                self._save('editor_target')
                self._save_sent = True
                self.ctx.controller.btn_tap('west')
                return self.round_retry('已保存卡片，等待实际消耗确认', wait=0.8)
            if self._edit_steps >= 4:
                return self.round_fail('卡片调整次数超限')
            remove = required > self.num_cards * 20
            self._expected_required = required + (-20 if remove else 20)
            self._edit_steps += 1
            self.ctx.controller.btn_tap('north' if remove else 'south')
            return self.round_retry('等待卡片减少' if remove else '等待卡片增加', wait=0.6)
        menu_visible, selected = self._preset_menu()
        if menu_visible:
            self._save('preset_menu')
            if selected is None:
                return self.round_fail('未识别预设菜单唯一焦点，未发送确认', data={
                    'evidence': dict(self.evidence),
                })
            if selected == '编辑':
                if not self._menu_confirm_sent:
                    self.ctx.controller.btn_tap('south')
                    self._menu_confirm_sent = True
                return self.round_retry('等待真正的卡片编辑页', wait=1)
            if self._last_menu_focus != selected and not self._menu_confirm_sent:
                self.ctx.controller.btn_tap('dpad_down' if selected == '开始战斗' else 'dpad_up')
                self._last_menu_focus = selected
            return self.round_retry('等待编辑项黄色焦点，未发送确认', wait=0.8)
        if self._preset_visible():
            if not survey_preset_focused(self.ctx, self.last_screenshot):
                return self.round_fail('当前未选中调查专项，未进入卡片编辑')
            charge = read_preset_charge(self.ctx, self.last_screenshot)
            if charge is None:
                return self.round_retry('等待实际电量消耗', wait=0.8)
            current, required = charge
            if required == self.num_cards * 20:
                self._save('configured')
                return self.round_success(f'已配置{self.num_cards}张卡片', data={
                    'num_cards': self.num_cards, 'current_charge': current,
                    'required_charge': required, 'evidence': dict(self.evidence),
                })
            if self._edit_sent:
                self._save('editor_pending')
                return self.round_fail('编辑后的新画面尚未建档，已保存截图', data={
                    'evidence': dict(self.evidence), 'num_cards': self.num_cards,
                })
            if not self._edit_sent:
                self._save('before_edit')
                self.ctx.controller.btn_tap('south')
                self._edit_sent = True
            return self.round_retry('等待调查专项卡片编辑页', wait=1)
        if self._save_sent or self._menu_confirm_sent:
            self._unknown_rounds += 1
            if self._unknown_rounds <= 3:
                return self.round_retry('等待编辑切换的稳定画面', wait=0.6)
        self._save('editor_pending' if self._edit_sent else 'unknown_editor')
        return self.round_fail('卡片编辑页尚未建档，已保存截图，未发送后续输入', data={
            'evidence': dict(self.evidence), 'num_cards': self.num_cards,
        })
