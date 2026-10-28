"""Mac 局内继续复用原层间移动，菜单和战斗输入使用手柄分支。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, ClassVar

import numpy as np

from one_dragon.base.operation.operation import Operation
from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from one_dragon.utils.log_utils import log
from zzz_od.application.hollow_zero.lost_void.context.lost_void_detector import (
    LostVoidDetector,
)
from zzz_od.application.hollow_zero.lost_void.lost_void_challenge_config import (
    LostVoidRegionType,
)
from zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_interact_target_const import (
    LostVoidInteractTarget,
)
from zzz_od.application.hollow_zero.lost_void.operation.lost_void_move_by_det import (
    LostVoidMoveByDet,
)
from zzz_od.application.hollow_zero.lost_void.operation.lost_void_run_level import (
    LostVoidRunLevel,
)
from zzz_od.operation.gamepad.focus import has_filled_highlight
from zzz_od.operation.gamepad.gamepad_operation import (
    GamepadMenuDelayMixin,
    GamepadOperation,
)
from zzz_od.operation.gamepad.lost_void_turn import GamepadLostVoidMoveByDet
from zzz_od.operation.gamepad.transport_by_compendium import (
    GamepadTransportByCompendium,
)

if TYPE_CHECKING:
    from cv2.typing import MatLike

    from one_dragon.base.operation.operation_base import OperationResult
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class GamepadLostVoidRunLevel(GamepadMenuDelayMixin, LostVoidRunLevel):
    """原寻路和区域优先级沿用，未建档菜单停止留图。"""

    realtime_nodes: ClassVar[frozenset[str]] = frozenset({'非战斗画面识别', '战斗中'})
    move_by_det_class: ClassVar[type[LostVoidMoveByDet]] = GamepadLostVoidMoveByDet

    def __init__(self, ctx: ZContext, region_type: LostVoidRegionType | str = '入口') -> None:
        """开发恢复与原应用共用同一个区域枚举入口。"""
        if isinstance(region_type, str):
            region_type = LostVoidRegionType.from_value(region_type)
        super().__init__(ctx, region_type)
        self._battle_scope: bool = False
        self._battle_active: bool = False
        self._unknown_hud_since: float = 0
        self._invalid_battle_frames: int = 0
        self._recovering_battle_frame: bool = False
        self._battle_interact_frames: int = 0
        self._battle_interact_frame_time: float = -1
        self._resume_menu_sent: bool = False
        self._challenge_confirm_attempts: int = 0
        self._challenge_confirm_sent_at: float = 0
        self._challenge_confirm_frame_time: float = 0
        self._boss_completion_seen: bool = False
        self._boss_result_wait_since: float = 0
        self._interact_sent_at: float = 0
        self._interact_attempts: int = 0
        self._unknown_interact_rounds: int = 0
        self._dialog_frame_time: float = -1
        self._dialog_sent_at: float = 0
        self._dialog_text: str | None = None
        self._dialog_repeats: int = 0

    def _sidestep_by_dx(self, dx: float) -> None:
        """入口用已校准镜头纠偏，下一次前进朝向目标，避免纯横移反复换焦点。"""
        if abs(dx) <= 60:
            return
        speed = self.ctx.macos_config.turn_distance_per_second
        if speed <= 0:
            raise ValueError('请先完成 Mac 镜头校准')
        amplitude = self.ctx.macos_config.turn_stick_amplitude
        duration = min(0.15, max(0.1, abs(dx) * 0.65 / speed))
        self.ctx.controller.move_camera(amplitude if dx > 0 else -amplitude, 0, press_time=duration)

    @node_from(from_name='非战斗画面识别', status=LostVoidDetector.CLASS_INTERACT)
    @node_from(from_name='下层入口处理')
    @operation_node(name='尝试交互')
    def try_interact(self) -> OperationRoundResult:
        """菜单出现优先于残留交互图标；首个交互后留出动画，不连按A。"""
        now = time.monotonic()
        if self.interact_attempted:
            if not self.ctx.lost_void.in_normal_world(self.last_screenshot):
                self.interact_attempted = False
                self._interact_attempts = 0
                return self.round_success('交互成功')
            if now - self._interact_sent_at < 2:
                return self.round_wait('等待首次交互的画面响应', wait=0.5)
            if self._interact_attempts >= 3:
                self.save_screenshot(prefix='macos_lost_void_interact_response_pending')
                return self.round_fail('同一交互三次未响应，已停止')
        else:
            self._interact_attempts = 0
        result = super().try_interact()
        if self.interact_attempted:
            self._interact_sent_at = now
            self._interact_attempts += 1
        return result

    def _try_challenge_dialog(self) -> OperationRoundResult | None:
        """只有挑战类型、黄色确认和A选择共同成立才启动挑战。"""
        if getattr(self.ctx,'screen_loader',None) is None:
            return None
        nav=GamepadTransportByCompendium(self.ctx,'作战','周期征讨')
        nav.last_screenshot=self.last_screenshot
        title=nav._read_area('迷失之地-大世界','手柄-挑战说明')
        text=''.join(title[1]).replace(' ','') if title is not None else ''
        kinds={'无伤':LostVoidRegionType.CHANLLENGE_FLAWLESS,
               '限时':LostVoidRegionType.CHANLLENGE_TIME_TRAIL,
               '收割':LostVoidRegionType.CHANLLENGE_ENEMY_TRAIL}
        matched=[kind for name,kind in kinds.items() if name in text[:16]]
        if '挑战' not in text or len(matched)!=1:
            return None
        confirm=nav._read_area('迷失之地-大世界','手柄-挑战确认')
        prompt=nav._read_area('迷失之地-大世界','手柄-挑战选择提示')
        button=nav._text_rect(confirm[1],'确认') if confirm is not None else None
        if button is None or not has_filled_highlight(confirm[0],button,'yellow') or prompt is None:
            return self.round_retry('等待挑战确认焦点',wait=1)
        if not all(nav._text_rect(prompt[1],word) is not None for word in ('A','选择')):
            return self.round_retry('等待挑战的A选择提示',wait=1)
        now = time.monotonic()
        if not self.click_challenge_confirm or (
            now - self._challenge_confirm_sent_at >= 2
            and self.last_screenshot_time > self._challenge_confirm_frame_time
        ):
            if self._challenge_confirm_attempts >= 3:
                self.save_screenshot(prefix='macos_lost_void_challenge_confirm_pending')
                return self.round_fail('挑战确认三次未响应，已停止')
            self.ctx.controller.btn_tap('south')
            self.region_type=matched[0]
            self.click_challenge_confirm=True
            self._challenge_confirm_attempts += 1
            self._challenge_confirm_sent_at = now
            self._challenge_confirm_frame_time = self.last_screenshot_time
        return self.round_wait('等待挑战说明关闭',wait=1)

    @node_from(from_name='等待加载')
    @operation_node(name='区域类型初始化')
    def init_for_region_type(self) -> OperationRoundResult:
        """挑战已经明确确认后启动战斗，其余区域仍按原接敌流程。"""
        if self.click_challenge_confirm and self.region_type in (
            LostVoidRegionType.CHANLLENGE_FLAWLESS,LostVoidRegionType.CHANLLENGE_TIME_TRAIL,
            LostVoidRegionType.CHANLLENGE_ENEMY_TRAIL,
        ):
            self.click_challenge_confirm=False
            return self.round_success('战斗区域')
        return super().init_for_region_type()

    @node_from(from_name='区域类型初始化',status='非战斗区域')
    @node_from(from_name='非战斗画面识别',status=LostVoidDetector.CLASS_DISTANCE)
    @node_from(from_name='非战斗画面识别',status=LostVoidMoveByDet.STATUS_NEED_DETECT)
    @node_from(from_name='交互后处理',status='大世界')
    @node_from(from_name='战斗中',status='识别需移动交互')
    @node_from(from_name='准备自动战斗',status='识别需移动交互')
    @node_from(from_name='尝试交互',success=False)
    @node_from(from_name='更新优先级')
    @node_from(from_name='追加代理人类型优先级',status='非战斗区域')
    @operation_node(name='非战斗画面识别',timeout_seconds=200)
    def non_battle_check(self) -> OperationRoundResult:
        """Mac弹窗交给明确的手柄确认，不进入原鼠标确认分支。"""
        if self.last_screenshot is None:
            return self.round_retry('等待有效截图',wait=1)
        challenge=self._try_challenge_dialog()
        if challenge is not None:
            return challenge
        if not self.ctx.lost_void.in_normal_world(self.last_screenshot):
            return self.round_success('未在大世界')
        if self.click_challenge_confirm:
            self.click_challenge_confirm=False
            return self.enter_battle()
        return super().non_battle_check()

    def execute(self) -> OperationResult:
        """任意退出都停止原策略并结束本场输入范围。"""
        result: OperationResult | None = None
        battle = self.ctx.auto_battle_context
        previous_variants = battle.normal_attack_template_variants
        battle.normal_attack_template_variants = (*previous_variants, ('ios_gamepad', 'lost_void_attack_inner'))
        try:
            result = super().execute()
            return result
        finally:
            self._stop_battle()
            battle.normal_attack_template_variants = previous_variants
            if (result is None or not result.success) and self.ctx.run_context.is_context_running:
                from zzz_od.operation.gamepad.lost_void import GamepadLostVoidPause

                try:
                    self.ctx.controller.resume_input()
                    GamepadLostVoidPause(self.ctx).execute()
                except Exception:
                    log.exception('迷失之地失败后的场景暂停未完成')

    def _stop_battle(self, resume_menu: bool = False) -> None:
        """策略停下后才开放菜单输入，避免迟到攻击落在选择页。"""
        self.ctx.auto_battle_context.stop_auto_battle()
        self._battle_active = False
        self._unknown_hud_since = 0
        self._recovering_battle_frame = False
        self._battle_interact_frames = 0
        self._battle_interact_frame_time = -1
        if self._battle_scope:
            self.ctx.controller.end_battle_input_scope()
            self._battle_scope = False
            if resume_menu:
                self.ctx.controller.resume_input()

    def handle_pause(self) -> None:
        """暂停后停止原策略，保留保护范围等待复核。"""
        super().handle_pause()
        self._battle_active = False

    def handle_resume(self) -> None:
        """只在本场新帧重新命中 HUD 后恢复战斗。"""
        if self._battle_scope and self.ctx.controller.refresh_battle_input_scope():
            self.ctx.auto_battle_context.resume_auto_battle()
            self._battle_active = True

    def try_talk(self, screen: MatLike) -> OperationRoundResult | None:
        """按面板、选项焦点和专属提示推进，不限制姓名、台词内容或字数。"""
        if screen is None or self.ctx.lost_void.in_normal_world(screen):
            return None
        nav = GamepadTransportByCompendium(self.ctx, '作战', '周期征讨')
        nav.last_screenshot = screen
        area = nav._read_area('迷失之地-大世界', '手柄-对话框')
        if area is None:
            return None
        names = [text for text, matches in area[1].items() if matches.max is not None
                 and matches.max.center.y < 65 and 470 < matches.max.center.x < 670 and len(text.strip()) >= 1]
        body = ''.join(text.strip() for text, matches in area[1].items() if matches.max is not None
                       and 75 < matches.max.center.y < 200)
        choices = nav._read_area('大世界', '手柄-对话选项带')
        # 对话面板与专属提示决定交互类型，台词只用于判断推进后是否变化。
        panel = area[0][60:240, 20:-20]
        if not panel.size or np.mean(np.max(panel, axis=2) < 80) < 0.65:
            return None
        if choices is not None:
            rows = [(text, matches.max) for text, matches in choices[1].items()
                    if text.strip() and text.strip() != 'A' and matches.max is not None and matches.max.x >= 100]
            focused = [match for _, match in rows if has_filled_highlight(choices[0], match.rect, 'yellow')]
            if rows and len(focused) == 1:
                from zzz_od.operation.gamepad.dialog import GamepadChooseDialogOption

                # 鸣徽卡片的黄色数量也可能落入选项带，同行左侧 A 才能证明是对话焦点。
                prompts = [matches.max for text, matches in choices[1].items()
                           if text.strip() == 'A' and matches.max is not None]
                if not prompts:
                    prompts = list(self.ctx.tm.match_template(
                        choices[0], 'ios_gamepad', 'dialog_a', threshold=0.8,
                    ))
                current = focused[0]
                if not any(prompt.x + prompt.w < current.x and abs(prompt.center.y - current.center.y)
                           <= max(40, prompt.h, current.h) for prompt in prompts):
                    return None
                rows.sort(key=lambda item: item[1].center.y)
                target = rows[self.talk_opt_idx % len(rows)][0]
                result = GamepadChooseDialogOption(self.ctx, target, prompt_threshold=0.8).execute()
                if result.success:
                    self.talk_opt_idx += 1
                    return self.round_wait('已选择局内对话选项', wait=0.8)
                return self.round_by_op_result(result)
        prompt = self.round_by_find_area(screen, '迷失之地-大世界', '手柄-对话推进')
        prompt_text = any(text.strip() == 'A' and matches.max is not None
                          and matches.max.center.x > 1040 and matches.max.center.y > 190
                          for text, matches in area[1].items())
        if prompt.is_success or prompt_text:
            now = time.monotonic()
            if (self.last_screenshot_time <= self._dialog_frame_time
                    or now - self._dialog_sent_at < 1):
                return self.round_wait('等待对话推进后的新帧', wait=0.5)
            if body != self._dialog_text:
                self._dialog_text = body
                self._dialog_repeats = 0
            if self._dialog_repeats >= 3:
                self.save_screenshot(prefix='macos_lost_void_dialog_stalled')
                return self.round_fail('对话推进未取得进展，已停止')
            self._dialog_frame_time = self.last_screenshot_time
            self._dialog_sent_at = now
            self._dialog_repeats += 1
            self.talk_opt_idx = 0
            self.ctx.controller.btn_tap('south')
            return self.round_wait(f'推进局内对话：{names[0] if len(names) == 1 else "台词"}', wait=0.8)
        return None

    @node_from(from_name='非战斗画面识别', status='需要更新优先级')
    @operation_node(name='更新优先级')
    def update_priority(self) -> OperationRoundResult:
        """保留原动态分类与代理人类型追加，只替换菜单入口。"""
        from zzz_od.operation.gamepad.lost_void_priority import (
            GamepadLostVoidUpdatePriority,
        )

        result = GamepadLostVoidUpdatePriority(self.ctx).execute()
        return self.round_success('需要追加代理人类型优先级') if result.success else self.round_by_op_result(result)

    @node_from(from_name='非战斗画面识别', status='未在大世界')
    @node_from(from_name='非战斗画面识别', status='按钮-挑战-确认')
    @node_from(from_name='处理寻路失败或阵亡', status='准备重试')
    @operation_node(name='等待加载', node_max_retry_times=30, is_start_node=True)
    def wait_loading(self) -> OperationRoundResult:
        """Mac 不使用原鼠标确认兜底；未知画面保留证据后停止。"""
        if self.last_screenshot is None:
            return self.round_retry('等待有效截图', wait=1)
        challenge=self._try_challenge_dialog()
        if challenge is not None:
            return challenge
        if self.ctx.lost_void.in_normal_world(self.last_screenshot):
            self.room_inited_times = 0
            return self.round_success('大世界')
        if np.mean(np.max(self.last_screenshot, axis=2) < 12) > 0.95:
            return self.round_retry('等待区域加载', wait=1)
        nav = GamepadTransportByCompendium(self.ctx, '作战', '周期征讨')
        nav.last_screenshot = self.last_screenshot
        menu = nav._read_area('迷失之地-大世界', '手柄-战况返回')
        if menu and all(nav._text_rect(menu[1], word) is not None for word in ('重新开始', '退出战斗', '返回')):
            if not self._resume_menu_sent:
                self.ctx.controller.btn_tap('east')
                self._resume_menu_sent = True
            return self.round_retry('等待恢复局内场景', wait=1)
        talk = self.try_talk(self.last_screenshot)
        if talk is not None:
            return talk
        from zzz_od.operation.gamepad.lost_void_common import (
            GamepadLostVoidChooseCommon,
        )

        common = GamepadLostVoidChooseCommon(self.ctx)
        common.last_screenshot = self.last_screenshot
        route=self.check_and_update_current_screen(self.last_screenshot,screen_name_list=['迷失之地-路径迭换','迷失之地-邦布商店','迷失之地-抽奖机'])
        from zzz_od.operation.gamepad.lost_void_store import GamepadLostVoidStoreConfirm
        purchase = GamepadLostVoidStoreConfirm(self.ctx, '购买', accept=False)
        purchase.last_screenshot = self.last_screenshot
        if route is not None or purchase.can_handle() or common.can_handle() or all(self.round_by_find_area(self.last_screenshot, '迷失之地-武备选择', key).is_success
                                     for key in ('按钮-携带', '文本-详情')) or self.round_by_find_area(
            self.last_screenshot,'迷失之地-挑战结果','标题-挑战结果',
        ).is_success:
            return self.round_success('识别正在交互')
        if self.node_retry_times >= 10:
            self.save_screenshot(prefix='macos_lost_void_menu_pending')
        return self.round_retry('等待加载或明确的交互画面', wait=1)

    @node_from(from_name='等待加载', status='识别正在交互')
    @node_from(from_name='尝试交互', status='交互成功')
    @node_from(from_name='战斗中', status='识别正在交互')
    @operation_node(name='交互处理')
    def handle_interact(self) -> OperationRoundResult:
        """新画面先留图，不回退为坐标点击。"""
        if self.last_screenshot is None:
            return self.round_retry('等待交互截图', wait=1)
        if self.interact_target is not None and self.interact_target.is_entry and np.mean(
            np.max(self.last_screenshot, axis=2) < 12,
        ) > 0.95:
            return self.round_success(self.STATUS_NEXT_LEVEL, data=self.interact_target.icon)
        if self.ctx.lost_void.in_normal_world(self.last_screenshot):
            self._unknown_interact_rounds = 0
            return self.round_success('迷失之地-大世界')
        talk = self.try_talk(self.last_screenshot)
        if talk is not None:
            self._unknown_interact_rounds = 0
            return talk
        lottery = self.check_and_update_current_screen(self.last_screenshot, screen_name_list=['迷失之地-抽奖机'])
        if lottery is not None:
            from zzz_od.operation.gamepad.lost_void_lottery import (
                GamepadLostVoidLottery,
            )

            result = GamepadLostVoidLottery(self.ctx).execute()
            # 与原流程一致：抽奖机也可能被模型识别为商店，完成后本层不再追踪。
            if result.success and '邦布商店' not in self.had_been_list:
                self.had_been_list.append('邦布商店')
            return self.round_wait('抽奖机已返回', wait=1) if result.success else self.round_by_op_result(result)
        if self.round_by_find_area(self.last_screenshot,'迷失之地-挑战结果','标题-挑战结果').is_success:
            from zzz_od.operation.gamepad.lost_void_result import (
                GamepadLostVoidBattleResult,
            )

            return self.round_by_op_result(GamepadLostVoidBattleResult(
                self.ctx, investigation_completed=self._boss_completion_seen,
            ).execute())
        route=self.check_and_update_current_screen(self.last_screenshot,screen_name_list=['迷失之地-路径迭换'])
        if route is not None:
            from zzz_od.operation.gamepad.lost_void_route_change import (
                GamepadLostVoidRouteChange,
            )

            result=GamepadLostVoidRouteChange(self.ctx).execute()
            if not result.success:
                return self.round_by_op_result(result)
            if '路径迭换' not in self.had_been_list:
                self.had_been_list.append('路径迭换')
            return self.round_wait('路径迭换已返回',wait=1)
        store=self.check_and_update_current_screen(self.last_screenshot,screen_name_list=['迷失之地-邦布商店'])
        from zzz_od.operation.gamepad.lost_void_store import (
            GamepadLostVoidBangbooStore,
            GamepadLostVoidStoreConfirm,
        )
        purchase = GamepadLostVoidStoreConfirm(self.ctx, '购买', accept=False)
        purchase.last_screenshot = self.last_screenshot
        if store is not None or purchase.can_handle():

            result=GamepadLostVoidBangbooStore(self.ctx).execute()
            if result.success:
                # 商店 NPC 的图标会保留，沿用原流程的本层忽略列表避免反复走回。
                if '邦布商店' not in self.had_been_list:
                    self.had_been_list.append('邦布商店')
                return self.round_wait(result.status,wait=1)
            return self.round_by_op_result(result)
        from zzz_od.operation.gamepad.lost_void_common import (
            GamepadLostVoidChooseCommon,
        )

        common = GamepadLostVoidChooseCommon(self.ctx)
        common.last_screenshot = self.last_screenshot
        if common.can_handle():
            self._unknown_interact_rounds = 0
            result = common.execute()
            return self.round_wait(result.status, wait=1) if result.success else self.round_by_op_result(result)
        if all(self.round_by_find_area(self.last_screenshot, '迷失之地-武备选择', key).is_success
               for key in ('按钮-携带', '文本-详情')):
            from zzz_od.operation.gamepad.lost_void_gear import (
                GamepadLostVoidChooseGear,
            )

            gear = GamepadLostVoidChooseGear(self.ctx, self.entry_gear_name_list if self.region_type == LostVoidRegionType.ENTRY else None)
            result = gear.execute()
            if result.success:
                self.entry_gear_interact_done = self.region_type == LostVoidRegionType.ENTRY
                if self.entry_gear_interact_done and 'NPC武备' not in self.had_been_list:
                    self.had_been_list.append('NPC武备')
                if self.entry_gear_interact_done and result.status == gear.parser.STATUS_REPEATED:
                    self.entry_gear_repeat_times += 1
                    self.entry_door_block_times = 0
                    interact_class = LostVoidDetector.CLASS_INTERACT[5:]
                    if self.entry_gear_repeat_times >= 3 and interact_class not in self.had_been_list:
                        self.had_been_list.append(interact_class)
                        log.info('入口层重复武备达到三次，沿用原流程忽略感叹号并寻找下层入口')
                return self.round_wait(result.status, wait=1)
            return self.round_by_op_result(result)
        if self.interact_target is not None and self.interact_target.is_entry:
            return self.round_success(self.STATUS_NEXT_LEVEL, data=self.interact_target.icon)
        self._unknown_interact_rounds += 1
        if self._unknown_interact_rounds <= 3:
            return self.round_wait('等待交互画面稳定', wait=0.6)
        self.save_screenshot(prefix='macos_lost_void_interact_pending')
        return self.round_fail('迷失之地手柄交互画面待适配')

    @node_from(from_name='交互处理', status='迷失之地-大世界')
    @node_from(from_name='交互处理', status='迷失之地-挑战结果')
    @node_from(from_name='交互处理', status=LostVoidRunLevel.STATUS_NEXT_LEVEL)
    @node_from(from_name='交互处理', success=False, status='未知画面')
    @operation_node(name='交互后处理', node_max_retry_times=10)
    def after_interact(self) -> OperationRoundResult:
        """入口已确认切层后保留层间返回，不因加载较快又回到上一层循环。"""
        if self.previous_node.status == self.STATUS_NEXT_LEVEL:
            return self.round_success(self.STATUS_NEXT_LEVEL, data=self.previous_node.data or self.interact_target.icon)
        return super().after_interact()

    @node_from(from_name='非战斗画面识别', status='进入战斗')
    @node_from(from_name='非战斗画面识别', status=LostVoidMoveByDet.STATUS_IN_BATTLE)
    @node_from(from_name='区域类型初始化', status='战斗区域')
    @operation_node(name='准备自动战斗')
    def init_auto_op(self) -> OperationRoundResult:
        """逐帧保护确认当前 HUD 后，才启动原队伍的自动战斗。"""
        from zzz_od.controller.macos_battle_input_guard import MacBattleHudGuard

        battle = self.ctx.auto_battle_context
        if self.last_screenshot is None:
            return self.round_retry('等待有效战斗HUD', wait=0.5)
        if not battle.is_normal_attack_btn_available(self.last_screenshot):
            if self.round_by_find_area(self.last_screenshot, '战斗画面', '按键-交互').is_success:
                return self.round_success('识别需移动交互')
            return self.round_retry('等待有效战斗HUD', wait=0.5)
        if battle.auto_op is None:
            return self.round_fail('自动战斗策略未加载')
        if battle.auto_op.auto_turn_interval > 0 and self.ctx.macos_config.turn_distance_per_second <= 0:
            return self.round_fail('Mac 自动转向需要先完成镜头校准')
        self.ctx.controller.begin_battle_input_scope(MacBattleHudGuard(battle))
        self._battle_scope = True
        self._unknown_hud_since = 0
        self._invalid_battle_frames = 0
        self._recovering_battle_frame = False
        battle.start_auto_battle()
        self._battle_active = True
        return self.round_success()

    @node_from(from_name='准备自动战斗')
    @operation_node(name='战斗中', mute=True, timeout_seconds=600)
    def in_battle(self) -> OperationRoundResult:
        """沿用原战斗上下文和明确脱战提示，菜单出现先停策略。"""
        if self.last_screenshot is None:
            if self._battle_active:
                self.ctx.auto_battle_context.stop_auto_battle()
                self._battle_active = False
            self._recovering_battle_frame = True
            self._invalid_battle_frames += 1
            if self._invalid_battle_frames >= 3:
                self._stop_battle()
                return self.round_fail('连续三帧战斗截图无效，已停止')
            return self.round_wait('战斗截图暂时无效，已停策略等待新帧', wait=0.5)
        self._invalid_battle_frames = 0
        if self.ctx.controller.battle_input_blocked or self._recovering_battle_frame:
            if self._battle_active:
                self.ctx.auto_battle_context.stop_auto_battle()
                self._battle_active = False
            screen = self.check_and_update_current_screen(self.last_screenshot, screen_name_list=[
                '迷失之地-武备选择', '迷失之地-通用选择', '迷失之地-挑战结果', '迷失之地-战斗失败',
            ])
            if screen is not None:
                self._stop_battle(resume_menu=True)
                self.interact_target = LostVoidInteractTarget(name='战斗后', icon='战斗后', after_battle=True)
                return self.round_success(screen if screen == '迷失之地-战斗失败' else '识别正在交互')
            interact = self.round_by_find_area(self.last_screenshot, '战斗画面', '按键-交互').is_success
            if interact:
                if self.last_screenshot_time > self._battle_interact_frame_time:
                    self._battle_interact_frames += 1
                    self._battle_interact_frame_time = self.last_screenshot_time
                if self._battle_interact_frames >= 3:
                    self._stop_battle(resume_menu=True)
                    return self.round_success('识别需移动交互')
                return self.round_wait('复核普攻已切换为交互按钮', wait=0.3)
            self._battle_interact_frames = 0
            if self.region_type == LostVoidRegionType.BOSS:
                completed = self.round_by_find_area(self.last_screenshot, '迷失之地-大世界', '手柄-调查完成').is_success
                if completed:
                    self._boss_completion_seen = True
                    if self._boss_result_wait_since == 0:
                        self._boss_result_wait_since = time.monotonic()
                if self._boss_completion_seen:
                    if time.monotonic() - self._boss_result_wait_since > 40:
                        self.save_screenshot(prefix='macos_lost_void_final_result_pending')
                        return self.round_fail('调查完成后结果页未出现，已停止')
                    return self.round_wait('等待调查完成结算动画', wait=1)
            if self.ctx.controller.refresh_battle_input_scope():
                self.ctx.auto_battle_context.resume_auto_battle()
                self._battle_active = True
                self._recovering_battle_frame = False
                self._unknown_hud_since = 0
            elif self._unknown_hud_since == 0:
                self._unknown_hud_since = time.monotonic()
            elif time.monotonic() - self._unknown_hud_since > 12:
                self._stop_battle()
                self.save_screenshot(prefix='macos_lost_void_battle_menu_pending')
                return self.round_fail('迷失之地战斗后未知画面，已停止输入')
            return self.round_wait(wait=self.ctx.battle_assistant_config.screenshot_interval)
        self._unknown_hud_since = 0
        result = super().in_battle()
        if result.is_success or result.is_fail:
            self._stop_battle(resume_menu=result.is_success)
        return result

    @node_from(from_name='非战斗画面识别', success=False, status=Operation.STATUS_TIMEOUT)
    @node_from(from_name='战斗中', success=False, status=Operation.STATUS_TIMEOUT)
    @node_from(from_name='战斗中', success=False, status=LostVoidRunLevel.STATUS_AGENT_DEAD)
    @operation_node(name='处理寻路失败或阵亡')
    def handle_find_target_fail(self) -> OperationRoundResult:
        """开发期间未知失败先停止，不调用尚未迁移的鼠标重开路径。"""
        self._stop_battle()
        self.save_screenshot(prefix='macos_lost_void_failure_pending')
        return self.round_fail('迷失之地寻路或战斗失败，已停止输入')


class GamepadLostVoidDeploy(GamepadOperation):
    """在原出战页加载既有模型与策略，然后进入原层间移动。"""

    def __init__(self, ctx: ZContext, auto_battle: str, team_idx: int = -1, prepare_only: bool = True,
                 explore_first_level: bool = True) -> None:
        super().__init__(ctx, op_name='手柄迷失之地出战', timeout_seconds=180)
        self.auto_battle: str = auto_battle
        self.team_idx: int = team_idx
        self.prepare_only: bool = prepare_only
        self.explore_first_level: bool = explore_first_level
        self._sent: bool = False

    @operation_node(name='加载原玩法模型', is_start_node=True, screenshot_before_round=False)
    def initialize(self) -> OperationRoundResult:
        """出战前加载，开启原自动转向时须已有 Mac 独立校准。"""
        self.ctx.lost_void.init_before_run()
        self.ctx.lost_void.predefined_team_idx = self.team_idx
        self.ctx.auto_battle_context.init_auto_op(sub_dir='auto_battle', op_name=self.auto_battle)
        auto_op = self.ctx.auto_battle_context.auto_op
        if auto_op is None:
            return self.round_fail('自动战斗策略未加载')
        if auto_op.auto_turn_interval > 0 and self.ctx.macos_config.turn_distance_per_second <= 0:
            return self.round_fail('Mac 自动转向需要先完成镜头校准')
        return self.round_success()

    @node_from(from_name='加载原玩法模型')
    @operation_node(name='出战并等待场景', node_max_retry_times=20)
    def deploy(self) -> OperationRoundResult:
        """仅在编队页明确就绪时请求一次出战，加载后检查局内 HUD。"""
        if self.last_screenshot is None:
            return self.round_retry('等待有效截图', wait=1)
        if self.prepare_only:
            return self.round_success('仅准备模型，未出战')
        if self._sent and self.ctx.lost_void.in_normal_world(self.last_screenshot):
            self.save_screenshot(prefix='macos_lost_void_first_level')
            return self.round_success('局内场景已确认')
        if not self._sent and all(self.round_by_find_area(self.last_screenshot, '实战模拟室', name).is_success
                                  for name in ('手柄-出战', '手柄-预备编队')):
            self.ctx.controller.btn_tap('start')
            self._sent = True
        return self.round_retry('等待迷失之地局内场景', wait=1)

    @node_from(from_name='出战并等待场景', status='局内场景已确认')
    @operation_node(name='原层间移动')
    def explore(self) -> OperationRoundResult:
        """原区域类型、优先级与检测寻路由原操作继承。"""
        if not self.explore_first_level:
            return self.round_success('局内场景已确认，交由原应用连续调度')
        return self.round_by_op_result(GamepadLostVoidRunLevel(self.ctx, LostVoidRegionType.ENTRY).execute())
