"""迷失之地的手柄入口，复用快捷手册识别与原玩法画面。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from zzz_od.operation.gamepad.focus import (
    find_yellow_frames,
    has_filled_highlight,
    highlight_mask,
    text_inside_frame,
)
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation
from zzz_od.operation.gamepad.transport_by_compendium import (
    GamepadTransportByCompendium,
)

if TYPE_CHECKING:
    from cv2.typing import MatLike

    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class GamepadLostVoidBackToWorld(GamepadOperation):
    """从已确认的悬赏、迷失入口和零号入口逐层返回主界面。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx,op_name='手柄迷失之地返回主界面',timeout_seconds=40)
        self.navigation: GamepadTransportByCompendium=GamepadTransportByCompendium(ctx,'作战','周期征讨')
        self._sent: dict[str,int]={}
        self._last_page: str | None=None
        self._same_page: int=0
        self._unknown_return_waits: int=0

    @operation_node(name='返回游戏主界面',is_start_node=True,node_max_retry_times=20)
    def back(self) -> OperationRoundResult:
        if self.last_screenshot is None:
            return self.round_retry('等待返回截图',wait=1)
        if self.round_by_find_area(self.last_screenshot,'大世界-普通','快捷手册').is_success:
            self.save_screenshot(prefix='macos_lost_void_returned_world')
            return self.round_success('已返回游戏主界面')
        nav=self.navigation
        nav.last_screenshot=self.last_screenshot
        title=nav._read_area('迷失之地-入口','手柄-悬赏面板标题')
        if title and nav._text_rect(title[1],'悬赏委托') is not None:
            from zzz_od.operation.gamepad.lost_void_rewards import (
                GamepadLostVoidCloseBounty,
            )

            result=GamepadLostVoidCloseBounty(self.ctx).execute()
            return self.round_retry('等待关闭悬赏后的入口',wait=1) if result.success else self.round_by_op_result(result)
        event=nav._read_area('Mac启动','登录后-活动说明')
        event_keys=nav._read_area('Mac启动','登录后-活动按键')
        is_event=bool(event and event_keys and all(nav._text_rect(event[1],word) is not None
            for word in ('全新放送','累计登录7天')) and all(nav._text_rect(event_keys[1],word) is not None
            for word in ('B','返回')))
        page='全新放送' if is_event else self.check_and_update_current_screen(self.last_screenshot,screen_name_list=[
            '迷失之地-入口-周期','迷失之地-入口-常规','迷失之地-战线肃清',
        ])
        if page == '迷失之地-战线肃清':
            page='副本详情'
        elif page in ('迷失之地-入口-周期','迷失之地-入口-常规'):
            page='迷失之地入口'
        elif page is None:
            entry=GamepadLostVoidTransport(self.ctx)
            entry.last_screenshot=self.last_screenshot
            if entry._at_hollow_entry():
                page='零号空洞入口'
            else:
                tabs=nav._read_area('快捷手册','手柄-顶部标签')
                if tabs and all(nav._text_rect(tabs[1],word) is not None for word in ('目标','日常','训练')):
                    page='快捷手册'
        if page is None:
            if self._sent and self._unknown_return_waits<4:
                self._unknown_return_waits+=1
                return self.round_retry('等待已请求返回后的画面',wait=1)
            self.save_screenshot(prefix='macos_lost_void_return_pending')
            return self.round_fail('迷失之地返回画面未建档，已停止')
        self._unknown_return_waits=0
        self._same_page=self._same_page+1 if page==self._last_page else 0
        self._last_page=page
        attempts=self._sent.get(page,0)
        if attempts==0 or (self._same_page==3 and attempts<2):
            self.ctx.controller.btn_tap('east')
            self._sent[page]=attempts+1
        if self._same_page>=6:
            return self.round_fail(f'{page}返回后未变化')
        return self.round_retry(f'等待离开{page}',wait=1)


class GamepadLostVoidPause(GamepadOperation):
    """开发或运行失败时只打开已确认局内的战况菜单，阻止角色原地受击。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄暂停迷失之地场景', timeout_seconds=6)
        self.navigation: GamepadTransportByCompendium = GamepadTransportByCompendium(ctx, '作战', '周期征讨')
        self._sent: bool = False

    @operation_node(name='确认局内暂停', is_start_node=True, node_max_retry_times=4)
    def pause_scene(self) -> OperationRoundResult:
        """只在实时局内发送一次菜单键，陌生菜单不追加游戏输入。"""
        if self.last_screenshot is None:
            return self.round_retry('等待暂停场景截图', wait=1)
        self.navigation.last_screenshot = self.last_screenshot
        area = self.navigation._read_area('迷失之地-大世界', '手柄-战况返回')
        if area and all(self.navigation._text_rect(area[1], word) is not None for word in ('重新开始', '退出战斗', '返回')):
            return self.round_success('已确认战况菜单暂停')
        if not self._sent and self.ctx.lost_void.in_normal_world(self.last_screenshot):
            self.ctx.controller.btn_tap('start')
            self._sent = True
            return self.round_retry('等待战况菜单', wait=1)
        if not self._sent:
            return self.round_success('当前为交互或结算画面，无需暂停')
        return self.round_retry('等待暂停结果', wait=1)


class GamepadLostVoidExit(GamepadOperation):
    """从已确认的局内战况菜单退出，供更换编队后重新开始。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄退出迷失之地', timeout_seconds=30)
        self.navigation: GamepadTransportByCompendium = GamepadTransportByCompendium(ctx, '作战', '周期征讨')
        self._opened: bool = False
        self._exit_requested: bool = False
        self._confirmed: bool = False
        self._result_finished: bool = False
        self._closed_shop: bool = False

    @operation_node(name='退出当前挑战', is_start_node=True, node_max_retry_times=15)
    def leave(self) -> OperationRoundResult:
        """只在完整底栏明确标记时请求退出；陌生确认保留画面。"""
        if self.last_screenshot is None:
            return self.round_retry('等待有效截图', wait=1)
        self.navigation.last_screenshot = self.last_screenshot
        entry = self.check_and_update_current_screen(self.last_screenshot, screen_name_list=[
            '迷失之地-入口-周期', '迷失之地-入口-常规',
        ])
        if entry is not None:
            return self.round_success('已退出迷失之地挑战')
        if self.round_by_find_area(self.last_screenshot, '迷失之地-挑战结果', '标题-挑战结果').is_success:
            result_bar = self.navigation._read_area('迷失之地-挑战结果', '按钮-完成')
            if result_bar and self.navigation._text_rect(result_bar[1], '完成') is not None and not self._result_finished:
                self.save_screenshot(prefix='macos_lost_void_aborted_result')
                self.ctx.controller.btn_tap('east')
                self._result_finished = True
            return self.round_retry('等待退出结算完成', wait=2)
        confirm_area = self.navigation._read_area('迷失之地-大世界', '手柄-退出确认')
        if confirm_area and self.navigation._text_rect(confirm_area[1], '是否确认退出战斗'):
            buttons = {text: matches for text, matches in confirm_area[1].items() if text.replace(' ', '') == '确认'}
            confirm = self.navigation._text_rect(buttons, '确认')
            cancel = self.navigation._text_rect(confirm_area[1], '取消')
            if confirm is not None and cancel is not None and has_filled_highlight(confirm_area[0], confirm, 'yellow'):
                if not self._confirmed:
                    self.ctx.controller.btn_tap('south')
                    self._confirmed = True
                    self._exit_requested = True
                return self.round_retry('等待退出后入口', wait=2)
            return self.round_retry('等待明确确认焦点', wait=1)
        if self.check_and_update_current_screen(self.last_screenshot, screen_name_list=['迷失之地-邦布商店']) is not None:
            if not self._closed_shop:
                self.ctx.controller.btn_tap('east')
                self._closed_shop = True
            return self.round_retry('等待商店关闭后退出挑战', wait=1)
        if self._exit_requested:
            entry = self.check_and_update_current_screen(self.last_screenshot, screen_name_list=[
                '迷失之地-入口-周期', '迷失之地-入口-常规',
            ])
            if entry is not None:
                return self.round_success('已退出迷失之地挑战')
            if self._confirmed:
                return self.round_retry('等待退出加载', wait=2)
            self.save_screenshot(prefix='macos_lost_void_exit_confirmation')
            return self.round_fail('迷失之地退出确认待适配')
        area = self.navigation._read_area('迷失之地-大世界', '手柄-战况返回')
        if area and all(self.navigation._text_rect(area[1], word) is not None for word in ('重新开始', '退出战斗', '返回')):
            self.ctx.controller.btn_tap('north')
            self._exit_requested = True
            return self.round_retry('等待退出确认', wait=1)
        if not self._opened and self.ctx.lost_void.in_normal_world(self.last_screenshot):
            self.ctx.controller.btn_tap('start')
            self._opened = True
        return self.round_retry('等待迷失之地战况菜单', wait=1)


class GamepadLostVoidTransport(GamepadOperation):
    """打开周期征讨中的迷失之地；不出战、不更改原任务配置。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄前往迷失之地', timeout_seconds=90)
        self.navigation: GamepadTransportByCompendium = GamepadTransportByCompendium(
            ctx, '作战', '周期征讨', '迷失之地',
        )
        self._entered: bool = False
        self._requested: bool = False
        self._last_focus: str | None = None
        self._unchanged: int = 0
        self._entered_hollow: bool = False
        self._closed_update: bool = False

    def handle_init(self) -> None:
        """每次重新识别当前焦点，不能复用上次确认记录。"""
        self.navigation.handle_init()
        self._entered = False
        self._requested = False
        self._last_focus = None
        self._unchanged = 0
        self._entered_hollow = False
        self._closed_update = False

    def _update_notice(self) -> bool:
        """版本公告仅匹配专属标题，不依据遮罩背后的入口判断完成。"""
        return self.round_by_find_area(
            self.last_screenshot, '迷失之地-入口', '手柄-更新标题',
        ).is_success

    def _entry_name(self) -> str | None:
        """复用原入口识别，优先排除版本公告。"""
        if self._update_notice():
            return None
        return self.check_and_update_current_screen(self.last_screenshot, screen_name_list=[
            '迷失之地-入口-周期', '迷失之地-入口-常规',
        ])

    def _at_hollow_entry(self) -> bool:
        """左右玩法标题不能混用；A 提示须位于迷失之地一侧。"""
        nav = self.navigation
        nav.last_screenshot = self.last_screenshot
        tabs = nav._read_area('零号空洞-入口', '手柄-调查标签')
        entry = nav._read_area('零号空洞-入口', '手柄-迷失之地入口')
        return bool(tabs and entry and nav._text_rect(tabs[1], '深层调查')
                    and nav._text_rect(entry[1], '迷失之地')
                    and nav._text_rect(entry[1], 'A'))

    @operation_node(name='打开快捷手册', is_start_node=True, node_max_retry_times=6)
    def open_handbook(self) -> OperationRoundResult:
        """复用已确认的大世界快捷键。"""
        if self._at_hollow_entry() or self._update_notice() or self._entry_name() is not None:
            return self.round_success('已在零号入口')
        self.navigation.last_screenshot = self.last_screenshot
        return self.navigation.open_compendium()

    @node_from(from_name='打开快捷手册')
    @operation_node(name='选择作战', node_max_retry_times=7)
    def choose_combat(self) -> OperationRoundResult:
        """根据当前高亮标签决定肩键方向。"""
        nav = self.navigation
        nav.last_screenshot = self.last_screenshot
        current = nav._selected('手柄-顶部标签', nav.TABS, 'yellow')
        if current == '作战':
            return self.round_success()
        if current is not None:
            self.ctx.controller.btn_tap('right_shoulder' if nav.TABS.index(current) < 3 else 'left_shoulder')
        return self.round_retry('等待作战标签', wait=0.8)

    @node_from(from_name='选择作战')
    @operation_node(name='选择周期征讨', node_max_retry_times=8)
    def choose_category(self) -> OperationRoundResult:
        """周期征讨位于作战首项；只在识别到当前分类时向上移动。"""
        nav = self.navigation
        nav.last_screenshot = self.last_screenshot
        current = nav._selected('手柄-分类列表', (
            '周期征讨', '式舆防卫战', '危局强袭战', '临界推演', '拟真鏖战试炼', '零号空洞',
        ), 'blue')
        if current == '周期征讨':
            return self.round_success()
        if current is not None:
            self.ctx.controller.btn_tap('dpad_up')
        return self.round_retry('等待周期征讨分类', wait=0.8)

    @node_from(from_name='选择周期征讨')
    @operation_node(name='选择迷失之地', node_max_retry_times=15)
    def choose_lost_void(self) -> OperationRoundResult:
        """将整行黄框或同一行的黄色前往按钮关联到标题。"""
        nav = self.navigation
        nav.last_screenshot = self.last_screenshot
        if nav._teleport_dialog():
            return self.round_success() if self._requested else self.round_fail('传送弹窗来源未确认')
        area = nav._read_area('快捷手册', '手柄-副本列表')
        if area is None:
            return self.round_retry('等待周期征讨列表', wait=0.8)
        image, words = area
        frames = find_yellow_frames(image)
        buttons = [match.rect for text, matches in words.items() if text.replace(' ', '') == '前往'
                   for match in matches if has_filled_highlight(image, match.rect, 'yellow')]
        selected = [text for text, matches in words.items() if matches.max is not None and (
            text_inside_frame(matches.max.rect, frames)
            or len(buttons) == 1 and 0 < buttons[0].center.y - matches.max.center.y < 170
        ) and matches.max.center.x < 500]
        if len(selected) == 1:
            current = selected[0]
            if '迷失之地' in current:
                if not self._requested:
                    self.save_screenshot(prefix='macos_lost_void_handbook')
                    self.ctx.controller.btn_tap('south')
                    self._requested = True
                return self.round_retry('等待迷失之地传送弹窗', wait=1)
            if current == self._last_focus:
                self._unchanged += 1
                if self._unchanged >= 3:
                    return self.round_fail('周期征讨焦点未移动，已停止输入')
            else:
                self._last_focus = current
                self._unchanged = 0
                self.ctx.controller.btn_tap('dpad_down')
            return self.round_retry('等待迷失之地焦点', wait=0.8)
        if not self._entered and not frames and not buttons:
            if nav._selected('手柄-分类列表', ('周期征讨',), 'blue') == '周期征讨':
                self.ctx.controller.btn_tap('south')
                self._entered = True
        return self.round_retry('等待唯一目标焦点', wait=0.8)

    @node_from(from_name='选择迷失之地')
    @operation_node(name='确认传送', node_max_retry_times=6)
    def confirm_teleport(self) -> OperationRoundResult:
        """沿用明确传送文案与黄色确认按钮保护。"""
        self.navigation.last_screenshot = self.last_screenshot
        return self.navigation.confirm_teleport()

    @node_from(from_name='确认传送')
    @node_from(from_name='打开快捷手册', status='已在零号入口')
    @operation_node(name='等待迷失之地入口', node_max_retry_times=20)
    def wait_entry(self) -> OperationRoundResult:
        """周期与常规入口任一匹配才算抵达。"""
        if self._update_notice():
            self.navigation.last_screenshot = self.last_screenshot
            area = self.navigation._read_area('迷失之地-入口', '手柄-更新返回')
            if area and self.navigation._text_rect(area[1], 'B') and not self._closed_update:
                self.ctx.controller.btn_tap('east')
                self._closed_update = True
            return self.round_retry('等待迷失之地更新公告关闭', wait=1)
        name = self._entry_name()
        if name is not None:
            self.save_screenshot(prefix='macos_lost_void_entry')
            return self.round_success(name)
        if not self._entered_hollow and self._at_hollow_entry():
            self.ctx.controller.btn_tap('south')
            self._entered_hollow = True
        return self.round_retry('等待迷失之地入口加载', wait=1)


class GamepadLostVoidChooseMission(GamepadOperation):
    """按原副本名切换周期或常规入口。"""

    def __init__(self, ctx: ZContext, mission_name: str) -> None:
        super().__init__(ctx, op_name=f'手柄选择迷失之地 {mission_name}', timeout_seconds=35)
        self.mission_name: str = mission_name
        self.navigation: GamepadTransportByCompendium = GamepadTransportByCompendium(ctx, '作战', '周期征讨')
        self._requested: bool = False

    def handle_init(self) -> None:
        """每次只按一次进入，等待目标详情出现。"""
        self._requested = False

    @operation_node(name='选择入口标签', is_start_node=True, node_max_retry_times=5)
    def choose_tab(self) -> OperationRoundResult:
        if self.last_screenshot is None:
            return self.round_retry('等待有效游戏截图', wait=1)
        """副本来自原配置，不因当前周期有推荐玩法而覆盖。"""
        if self.mission_name not in ('战线肃清', '特遣调查', '矩阵行动'):
            return self.round_fail(f'未知迷失之地副本：{self.mission_name}')
        if self.check_and_update_current_screen(self.last_screenshot, screen_name_list=[f'迷失之地-{self.mission_name}']):
            return self.round_success('已在副本详情')
        nav = self.navigation
        nav.last_screenshot = self.last_screenshot
        area = nav._read_area('迷失之地-入口', '手柄-入口标签')
        if area:
            target = '周期' if self.mission_name == '矩阵行动' else '常规'
            selected = [name for name in ('周期', '常规') if (
                (rect := nav._text_rect(area[1], name)) is not None
                and has_filled_highlight(area[0], rect, 'yellow' if name == '周期' else 'blue')
            )]
            if selected == [target]:
                return self.round_success(f'{target}入口')
            if len(selected) == 1:
                self.ctx.controller.btn_tap('right_shoulder' if target == '常规' else 'left_shoulder')
        return self.round_retry('等待迷失之地入口标签', wait=1)

    @node_from(from_name='选择入口标签')
    @operation_node(name='选择副本卡片', node_max_retry_times=9)
    def choose_mission(self) -> OperationRoundResult:
        """仅依据已识别的卡片名称与完整边框移动。"""
        name = self.check_and_update_current_screen(self.last_screenshot, screen_name_list=[f'迷失之地-{self.mission_name}'])
        if name is not None:
            return self.round_success(name)
        nav = self.navigation
        nav.last_screenshot = self.last_screenshot
        if self._requested:
            name = self.check_and_update_current_screen(self.last_screenshot, screen_name_list=[
                f'迷失之地-{self.mission_name}',
            ])
            if name is not None:
                self.save_screenshot(prefix='macos_lost_void_mission')
                return self.round_success(name)
            return self.round_retry('等待指定副本详情', wait=1)
        area = nav._read_area('迷失之地-入口', '手柄-入口内容')
        if area is None:
            return self.round_retry('等待副本卡片', wait=1)
        image, words = area
        frames = self._find_mission_frames(image)
        names = ('特殊行动', '战线肃清', '特遣调查', '祸首歼灭战', '溯影行动', '矩阵行动')
        visible = {name: rect for name in names if (rect := nav._text_rect(words, name)) is not None}
        selected = [name for name, rect in visible.items() if text_inside_frame(rect, frames)]
        if len(selected) != 1 or self.mission_name not in visible:
            return self.round_retry('副本焦点不明确，未发送输入', wait=1)
        current = visible[selected[0]].center
        target = visible[self.mission_name].center
        if selected[0] == self.mission_name:
            self.ctx.controller.btn_tap('south')
            self._requested = True
        else:
            dx, dy = target.x - current.x, target.y - current.y
            self.ctx.controller.btn_tap(
                ('dpad_right' if dx > 0 else 'dpad_left') if abs(dx) > 200
                else ('dpad_down' if dy > 0 else 'dpad_up')
            )
        return self.round_retry('等待副本卡片选择', wait=1)

    @staticmethod
    def _find_mission_frames(image: MatLike) -> list[Rect]:
        """逐边核对卡片焦点，允许箭头和通知的局部遮挡，不用闭合把NEW连入边框。"""
        mask = highlight_mask(image, 'yellow') > 0
        contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        frames: list[Rect] = []
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            if width < 400 or not 150 <= height <= 500:
                continue
            # 通知与箭头同时遮挡时，左上短边可能与主体断开，仅在相邻60像素找回。
            x1, x2 = max(0, x - 60), min(mask.shape[1], x + width + 60)
            rows = np.flatnonzero(mask[y:y + height, x1:x2].mean(axis=1) >= 0.65)
            if len(rows) < 2:
                continue
            top, bottom = y + int(rows[0]), y + int(rows[-1]) + 1
            columns = np.flatnonzero(mask[top:bottom, x1:x2].mean(axis=0) >= 0.5)
            if len(columns) < 2:
                continue
            left, right = x1 + int(columns[0]), x1 + int(columns[-1]) + 1
            if right - left < 450 or not 150 <= bottom - top <= 500:
                continue
            border = mask[top:bottom, left:right]
            horizontal = min(border[:12].any(axis=0).mean(), border[-12:].any(axis=0).mean())
            vertical = min(border[:, :12].any(axis=1).mean(), border[:, -12:].any(axis=1).mean())
            if horizontal >= 0.75 and vertical >= 0.6:
                frames.append(Rect(left, top, right, bottom))
        return frames


class GamepadLostVoidOpenStrategy(GamepadOperation):
    """打开配置所需的调查战略列表，保留原追新与指定战略语义。"""

    def __init__(self, ctx: ZContext, mission_name: str) -> None:
        super().__init__(ctx, op_name='手柄选择调查战略', timeout_seconds=90)
        self.mission_name: str = mission_name
        self._opened: bool = False
        self._confirmed: bool = False
        self._target: str | None = None
        self._seen: set[str] = set()
        self._previous: str | None = None
        self._unchanged: int = 0
        self.navigation: GamepadTransportByCompendium = GamepadTransportByCompendium(ctx, '作战', '周期征讨')

    def handle_init(self) -> None:
        """只加载原挑战配置和战略数据，不初始化战斗模型。"""
        self.ctx.lost_void.load_challenge_config()
        self.ctx.lost_void.load_investigation_strategy()
        self._opened = False
        self._confirmed = False
        self._target = None
        self._seen.clear()
        self._previous = None
        self._unchanged = 0

    @operation_node(name='打开调查战略', is_start_node=True, node_max_retry_times=4)
    def open_strategy(self) -> OperationRoundResult:
        """只在指定副本和调查战略提示同时出现时按 Y 一次。"""
        if self.round_by_find_area(self.last_screenshot, '迷失之地-调查战略选择', '手柄-标题').is_success:
            return self.round_success('已确认调查战略列表')
        if self.round_by_find_area(self.last_screenshot, f'迷失之地-{self.mission_name}', '标题-战线肃清').is_success \
                and self.round_by_find_area(self.last_screenshot, f'迷失之地-{self.mission_name}', '手柄-调查战略').is_success and not self._opened:
            self.ctx.controller.btn_tap('north')
            self._opened = True
            return self.round_wait('等待调查战略列表', wait=1)
        return self.round_retry('等待指定副本的调查战略入口', wait=1)

    @node_from(from_name='打开调查战略')
    @operation_node(name='选择原配置战略', node_max_retry_times=40)
    def choose_strategy(self) -> OperationRoundResult:
        """追新复用原等级图像分析；指定模式按原战略名称导航。"""
        if self._confirmed:
            if self.round_by_find_area(self.last_screenshot, f'迷失之地-{self.mission_name}', '手柄-调查战略').is_success \
                    and not self.round_by_find_area(self.last_screenshot, '迷失之地-调查战略选择', '手柄-标题').is_success:
                return self.round_success('调查战略已选择', data=self._target)
            return self.round_retry('等待调查战略选择后返回', wait=1)
        if not self.round_by_find_area(self.last_screenshot, '迷失之地-调查战略选择', '手柄-标题').is_success:
            return self.round_retry('等待调查战略列表', wait=1)
        nav = self.navigation
        nav.last_screenshot = self.last_screenshot
        area = nav._read_area('迷失之地-调查战略选择', '手柄-战略卡片')
        if area is None:
            return self.round_retry('等待战略卡片识别', wait=1)
        image, words = area
        names = [item.strategy_name for item in self.ctx.lost_void.investigation_strategy_list]
        visible = {name: rect for name in names if (rect := nav._text_rect(words, name)) is not None}
        mask = cv2.morphologyEx(highlight_mask(image, 'yellow'), cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        frames = []
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            if 250 <= width <= 400 and 400 <= height <= 550 and cv2.contourArea(contour) / width / height >= 0.7:
                frames.append(Rect(x, y, x + width, y + height))
        selected = [name for name, rect in visible.items() if text_inside_frame(rect, frames)]
        if len(selected) != 1:
            return self.round_retry('未识别唯一战略焦点', wait=1)
        current = selected[0]
        if current == self._previous:
            self._unchanged += 1
            if self._unchanged >= 3:
                return self.round_fail('调查战略焦点未响应，已停止输入')
            return self.round_retry('等待战略焦点移动', wait=1)
        self._previous = current
        self._unchanged = 0
        self._seen.add(current)
        config = self.ctx.lost_void.challenge_config
        if not config.chase_new_mode:
            self._target = config.investigation_strategy
        elif self._target is None:
            circles = self.ctx.cv_service.run_pipeline('调查战略等级圈圈', self.last_screenshot)
            digits = self.ctx.cv_service.run_pipeline('调查战略等级分析', self.last_screenshot)
            empty = self.ctx.cv_service.run_pipeline('调查战略无等级圈圈', self.last_screenshot)
            empty_rects = [cv2.boundingRect(c) for c in empty.contours]
            badge_rects = [cv2.boundingRect(c) for c in circles.contours]
            digit_rects = [cv2.boundingRect(c) for c in digits.contours]
            if not badge_rects and not any(40 <= r[2] <= 90 and 40 <= r[3] <= 90 for r in empty_rects):
                return self.round_fail('调查战略追新等级识别失败')
            for name, rect in visible.items():
                for x, y, width, height in badge_rects + [r for r in empty_rects if 40 <= r[2] <= 90 and 40 <= r[3] <= 90]:
                    if not (50 < x + circles.crop_offset[0] - (rect.center.x + 40) < 170):
                        continue
                    has_digit = any(x <= dx + dw / 2 <= x + width and y <= dy + dh / 2 <= y + height
                                    for dx, dy, dw, dh in digit_rects)
                    if not has_digit:
                        self._target = name
                        break
                if self._target is not None:
                    break
            if self._target is None and len(self._seen) >= len(names):
                self._target = config.investigation_strategy
        if self._target is not None and self._target not in names:
            return self.round_fail(f'原配置战略不在玩法数据中：{self._target}')
        if self._target == current:
            if self.round_by_find_area(self.last_screenshot, '迷失之地-调查战略选择', '手柄-确定').is_success:
                self.ctx.controller.btn_tap('south')
                self._confirmed = True
        else:
            target_idx = names.index(self._target) if self._target is not None else (
                len(names) - 1 if names[-1] not in self._seen else 0
            )
            self.ctx.controller.btn_tap('dpad_right' if names.index(current) < target_idx else 'dpad_left')
        return self.round_retry('等待配置调查战略进入焦点', wait=1)


class GamepadLostVoidChooseBuff(GamepadOperation):
    """按原挑战配置选择周期增益，不使用固定联调值替换配置。"""

    def __init__(self, ctx: ZContext, buff_no: str) -> None:
        super().__init__(ctx, op_name='手柄选择周期增益', timeout_seconds=20)
        self.buff_no: str = buff_no
        self._returned: bool = False
        self._entered: bool = False
        self._selected: bool = False
        self.navigation: GamepadTransportByCompendium = GamepadTransportByCompendium(ctx, '作战', '周期征讨')

    def checked_state(self, row: np.ndarray) -> bool | None:
        """选中/空心圆互斥命中才返回状态，兼容归一化采集的抗锯齿差异。"""
        checked = self.ctx.tm.match_template(row, 'ios_gamepad', 'lost_void_buff_checked', threshold=0.8).max is not None
        unchecked = self.ctx.tm.match_template(row, 'ios_gamepad', 'lost_void_buff_unchecked', threshold=0.8).max is not None
        return checked if checked != unchecked else None

    @operation_node(name='定位周期增益', is_start_node=True, node_max_retry_times=5)
    def choose_buff(self) -> OperationRoundResult:
        """先恢复周期增益面板，不能在活性选项上误选。"""
        if self.buff_no not in ('第一个', '第二个', '第三个'):
            return self.round_fail('原配置周期增益序号无效')
        if self.last_screenshot is None:
            return self.round_retry('等待游戏截图', wait=1)
        nav = self.navigation
        nav.last_screenshot = self.last_screenshot
        area = nav._read_area('迷失之地-战线肃清', '手柄-以太活性')
        if area is None:
            return self.round_retry('等待副本准备面板', wait=1)
        if nav._text_rect(area[1], '选择周期增益') is not None:
            image, words = area
            mask = cv2.morphologyEx(highlight_mask(image, 'yellow'), cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            frames = [Rect(x, y, x + width, y + height) for contour in contours
                      for x, y, width, height in [cv2.boundingRect(contour)] if width > 700 and height > 50]
            summary = nav._text_rect(words, '以太活性')
            if summary and text_inside_frame(summary, frames):
                self.ctx.controller.btn_tap('dpad_up')
                return self.round_retry('从活性返回周期增益焦点', wait=1)
            group = [frame for frame in frames if frame.height > 400]
            row_area = nav._read_area('迷失之地-战线肃清', '手柄-周期增益选项')
            rows = find_yellow_frames(row_area[0]) if row_area else []
            if len(rows) == 1:
                area_rect = self.ctx.screen_loader.get_area('迷失之地-战线肃清', '手柄-周期增益选项').rect
                index = min(range(3), key=lambda i: abs(rows[0].center.y + area_rect.y1 - self.ctx.screen_loader.get_area(
                    '迷失之地-战线肃清', f'周期增益-{("第一个", "第二个", "第三个")[i]}',
                ).rect.center.y))
                target = ('第一个', '第二个', '第三个').index(self.buff_no)
                if index == target:
                    row = row_area[0][rows[0].y1:rows[0].y2, rows[0].x2 - 90:rows[0].x2]
                    state = self.checked_state(row)
                    if state is True:
                        return self.round_success('周期增益已核对', data=self.buff_no)
                    if state is None:
                        return self.round_retry('等待周期增益选中状态明确', wait=1)
                if index != target:
                    self.ctx.controller.btn_tap('dpad_down' if index < target else 'dpad_up')
                elif not self._selected:
                    self.ctx.controller.btn_tap('south')
                    self._selected = True
                else:
                    return self.round_retry('等待目标周期增益勾选', wait=1)
                return self.round_retry('等待周期增益选择确认', wait=1)
            if group and not self._entered:
                self.ctx.controller.btn_tap('south')
                self._entered = True
                return self.round_retry('等待周期增益行焦点', wait=1)
            return self.round_retry('等待周期增益明确焦点', wait=1)
        if nav._text_rect(area[1], '以太活性') is not None and not self._returned:
            self.ctx.controller.btn_tap('east')
            self._returned = True
        return self.round_retry('等待返回周期增益面板', wait=1)


class GamepadLostVoidPrepareTeam(GamepadOperation):
    """复用原预备编队选择器，到达出战页后再次核对实际成员。"""

    def __init__(self, ctx: ZContext, team_idx: int = -1) -> None:
        super().__init__(ctx, op_name='手柄迷失之地编队准备', timeout_seconds=180)
        self.team_idx: int = team_idx
        self._next: bool = False
        self._team: bool = False

    @operation_node(name='准备编队', is_start_node=True, node_max_retry_times=12, timeout_seconds=175)
    def prepare_team(self) -> OperationRoundResult:
        """保留当前编队或使用原配置二十队序号，不直接出战。"""
        if self.team_idx not in range(-1, 20):
            return self.round_fail('Mac 迷失之地支持当前编队或二十个预备编队')
        if self.last_screenshot is None:
            return self.round_retry('等待有效截图', wait=1)
        ready = all(self.round_by_find_area(self.last_screenshot, '实战模拟室', name).is_success
                    for name in ('手柄-出战', '手柄-预备编队'))
        if ready:
            if self.team_idx >= 0 and not self._team:
                from zzz_od.operation.gamepad.predefined_team import (
                    GamepadChoosePredefinedTeam,
                )

                result = GamepadChoosePredefinedTeam(self.ctx, self.team_idx).execute()
                if not result.success:
                    return self.round_by_op_result(result)
                self._team = True
                return self.round_retry('等待已选编队准备页', wait=1)
            self.save_screenshot(prefix='macos_lost_void_team_ready')
            return self.round_success('迷失之地编队已准备')
        if not self._next and all(self.round_by_find_area(self.last_screenshot, '迷失之地-战线肃清', name).is_success
                                  for name in ('标题-战线肃清', '手柄-下一步')):
            self.ctx.controller.btn_tap('start')
            self._next = True
        return self.round_retry('等待迷失之地出战页', wait=1)
