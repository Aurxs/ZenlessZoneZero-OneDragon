"""普通材料专项的识别、选择与实际电量读取。"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING

import cv2

from one_dragon.base.operation.operation_node import operation_node
from zzz_od.game_data.compendium import CompendiumService
from zzz_od.operation.gamepad.focus import highlight_mask
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation

if TYPE_CHECKING:
    from cv2.typing import MatLike

    from one_dragon.base.matcher.match_result import MatchResultList
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext

SIMULATION_TYPES: tuple[str, ...] = ('基础材料', '代理人晋升', '音擎改装', '代理人技能')


@lru_cache(maxsize=1)
def simulation_targets() -> dict[str, tuple[str, ...]]:
    """复用原副本数据，不维护另一套专项名称和排序。"""
    service = CompendiumService()
    service.reload()
    return {
        name: tuple(item.mission_name for item in service.get_mission_list_data('训练', '实战模拟室', name))
        for name in SIMULATION_TYPES
    }


def read_preset_area(
    ctx: ZContext, screen: MatLike | None, area_name: str,
    screen_name: str = '实战模拟室',
) -> tuple[MatLike, dict[str, MatchResultList]] | None:
    """读取平台模拟室区域，缺少截图或配置时不产生输入。"""
    area = ctx.screen_loader.get_area(screen_name, area_name)
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


def read_focused_choice(
    ctx: ZContext, screen: MatLike | None, area_name: str, names: tuple[str, ...],
    screen_name: str = '实战模拟室', border_gap: int = 5, allow_corner_gap: bool = False,
) -> tuple[str | None, set[str]]:
    """一次 OCR 匹配名称和完整黄框，同时返回可见目标。"""
    area = read_preset_area(ctx, screen, area_name, screen_name)
    if area is None:
        return None, set()
    image, results = area
    visible = {text.replace(' ', '') for text in results} & set(names)
    # 压缩、NEW 标记和翻页箭头会遮挡边框；按页面实际缺口闭合。
    mask = cv2.morphologyEx(
        highlight_mask(image, 'yellow'), cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (border_gap, border_gap)),
    )
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    selected: set[str] = set()
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if width < 150 or height < 100:
            continue
        if cv2.contourArea(contour) / (width * height) < 0.75:
            # 培养头像遮住角落时，仍要求四条边大部存在，不能仅凭外接矩形放行。
            border = mask[y:y + height, x:x + width]
            coverage = (border[:12].any(axis=0).mean(), border[-12:].any(axis=0).mean(),
                        border[:, :12].any(axis=1).mean(), border[:, -12:].any(axis=1).mean())
            if not allow_corner_gap or min(coverage) < 0.6 or cv2.contourArea(cv2.convexHull(contour)) / (width * height) < 0.85:
                continue
        for text, matches in results.items():
            name = text.replace(' ', '')
            target = matches.max
            if name not in visible or target is None:
                continue
            if x < target.x < target.x + target.w < x + width and y < target.y < target.y + target.h < y + height:
                selected.add(name)
    return (next(iter(selected)) if len(selected) == 1 else None), visible


def selected_preset(ctx: ZContext, screen: MatLike | None) -> str | None:
    """识别原副本数据中的唯一专项焦点。"""
    names = tuple(name for group in simulation_targets().values() for name in group)
    return read_focused_choice(ctx, screen, '手柄-预设列表', names)[0]


def preset_focused(ctx: ZContext, screen: MatLike | None, mission_name: str) -> bool:
    """材料名称与当前唯一焦点必须一致。"""
    return selected_preset(ctx, screen) == mission_name


class GamepadChooseSimulationPreset(GamepadOperation):
    """从当前专项焦点移到配置目标，每次移动后确认新帧。"""

    def __init__(self, ctx: ZContext, mission_name: str, mission_type_name: str = '基础材料') -> None:
        super().__init__(ctx, op_name=f'手柄选择{mission_name}', timeout_seconds=70)
        self.mission_name: str = mission_name
        self.mission_type_name: str = mission_type_name
        self._category_confirm_sent: bool = False
        self._preset_back_sent: bool = False
        self._last_focus: str | None = None
        self._unchanged_rounds: int = 0
        self._moves: int = 0
        self._menu_back_sent: bool = False

    def handle_init(self) -> None:
        """每次运行重新识别起点。"""
        self._last_focus = None
        self._unchanged_rounds = 0
        self._moves = 0
        self._menu_back_sent = False
        self._category_confirm_sent = False
        self._preset_back_sent = False

    @operation_node(name='选择材料专项', is_start_node=True, node_max_retry_times=24)
    def choose(self) -> OperationRoundResult:
        """目标和唯一整卡焦点都已确认才移动，未知状态不猜方向。"""
        names = simulation_targets().get(self.mission_type_name, ())
        if self.mission_name not in names:
            return self.round_fail(f'尚未支持专项：{self.mission_name}')
        menu = read_preset_area(self.ctx, self.last_screenshot, '手柄-预设操作菜单')
        if menu is not None and all(
            name in {text.replace(' ', '') for text in menu[1]}
            for name in ('开始战斗', '编辑', '重命名')
        ):
            if not self._menu_back_sent:
                self.ctx.controller.btn_tap('east')
                self._menu_back_sent = True
            return self.round_retry('关闭旧方案菜单后重新核对材料', wait=0.8)
        category_names = (*SIMULATION_TYPES, '自定义模板')
        category, _ = read_focused_choice(self.ctx, self.last_screenshot, '手柄-材料分类列表', category_names)
        if category is not None:
            if category == self.mission_type_name:
                if not self._category_confirm_sent:
                    self.ctx.controller.btn_tap('south')
                    self._category_confirm_sent = True
                return self.round_retry('等待目标材料分类的方案页', wait=1)
            return self._move_focus(category, self.mission_type_name, category_names)
        if self.last_screenshot is None or not all(
            self.round_by_find_area(self.last_screenshot, '实战模拟室', area).is_success
            for area in ('手柄-挑战等级', '手柄-下一步')
        ):
            return self.round_retry('等待材料分类或方案页', wait=0.8)
        current = selected_preset(self.ctx, self.last_screenshot)
        if current is None:
            return self.round_retry('未识别唯一专项焦点，未发送按键', wait=0.8)
        if current not in names:
            if not self._preset_back_sent:
                self.ctx.controller.btn_tap('east')
                self._preset_back_sent = True
                self._last_focus = None
            return self.round_retry('返回材料分类以匹配计划', wait=0.8)
        if current == self.mission_name:
            self.save_screenshot(prefix='macos_material_selected')
            return self.round_success(f'已选中{current}')
        return self._move_focus(current, self.mission_name, names)

    def _move_focus(self, current: str, target: str, names: tuple[str, ...]) -> OperationRoundResult:
        """复用已确认排序逐格移动，跨页仍以实际焦点反馈为准。"""
        if current == self._last_focus:
            self._unchanged_rounds += 1
            if self._unchanged_rounds >= 3:
                self.save_screenshot(prefix='macos_material_focus_unchanged')
                return self.round_fail('材料焦点未按预期移动')
            return self.round_retry('等待材料焦点更新', wait=0.8)
        if self._moves >= 15:
            self.save_screenshot(prefix='macos_material_move_limit')
            return self.round_fail('材料切换超过预期步数')
        self._last_focus = current
        self._unchanged_rounds = 0
        self._moves += 1
        direction = 'dpad_right' if names.index(current) < names.index(target) else 'dpad_left'
        self.ctx.controller.btn_tap(direction)
        return self.round_retry('等待目标材料焦点', wait=0.8)
