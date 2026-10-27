"""情报板的原生手柄入口和代行委托流程。"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, ClassVar

import cv2
import numpy as np

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from zzz_od.operation.gamepad.focus import has_filled_highlight, highlight_mask
from zzz_od.operation.gamepad.function_guide import GamepadOpenFunction
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation
from zzz_od.operation.gamepad.rewards import _GamepadRewardOperation
from zzz_od.operation.gamepad.transport import find_yellow_focus_frames

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_base import OperationResult
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class GamepadOpenIntelBoard(_GamepadRewardOperation):
    """通过功能导览选择情报板，再确认目的页面。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄打开情报板', timeout_seconds=55)

    @operation_node(name='选择情报板入口', is_start_node=True)
    def select_entry(self) -> OperationRoundResult:
        """复用功能名与唯一黄色框导航。"""
        if self._has_text('情报板', '手柄-委托详情', '放弃委托') and self._has_text('情报板', '手柄-委托详情', '前往'):
            self.ctx.controller.btn_tap('east')
            return self.round_retry('关闭已有代行详情', wait=1)
        if self._has_text('情报板', '手柄-顶部标签', '情报板') and self._has_text('情报板', '手柄-底部提示', '周期内可获取'):
            return self.round_success()
        return self.round_by_op_result(GamepadOpenFunction(self.ctx, '情报板').execute())

    @node_from(from_name='选择情报板入口')
    @operation_node(name='确认情报板', node_max_retry_times=5)
    def check_board(self) -> OperationRoundResult:
        """未知目的页保存现场，后续节点不发送输入。"""
        if self._has_text('情报板', '手柄-顶部标签', '情报板') and self._has_text('情报板', '手柄-底部提示', '周期内可获取'):
            self._save_evidence('intel_board')
            return self.round_success('情报板已打开')
        return self.round_retry('等待情报板页面', wait=1)


class GamepadIntelBoardFilter(_GamepadRewardOperation):
    """沿原配置筛选并代行委托，未知弹窗保存现场。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄情报板', timeout_seconds=60)
        self._focus_requested: bool = False
        self._filter_opened: bool = False
        self._reset_sent: bool = False
        self._type_index: int = 0
        self._toggle_sent: bool = False
        self._closed: bool = False

    def _action_focused(self, name: str) -> bool:
        """底部圆形按钮必须有大块黄色填充。"""
        area = self.ctx.screen_loader.get_area('情报板', f'手柄-{name}焦点')
        if area is None or self.last_screenshot is None:
            return False
        rect = area.rect
        mask = highlight_mask(self.last_screenshot[rect.y1:rect.y2, rect.x1:rect.x2], 'yellow')
        return bool(mask.size and np.count_nonzero(mask) / mask.size > 0.25)

    @operation_node(name='筛选委托', is_start_node=True)
    def filter_commissions(self) -> OperationRoundResult:
        """确认底部功能提示后保持 LT，读取筛选操作。"""
        if self.round_by_find_area(self.last_screenshot, '情报板', '手柄-筛选标题').is_success:
            if not self._reset_sent:
                self.ctx.controller.btn_tap('north')
                self._reset_sent = True
                return self.round_wait('等待筛选重置', wait=0.7)
            image, words = self._read_area('情报板', '手柄-筛选条件')
            types = ('恶名狩猎', '专业挑战室')
            if self._type_index >= len(types):
                self._save_evidence('intel_filter_selected')
                self.ctx.controller.btn_tap('east')
                self._closed = True
                return self.round_wait('等待筛选完成返回列表', wait=1)
            target = self._text_rect(words, types[self._type_index])
            if target is not None and has_filled_highlight(image, target, 'blue'):
                self._type_index += 1
                self._toggle_sent = False
                return self.round_wait('委托类型已选中', wait=0.5)
            if self._toggle_sent:
                return self.round_retry('等待筛选蓝色选中状态', wait=0.5)
            contours, _ = cv2.findContours(highlight_mask(image, 'yellow'), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            frames = [cv2.boundingRect(item) for item in contours
                      if 180 < cv2.boundingRect(item)[2] < 300 and 25 < cv2.boundingRect(item)[3] < 65]
            if len(frames) != 1 or target is None:
                return self._pending_evidence('intel_filter_focus', '未确认筛选条件唯一焦点')
            x, y, width, height = frames[0]
            if x <= target.center.x <= x + width and y <= target.center.y <= y + height:
                self.ctx.controller.btn_tap('south')
                self._toggle_sent = True
            elif target.center.y > y + height:
                self.ctx.controller.btn_tap('dpad_down')
            elif target.center.y < y:
                self.ctx.controller.btn_tap('dpad_up')
            else:
                self.ctx.controller.btn_tap('dpad_right' if target.center.x > x + width / 2 else 'dpad_left')
            return self.round_wait('等待委托类型焦点', wait=0.6)
        if self._closed and self._has_text('情报板', '手柄-底部提示', '周期内可获取'):
            return self.round_success('情报板筛选完成')
        if self._filter_opened:
            return self.round_retry('等待筛选页面', wait=1)
        if not self._has_text('情报板', '手柄-底部提示', '周期内可获取'):
            return self._pending_evidence('intel_filter_unknown', '未确认情报板列表')
        if self._action_focused('筛选'):
            self.ctx.controller.btn_tap('south')
            self._filter_opened = True
        elif self._action_focused('刷新'):
            self.ctx.controller.btn_tap('dpad_right')
        elif not self._focus_requested:
            self.ctx.controller.btn_tap('left_trigger')
            self._focus_requested = True
        return self.round_wait('等待筛选焦点或打开筛选', wait=1)


class GamepadChooseIntelCommission(_GamepadRewardOperation):
    """只选择允许的代行类型，不接取困难委托或自己的帖子。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄选择代行委托', timeout_seconds=35)
        self._opened: bool = False
        self.commission_type: str | None = None
        self._list_focus_requested: bool = False

    @operation_node(name='选择代行委托', is_start_node=True, node_max_retry_times=12)
    def choose(self) -> OperationRoundResult:
        """按当前完整卡片的类别和归属判断，不用坐标点击帖子。"""
        if self._opened:
            if any(self._has_text('情报板', '手柄-委托详情', text) for text in ('接取委托', '放弃委托')):
                return self.round_success(data={'commission_type': self.commission_type})
            return self.round_retry('等待代行委托详情', wait=1)
        if self.round_by_find_area(self.last_screenshot, '情报板', '手柄-筛选标题').is_success:
            self.ctx.controller.btn_tap('east')
            return self.round_retry('关闭已有筛选面板', wait=1)
        for name in ('刷新', '筛选'):
            rect = self.ctx.screen_loader.get_area('情报板', f'手柄-{name}焦点').rect
            mask = highlight_mask(self.last_screenshot[rect.y1:rect.y2, rect.x1:rect.x2], 'yellow')
            if np.count_nonzero(mask) / mask.size > 0.25:
                self.ctx.controller.btn_tap('left_trigger')
                return self.round_retry('从底部功能返回卡片列表', wait=0.7)
        area = self._read_area('情报板', '手柄-委托卡片')
        if area is None or not self._has_text('情报板', '手柄-底部提示', '周期内可获取'):
            return self._pending_evidence('intel_list', '未识别情报板列表')
        image, words = area
        frames = find_yellow_focus_frames(image, 250, 360, 150, 850)
        if len(frames) != 1:
            if not self._list_focus_requested:
                self.ctx.controller.btn_tap('dpad_up')
                self._list_focus_requested = True
                return self.round_retry('等待委托列表焦点', wait=0.8)
            return self._pending_evidence('intel_card_focus', '未识别唯一委托卡片焦点')
        focus = frames[0]
        types = [name for name in ('恶名狩猎', '专业挑战室')
                 for text, matches in words.items() if name in text
                 for item in matches if focus.x1 < item.center.x < focus.x2 and focus.y1 < item.center.y < focus.y2]
        if len(types) != 1:
            return self._pending_evidence('intel_card_type', '当前卡片不是已支持的代行委托')
        stars = self.ctx.tm.match_template(source=self.last_screenshot, template_sub_dir='intel_board',
                                           template_id='Star', threshold=0.8, only_best=False)
        offset = self.ctx.screen_loader.get_area('情报板', '手柄-委托卡片').rect
        if any(focus.x1 + offset.x1 < star.center.x < focus.x2 + offset.x1
               and focus.y1 + offset.y1 < star.center.y < focus.y2 + offset.y1 for star in stars):
            self.ctx.controller.btn_tap('dpad_right')
            return self.round_retry('跳过自己发布的委托', wait=0.7)
        self.commission_type = types[0]
        self._save_evidence('intel_commission_selected')
        self.ctx.controller.btn_tap('south')
        self._opened = True
        return self.round_retry('等待代行委托详情', wait=1)


class GamepadAcceptIntelCommission(_GamepadRewardOperation):
    """只在已确认的代行详情中接取，不发布消耗电量的委托。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄接取代行委托', timeout_seconds=25)
        self._accepted: bool = False
        self._forward_requested: bool = False
        self._went: bool = False

    @operation_node(name='接取代行委托', is_start_node=True, node_max_retry_times=8)
    def accept(self) -> OperationRoundResult:
        """接取前保存详情，未知结果留图。"""
        if self._has_text('情报板', '手柄-挑战入口', '委托代行中'):
            return self.round_success('委托代行中')
        if self._went:
            return self.round_retry('等待代行挑战入口', wait=1)
        area = self._read_area('情报板', '手柄-委托详情')
        if area is not None and all(self._text_rect(area[1], text) is not None for text in ('前往', '放弃委托')):
            target = self._text_rect(area[1], '前往')
            if has_filled_highlight(area[0], target, 'yellow'):
                self.ctx.controller.btn_tap('south')
                self._went = True
            else:
                self.ctx.controller.btn_tap('dpad_right')
            return self.round_retry('移焦至前往', wait=1)
        if self._accepted:
            return self._pending_evidence('intel_accepted', '接取后页面待建档')
        if self._has_text('情报板', '手柄-委托详情', '接取委托') and self._has_text(
            '情报板', '手柄-委托详情', '成功挑战1次指定',
        ):
            self._save_evidence('intel_before_accept')
            self.ctx.controller.btn_tap('south')
            self._accepted = True
            return self.round_retry('等待委托接取结果', wait=1)
        return self._pending_evidence('intel_accept_unknown', '未确认可接取的战斗代行委托')


class GamepadIntelNextStep(_GamepadRewardOperation):
    """只在明确代行且消耗为零的入口进入编队。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄代行出战准备', timeout_seconds=35)
        self._next_sent: bool = False

    @operation_node(name='进入代行编队', is_start_node=True, node_max_retry_times=12)
    def prepare(self) -> OperationRoundResult:
        """保留委托指定等级和队伍；实际零消耗才发送下一步。"""
        if all(self.round_by_find_area(self.last_screenshot, '实战模拟室', name).is_success
               for name in ('手柄-出战', '手柄-预备编队')):
            self._save_evidence('intel_deployment')
            return self.round_success()
        area = self._read_area('情报板', '手柄-挑战入口')
        if area is None:
            return self.round_retry('等待代行入口', wait=1)
        text = ''.join(area[1]).replace(' ', '')
        charge = re.search(r'(\d+)/(\d+)', text)
        if '委托代行中' in text and 'ON' in text.upper() and any(name in text for name in ('下一步', '无报酬模式')):
            free_hunt = '无报酬模式' in text and self._has_text('情报板', '手柄-深度追猎', 'OFF')
            if not free_hunt and (charge is None or int(charge[2]) != 0):
                return self._pending_evidence('intel_charge', '未确认代行电量消耗为零')
            if not self._next_sent:
                self._save_evidence('intel_zero_charge')
                self.ctx.controller.btn_tap('start')
                self._next_sent = True
            return self.round_retry('等待代行编队页', wait=1)
        return self._pending_evidence('intel_prepare', '未确认代行模式，未进入普通挑战')


class GamepadIntelDeploy(_GamepadRewardOperation):
    """从代行编队页出战，并确认已进入战斗。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄代行出战', timeout_seconds=45)
        self._deployed: bool = False
        self._confirmed: bool = False

    @operation_node(name='代行出战', is_start_node=True, node_max_retry_times=25)
    def deploy(self) -> OperationRoundResult:
        """沿用 START 出战；未知弹窗保存现场，不任意确认。"""
        if self.ctx.auto_battle_context.is_normal_attack_btn_available(self.last_screenshot) or self.round_by_find_area(
            self.last_screenshot, '战斗画面', '按键-交互',
        ).is_success:
            return self.round_success('代行场景已加载')
        popup = self._read_area('情报板', '手柄-弹窗')
        if popup is not None and all(self._text_rect(popup[1], name) is not None
                                     for name in ('委托代行中', '无法获得常规报酬', '确认')):
            target = self._text_rect(popup[1], '确认')
            if not self._confirmed and has_filled_highlight(popup[0], target, 'yellow'):
                self._save_evidence('intel_delegation_notice')
                self.ctx.controller.btn_tap('south')
                self._confirmed = True
                self._deployed = True
            return self.round_retry('等待代行说明确认后加载', wait=1)
        if not self._deployed and all(self.round_by_find_area(
            self.last_screenshot, '实战模拟室', name,
        ).is_success for name in ('手柄-出战', '手柄-预备编队')):
            self._save_evidence('intel_before_deploy')
            self.ctx.controller.btn_tap('start')
            self._deployed = True
            return self.round_retry('等待代行出战结果', wait=1)
        if self._deployed and self.node_retry_times <= 18:
            return self.round_retry('等待战斗加载或代行确认', wait=1)
        return self._pending_evidence('intel_deploy_pending', '未识别代行战斗画面')


def read_intel_result(operation: GamepadOperation) -> bool | None:
    """通关目标的实际 1/1 才算胜利，标题本身不代表成功。"""
    if operation.last_screenshot is None or not operation.round_by_find_area(
        operation.last_screenshot, '战斗画面', '手柄-挑战结果',
    ).is_success:
        return None
    area = operation.ctx.screen_loader.get_area('恶名狩猎', '手柄-通关目标')
    words = operation.ctx.ocr.run_ocr(operation.last_screenshot)
    row = [(item.center.x, text) for text, matches in words.items() for item in matches
           if area.rect.x1 <= item.center.x <= area.rect.x2 and area.rect.y1 <= item.center.y <= area.rect.y2]
    text = ''.join(text for _, text in sorted(row)).replace(' ', '')
    match = re.search(r'完成(?:恶名狩猎|专业挑战(?:室)?).*?([01])/1', text)
    return None if match is None else match[1] == '1'


class GamepadIntelBattle(GamepadOperation):
    """复用原自动战斗上下文，用实际结果结束并释放输入。"""

    realtime_nodes: ClassVar[frozenset[str]] = frozenset({'代行战斗中'})

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄代行自动战斗', timeout_seconds=630)
        self._scope: bool = False
        self._active: bool = False
        self._blocked_since: float | None = None

    def execute(self) -> OperationResult:
        """异常、停止和正常结束都先停策略，再结束输入限制。"""
        try:
            return super().execute()
        finally:
            self.ctx.auto_battle_context.stop_auto_battle()
            if self._scope:
                self.ctx.controller.end_battle_input_scope()
                self._scope = False
            self._active = False

    @operation_node(name='开始代行战斗', is_start_node=True, node_max_retry_times=5)
    def start(self) -> OperationRoundResult:
        """只在战斗 HUD 明确时放行策略。"""
        from zzz_od.controller.macos_battle_input_guard import MacBattleHudGuard

        battle = self.ctx.auto_battle_context
        if not battle.is_normal_attack_btn_available(self.last_screenshot):
            return self.round_retry('等待代行战斗 HUD', wait=0.5)
        self.ctx.controller.begin_battle_input_scope(MacBattleHudGuard(battle))
        self._scope = True
        battle.start_auto_battle()
        self._active = True
        return self.round_success()

    @node_from(from_name='开始代行战斗')
    @operation_node(name='代行战斗中', mute=True, timeout_seconds=600)
    def battle(self) -> OperationRoundResult:
        """HUD 消失先停策略，按通关目标区分胜负。"""
        battle = self.ctx.auto_battle_context
        if self.ctx.controller.battle_input_blocked:
            self._blocked_since = self._blocked_since or time.monotonic()
            if self._active:
                battle.stop_auto_battle()
                self._active = False
            won = read_intel_result(self)
            if won is not None:
                self.save_screenshot(prefix='macos_intel_battle_result')
                return self.round_success('代行战斗结束', data={'won': won})
            if self.ctx.controller.refresh_battle_input_scope():
                battle.resume_auto_battle()
                self._active = True
                self._blocked_since = None
            elif time.monotonic() - self._blocked_since > 20:
                self.save_screenshot(prefix='macos_intel_unknown_battle_result')
                return self.round_fail('代行战斗 HUD 消失，未识别通关结果')
            return self.round_wait(wait=0.3)
        battle.check_battle_state(self.last_screenshot, self.last_screenshot_time, check_battle_end_normal_result=True)
        return self.round_wait(wait=self.ctx.battle_assistant_config.screenshot_interval)

    def handle_pause(self) -> None:
        """暂停停止策略并清空输入。"""
        self.ctx.auto_battle_context.stop_auto_battle()
        self.ctx.controller.pause_input()
        self._active = False

    def handle_resume(self) -> None:
        """恢复前重新检查战斗 HUD。"""
        if self._scope and self.ctx.controller.refresh_battle_input_scope():
            self.ctx.auto_battle_context.resume_auto_battle()
            self._active = True


class GamepadIntelSettlement(_GamepadRewardOperation):
    """关闭真实挑战结果，回到板面后由原应用记录次数。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄代行结算', timeout_seconds=40)
        self._finish_sent: bool = False
        self._reward_sent: bool = False
        self._detail_back_sent: bool = False
        self._outcome: bool | None = None

    @operation_node(name='代行结算返回', is_start_node=True, node_max_retry_times=15)
    def finish(self) -> OperationRoundResult:
        """只确认已知结果，未知奖励页留图。"""
        self.ctx.controller.resume_input()
        if self._finish_sent and self._outcome is False:
            result = GamepadIntelBackToWorld(self.ctx).execute()
            return self.round_success('代行失败') if result.success else self.round_by_op_result(result)
        if self._has_text('情报板', '手柄-委托详情', '放弃委托') and self._has_text('情报板', '手柄-委托详情', '前往'):
            if not self._detail_back_sent:
                self.ctx.controller.btn_tap('east')
                self._detail_back_sent = True
            return self.round_retry('关闭未完成的代行详情', wait=1)
        popup = self._read_area('情报板', '手柄-代行奖励确认')
        if popup is not None and self.round_by_find_area(
            self.last_screenshot, '情报板', '手柄-代行奖励标题',
        ).is_success:
            target = self._text_rect(popup[1], '确认')
            if target is not None and not self._reward_sent and has_filled_highlight(popup[0], target, 'yellow'):
                self._save_evidence('intel_commission_reward')
                self.ctx.controller.btn_tap('south')
                self._reward_sent = True
            return self.round_retry('等待代行奖励确认', wait=1)
        if self._has_text('情报板', '手柄-顶部标签', '情报板') and self._has_text('情报板', '手柄-底部提示', '周期内可获取'):
            return self.round_success('代行结算已返回板面')
        outcome = read_intel_result(self)
        words = self.ctx.ocr.run_ocr(self.last_screenshot) if outcome is not None else {}
        exit_visible = any(
            text.replace(' ', '') in ('完成', '退出') and any(item.center.x >= 1630 and item.center.y >= 980 for item in matches)
            for text, matches in words.items()
        )
        if outcome is not None and exit_visible:
            self._outcome = outcome
            if not self._finish_sent:
                self._save_evidence('intel_before_finish')
                self.ctx.controller.btn_tap('east')
                self._finish_sent = True
            return self.round_retry('等待代行结果返回', wait=1)
        if self.node_retry_times < 4:
            return self.round_retry('等待代行结算稳定', wait=1)
        return self._pending_evidence('intel_settlement', '代行奖励或返回页面待建档')


class GamepadIntelRefresh(_GamepadRewardOperation):
    """只刷新他人的代行列表，不发布委托。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄刷新情报板', timeout_seconds=20)
        self._sent: bool = False

    @operation_node(name='刷新代行列表', is_start_node=True, node_max_retry_times=8)
    def refresh(self) -> OperationRoundResult:
        """LT 切到底部，用唯一黄色圆按钮确认刷新焦点。"""
        if not self._has_text('情报板', '手柄-底部提示', '周期内可获取'):
            return self._pending_evidence('intel_refresh', '未确认情报板列表')
        if self._sent:
            return self.round_success('代行列表已刷新')
        if GamepadIntelBoardFilter._action_focused(self, '刷新'):
            self.ctx.controller.btn_tap('south')
            self._sent = True
        elif GamepadIntelBoardFilter._action_focused(self, '筛选'):
            self.ctx.controller.btn_tap('dpad_left')
        else:
            self.ctx.controller.btn_tap('left_trigger')
        return self.round_retry('等待刷新列表', wait=1)


class GamepadIntelBackToWorld(_GamepadRewardOperation):
    """从已确认的板面或功能导览返回大世界。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄退出情报板', timeout_seconds=35)
        self._back_count: int = 0
        self._last_action_frame: float = -1

    @operation_node(name='退出情报板', is_start_node=True, node_max_retry_times=10)
    def back(self) -> OperationRoundResult:
        """每个已知页面只返回一次，不确认未知弹窗。"""
        if self.last_screenshot is None or self.last_screenshot_time <= self._last_action_frame:
            return self.round_retry('等待返回后的新帧', wait=1)
        if self.round_by_find_area(self.last_screenshot, '大世界-普通', '快捷手册').is_success:
            self._save_evidence('intel_world')
            return self.round_success('情报板已返回大世界')
        guide = self.round_by_find_area(self.last_screenshot, '功能导览', '标题').is_success
        board = self._has_text('情报板', '手柄-顶部标签', '情报板') and self._has_text('情报板', '手柄-底部提示', '周期内可获取')
        generic_back = self.round_by_find_area(self.last_screenshot, '画面-通用', '返回').is_success
        detail = self._has_text('情报板', '手柄-委托详情', '放弃委托') and self._has_text('情报板', '手柄-委托详情', '前往')
        if not any((guide, board, generic_back, detail)):
            return self._pending_evidence('intel_return', '未识别情报板返回页面')
        if self._back_count >= 8:
            return self._pending_evidence('intel_return_limit', '情报板返回次数达到上限')
        self._save_evidence('intel_before_return')
        self.ctx.controller.btn_tap('east')
        self._back_count += 1
        self._last_action_frame = self.last_screenshot_time
        return self.round_retry('等待情报板返回大世界', wait=1)
