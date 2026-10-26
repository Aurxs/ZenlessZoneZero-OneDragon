"""读取游戏中保存的代理人培养目标，复用原手册入口。"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, ClassVar

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from one_dragon.utils import cv2_utils, debug_utils
from zzz_od.operation.gamepad.charge_transport import (
    GamepadChargeTransport,
    charge_mission_names,
    match_charge_mission,
)
from zzz_od.operation.gamepad.focus import (
    find_yellow_frames,
    has_filled_highlight,
    text_inside_frame,
)
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation
from zzz_od.operation.gamepad.simulation_preset import SIMULATION_TYPES

if TYPE_CHECKING:
    from cv2.typing import MatLike

    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem
    from zzz_od.context.zzz_context import ZContext


class GamepadOpenTrainingTarget(GamepadOperation):
    """打开原手册分类，供培养目标解析使用，不修改培养方案。"""

    def __init__(self, ctx: ZContext, category_name: str = '特训目标') -> None:
        """分类来自原计划，特训总览仅用于读取游戏已有目标。"""
        super().__init__(ctx, op_name=f'手柄查看培养目标 {category_name}', timeout_seconds=45)
        self.category_name: str = category_name
        self.navigation: GamepadChargeTransport = GamepadChargeTransport(ctx, category_name, '')

    def handle_init(self) -> None:
        """清除导航的一次性输入标记。"""
        self.navigation.handle_init()

    @operation_node(name='打开培养手册', is_start_node=True, node_max_retry_times=6)
    def open_handbook(self) -> OperationRoundResult:
        """只接受原手册中有培养入口的分类。"""
        if self.category_name not in ('特训目标', '实战模拟室', '区域巡防', '专业挑战室', '恶名狩猎'):
            return self.round_fail('未支持的培养目标分类')
        self.navigation.last_screenshot = self.last_screenshot
        return self.navigation.open_handbook()

    @node_from(from_name='打开培养手册')
    @operation_node(name='选择培养训练标签', node_max_retry_times=6)
    def choose_training(self) -> OperationRoundResult:
        """复用已验证训练标签导航。"""
        self.navigation.last_screenshot = self.last_screenshot
        return self.navigation.choose_training()

    @node_from(from_name='选择培养训练标签')
    @operation_node(name='选择培养分类', node_max_retry_times=10)
    def choose_category(self) -> OperationRoundResult:
        """确认左栏高亮后再读取内容，不点击目标或确认传送。"""
        self.navigation.last_screenshot = self.last_screenshot
        return self.navigation.choose_category()

    @node_from(from_name='选择培养分类')
    @operation_node(name='读取培养目标', node_max_retry_times=6)
    def inspect(self) -> OperationRoundResult:
        """保存实际目标画面，未解析前不进入副本。"""
        name = self.save_screenshot(prefix='macos_agent_training')
        return self.round_success('培养目标分类已打开', data={
            'category_name': self.category_name,
            'screenshot': debug_utils.get_debug_image_path(name),
        })


def marked_training_targets(ctx: ZContext, screen: MatLike, category_name: str) -> list[str]:
    """将原头像轮廓关联到其上方副本标题，排除无头像的普通推荐行。"""
    area = ctx.screen_loader.get_area('快捷手册', '手柄-培养头像标记')
    if area is None:
        raise ValueError('缺少培养头像标记区域')
    image = cv2_utils.crop_image_only(screen, area.rect)
    boxes = cv2_utils.find_character_avatars(image, min_area=400)
    marker_y = sorted(area.rect.y1 + y + height / 2 for _, y, width, height in boxes
                      if 25 <= width <= 70 and 25 <= height <= 70 and 0.8 < width / height < 1.2)
    words = ctx.ocr.run_ocr(screen)
    titles = [(training_mission_name(text, category_name), match.rect)
              for text, matches in words.items() for match in matches]
    targets: list[str] = []
    for y in marker_y:
        candidates = [(name, rect) for name, rect in titles if name is not None
                      and 450 < rect.center.x < area.rect.x1 and 0 < y - rect.center.y < 170]
        if not candidates:
            continue
        name, _ = min(candidates, key=lambda item: y - item[1].center.y)
        if name not in targets:
            targets.append(name)
    return targets


def resolve_training_plan(plan: ChargePlanItem, target: str) -> ChargePlanItem:
    """生成本场具体目标，保留原计划ID计数，绝不改写用户的培养计划。"""
    if not plan.is_agent_plan or target not in charge_mission_names(plan.category_name):
        raise ValueError('培养目标不在原副本数据中')
    return replace(plan, mission_type_name=target)


def training_mission_name(text: str, category_name: str) -> str | None:
    """模拟室先解析材料分类，其他副本沿用原名称与剧情别名。"""
    if category_name == '实战模拟室':
        name = text.replace(' ', '')
        return name if name in (*SIMULATION_TYPES, '自定义模板') else None
    return match_charge_mission(text, category_name)


class GamepadResolveTrainingTarget(GamepadOperation):
    """读取分类内已标记的目标，未找到时明确停止而不换成普通材料。"""

    STATUS_NO_TARGET: ClassVar[str] = '本分类未找到培养标记'

    def __init__(self, ctx: ZContext, category_name: str) -> None:
        """先支持有独立副本名称的分类，模拟室专项继续单独解析。"""
        super().__init__(ctx, op_name=f'手柄解析培养目标 {category_name}', timeout_seconds=180)
        self.category_name: str = category_name
        self.navigation: GamepadChargeTransport = GamepadChargeTransport(ctx, category_name, '')
        self._entered: bool = False
        self._last: str | None = None
        self._unchanged: int = 0
        self._down: bool = True
        self._seen: set[str] = set()

    def handle_init(self) -> None:
        """每场重新扫描标记，不复用上一次缺失结论。"""
        self.navigation.handle_init()
        self._entered = False
        self._last = None
        self._unchanged = 0
        self._down = True
        self._seen = set()

    @operation_node(name='打开原培养分类', is_start_node=True, screenshot_before_round=False)
    def open_category(self) -> OperationRoundResult:
        """只打开原计划分类，不更换培养角色。"""
        if self.category_name not in ('实战模拟室', '区域巡防', '专业挑战室', '恶名狩猎'):
            return self.round_fail('该培养分类尚未解析')
        return self.round_by_op_result(GamepadOpenTrainingTarget(self.ctx, self.category_name).execute())

    @node_from(from_name='打开原培养分类')
    @operation_node(name='解析已标记副本', node_max_retry_times=80, timeout_seconds=140)
    def resolve(self) -> OperationRoundResult:
        """多个目标沿原列表顺序取第一个；无标记不能直接宣称培养完成。"""
        if self.last_screenshot is None:
            return self.round_retry('等待培养目标截图', wait=0.6)
        targets = marked_training_targets(self.ctx, self.last_screenshot, self.category_name)
        if not targets:
            return self.scan_next()
        name = self.save_screenshot(prefix='macos_training_resolved')
        return self.round_success('培养副本已解析', data={
            'target': targets[0], 'visible_targets': targets,
            'screenshot': debug_utils.get_debug_image_path(name),
        })


    def scan_next(self) -> OperationRoundResult:
        """先向下、再向上有限遍历；无头像只记本轮跳过，不增加完成次数。"""
        nav = self.navigation.navigation
        nav.last_screenshot = self.last_screenshot
        area = nav._read_area('快捷手册', '手柄-副本列表')
        if area is None:
            return self.round_retry('等待培养列表', wait=0.7)
        image, words = area
        frames = find_yellow_frames(image)
        buttons = [match.rect for text, matches in words.items() if text.replace(' ', '') == '前往'
                   for match in matches if has_filled_highlight(image, match.rect, 'yellow')]
        selected: set[str] = set()
        visible: set[str] = set()
        for text, matches in words.items():
            name = training_mission_name(text, self.category_name)
            if name is None:
                continue
            for match in matches:
                list_rect = self.ctx.screen_loader.get_area('快捷手册', '手柄-副本列表').rect
                marker_rect = self.ctx.screen_loader.get_area('快捷手册', '手柄-培养头像标记').rect
                if match.center.y + list_rect.y1 + 115 < marker_rect.y2:
                    visible.add(name)
                if text_inside_frame(match.rect, frames) or (len(buttons) == 1 and 0 < buttons[0].center.y - match.center.y < 170):
                    selected.add(name)
        self._seen.update(visible)
        expected = set(SIMULATION_TYPES if self.category_name == '实战模拟室' else charge_mission_names(self.category_name))
        if expected and expected <= self._seen:
            return self.round_success(self.STATUS_NO_TARGET, data={'target': None, 'seen': sorted(self._seen)})
        if len(selected) == 1:
            current = next(iter(selected))
            if current == self._last:
                self._unchanged += 1
                if self._unchanged < 3:
                    return self.round_retry('等待培养列表移动', wait=0.7)
                if not self._down:
                    return self.round_success(self.STATUS_NO_TARGET, data={'target': None, 'seen': sorted(self._seen)})
                self._down = False
                self._unchanged = 0
            else:
                self._last = current
                self._unchanged = 0
            self.ctx.controller.btn_tap('dpad_down' if self._down else 'dpad_up')
            return self.round_retry('遍历尚未发现培养标记的列表', wait=0.8)
        if not self._entered and not frames and not buttons and nav._selected('手柄-分类列表', nav.CATEGORIES, 'blue') == self.category_name:
            self.ctx.controller.btn_tap('south')
            self._entered = True
        return self.round_retry('等待培养列表明确焦点', wait=0.8)


class GamepadCloseTrainingHandbook(GamepadOperation):
    """培养计划本轮跳过后退出手册，让下一计划从已确认大世界开始。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄退出培养手册', timeout_seconds=20)
        self.navigation: GamepadChargeTransport = GamepadChargeTransport(ctx, '实战模拟室', '')
        self._attempts: int = 0

    def handle_init(self) -> None:
        self._attempts = 0

    @operation_node(name='退出训练手册', is_start_node=True, node_max_retry_times=8)
    def close(self) -> OperationRoundResult:
        """只在训练手册正面特征存在时返回，不在未知界面猜按键。"""
        if self.last_screenshot is None:
            return self.round_retry('等待截图', wait=0.8)
        if self.round_by_find_area(self.last_screenshot, '大世界-普通', '快捷手册').is_success:
            return self.round_success('已退出培养手册')
        nav = self.navigation.navigation
        nav.last_screenshot = self.last_screenshot
        if nav._selected('手柄-顶部标签', nav.TABS, 'yellow') == '训练' and self._attempts < 3:
            self.ctx.controller.btn_tap('east')
            self._attempts += 1
        return self.round_retry('等待训练手册退出', wait=1)
