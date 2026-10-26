"""出战准备页的手柄预备编队入口。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from one_dragon.utils import debug_utils
from zzz_od.operation.gamepad.transport import find_yellow_focus_frames
from zzz_od.operation.predefined_team_recognizer import recognize_predefined_team
from zzz_od.operation.zzz_operation import ZOperation

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class GamepadOpenPredefinedTeam(ZOperation):
    """打开已有预备编队列表，不创建或修改游戏里的编队。"""

    def __init__(self, ctx: ZContext) -> None:
        """选择页由业务操作调用，不能从任意页面盲发 X。"""
        super().__init__(ctx, op_name='手柄打开预备编队', timeout_seconds=20)
        self._opened: bool = False

    def handle_init(self) -> None:
        """新运行清除打开标记。"""
        self._opened = False

    @operation_node(name='打开预备编队', is_start_node=True, node_max_retry_times=8)
    def open_teams(self) -> OperationRoundResult:
        """只在准备页固定按钮可见时打开列表。"""
        if self.last_screenshot is None:
            return self.round_retry('等待截图', wait=0.5)
        words = self.ctx.ocr.run_ocr(self.last_screenshot)
        if any('预备出战' in text for text in words):
            return self.round_success()
        if not self._opened and all(
            self.round_by_find_area(self.last_screenshot, '实战模拟室', name).is_success
            for name in ('手柄-出战', '手柄-预备编队')
        ):
            self.ctx.controller.btn_tap('west')
            self._opened = True
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


class GamepadChoosePredefinedTeam(ZOperation):
    """用原编队序号和成员核对第一屏六队，完成后回到出战准备。"""

    def __init__(self, ctx: ZContext, target_team_idx: int) -> None:
        """序号来自原计划配置，不通过临时队名替换游戏队伍。"""
        super().__init__(ctx, op_name='手柄选择预备编队', timeout_seconds=35)
        self.target_team_idx: int = target_team_idx
        self._selected: bool = False
        self._confirmed: bool = False
        self._verified_members: list[str] = []

    def handle_init(self) -> None:
        """每轮重新核对游戏队员。"""
        self._selected = False
        self._confirmed = False
        self._verified_members = []

    @operation_node(name='打开编队列表', is_start_node=True)
    def open_list(self) -> OperationRoundResult:
        """首版只开放已建档第一页，其他序号明确提示未支持。"""
        if not 0 <= self.target_team_idx < 6:
            return self.round_fail('Mac 预备编队暂支持前六队')
        return self.round_by_op_result(GamepadOpenPredefinedTeam(self.ctx).execute())

    @node_from(from_name='打开编队列表')
    @operation_node(name='选择目标编队', node_max_retry_times=12, timeout_seconds=20)
    def choose(self) -> OperationRoundResult:
        """由实际黄框导航；已选中目标时直接准备，不重复 A 取消。"""
        if self.last_screenshot is None:
            return self.round_retry('等待截图', wait=0.5)
        words = self.ctx.ocr.run_ocr(self.last_screenshot)
        target_area = self.ctx.screen_loader.get_area('编队选择', f'编队槽位{self.target_team_idx}')
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
        if focus == self.target_team_idx:
            if not self._selected:
                self.ctx.controller.btn_tap('south')
                self._selected = True
        else:
            row, col = divmod(focus, 2)
            target_row, target_col = divmod(self.target_team_idx, 2)
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
