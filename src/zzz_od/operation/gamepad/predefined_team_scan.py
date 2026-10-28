"""扫描管理页的二十队，沿原 Windows 配置方法同步识别结果。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation
from zzz_od.operation.gamepad.predefined_team import GamepadFocusPredefinedTeam
from zzz_od.operation.gamepad.transport import find_yellow_focus_frames
from zzz_od.operation.predefined_team_recognizer import (
    PredefinedTeamRecognition,
    find_team_name,
    recognize_predefined_team,
)

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class GamepadScanPredefinedTeams(GamepadOperation):
    """先由原定位器确认首队，再按四张重叠卡核对每次滚动。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄识别并同步预备编队', timeout_seconds=300)
        self._instance_idx: int = ctx.current_instance_idx
        self._page_start: int = 0
        self._seen: dict[int, PredefinedTeamRecognition] = {}
        self.updated_indices: set[int] = set()
        self._screenshots: list[str] = []
        self._previous_state: tuple[int, tuple[str, ...]] | None = None
        self._waiting: int = 0

    def _sync_recognition(self, team_idx: int, recognition: PredefinedTeamRecognition) -> None:
        """与 Windows 一致：无成员时跳过，其余由原更新方法补空位并保留策略。"""
        members = [match.data for match in recognition.agent_match_result_list]
        if not members:
            return
        self.ctx.team_config.update_team_by_idx(team_idx, recognition.team_name, members)
        self.updated_indices.add(team_idx)

    @operation_node(name='确认管理页首队', is_start_node=True)
    def locate_top(self) -> OperationRoundResult:
        return self.round_by_op_result(GamepadFocusPredefinedTeam(self.ctx, 0, management=True).execute())

    @node_from(from_name='确认管理页首队')
    @operation_node(name='读取并滚动编队', node_max_retry_times=60, timeout_seconds=180)
    def scan(self) -> OperationRoundResult:
        if self.ctx.current_instance_idx != self._instance_idx:
            return self.round_fail('账户已改变，停止继续同步编队')
        if self.last_screenshot is None:
            return self.round_retry('等待管理页截图', wait=0.6)
        words = self.ctx.ocr.run_ocr(self.last_screenshot)
        if any('预备出战' in word for word in words) or not all(any(name in word for word in words) for name in ('BANGBOO', '选择', '返回')):
            return self.round_fail('管理页特征消失，停止继续同步编队')
        areas = [self.ctx.screen_loader.get_area('编队选择', f'编队槽位{i}') for i in range(6)]
        if any(area is None for area in areas):
            return self.round_fail('编队槽位区域缺失')
        frames = find_yellow_focus_frames(self.last_screenshot, 750, 850, 240, 300)
        names = tuple(find_team_name(words, area.rect) or '' for area in areas)
        if len(frames) != 1 or not all(names):
            return self.round_retry('等待六张完整卡片与唯一焦点', wait=0.6)
        focus = min(range(6), key=lambda i: (areas[i].center.x - frames[0].center.x) ** 2 + (areas[i].center.y - frames[0].center.y) ** 2)
        state = (focus, names)
        if state == self._previous_state:
            self._waiting += 1
            if self._waiting >= 4:
                return self.round_fail('管理页焦点未移动，停止继续同步编队')
            return self.round_retry('等待管理页导航反馈', wait=0.8)
        if self._previous_state is not None:
            old_focus, old_names = self._previous_state
            within_page = old_focus < 4 and focus == old_focus + 2 and all(names[i] == old_names[i] for i in range(6) if i not in (old_focus, focus))
            scrolled = old_focus >= 4 and focus == old_focus and names != old_names and all(names[i] == old_names[i + 2] for i in range(4) if i != old_focus - 2)
            if scrolled:
                self._page_start += 2
            elif not within_page:
                self._waiting += 1
                if self._waiting >= 4:
                    return self.round_fail('卡片重叠不一致，未猜测编队序号')
                return self.round_retry('等待滚动重叠稳定', wait=0.8)
        self._waiting = 0
        for slot, area in enumerate(areas):
            idx = self._page_start + slot
            if idx >= 20:
                continue
            if idx in self._seen:
                old = self._seen[idx]
                if old.team_name is None and names[slot] not in ('编队', 'RS', 'LS'):
                    old.team_name = names[slot]
                    self._sync_recognition(idx, old)
                continue
            actual = recognize_predefined_team(self.ctx, self.last_screenshot, words, area.rect)
            if actual.team_name in ('编队', 'RS', 'LS'):
                actual.team_name = None
            self._seen[idx] = actual
            self._sync_recognition(idx, actual)
        self._screenshots.append(self.save_screenshot(prefix=f'macos_team_scan_{self._page_start}'))
        if len(self._seen) == 20:
            return self.round_success(f'二十队扫描完成，已同步{len(self.updated_indices)}队', data={
                'teams': [{'team_idx': idx, 'name': team.team_name, 'agent_ids': [match.data.agent_id for match in team.agent_match_result_list]} for idx, team in sorted(self._seen.items())],
                'screenshots': self._screenshots, 'updated_indices': sorted(self.updated_indices),
            })
        self._previous_state = state
        self.ctx.controller.btn_tap('dpad_down')
        return self.round_retry('等待下一行编队', wait=0.8)


class GamepadClosePredefinedTeams(GamepadOperation):
    """只从管理列表和功能导览返回，不选择或编辑游戏编队。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄退出编队管理', timeout_seconds=25)
        self._back_count: int = 0
        self._last_frame: float = -1

    @operation_node(name='退出管理返回大世界', is_start_node=True, node_max_retry_times=10)
    def back(self) -> OperationRoundResult:
        if self.last_screenshot is None or self.last_screenshot_time <= self._last_frame:
            return self.round_retry('等待返回新帧', wait=0.8)
        if self.round_by_find_area(self.last_screenshot, '大世界-普通', '快捷手册').is_success:
            return self.round_success('编队扫描已返回大世界')
        words = self.ctx.ocr.run_ocr(self.last_screenshot)
        management = not any('预备出战' in word for word in words) and all(any(name in word for word in words) for name in ('BANGBOO', '选择', '返回'))
        guide = self.round_by_find_area(self.last_screenshot, '功能导览', '标题').is_success
        if (management or guide) and self._back_count < 3:
            self.ctx.controller.btn_tap('east')
            self._last_frame = self.last_screenshot_time
            self._back_count += 1
            return self.round_retry('等待退出编队管理', wait=1)
        if self._back_count and self.node_retry_times < 6:
            return self.round_retry('等待返回大世界加载结束', wait=1)
        self.save_screenshot(prefix='macos_team_return_pending')
        return self.round_fail('未识别编队返回页面')
