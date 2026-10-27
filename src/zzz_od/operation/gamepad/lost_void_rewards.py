"""从迷失之地入口打开悬赏委托，领取必须另外核对真实进度与奖励状态。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from one_dragon.base.operation.operation_node import operation_node
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation
from zzz_od.operation.gamepad.rewards import _GamepadRewardOperation
from zzz_od.operation.gamepad.transport_by_compendium import (
    GamepadTransportByCompendium,
)

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class GamepadLostVoidOpenBounty(GamepadOperation):
    """只打开已确认入口的悬赏页面，不领取、不把打开页面记为奖励完成。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄迷失之地悬赏委托入口', timeout_seconds=20)
        self.navigation: GamepadTransportByCompendium = GamepadTransportByCompendium(ctx, '作战', '周期征讨')
        self._sent: bool = False

    @operation_node(name='打开悬赏委托页面', is_start_node=True, node_max_retry_times=8)
    def open(self) -> OperationRoundResult:
        """只有入口双页签及Y悬赏委托同时成立才打开一次。"""
        if self.last_screenshot is None:
            return self.round_retry('等待悬赏入口截图', wait=1)
        nav=self.navigation
        nav.last_screenshot=self.last_screenshot
        if self._sent:
            words=self.ctx.ocr.run_ocr(self.last_screenshot)
            if any('全部领取' in text for text in words):
                path=self.save_screenshot(prefix='macos_lost_void_bounty_rewards')
                return self.round_success('悬赏委托页面已确认，尚未领取',data={'screenshot':path})
            if self.node_retry_times>=3:
                self.save_screenshot(prefix='macos_lost_void_bounty_pending')
                return self.round_fail('迷失之地悬赏奖励画面待适配')
            return self.round_retry('等待悬赏页面',wait=1)
        entry=self.check_and_update_current_screen(self.last_screenshot,screen_name_list=[
            '迷失之地-入口-周期','迷失之地-入口-常规',
        ])
        area=nav._read_area('迷失之地-入口','手柄-悬赏委托')
        if entry is not None and area is not None and all(nav._text_rect(area[1],word) is not None for word in ('Y','悬赏委托')):
            self.ctx.controller.btn_tap('north')
            self._sent=True
        return self.round_retry('等待悬赏委托入口',wait=1)


class GamepadLostVoidCloseBounty(GamepadOperation):
    """关闭已确认的悬赏面板，等待入口新帧。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx,op_name='手柄关闭迷失之地悬赏',timeout_seconds=15)
        self.navigation: GamepadTransportByCompendium=GamepadTransportByCompendium(ctx,'作战','周期征讨')
        self._sent: bool=False

    @operation_node(name='关闭悬赏面板',is_start_node=True,node_max_retry_times=8)
    def close(self) -> OperationRoundResult:
        if self.last_screenshot is None:
            return self.round_retry('等待悬赏返回截图',wait=1)
        nav=self.navigation
        nav.last_screenshot=self.last_screenshot
        title=nav._read_area('迷失之地-入口','手柄-悬赏面板标题')
        footer=nav._read_area('迷失之地-入口','手柄-悬赏底栏')
        if title and footer and nav._text_rect(title[1],'悬赏委托') and all(nav._text_rect(footer[1],word) for word in ('B','返回')):
            if not self._sent:
                self.ctx.controller.btn_tap('east')
                self._sent=True
            return self.round_retry('等待悬赏面板关闭',wait=1)
        entry=self.check_and_update_current_screen(self.last_screenshot,screen_name_list=[
            '迷失之地-入口-周期','迷失之地-入口-常规',
        ])
        return self.round_success('已返回迷失之地入口') if entry is not None else self.round_retry('等待入口新帧',wait=1)


class GamepadLostVoidClaimBounty(_GamepadRewardOperation):
    """按实际进度核对四档状态，领取后必须看到对应行已领取。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx,op_name='手柄领取迷失之地悬赏',timeout_seconds=45)
        self._claim_sent: bool=False
        self._popup_confirmed: bool=False

    @operation_node(name='领取并核对悬赏',is_start_node=True,node_max_retry_times=20)
    def claim(self) -> OperationRoundResult:
        if self.last_screenshot is None:
            return self.round_retry('等待悬赏领取截图',wait=1)
        if self._known_reward_visible():
            if not self._claim_sent:
                return self._pending_evidence('lost_void_unrelated_reward','未确认获得弹窗由本次悬赏领取产生')
            if not self._popup_confirmed:
                self._save_evidence('lost_void_popup_before_confirm')
                self.ctx.controller.btn_tap('south')
                self._popup_confirmed=True
            return self.round_retry('等待悬赏获得弹窗关闭',wait=1)
        title=self._read_area('迷失之地-入口','手柄-悬赏面板标题')
        progress=self._read_area('迷失之地-入口','手柄-悬赏实际进度')
        states=self._read_area('迷失之地-入口','手柄-悬赏奖励状态')
        footer=self._read_area('迷失之地-入口','手柄-悬赏底栏')
        if not title or self._text_rect(title[1],'悬赏委托') is None or not progress or not states or not footer:
            return self._pending_evidence('lost_void_bounty_unknown','悬赏面板或领取结果未识别')
        scores={int(match[1]) for text in progress[1] if (match:=re.search(r'(?<!\d)(\d{1,4})\s*/\s*8000(?!\d)',text))}
        if len(scores)!=1 or not 0<=next(iter(scores))<=8000:
            return self.round_fail('未读到实际悬赏进度，未领取')
        score=next(iter(scores))
        if score!=8000:
            return self.round_fail(f'悬赏实际进度{score}/8000，尚未完成周活')
        eligible=score//2000
        done=sum(len(matches) for text,matches in states[1].items() if '已领取' in text.replace(' ',''))
        incomplete=sum(len(matches) for text,matches in states[1].items() if '未完成' in text.replace(' ',''))
        if done==eligible and incomplete==4-eligible:
            self._save_evidence('lost_void_bounty_verified')
            return self.round_success('本次可领取悬赏已核对',data={'score':score,'claimed_tiers':done,'maximum':8000})
        if done>eligible or incomplete!=4-eligible:
            return self.round_retry('悬赏进度与四档奖励状态不一致',wait=1)
        if not self._claim_sent:
            controls={text.upper():matches for text,matches in footer[1].items()}
            if not all(self._text_rect(controls,word) is not None for word in ('X','全部领取')):
                return self.round_fail('未确认全部领取的X提示')
            if not self._save_evidence('lost_void_bounty_before_claim'):
                return self.round_fail('领取前证据保存失败')
            self.ctx.controller.btn_tap('west')
            self._claim_sent=True
        return self.round_retry('等待悬赏各档已领取证据',wait=1)
