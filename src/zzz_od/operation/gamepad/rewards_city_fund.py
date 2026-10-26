"""丽都城募的原生手柄领奖，只领取现有任务与等级奖励。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from zzz_od.operation.gamepad.focus import has_filled_highlight
from zzz_od.operation.gamepad.rewards import _GamepadRewardOperation

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class GamepadCityFund(_GamepadRewardOperation):
    """沿用原应用先任务、后等级的范围，不进入解锁和购买入口。"""

    MAIN_TABS: tuple[str, ...] = ('等级回馈', '成长任务', '城募赠礼')
    TASK_TABS: tuple[str, ...] = ('今日任务', '本周任务', '本期任务')
    MENU_ITEMS: tuple[str, ...] = (
        '更多', '勘域编队', '邮件', '设置', '公告', '成就',
        '绳网', '仓库', '代理人', '商城', '丽都城募', '调频',
    )

    def __init__(self, ctx: ZContext) -> None:
        """共用原生手柄输入与奖励确认，不新建运行配置。"""
        super().__init__(ctx, op_name='手柄丽都城募奖励', timeout_seconds=150)
        self._menu_opened: bool = False
        self._entered: bool = False
        self._task_scan_index: int = 0
        self._task_counts: dict[str, int] = {}
        self._claim_categories: list[str] = []
        self._task_verify_index: int = 0
        self._task_verify_waits: int = 0
        self._tasks_claim_sent: bool = False
        self._tasks_confirm_sent: bool = False
        self._level_claim_sent: bool = False
        self._level_confirm_sent: bool = False
        self._city_back_sent: bool = False
        self._menu_back_sent: bool = False

    def handle_init(self) -> None:
        """新运行重读实际任务，已有奖励弹窗不自动算作本次领取。"""
        self.evidence_paths.clear()
        self._menu_opened = False
        self._entered = False
        self._task_scan_index = 0
        self._task_counts.clear()
        self._claim_categories.clear()
        self._task_verify_index = 0
        self._task_verify_waits = 0
        self._tasks_claim_sent = False
        self._tasks_confirm_sent = False
        self._level_claim_sent = False
        self._level_confirm_sent = False
        self._city_back_sent = False
        self._menu_back_sent = False

    def _selected(self, screen: str, area: str, names: tuple[str, ...]) -> str | None:
        """文字周围必须有黄色填充，不以 NEW 或红叹号猜焦点。"""
        content = self._read_area(screen, area)
        if content is None:
            return None
        image, results = content
        selected: list[str] = []
        for name in names:
            rect = self._text_rect(results, name)
            if rect is not None and has_filled_highlight(image, rect, 'yellow'):
                selected.append(name)
        return selected[0] if len(selected) == 1 else None

    def main_tab(self) -> str | None:
        """左侧选择奖励、兑换商店不是 LB/RB 主标签。"""
        return self._selected('丽都城募', '手柄-主标签', self.MAIN_TABS)

    def task_tab(self) -> str | None:
        """按 LT/RT 提示读取今日、本周、本期的当前标签。"""
        return self._selected('丽都城募', '手柄-任务分类', self.TASK_TABS)

    def _city_visible(self) -> bool:
        """城募标题与一个主标签高亮同时出现才确认页面。"""
        return self.main_tab() is not None and self._has_text('丽都城募', '手柄-标题', '丽都城募')

    def _menu_visible(self) -> bool:
        """菜单底部必须能同时读到目标和相邻应用。"""
        area = self._read_area('菜单', '手柄-底部应用')
        return area is not None and all(
            self._text_rect(area[1], text) is not None for text in ('代理人', '商城', '丽都城募')
        )

    def _select_main_tab(self, target: str) -> OperationRoundResult:
        """主标签每次只走一格，并从下一帧重新确认高亮。"""
        selected = self.main_tab()
        if selected == target:
            return self.round_success()
        if selected is not None:
            key = 'right_shoulder' if self.MAIN_TABS.index(selected) < self.MAIN_TABS.index(target) else 'left_shoulder'
            self.ctx.controller.btn_tap(key)
        return self.round_retry(f'等待城募{target}标签', wait=0.6)

    def _select_task_tab(self, target: str) -> bool:
        """按当前高亮选择 LT/RT，不固定假设初始为今日任务。"""
        selected = self.task_tab()
        if selected == target:
            return True
        if selected is not None:
            key = 'right_trigger' if self.TASK_TABS.index(selected) < self.TASK_TABS.index(target) else 'left_trigger'
            self.ctx.controller.btn_tap(key)
        return False

    def task_claim_count(self) -> int | None:
        """只数右侧独立的领取状态，已领取和前往不能当作可领。"""
        area = self._read_area('丽都城募', '手柄-任务状态')
        if area is None:
            return None
        ready = 0
        known = 0
        for text, matches in area[1].items():
            normalized = text.replace(' ', '').upper()
            if normalized in ('领取', 'A领取'):
                ready += len(matches)
                known += len(matches)
            elif normalized in ('已领取', '前往', 'A前往', '-EMPTY-', 'EMPTY'):
                known += len(matches)
        return ready if known else None

    def _x_claim_available(self) -> bool:
        """黄色全部领取文字及左侧 X 字母都命中才允许输入。"""
        area = self._read_area('丽都城募', '手柄-底部提示')
        if area is None or not self._yellow_text('丽都城募', '手柄-底部提示', '全部领取'):
            return False
        _, results = area
        target = self._text_rect(results, '全部领取')
        if target is None:
            return False
        return any(
            text.strip().upper() == 'X' and matches.max is not None
            and 0 <= target.x1 - matches.max.rect.x2 <= 140
            and abs(target.center.y - matches.max.center.y) <= 45
            for text, matches in results.items()
        )

    @operation_node(name='打开丽都城募', is_start_node=True, node_max_retry_times=18, timeout_seconds=35)
    def open_city(self) -> OperationRoundResult:
        """从已观察菜单焦点导航，不使用固定两次右键或坐标点击。"""
        if self._city_visible():
            return self.round_success()
        if self._known_reward_visible():
            return self._pending_evidence('city_unrelated_reward', '未确认已有获得弹窗属于本次城募领取')
        if self._menu_visible():
            if self._entered:
                return self.round_retry('等待丽都城募页面', wait=0.8)
            area = self._read_area('菜单', '手柄-底部应用')
            selected = self._selected('菜单', '手柄-底部应用', self.MENU_ITEMS)
            if area is None or selected is None:
                return self._pending_evidence('city_menu_unknown_focus', '菜单底部焦点未知')
            target = self._text_rect(area[1], '丽都城募')
            current = self._text_rect(area[1], selected)
            if target is None or current is None:
                return self._pending_evidence('city_menu_missing_target', '菜单目标或焦点文字缺失')
            if selected == '丽都城募':
                self._save_evidence('city_menu_before')
                self.ctx.controller.btn_tap('south')
                self._entered = True
            else:
                self.ctx.controller.btn_tap('dpad_right' if current.center.x < target.center.x else 'dpad_left')
            return self.round_retry('等待菜单城募焦点或页面切换', wait=0.7)
        if self.last_screenshot is not None and self.round_by_find_area(
            self.last_screenshot, '大世界-普通', '快捷手册'
        ).is_success:
            if not self._menu_opened:
                self.ctx.controller.click(gamepad_key='menu')
                self._menu_opened = True
            return self.round_retry('等待游戏菜单', wait=0.8)
        if (self._menu_opened or self._entered) and self.node_retry_times < 16:
            return self.round_retry('等待菜单或城募入场动画结束', wait=0.5)
        return self._pending_evidence('city_unknown_entry', '城募入口画面尚未建档')

    @node_from(from_name='打开丽都城募')
    @operation_node(name='城募选择成长任务', node_max_retry_times=6, timeout_seconds=10)
    def choose_growth(self) -> OperationRoundResult:
        """仅切主标签，不进入左侧奖励选择和兑换。"""
        return self._select_main_tab('成长任务')

    @node_from(from_name='城募选择成长任务')
    @operation_node(name='城募检查任务分类', node_max_retry_times=20, timeout_seconds=25)
    def inspect_tasks(self) -> OperationRoundResult:
        """全部领取在三个分类均亮黄，必须先读行状态再决定是否领取。"""
        if self.main_tab() != '成长任务':
            return self._pending_evidence('city_unknown_tasks', '城募成长任务标签未知')
        target = self.TASK_TABS[self._task_scan_index]
        if not self._select_task_tab(target):
            return self.round_retry(f'等待城募{target}', wait=0.6)
        count = self.task_claim_count()
        if count is None:
            return self._pending_evidence('city_unknown_task_rows', f'城募{target}任务状态未知')
        self._task_counts[target] = count
        self._save_evidence(f'city_tasks_before_{self._task_scan_index}')
        self._task_scan_index += 1
        if self._task_scan_index < len(self.TASK_TABS):
            return self.round_retry('继续检查城募任务分类', wait=0.3)
        self._claim_categories = [name for name in self.TASK_TABS if self._task_counts[name] > 0]
        return self.round_success('无可领取任务' if not self._claim_categories else None)

    @node_from(from_name='城募检查任务分类')
    @operation_node(name='城募任务全部领取', node_max_retry_times=8, timeout_seconds=12)
    def claim_tasks(self) -> OperationRoundResult:
        """在有已确认可领项的分类中，只发送一次全局 X。"""
        if self._tasks_claim_sent:
            return self.round_success()
        if not self._claim_categories:
            return self.round_success('无可领取任务')
        if not self._select_task_tab(self._claim_categories[0]):
            return self.round_retry('等待可领取任务分类', wait=0.6)
        if not self._x_claim_available():
            return self._pending_evidence('city_unknown_task_claim', '城募任务 X 全部领取提示未知')
        if not self._save_evidence('city_tasks_claim_before'):
            return self.round_fail('城募任务领取前截图保存失败')
        self.ctx.controller.btn_tap('west')
        self._tasks_claim_sent = True
        return self.round_success(wait=1)

    @node_from(from_name='城募任务全部领取')
    @operation_node(name='城募核对任务领取', node_max_retry_times=20, timeout_seconds=25)
    def verify_tasks(self) -> OperationRoundResult:
        """只确认本次产生的已知获得页，并核对原可领行不再可领。"""
        if self._tasks_claim_sent and self._known_reward_visible():
            if not self._save_evidence('city_tasks_reward_before'):
                return self.round_fail('城募任务确认前截图保存失败')
            if not self._tasks_confirm_sent:
                self.ctx.controller.btn_tap('south')
                self._tasks_confirm_sent = True
            return self.round_retry('等待城募任务奖励确认返回', wait=0.8)
        if self.main_tab() != '成长任务':
            return self._pending_evidence('city_tasks_unknown_result', '城募任务领取结果尚未建档')
        target = self._claim_categories[self._task_verify_index]
        if not self._select_task_tab(target):
            return self.round_retry('等待领取后的任务分类', wait=0.6)
        count = self.task_claim_count()
        if count is None or count > 0:
            self._task_verify_waits += 1
            if self._task_verify_waits <= 3:
                return self.round_retry('等待城募任务领取状态更新', wait=0.6)
            return self._pending_evidence('city_tasks_unconfirmed_result', '城募原可领取任务尚未确认全部领取')
        self._save_evidence(f'city_tasks_after_{self._task_verify_index}')
        self._task_verify_index += 1
        self._task_verify_waits = 0
        if self._task_verify_index < len(self._claim_categories):
            return self.round_retry('继续核对已领取任务分类', wait=0.3)
        return self.round_success()

    @node_from(from_name='城募检查任务分类', status='无可领取任务')
    @node_from(from_name='城募任务全部领取', status='无可领取任务')
    @node_from(from_name='城募核对任务领取')
    @operation_node(name='城募选择等级回馈', node_max_retry_times=6, timeout_seconds=10)
    def choose_levels(self) -> OperationRoundResult:
        """任务经验结算后才检查等级奖励。"""
        return self._select_main_tab('等级回馈')

    @node_from(from_name='城募选择等级回馈')
    @operation_node(name='城募等级全部领取', node_max_retry_times=5, timeout_seconds=10)
    def claim_levels(self) -> OperationRoundResult:
        """只接受明确的 X 全部领取，Y 解锁等入口一律不操作。"""
        if self.main_tab() != '等级回馈':
            return self.round_retry('等待等级回馈页面', wait=0.6)
        if not self._save_evidence('city_levels_before'):
            return self.round_fail('城募等级领取前截图保存失败')
        if self._level_claim_sent:
            return self.round_success()
        if self._x_claim_available():
            self.ctx.controller.btn_tap('west')
            self._level_claim_sent = True
            return self.round_success(wait=1)
        if self._has_text('丽都城募', '手柄-底部提示', '全部领取'):
            return self._pending_evidence('city_levels_unknown_prompt', '等级全部领取提示未确认对应 X')
        return self.round_success('无可领取等级奖励')

    @node_from(from_name='城募等级全部领取')
    @operation_node(name='城募核对等级领取', node_max_retry_times=6, timeout_seconds=12)
    def verify_levels(self) -> OperationRoundResult:
        """明确发起等级领取后才确认通用获得弹窗。"""
        if self._level_claim_sent and self._known_reward_visible():
            if not self._save_evidence('city_levels_reward_before'):
                return self.round_fail('城募等级确认前截图保存失败')
            if not self._level_confirm_sent:
                self.ctx.controller.btn_tap('south')
                self._level_confirm_sent = True
            return self.round_retry('等待等级奖励返回', wait=0.8)
        if self._level_confirm_sent and self.main_tab() == '等级回馈' and not self._x_claim_available():
            self._save_evidence('city_levels_after')
            return self.round_success()
        return self._pending_evidence('city_levels_unknown_result', '等级奖励领取结果尚未建档')

    @node_from(from_name='城募等级全部领取', status='无可领取等级奖励')
    @node_from(from_name='城募核对等级领取')
    @operation_node(name='城募返回大世界', node_max_retry_times=10, timeout_seconds=15)
    def back_to_world(self) -> OperationRoundResult:
        """在城募和菜单各返回一次，未知页面不补按 B。"""
        if self.last_screenshot is not None and self.round_by_find_area(
            self.last_screenshot, '大世界-普通', '快捷手册'
        ).is_success:
            self._save_evidence('city_world')
            return self.round_success('丽都城募现有奖励检查完成', data={
                'evidence_paths': self.evidence_paths,
                'task_claims_before': self._task_counts,
                'tasks_claimed_by_operation': self._tasks_claim_sent,
                'levels_claimed_by_operation': self._level_claim_sent,
            })
        if self._city_visible():
            if not self._city_back_sent:
                self.ctx.controller.btn_tap('east')
                self._city_back_sent = True
            return self.round_retry('等待城募返回菜单', wait=0.8)
        if self._menu_visible():
            if not self._menu_back_sent:
                self.ctx.controller.btn_tap('east')
                self._menu_back_sent = True
            return self.round_retry('等待城募返回大世界', wait=0.8)
        return self._pending_evidence('city_unknown_return', '城募返回画面尚未建档')
