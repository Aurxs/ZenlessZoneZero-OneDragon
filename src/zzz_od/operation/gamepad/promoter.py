"""按原候选优先级定位录像店宣传员，不替用户确认人物。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from zzz_od.game_data.agent import AgentEnum
from zzz_od.operation.gamepad.focus import highlight_mask
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation
from zzz_od.operation.gamepad.shop import (
    business_card_titles,
    focused_promoter_name,
    press_shop_action,
    promoter_name,
    read_shop_area,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from cv2.typing import MatLike

    from one_dragon.base.matcher.match_result import MatchResult
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class GamepadFocusPromoter(GamepadOperation):
    """逐帧确认焦点，扫描名单后才使用下一个配置候选。"""

    def __init__(
        self, ctx: ZContext, candidates: list[str],
        avatar_lookup: Callable[[MatLike, str], MatchResult | None] | None = None,
    ) -> None:
        super().__init__(ctx, op_name='手柄定位指定宣传员', timeout_seconds=120)
        self.candidates: list[str] = list(dict.fromkeys(candidates))
        self.avatar_lookup: Callable[[MatLike, str], MatchResult | None] | None = avatar_lookup
        self.valid_names: set[str] = {item.value.agent_name for item in AgentEnum} | {'邦布18'}
        self._index: int = 0
        self._direction: str = 'up'
        self._signature: tuple[str, tuple[str, ...]] | None = None
        self._stuck: int = 0
        self._moves: int = 0
        self._frame_time: float = -1

    def _target_rect(self, names: dict[str, Rect], target: str) -> Rect | None:
        """名称优先；原头像识别只用于定位卡片所在行，不直接点击坐标。"""
        if target in names:
            return names[target]
        if self.avatar_lookup is None or self.last_screenshot is None:
            return None
        match = self.avatar_lookup(self.last_screenshot, target)
        area = self.ctx.screen_loader.get_area('影像店营业', '手柄-宣传员列表')
        if match is None or area is None:
            return None
        x, y = match.center.x - area.x1, match.center.y - area.y1
        rows = [rect.center.y for rect in names.values() if 30 < rect.center.y - y < 300]
        if not rows:
            return None
        row = min(rows)
        return Rect(int(x - 20), int(row - 15), int(x + 20), int(row + 15))

    @operation_node(name='定位配置宣传员', is_start_node=True, node_max_retry_times=6)
    def focus(self) -> OperationRoundResult:
        """只在已建档列表移动，两个候选均不可选时明确失败。"""
        if not self.candidates or any(name not in self.valid_names for name in self.candidates):
            return self.round_fail('宣传员配置不在原人物列表中')
        if self._index >= len(self.candidates):
            return self.round_fail('未找到配置的宣传员候选，未替换为其他人物')
        if not self.round_by_find_area(self.last_screenshot, '影像店营业', '手柄-宣传员列表标题').is_success:
            return self.round_retry('等待宣传员列表', wait=0.5)
        controls = read_shop_area(self, '手柄-确认宣传员')
        if controls is not None and any('正在营业' in text for text in controls[1]):
            self.save_screenshot(prefix='macos_promoter_business_locked')
            return self.round_fail('今日已营业，宣传员锁定；未更换人物，待每日刷新')
        if self.last_screenshot_time <= self._frame_time:
            return self.round_retry('等待移焦后的新帧', wait=0.5)
        read = read_shop_area(self, '手柄-宣传员列表')
        current = focused_promoter_name(self, self.valid_names)
        if read is None or current is None:
            return self.round_retry('等待宣传员唯一焦点与名称', wait=0.5)
        target = self.candidates[self._index]
        if current == target:
            self.save_screenshot(prefix='macos_promoter_target_focused')
            return self.round_success('配置宣传员已聚焦', data={'agent_name': target})
        names = {promoter_name(text): matches.max.rect for text, matches in read[1].items()
                 if matches.max is not None and promoter_name(text) in self.valid_names}
        target_rect = self._target_rect(names, target)
        current_rect = names.get(current)
        if current_rect is None:
            contours, _ = cv2.findContours(highlight_mask(read[0], 'yellow'), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cards = [(x, y, w, h) for contour in contours for x, y, w, h in [cv2.boundingRect(contour)]
                     if 160 <= w <= 240 and 250 <= h <= 330 and cv2.contourArea(contour) / (w * h) >= 0.85]
            if len(cards) == 1:
                x, y, width, height = cards[0]
                current_rect = Rect(x, y + height - 65, x + width, y + height)
        if target_rect is not None and current_rect is not None:
            if abs(target_rect.center.y - current_rect.center.y) > 100:
                key = 'dpad_down' if target_rect.center.y > current_rect.center.y else 'dpad_up'
            else:
                key = 'dpad_right' if target_rect.center.x > current_rect.center.x else 'dpad_left'
            self._signature = None
            self._stuck = 0
        else:
            signature = (current, tuple(sorted(names)))
            self._stuck = self._stuck + 1 if self._signature == signature else 0
            self._signature = signature
            if self._stuck >= 2:
                if self._direction == 'up':
                    self._direction = 'down'
                else:
                    self._index += 1
                    self._direction = 'up'
                self._signature = None
                self._stuck = 0
                return self.round_wait('当前方向已到边界，继续核对候选', wait=0.5)
            key = f'dpad_{self._direction}'
        if self._moves >= 48:
            return self.round_fail('宣传员扫描达到上限，未确认其他人物')
        self.ctx.controller.btn_tap(key)
        self._moves += 1
        self._frame_time = self.last_screenshot_time
        return self.round_wait(f'定位配置宣传员 {target}', wait=0.5)


class GamepadConfirmPromoter(GamepadOperation):
    """核对指定焦点后沿原商店确认，必须看到主页实际人物才成功。"""

    def __init__(self, ctx: ZContext, agent_name: str) -> None:
        from zzz_od.application.random_play.random_play_app import RandomPlayApp

        super().__init__(ctx, op_name=f'手柄确认宣传员 {agent_name}', timeout_seconds=20)
        self.original: RandomPlayApp = RandomPlayApp(ctx)
        self.original.handle_init()
        self.agent_name: str = agent_name
        self._sent: bool = False

    @operation_node(name='确认并核对主页人物', is_start_node=True, node_max_retry_times=8)
    def confirm(self) -> OperationRoundResult:
        valid = {item.value.agent_name for item in AgentEnum} | {'邦布18'}
        if self.agent_name not in valid:
            return self.round_fail('指定宣传员不在原人物列表中')
        self.original.last_screenshot = self.last_screenshot
        self.original.last_screenshot_time = self.last_screenshot_time
        if self._sent:
            if self.original._macos_business_visible():
                if business_card_titles(self.original)[0] != self.agent_name:
                    return self.round_fail('主页宣传员与指定人物不同')
                self.save_screenshot(prefix='macos_promoter_confirmed')
                return self.round_success('指定宣传员已确认', data={'agent_name': self.agent_name})
            return self.round_retry('等待人物确认后的经营主页', wait=0.8)
        controls = read_shop_area(self.original, '手柄-确认宣传员')
        if controls is None or any('正在营业' in word for word in controls[1]):
            return self.round_fail('宣传员确认不可用，未开始营业或更换其他人物')
        if focused_promoter_name(self.original, valid) != self.agent_name:
            return self.round_fail('当前焦点不是指定人物，未确认')
        result = press_shop_action(self.original, '影像店营业', '确认宣传员')
        if not result.is_success:
            return result
        self._sent = True
        return self.round_retry('等待指定人物显示在主页', wait=0.8)


class GamepadOpenPromoterList(GamepadOperation):
    """复用原应用的进入步骤，只打开人物列表，不开始营业或写记录。"""

    def __init__(self, ctx: ZContext) -> None:
        from zzz_od.application.random_play.random_play_app import RandomPlayApp

        super().__init__(ctx, op_name='手柄打开录像店宣传员列表', timeout_seconds=220)
        self.original: RandomPlayApp = RandomPlayApp(ctx)
        self.original.handle_init()

    def _copy_frame(self) -> None:
        """原节点继续读取同一控制器的新帧。"""
        self.original.last_screenshot = self.last_screenshot
        self.original.last_screenshot_time = self.last_screenshot_time

    @operation_node(name='前往原营业点', is_start_node=True)
    def transport(self) -> OperationRoundResult:
        """目标沿原配置，已有经营页可直接接续。"""
        self._copy_frame()
        result = self.original.transport()
        if result.status in (self.original.STATUS_MACOS_CONFIRM, self.original.STATUS_MACOS_STARTED):
            return self.round_fail('当前处于营业确认，未把它作为人物列表处理')
        return result

    @node_from(from_name='前往原营业点')
    @operation_node(name='交互原营业点')
    def interact(self) -> OperationRoundResult:
        self._copy_frame()
        return self.original.move_and_interact()

    @node_from(from_name='交互原营业点')
    @operation_node(name='查看经营状况')
    def dialog(self) -> OperationRoundResult:
        self._copy_frame()
        return self.original.handle_interaction_dialog()

    @node_from(from_name='查看经营状况')
    @node_from(from_name='前往原营业点', status='Mac 已在录像店经营页面')
    @operation_node(name='等待原经营页', node_max_retry_times=10)
    def wait_shop(self) -> OperationRoundResult:
        self._copy_frame()
        return self.original.wait_run()

    @node_from(from_name='等待原经营页')
    @operation_node(name='打开人物列表', node_max_retry_times=10)
    def open_list(self) -> OperationRoundResult:
        self._copy_frame()
        return self.original._macos_open_card(0, '宣传员入口')

    @node_from(from_name='打开人物列表')
    @operation_node(name='确认人物列表', node_max_retry_times=6)
    def ready(self) -> OperationRoundResult:
        if self.round_by_find_area(self.last_screenshot, '影像店营业', '手柄-宣传员列表标题').is_success:
            return self.round_success('宣传员列表已打开')
        return self.round_retry('等待宣传员列表', wait=0.5)
