"""出战准备页的手柄预备编队入口。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from one_dragon.utils import debug_utils
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation
from zzz_od.operation.gamepad.transport import find_yellow_focus_frames
from zzz_od.operation.predefined_team_recognizer import (
    find_team_name,
    recognize_predefined_team,
)

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class GamepadOpenPredefinedTeam(GamepadOperation):
    """打开已有预备编队列表，不创建或修改游戏里的编队。"""

    def __init__(self, ctx: ZContext) -> None:
        """选择页由业务操作调用，不能从任意页面盲发 X。"""
        super().__init__(ctx, op_name='手柄打开预备编队', timeout_seconds=20)
        self._open_attempts: int = 0
        self._ready_frames: int = 0

    def handle_init(self) -> None:
        """新运行清除打开标记。"""
        self._open_attempts = 0
        self._ready_frames = 0

    @operation_node(name='打开预备编队', is_start_node=True, node_max_retry_times=8)
    def open_teams(self) -> OperationRoundResult:
        """只在准备页固定按钮可见时打开列表。"""
        if self.last_screenshot is None:
            return self.round_retry('等待截图', wait=0.5)
        words = self.ctx.ocr.run_ocr(self.last_screenshot)
        if any('预备出战' in text for text in words):
            return self.round_success()
        if all(
            self.round_by_find_area(self.last_screenshot, '实战模拟室', name).is_success
            for name in ('手柄-出战', '手柄-预备编队')
        ):
            self._ready_frames += 1
            if self._ready_frames % 2 == 1 and self._open_attempts < 3:
                self.ctx.controller.btn_tap('west')
                self._open_attempts += 1
            return self.round_retry('等待预备编队列表', wait=1)
        if self.node_retry_times >= 3:
            self.save_screenshot(prefix='macos_teams_open_pending')
        return self.round_retry('等待可识别的预备编队列表', wait=0.5)

    @node_from(from_name='打开预备编队')
    @operation_node(name='记录编队列表')
    def inspect(self) -> OperationRoundResult:
        """保存列表供既有识别与选择流程使用。"""
        name = self.save_screenshot(prefix='macos_teams_list')
        return self.round_success('预备编队列表已打开', data={
            'screenshot': debug_utils.get_debug_image_path(name),
        })


class GamepadChoosePredefinedTeam(GamepadOperation):
    """用原编队序号定位二十队并核对成员，完成后回到出战准备。"""

    def __init__(self, ctx: ZContext, target_team_idx: int) -> None:
        """序号来自原计划配置，不通过临时队名替换游戏队伍。"""
        super().__init__(ctx, op_name='手柄选择预备编队', timeout_seconds=150)
        self.target_team_idx: int = target_team_idx
        self._selected: bool = False
        self._confirmed: bool = False
        self._verified_members: list[str] = []
        self._visible_slot: int | None = target_team_idx if target_team_idx < 6 else None

    def handle_init(self) -> None:
        """每轮重新核对游戏队员。"""
        self._selected = False
        self._confirmed = False
        self._verified_members = []
        self._visible_slot = None

    @operation_node(name='打开编队列表', is_start_node=True)
    def open_list(self) -> OperationRoundResult:
        """打开列表后单独定位，不能把绝对队号当作当前可见槽位。"""
        if not 0 <= self.target_team_idx < 20:
            return self.round_fail('预备编队序号须为0至19')
        return self.round_by_op_result(GamepadOpenPredefinedTeam(self.ctx).execute())

    @node_from(from_name='打开编队列表')
    @operation_node(name='定位目标编队', screenshot_before_round=False)
    def locate(self) -> OperationRoundResult:
        """先完成带反馈的分页导航，保留实际可见槽位。"""
        result = GamepadFocusPredefinedTeam(self.ctx, self.target_team_idx).execute()
        if result.success:
            self._visible_slot = result.data['visible_slot']
        return self.round_by_op_result(result)

    @node_from(from_name='定位目标编队')
    @operation_node(name='选择目标编队', node_max_retry_times=12, timeout_seconds=20)
    def choose(self) -> OperationRoundResult:
        """由实际黄框导航；已选中目标时直接准备，不重复 A 取消。"""
        if self.last_screenshot is None:
            return self.round_retry('等待截图', wait=0.5)
        words = self.ctx.ocr.run_ocr(self.last_screenshot)
        if self._visible_slot is None:
            return self.round_fail('目标编队尚未定位')
        target_area = self.ctx.screen_loader.get_area('编队选择', f'编队槽位{self._visible_slot}')
        team = self.ctx.team_config.get_team_by_idx(self.target_team_idx)
        if target_area is None or team is None:
            return self.round_fail('预备编队配置缺失')
        if not self._verified_members:
            actual = recognize_predefined_team(self.ctx, self.last_screenshot, words, target_area.rect)
            members = [match.data.agent_id for match in actual.agent_match_result_list]
            if len(members) != 3 or members != team.agent_id_list:
                return self.round_fail('游戏编队成员与 GUI 配置不一致，请同步预备编队')
            self._verified_members = members
        selected = any(
            'SELECTED' in text.upper()
            and target_area.rect.x1 < match.center.x < target_area.rect.x2
            and target_area.rect.y1 < match.center.y < target_area.rect.y2
            for text, matches in words.items() for match in matches
        )
        if selected:
            self.save_screenshot(prefix='macos_team_selected')
            self.ctx.controller.btn_tap('start')
            self._confirmed = True
            return self.round_success(wait=1)
        frames = find_yellow_focus_frames(self.last_screenshot, 750, 850, 240, 300)
        if len(frames) != 1:
            return self.round_retry('等待编队黄色焦点', wait=0.5)
        areas = [self.ctx.screen_loader.get_area('编队选择', f'编队槽位{i}') for i in range(6)]
        if any(area is None for area in areas):
            return self.round_fail('编队槽位区域缺失')
        focus = min(range(6), key=lambda i: (areas[i].center.x - frames[0].center.x) ** 2
                    + (areas[i].center.y - frames[0].center.y) ** 2)
        if focus == self._visible_slot:
            if not self._selected:
                self.ctx.controller.btn_tap('south')
                self._selected = True
        else:
            row, col = divmod(focus, 2)
            target_row, target_col = divmod(self._visible_slot, 2)
            key = ('dpad_down' if row < target_row else 'dpad_up') if row != target_row else (
                'dpad_right' if col < target_col else 'dpad_left'
            )
            self.ctx.controller.btn_tap(key)
        return self.round_retry('等待目标编队选中', wait=0.6)

    @node_from(from_name='选择目标编队')
    @operation_node(name='核对编队返回', node_max_retry_times=8, timeout_seconds=12)
    def verify(self) -> OperationRoundResult:
        """预备编队确认后必须回到非空出战页，不能直接出战。"""
        if self.last_screenshot is None:
            return self.round_retry('等待截图', wait=0.5)
        ready = all(self.round_by_find_area(self.last_screenshot, '实战模拟室', name).is_success
                    for name in ('手柄-出战', '手柄-预备编队'))
        if ready:
            words = self.ctx.ocr.run_ocr(self.last_screenshot)
            if any('EMPTY' in text.upper() for text in words):
                return self.round_retry('等待编队成员加载', wait=0.5)
            name = self.save_screenshot(prefix='macos_team_ready')
            return self.round_success('预备编队已选择', data={
                'team_idx': self.target_team_idx, 'agent_ids': self._verified_members,
                'screenshot': debug_utils.get_debug_image_path(name),
            })
        return self.round_retry('等待返回出战准备', wait=0.5)


class GamepadFocusPredefinedTeam(GamepadOperation):
    """通过首尾循环确认行号，再按可见卡片反馈定位原配置序号。"""

    def __init__(self, ctx: ZContext, target_team_idx: int, management: bool = False) -> None:
        """只移动焦点，不选择、编辑或出战，可用于无消耗准备。"""
        super().__init__(ctx, op_name='手柄定位预备编队', timeout_seconds=100)
        self.target_team_idx: int = target_team_idx
        self.management: bool = management
        self._at_top: bool = False
        self._row: int = 0
        self._previous: tuple[int, tuple[str, ...]] | None = None
        self._pending: str | None = None
        self._unchanged: int = 0

    def handle_init(self) -> None:
        """每次重新定位列表起点，不继承上次页码。"""
        self._at_top = False
        self._row = 0
        self._previous = None
        self._pending = None
        self._unchanged = 0

    @operation_node(name='定位编队', is_start_node=True, node_max_retry_times=65)
    def focus_team(self) -> OperationRoundResult:
        """每次按键后核对黄框或卡片重叠，不按发送次数推断翻页成功。"""
        if not 0 <= self.target_team_idx < 20:
            return self.round_fail('预备编队序号须为0至19')
        if self.last_screenshot is None:
            return self.round_retry('等待截图', wait=0.5)
        words = self.ctx.ocr.run_ocr(self.last_screenshot)
        selection = any('预备出战' in text for text in words)
        if self.management:
            if selection or not all(any(name in text for text in words) for name in ('BANGBOO', '选择', '返回')):
                return self.round_fail('当前不是预备编队管理页')
        elif not selection:
            return self.round_fail('当前不是预备编队选择页')
        areas = [self.ctx.screen_loader.get_area('编队选择', f'编队槽位{i}') for i in range(6)]
        if any(area is None for area in areas):
            return self.round_fail('编队槽位区域缺失')
        frames = find_yellow_focus_frames(self.last_screenshot, 750, 850, 240, 300)
        if len(frames) != 1:
            return self.round_retry('等待编队黄色焦点', wait=0.6)
        focus = min(range(6), key=lambda i: (areas[i].center.x - frames[0].center.x) ** 2
                    + (areas[i].center.y - frames[0].center.y) ** 2)
        names = tuple(find_team_name(words, area.rect) or '' for area in areas)
        if not all(names):
            return self.round_retry('等待六个可见编队标题', wait=0.6)
        state = (focus, names)
        if self._pending is not None and self._previous is not None:
            old_focus, old_names = self._previous
            if state == self._previous:
                self._unchanged += 1
                if self._unchanged < 2:
                    return self.round_retry('等待编队移动反馈', wait=0.6)
                if self._unchanged >= 6:
                    return self.round_fail('编队导航未移动，停止定位')
            else:
                old_row, old_col = divmod(old_focus, 2)
                row, col = divmod(focus, 2)
                wrapped_up = self._pending == 'dpad_up' and old_row == 0 and row == 2 and col == old_col and names != old_names
                wrapped_down = self._pending == 'dpad_down' and old_row == 2 and row == 0 and col == old_col and names != old_names
                if wrapped_up:
                    self._at_top = True
                    self._row = 9
                    valid = True
                elif wrapped_down:
                    self._at_top = True
                    self._row = 0
                    valid = True
                elif self._pending in ('dpad_left', 'dpad_right'):
                    valid = names == old_names and row == old_row and col != old_col
                elif names == old_names:
                    valid = col == old_col and row - old_row == (1 if self._pending == 'dpad_down' else -1)
                elif self._pending == 'dpad_down':
                    valid = col == old_col and row == old_row and names[:4] == old_names[2:] and names != old_names
                else:
                    valid = col == old_col and row == old_row and names[2:] == old_names[:4] and names != old_names
                if not valid:
                    return self.round_retry('等待稳定的编队翻页重叠', wait=0.6)
                if self._at_top and not (wrapped_up or wrapped_down):
                    if self._pending == 'dpad_down':
                        self._row += 1
                    elif self._pending == 'dpad_up':
                        self._row -= 1
                self._unchanged = 0
        if not self._at_top:
            key = 'dpad_up'
        elif self._row != self.target_team_idx // 2:
            key = 'dpad_down' if self._row < self.target_team_idx // 2 else 'dpad_up'
        elif focus % 2 != self.target_team_idx % 2:
            key = 'dpad_right' if self.target_team_idx % 2 else 'dpad_left'
        else:
            name = self.save_screenshot(prefix='macos_team_focused')
            return self.round_success('目标编队已定位', data={
                'team_idx': self.target_team_idx, 'visible_slot': focus,
                'screenshot': debug_utils.get_debug_image_path(name),
            })
        self._previous = state
        self._pending = key
        self.ctx.controller.btn_tap(key)
        return self.round_retry('等待编队导航反馈', wait=0.8)
