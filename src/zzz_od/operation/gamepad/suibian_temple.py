"""随便观的手柄入口，保留原应用和配置。"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from zzz_od.operation.gamepad.rewards import _GamepadRewardOperation
from zzz_od.operation.gamepad.transport import GamepadTransport

if TYPE_CHECKING:
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.application.suibian_temple.suibian_temple_config import (
        SuibianTempleConfig,
    )
    from zzz_od.context.zzz_context import ZContext


def validate_macos_temple_config(config: SuibianTempleConfig) -> str | None:
    """不静默跳过用户启用的手动经营或购买配置。"""
    if not config.auto_manage_enabled:
        return 'Mac 随便观手动游历、饮茶仙、制造与售卖尚未适配；原配置保留'
    if config.good_goods_purchase_enabled or config.boo_box_purchase_enabled:
        return 'Mac 随便观好物铺与邦巢购买尚未适配；未修改原购买开关'
    return None


class GamepadTempleTransport(GamepadTransport):
    """地图传送沿现有导航，落点确认使用经营页而非大世界。"""

    SUPPORTED_TARGETS: ClassVar[set[tuple[str, str]]] = {('澄辉坪', '随便观')}

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, '澄辉坪', '随便观')
        self.timeout_seconds = 140

    @node_from(from_name='确认手柄地图传送')
    @operation_node(name='等待手柄传送落地', node_max_retry_times=30, timeout_seconds=40)
    def wait_for_world(self) -> OperationRoundResult:
        """只确认已有入口/托管标题，陌生落点保存现场。"""
        area = self.ctx.screen_loader.get_area('随便观-入口', '手柄-页面文字')
        if self.last_screenshot is None or area is None:
            return self.round_retry('等待随便观画面', wait=1)
        words = self.ctx.ocr.run_ocr(self.last_screenshot)
        text = ''.join(words).replace(' ', '')
        if ('经营日志' in text and '自动托管' in text) or ('邻里街坊' in text and any(word in text for word in ('托管中', '经营方针', '派驻邦布'))):
            self.save_screenshot(prefix='macos_temple_entry')
            return self.round_success('随便观入口已打开')
        if self.node_retry_times >= 15:
            path = self.save_screenshot(prefix='macos_temple_entry_pending')
            return self.round_fail('随便观手柄落点待建档', data={'screenshot': path})
        return self.round_retry('等待随便观落地或入口稳定', wait=1)


class GamepadTempleAutoManage(_GamepadRewardOperation):
    """领取已完成托管收益并重新开始，进行中的托管保留。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄随便观自动托管', timeout_seconds=150)
        self._claim_sent: bool = False
        self._start_sent: bool = False
        self._confirm_signature: tuple[str, ...] | None = None
        self._unknown: int = 0
        self.claimed: bool = False
        self._last_input_frame: float = -1

    @operation_node(name='领取并继续托管', is_start_node=True, node_max_retry_times=12)
    def manage(self) -> OperationRoundResult:
        """只在已识别的本业务状态输入，预计收益不能当作已成熟收益。"""
        if self.last_screenshot is None:
            return self.round_retry('等待托管截图', wait=1)
        words = self.ctx.ocr.run_ocr(self.last_screenshot)
        text = ''.join(words).replace(' ', '')
        if self.last_screenshot_time <= self._last_input_frame:
            return self.round_wait('等待操作后的新帧', wait=0.5)
        reward = '获得奖励' in text and '确认' in text and any(name in text for name in ('云纹徽', '百通宝'))
        paused_production = '已暂停正在运作的制造台和游历小队' in text and '确认' in text
        if reward or paused_production:
            if not (self._claim_sent or self._start_sent):
                return self._pending_evidence('temple_unrelated_reward', '已有奖励页未确认来源为本次托管操作')
            signature = tuple(sorted(word for word, matches in words.items()
                                     if any(500 <= item.center.x <= 1450 and 350 <= item.center.y <= 800 for item in matches)))
            if self._confirm_signature != signature:
                self._save_evidence('temple_reward' if reward else 'temple_start_confirmation')
                self.ctx.controller.btn_tap('south')
                self._confirm_signature = signature
                self._last_input_frame = self.last_screenshot_time
                if reward:
                    self.claimed = True
            return self.round_wait('等待托管确认后返回', wait=1)
        panel = '经营日志' in text and '自动托管' in text
        if '邻里街坊' in text and '自动托管中' in text and '可关闭自动托管进行手动操作' in text:
            self._save_evidence('temple_in_progress')
            return self.round_success('托管进行中，保留至完成后领取', data={'claimed': False, 'pending_completion': True})
        if panel:
            self._confirm_signature = None
            self._unknown = 0
            if self._start_sent and any(name in text for name in ('停止托管', '自动托管中')) and '领取收益' not in text:
                self._save_evidence('temple_running')
                return self.round_success('托管已继续', data={'claimed': self.claimed, 'evidence_paths': self.evidence_paths})
            if '领取收益' in text and '自动托管已完成' in text:
                if not self._claim_sent:
                    if not self._save_evidence('temple_before_claim'):
                        return self.round_fail('领取前证据保存失败')
                    self.ctx.controller.btn_tap('west')
                    self._claim_sent = True
                    self._last_input_frame = self.last_screenshot_time
                return self.round_wait('等待已完成托管结算', wait=1)
            if '开始托管' in text:
                if not self._start_sent:
                    self._save_evidence('temple_before_start')
                    self.ctx.controller.btn_tap('west')
                    self._start_sent = True
                    self._last_input_frame = self.last_screenshot_time
                return self.round_wait('等待开始托管', wait=1)
            if '停止托管' in text and not self._start_sent:
                self._save_evidence('temple_in_progress')
                return self.round_success('托管进行中，保留至完成后领取', data={'claimed': False, 'pending_completion': True})
        self._unknown += 1
        if self._unknown <= 4:
            return self.round_retry('等待托管页面动画或奖励稳定', wait=1)
        return self._pending_evidence('temple_unknown', '托管交互画面待建档，未猜测确认')


class GamepadTempleBackToWorld(_GamepadRewardOperation):
    """从已知托管页和入口退回大世界。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄退出随便观', timeout_seconds=30)
        self._count: int = 0
        self._last_frame: float = -1

    @operation_node(name='返回大世界', is_start_node=True, node_max_retry_times=10)
    def back(self) -> OperationRoundResult:
        if self.last_screenshot is None or self.last_screenshot_time <= self._last_frame:
            return self.round_retry('等待返回新帧', wait=1)
        if self.round_by_find_area(self.last_screenshot, '大世界-普通', '快捷手册').is_success:
            return self.round_success('随便观已返回大世界')
        words = ''.join(self.ctx.ocr.run_ocr(self.last_screenshot)).replace(' ', '')
        known = ('经营日志' in words and '自动托管' in words) or ('邻里街坊' in words and any(name in words for name in ('托管中','经营方针','派驻邦布')))
        if not known and self._count > 0 and self.node_retry_times < 6:
            return self.round_retry('等待退出随便观加载结束', wait=1)
        if not known or self._count >= 4:
            return self._pending_evidence('temple_unknown_return', '未识别随便观返回页面')
        self.ctx.controller.btn_tap('east')
        self._count += 1
        self._last_frame = self.last_screenshot_time
        return self.round_retry('等待退出随便观', wait=1)
