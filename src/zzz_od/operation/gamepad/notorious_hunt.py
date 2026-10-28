"""恶名狩猎的手柄入口，沿用原快捷手册页面资源。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, ClassVar

from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from one_dragon.utils import debug_utils
from zzz_od.application.notorious_hunt.notorious_hunt_config import MACOS_HIGHEST_LEVEL
from zzz_od.operation.compendium.notorious_hunt_move import NotoriousHuntMove
from zzz_od.operation.gamepad.battle_guide import GamepadBattleGuide
from zzz_od.operation.gamepad.focus import (
    find_yellow_frames,
    has_filled_highlight,
    text_inside_frame,
)
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation
from zzz_od.operation.gamepad.transport import find_yellow_focus_frames
from zzz_od.operation.gamepad.transport_by_compendium import (
    GamepadTransportByCompendium,
)

if TYPE_CHECKING:
    from one_dragon.base.geometry.rectangle import Rect
    from one_dragon.base.operation.operation_base import OperationResult
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem
    from zzz_od.context.zzz_context import ZContext


def validate_macos_hunt_plan(plans: list[ChargePlanItem]) -> str | None:
    """保留原计划选择，具体Boss由传送层按原副本数据核对。"""
    if not plans:
        return '请先在恶名狩猎设置中添加计划'
    for plan in plans:
        if plan.category_name != '恶名狩猎':
            return '恶名狩猎计划的分类不正确'
        if not plan.mission_type_name:
            return '请先选择恶名狩猎Boss'
        if plan.predefined_team_idx not in range(-1, 20):
            return 'Mac 暂支持当前编队或二十个预备编队'
        if plan.plan_times <= 0 or plan.run_times < 0:
            return '恶名狩猎计划次数必须大于零，已完成次数不能为负'
    return None


class GamepadOpenNotoriousHunt(GamepadOperation):
    """打开恶名狩猎列表，不消耗奖励次数或进入战斗。"""

    def __init__(self, ctx: ZContext) -> None:
        """复用手册的图像识别和标签导航，保留独立节点超时。"""
        super().__init__(ctx, op_name='手柄打开恶名狩猎列表', timeout_seconds=35)
        self.navigation: GamepadTransportByCompendium = GamepadTransportByCompendium(
            ctx, '训练', '恶名狩猎',
        )

    def handle_init(self) -> None:
        """新运行清除手册打开标记。"""
        self.navigation.handle_init()

    @operation_node(name='打开快捷手册', is_start_node=True, node_max_retry_times=6)
    def open_handbook(self) -> OperationRoundResult:
        """沿用已经验证的大世界组合键和顶部标签识别。"""
        self.navigation.last_screenshot = self.last_screenshot
        return self.navigation.open_compendium()

    @node_from(from_name='打开快捷手册')
    @operation_node(name='选择训练', node_max_retry_times=6)
    def choose_training(self) -> OperationRoundResult:
        """沿用训练标签导航。"""
        self.navigation.last_screenshot = self.last_screenshot
        return self.navigation.choose_training()

    @node_from(from_name='选择训练')
    @operation_node(name='选择恶名狩猎', node_max_retry_times=8)
    def choose_hunt(self) -> OperationRoundResult:
        """根据左栏固定文字与蓝色选中态定位，不假设默认分类。"""
        self.navigation.last_screenshot = self.last_screenshot
        names = self.navigation.CATEGORIES
        selected = self.navigation._selected('手柄-分类列表', names, 'blue')
        if selected == '恶名狩猎':
            name = self.save_screenshot(prefix='macos_hunt_handbook')
            return self.round_success('恶名狩猎列表已打开', data={
                'screenshot': debug_utils.get_debug_image_path(name),
            })
        if selected is not None:
            self.ctx.controller.btn_tap('dpad_down')
        return self.round_retry('等待恶名狩猎分类选中', wait=0.7)


class GamepadHuntTransport(GamepadOperation):
    """按配置目标导航并传送到恶名狩猎，不进入战斗。"""

    def __init__(self, ctx: ZContext, mission_type_name: str) -> None:
        """接受原计划副本名，不固定列表首项。"""
        super().__init__(ctx, op_name=f'手柄传送恶名狩猎 {mission_type_name}', timeout_seconds=150)
        self.target: str = mission_type_name
        self.navigation: GamepadTransportByCompendium = GamepadTransportByCompendium(
            ctx, '训练', '恶名狩猎', mission_type_name,
        )
        self._scan_direction: str = 'up'
        self._scan_previous: tuple[int, tuple[str, ...]] | None = None
        self._scan_stuck: int = 0
        self._entered: bool = False
        self._requested: bool = False

    def handle_init(self) -> None:
        """只清除本次导航标记。"""
        self.navigation.handle_init()
        self._entered = False
        self._requested = False
        self._scan_direction = 'up'
        self._scan_previous = None
        self._scan_stuck = 0

    def _scroll_missing_target(self, focus_y: int, visible_names: tuple[str, ...]) -> OperationRoundResult:
        """先核对上边界再往下扫描，无反馈时有限重试，不确认其他目标。"""
        signature = (focus_y // 20, visible_names)
        self._scan_stuck = self._scan_stuck + 1 if signature == self._scan_previous else 0
        if self._scan_stuck == 1:
            return self.round_retry('等待恶名列表滚动反馈', wait=0.6)
        if self._scan_stuck >= 4:
            if self._scan_direction == 'up':
                self._scan_direction = 'down'
                self._scan_stuck = 0
            else:
                self.save_screenshot(prefix='macos_hunt_target_not_found')
                return self.round_fail('双向扫描未找到配置Boss，未发送确认')
        self._scan_previous = signature
        self.ctx.controller.btn_tap(f'dpad_{self._scan_direction}')
        return self.round_retry('等待屏外恶名目标出现', wait=0.6)

    @operation_node(name='打开恶名列表', is_start_node=True)
    def open_list(self) -> OperationRoundResult:
        """复用手册入口并核对配置目标。"""
        category = self.ctx.compendium_service.get_category_data('训练', '恶名狩猎')
        if category is None or self.target not in {
            name for item in category.mission_type_list
            for name in [item.mission_type_name, *item.alias_list]
        }:
            return self.round_fail('恶名狩猎目标不在原副本数据中')
        return self.round_by_op_result(GamepadOpenNotoriousHunt(self.ctx).execute())

    @node_from(from_name='打开恶名列表')
    @operation_node(name='选择配置目标', node_max_retry_times=60, timeout_seconds=70)
    def select_target(self) -> OperationRoundResult:
        """以目标文字和整行焦点选择，未找到目标时不进入其他副本。"""
        nav = self.navigation
        nav.last_screenshot = self.last_screenshot
        if nav._teleport_dialog():
            return self.round_success()
        area = nav._read_area('快捷手册', '手柄-副本列表')
        if area is None:
            return self.round_retry('等待恶名列表', wait=0.5)
        image, words = area
        frames = find_yellow_frames(image)
        target = nav._text_rect(words, self.target)
        cycle = nav._text_rect(words, '周期挑战')
        if cycle is not None and has_filled_highlight(image, cycle, 'yellow'):
            self._scan_direction = 'down'
            self._scan_previous = None
            self._scan_stuck = 0
            self.ctx.controller.btn_tap('dpad_down')
            self._entered = True
            return self.round_retry('从周期奖励移至副本列表', wait=0.5)
        selected_buttons = [
            match.rect for text, matches in words.items() if text.replace(' ', '') == '前往'
            for match in matches if has_filled_highlight(image, match.rect, 'yellow')
        ]
        if target is not None and len(selected_buttons) == 1:
            button = selected_buttons[0]
            if 0 < button.center.y - target.center.y < 170:
                if not self._requested:
                    self.save_screenshot(prefix='macos_hunt_target')
                    self.ctx.controller.btn_tap('south')
                    self._requested = True
                return self.round_retry('等待目标传送确认', wait=0.8)
            self.ctx.controller.btn_tap('dpad_down' if button.center.y < target.center.y else 'dpad_up')
            return self.round_retry('等待配置目标的前往按钮', wait=0.5)
        if target is not None and text_inside_frame(target, frames):
            if not self._requested:
                self.save_screenshot(prefix='macos_hunt_target')
                self.ctx.controller.btn_tap('south')
                self._requested = True
            return self.round_retry('等待目标传送确认', wait=0.8)
        if len(frames) == 1 and target is not None:
            self.ctx.controller.btn_tap(
                'dpad_down' if frames[0].center.y < target.center.y else 'dpad_up'
            )
            return self.round_retry('等待目标焦点', wait=0.5)
        if target is None and (len(selected_buttons) == 1 or len(frames) == 1):
            category = self.ctx.compendium_service.get_category_data('训练', '恶名狩猎')
            known_names = {name for item in category.mission_type_list for name in (item.mission_type_name, *item.alias_list)}
            visible_names = tuple(sorted(name for name in known_names if nav._text_rect(words, name) is not None))
            if visible_names:
                focus = selected_buttons[0] if selected_buttons else frames[0]
                return self._scroll_missing_target(focus.center.y, visible_names)
        if not frames and not self._entered:
            self.ctx.controller.btn_tap('south')
            self._entered = True
            return self.round_retry('等待右侧列表焦点', wait=0.5)
        return self.round_retry('目标不可见或焦点不明，未发送确认', wait=0.5)

    @node_from(from_name='选择配置目标')
    @operation_node(name='确认传送', node_max_retry_times=5)
    def confirm_teleport(self) -> OperationRoundResult:
        """复用已验证的传送弹窗确认。"""
        self.navigation.last_screenshot = self.last_screenshot
        return self.navigation.confirm_teleport()

    @node_from(from_name='确认传送')
    @operation_node(name='等待恶名入口', node_max_retry_times=15, timeout_seconds=20)
    def wait_entry(self) -> OperationRoundResult:
        """只在固定剩余次数提示可见时保存落地画面。"""
        self.navigation.last_screenshot = self.last_screenshot
        area = self.navigation._read_area('恶名狩猎', '手柄-页面文字')
        text = ''.join(area[1]).replace(' ', '') if area is not None else ''
        if area is not None and (
            any('剩余' in word and '次数' in word for word in area[1])
            or (self.target in text and '挑战等级' in text and '深度追猎' in text)
        ):
            name = self.save_screenshot(prefix='macos_hunt_entry')
            return self.round_success('恶名狩猎入口已就绪', data={
                'screenshot': debug_utils.get_debug_image_path(name),
            })
        if self.node_retry_times >= 12:
            self.save_screenshot(prefix='macos_hunt_entry_pending')
        return self.round_retry('等待恶名狩猎入口', wait=1)


class GamepadConfirmUnrewardedHunt(GamepadOperation):
    """只确认奖励次数耗尽的免费提示，不确认电量购买。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='确认无报酬挑战', timeout_seconds=20)
        self._sent: bool = False

    @operation_node(name='确认无报酬提示', is_start_node=True, node_max_retry_times=8)
    def confirm(self) -> OperationRoundResult:
        """固定提示语义与黄色确认同时命中才按 A。"""
        if all(self.round_by_find_area(self.last_screenshot, '实战模拟室', name).is_success
               for name in ('手柄-出战', '手柄-预备编队')):
            return self.round_success('无报酬编队已打开')
        words = self.ctx.ocr.run_ocr(self.last_screenshot)
        text = ''.join(words).replace(' ', '')
        if not all(value in text for value in ('奖励的次数已耗尽', '无法获得挑战奖励', '是否继续挑战')):
            if self._sent:
                return self.round_retry('等待确认后的编队动画结束', wait=1)
            return self.round_fail('未确认无报酬提示，未发送确认')
        confirm = [item.rect for word, matches in words.items() if word.replace(' ', '') == '确认' for item in matches]
        if len(confirm) == 1 and has_filled_highlight(self.last_screenshot, confirm[0], 'yellow'):
            if not self._sent:
                self.save_screenshot(prefix='macos_hunt_unrewarded_notice')
                self.ctx.controller.btn_tap('south')
                self._sent = True
            return self.round_retry('等待无报酬编队页', wait=1)
        return self.round_retry('等待无报酬确认高亮', wait=1)


class GamepadHuntPrepare(GamepadOperation):
    """按原计划选择难度与当前编队，准备阶段不开始战斗。"""

    def __init__(self, ctx: ZContext, plan: ChargePlanItem, unrewarded: bool = False) -> None:
        """明确目标和难度，不把未知剩余次数当作免费机会。"""
        super().__init__(ctx, op_name='手柄恶名狩猎出战准备', timeout_seconds=220)
        self.plan: ChargePlanItem = plan
        self.unrewarded: bool = unrewarded
        self.navigation: GamepadTransportByCompendium = GamepadTransportByCompendium(
            ctx, '训练', '恶名狩猎', plan.mission_type_name,
        )
        self._level_opened: bool = False
        self._level_confirmed: bool = False
        self._next_sent: bool = False
        self.left_times: int | None = None
        self._resolved_level: int | None = None
        self._team_prepared: bool = False

    def handle_init(self) -> None:
        """清理本轮确认标记。"""
        self._level_opened = False
        self._level_confirmed = False
        self._next_sent = False
        self.left_times = None
        self._resolved_level = None
        self._team_prepared = False

    @operation_node(name='核对挑战目标', is_start_node=True, node_max_retry_times=4)
    def check_target(self) -> OperationRoundResult:
        """当前编队以外的能力暂不静默忽略。"""
        if self.plan.predefined_team_idx not in range(-1, 20):
            return self.round_fail('Mac 恶名狩猎暂支持当前编队或二十个预备编队')
        self.navigation.last_screenshot = self.last_screenshot
        area = self.navigation._read_area('恶名狩猎', '手柄-页面文字')
        if area is None:
            return self.round_retry('等待挑战入口', wait=0.5)
        words = area[1]
        if self.navigation._text_rect(words, self.plan.mission_type_name) is None:
            return self.round_fail('当前挑战目标与计划不符')
        text = ''.join(words).replace(' ', '')
        match = re.search(r'剩余奖励次数[:：]?(\d)/(\d)', text)
        if match is None or int(match[2]) != 3:
            return self.round_retry('等待免费奖励次数', wait=0.5)
        self.left_times = int(match[1])
        if self.unrewarded:
            if self.left_times != 0 or '无报酬模式' not in text or 'OFF' not in text.upper():
                return self.round_fail('未确认零奖励次数、无报酬模式及深度追猎 OFF，未进入练习')
            return self.round_success('已确认无报酬模式')
        if not 0 < self.left_times <= 3:
            return self.round_fail('免费奖励次数已用完，不进入深度追猎')
        return self.round_success()

    @node_from(from_name='核对挑战目标')
    @operation_node(name='选择计划难度', node_max_retry_times=10, timeout_seconds=20)
    def choose_level(self) -> OperationRoundResult:
        """LS 打开难度，用可见等级与当前黄色焦点导航。"""
        highest = self.plan.level in ('默认等级', MACOS_HIGHEST_LEVEL)
        requested = re.search(r'(\d+)$', self.plan.level)
        if not highest and requested is None:
            return self.round_fail('计划难度无效')
        level = self._resolved_level if highest else int(requested[1])
        self.navigation.last_screenshot = self.last_screenshot
        area = self.navigation._read_area('恶名狩猎', '手柄-页面文字')
        if area is None:
            return self.round_retry('等待难度页面', wait=0.5)
        image, words = area
        levels = [
            (int(match[1]), item.rect)
            for text, matches in words.items()
            if (match := re.search(r'Lv[.．]?\s*(\d+)', text, re.IGNORECASE))
            for item in matches
        ]
        if highest and len(levels) > 1 and self._resolved_level is None:
            self._resolved_level = max(value for value, _ in levels)
            level = self._resolved_level
        if len(levels) == 1 and levels[0][0] == level:
            return self.round_success()
        if len(levels) > 1:
            self._level_opened = True
            levels = [(value, rect) for value, rect in levels if rect.center.y > 95]
        if not self._level_opened:
            self.ctx.controller.btn_tap('left_stick_click')
            self._level_opened = True
            return self.round_retry('等待难度列表', wait=0.8)
        targets = [rect for value, rect in levels if value == level]
        selected = [(value, rect) for value, rect in levels if has_filled_highlight(image, rect, 'yellow')]
        if len(targets) == 1 and len(selected) == 1 and not self._level_confirmed:
            value, rect = selected[0]
            if value == level:
                self.ctx.controller.btn_tap('south')
                self._level_confirmed = True
            else:
                self.ctx.controller.btn_tap('dpad_down' if rect.center.y < targets[0].center.y else 'dpad_up')
            return self.round_retry('等待配置难度选中', wait=0.5)
        if self.node_retry_times >= 3:
            self.save_screenshot(prefix='macos_hunt_level_pending')
        return self.round_retry('等待明确的等级焦点', wait=0.5)

    @node_from(from_name='选择计划难度')
    @operation_node(name='进入当前编队', node_max_retry_times=8, timeout_seconds=180)
    def prepare_deployment(self) -> OperationRoundResult:
        """确认出战和预备编队出现后结束准备，不发送出战键。"""
        if self.last_screenshot is not None and all(
            self.round_by_find_area(self.last_screenshot, '实战模拟室', name).is_success
            for name in ('手柄-出战', '手柄-预备编队')
        ):
            if self.plan.predefined_team_idx >= 0 and not self._team_prepared:
                from zzz_od.operation.gamepad.predefined_team import (
                    GamepadChoosePredefinedTeam,
                )

                result = GamepadChoosePredefinedTeam(self.ctx, self.plan.predefined_team_idx).execute()
                if not result.success:
                    return self.round_by_op_result(result)
                self._team_prepared = True
                return self.round_retry('已选择配置编队，等待准备页面更新', wait=0.5)
            words = self.ctx.ocr.run_ocr(self.last_screenshot)
            if any('EMPTY' in text.upper() for text in words):
                return self.round_fail('出战编队含空位，请在 GUI 选择已配置的预备编队')
            name = self.save_screenshot(prefix='macos_hunt_deployment')
            return self.round_success('恶名狩猎当前编队准备就绪', data={
                'screenshot': debug_utils.get_debug_image_path(name),
                'left_times': self.left_times, 'level': self._resolved_level,
                'team_idx': self.plan.predefined_team_idx,
            })
        if self.unrewarded:
            words = self.ctx.ocr.run_ocr(self.last_screenshot)
            if '无法获得挑战奖励' in ''.join(words).replace(' ', ''):
                result = GamepadConfirmUnrewardedHunt(self.ctx).execute()
                if result.success:
                    self._next_sent = True
                    return self.round_retry('无报酬提示已确认，等待编队', wait=0.5)
                return self.round_by_op_result(result)
        if not self._next_sent:
            if self.unrewarded:
                self.navigation.last_screenshot = self.last_screenshot
                area = self.navigation._read_area('恶名狩猎', '手柄-页面文字')
                text = ''.join(area[1]).replace(' ', '') if area is not None else ''
                if '无报酬模式' not in text or 'OFF' not in text.upper():
                    return self.round_fail('无报酬模式发生变化，未进入出战编队')
            self.ctx.controller.btn_tap('start')
            self._next_sent = True
        return self.round_retry('等待当前编队页面', wait=0.8)


class GamepadHuntDeploy(GamepadOperation):
    """已选择编队后进入挑战，保存战前画面，不更新计划次数。"""

    def __init__(self, ctx: ZContext, plan: ChargePlanItem) -> None:
        """出战前先验证战斗策略可用。"""
        super().__init__(ctx, op_name='手柄恶名狩猎进入挑战', timeout_seconds=45)
        self.plan: ChargePlanItem = plan
        self._sent: bool = False

    @operation_node(name='出战', is_start_node=True, node_max_retry_times=5)
    def deploy(self) -> OperationRoundResult:
        """只从非空编队准备页发一次 Start。"""
        if not all(self.round_by_find_area(self.last_screenshot, '实战模拟室', name).is_success
                   for name in ('手柄-出战', '手柄-预备编队')):
            return self.round_retry('等待出战准备页', wait=0.5)
        words = self.ctx.ocr.run_ocr(self.last_screenshot)
        if any('EMPTY' in text.upper() for text in words):
            return self.round_fail('出战队伍包含空位')
        strategy = self.plan.auto_battle_config
        if self.plan.predefined_team_idx >= 0:
            team = self.ctx.team_config.get_team_by_idx(self.plan.predefined_team_idx)
            if team is None:
                return self.round_fail('预备编队配置缺失')
            strategy = team.auto_battle
        self.ctx.auto_battle_context.init_auto_op(op_name=strategy, sub_dir='auto_battle')
        auto_op = self.ctx.auto_battle_context.auto_op
        if auto_op is None or auto_op.auto_turn_interval != 0:
            return self.round_fail('Mac 策略须关闭未校准的自动转向')
        if not self._sent:
            self.ctx.controller.btn_tap('start')
            self._sent = True
        return self.round_success(wait=1)

    @node_from(from_name='出战')
    @operation_node(name='等待挑战场景', node_max_retry_times=25, timeout_seconds=30)
    def wait_scene(self) -> OperationRoundResult:
        """等战斗 HUD 出现后记录场景，后续由战前交互操作处理。"""
        if self.last_screenshot is not None and (
            self.ctx.auto_battle_context.is_normal_attack_btn_available(self.last_screenshot)
            or self.round_by_find_area(self.last_screenshot, '战斗画面', '按键-交互').is_success
        ):
            name = self.save_screenshot(prefix='macos_hunt_scene')
            return self.round_success('挑战场景已加载', data={
                'screenshot': debug_utils.get_debug_image_path(name),
            })
        if self.node_retry_times >= 20:
            self.save_screenshot(prefix='macos_hunt_loading_pending')
        return self.round_retry('等待挑战场景加载', wait=1)


class GamepadHuntApproach(GamepadOperation):
    """复用上游恶名狩猎战前移动，缺少手柄适配时保留现场。"""

    def __init__(self, ctx: ZContext, buff_num: int = 1) -> None:
        """原移动算法通过已有控制器适配器执行。"""
        super().__init__(ctx, op_name='复用恶名狩猎战前移动', timeout_seconds=90)
        self.buff_num: int = buff_num

    @operation_node(name='复用原战前移动', is_start_node=True, screenshot_before_round=False)
    def approach(self) -> OperationRoundResult:
        """沿用原距离模型、OCR 和移动编排，不写另一套寻路。"""
        self.ctx.lost_void.init_lost_void_det_model()
        operation = GamepadNotoriousHuntMove(self.ctx, self.buff_num)
        operation.timeout_seconds = 60
        result = operation.execute()
        self.last_screenshot = self.ctx.controller.get_screenshot()
        name = self.save_screenshot(prefix='macos_hunt_after_upstream_move')
        return self.round_success('原战前移动完成', data={
            'screenshot': debug_utils.get_debug_image_path(name),
        }) if result.success else self.round_fail(result.status, data={
            'screenshot': debug_utils.get_debug_image_path(name),
        })


class GamepadNotoriousHuntMove(NotoriousHuntMove):
    """继承原移动算法，仅增加可选战斗引导处理。"""

    def __init__(self, ctx: ZContext, buff_num: int = 1) -> None:
        """保留原鸣徽选项与移动计数。"""
        from zzz_od.operation.gamepad.lost_void_common import (
            GamepadLostVoidChooseCommon,
        )

        super().__init__(ctx, buff_num)
        self._battle_guide: GamepadBattleGuide = GamepadBattleGuide()
        self._buff_parser: GamepadLostVoidChooseCommon = GamepadLostVoidChooseCommon(ctx)
        self._buff_confirmed: bool = False

    def _buff_names(self) -> list[Rect]:
        """复用通用鸣徽黑色名称栏，不依赖随机鸣徽名。"""
        self._buff_parser.last_screenshot = self.last_screenshot
        return self._buff_parser.name_rects()

    def _move_by_hint(self) -> OperationRoundResult:
        """各 Boss 统一处理可选引导，其余移动沿用上游算法。"""
        result = self._battle_guide.handle(self)
        if result is not None:
            # 原移动将 RETRY 视为方向失败并补移动，引导期间只等待。
            if result.is_fail:
                return result
            return self.round_wait(result.status, wait=1)
        if len(self._buff_names()) == 3:
            return self.choose_buff()
        return super()._move_by_hint()

    @node_from(from_name='交互')
    @operation_node(name='选择', node_max_retry_times=10)
    def choose_buff(self) -> OperationRoundResult:
        """按原从左到右序号选择，整卡唯一焦点匹配后才按 A。"""
        names = self._buff_names()
        if len(names) == 3:
            frames = find_yellow_focus_frames(self.last_screenshot, 300, 430, 450, 600)
            selected = [i for i, rect in enumerate(names) for frame in frames
                        if frame.x1 < rect.center.x < frame.x2 and frame.y1 < rect.center.y < frame.y2]
            if len(selected) != 1:
                return self.round_retry('等待鸣徽唯一黄色焦点', wait=1)
            if self._buff_confirmed:
                return self.round_retry('等待鸣徽确认后返回', wait=1)
            target = self.buff_num - 1 if 1 <= self.buff_num <= len(names) else 0
            if selected[0] == target:
                self.save_screenshot(prefix='macos_hunt_buff_selected')
                self.ctx.controller.btn_tap('south')
                self._buff_confirmed = True
            else:
                self.ctx.controller.btn_tap('dpad_right' if selected[0] < target else 'dpad_left')
            return self.round_wait('等待计划鸣徽选中', wait=max(1, self.ctx.macos_config.menu_action_interval_ms / 1000))
        if self.ctx.auto_battle_context.is_normal_attack_btn_available(self.last_screenshot) or self.round_by_find_area(
            self.last_screenshot, '战斗画面', '按键-交互',
        ).is_success:
            return self.round_success()
        return self.round_retry('等待已识别的鸣徽选择页', wait=1)

    @node_from(from_name='移动靠近交互', status='标识-BOSS血条')
    @node_from(from_name='选择', success=False)
    @node_from(from_name='选择后移动')
    @operation_node(name='移动完成', node_max_retry_times=3)
    def move_done(self) -> OperationRoundResult:
        """选择失败不能沿父流程的兜底边当作接敌成功。"""
        if self.previous_node.name == '选择' and not self.previous_node.is_success:
            return self.round_fail('鸣徽选择失败，未开始自动战斗')
        if self.round_by_find_area(self.last_screenshot, '恶名狩猎', '标识-BOSS血条').is_success:
            return self.round_success()
        return self.round_retry('等待接敌后的 Boss 血条', wait=1)


class GamepadHuntBattle(GamepadOperation):
    """直接复用原恶名狩猎自动战斗，仅包裹 Mac 输入保护和结束清理。"""

    realtime_nodes: ClassVar[frozenset[str]] = frozenset({'执行原自动战斗'})

    def __init__(self, ctx: ZContext, plan: ChargePlanItem) -> None:
        """不重写策略、角色识别和战斗状态判断。"""
        from zzz_od.operation.compendium.notorious_hunt import NotoriousHunt

        super().__init__(ctx, op_name='复用恶名狩猎自动战斗', timeout_seconds=630)
        self.original: NotoriousHunt = NotoriousHunt(ctx, plan, use_charge_power=False)
        self._scope: bool = False
        self._active: bool = False

    def execute(self) -> OperationResult:
        """退出任何结果都释放本场战斗输入。"""
        try:
            return super().execute()
        finally:
            self.ctx.auto_battle_context.stop_auto_battle()
            if self._scope:
                self.ctx.controller.end_battle_input_scope()
            self._scope = False
            self._active = False

    @operation_node(name='启动原自动战斗', is_start_node=True, node_max_retry_times=5)
    def start(self) -> OperationRoundResult:
        """只在战斗 HUD 明确存在时启动原策略。"""
        from zzz_od.controller.macos_battle_input_guard import MacBattleHudGuard

        if self.last_screenshot is None or not self.ctx.auto_battle_context.is_normal_attack_btn_available(self.last_screenshot):
            self.save_screenshot(prefix='macos_hunt_battle_entry_pending')
            return self.round_retry('等待有效战斗 HUD', wait=0.5)
        self.original.init_auto_battle()
        if self.ctx.auto_battle_context.auto_op.auto_turn_interval != 0:
            return self.round_fail('Mac 战斗策略须关闭未校准的自动转向')
        self.ctx.controller.begin_battle_input_scope(MacBattleHudGuard(self.ctx.auto_battle_context))
        self._scope = True
        self.original.start_auto_op()
        self._active = True
        return self.round_success()

    @node_from(from_name='启动原自动战斗')
    @operation_node(name='执行原自动战斗', mute=True, timeout_seconds=600)
    def battle(self) -> OperationRoundResult:
        """原恶名狩猎处理战斗状态；Mac 只在 HUD 消失时阻止残留按键。"""
        battle = self.ctx.auto_battle_context
        if self.ctx.controller.battle_input_blocked:
            if self._active:
                battle.stop_auto_battle()
                self._active = False
            if self.ctx.controller.refresh_battle_input_scope():
                battle.resume_auto_battle()
                self._active = True
        if self.ctx.controller.battle_input_blocked:
            outcome = read_hunt_result(self)
            if outcome is not None:
                self.save_screenshot(prefix='macos_hunt_battle_result')
                return self.round_success('恶名狩猎胜利' if outcome else '恶名狩猎失败')
            return self.round_wait(wait=0.3)
        self.original.last_screenshot = self.last_screenshot
        self.original.last_screenshot_time = self.last_screenshot_time
        result = self.original.auto_battle()
        if result.is_success:
            outcome = read_hunt_result(self)
            if outcome is not None:
                return self.round_success('恶名狩猎胜利' if outcome else '恶名狩猎失败')
            return self.round_wait('等待恶名狩猎结算目标', wait=0.5)
        return result

    def handle_pause(self) -> None:
        """暂停继续使用原战斗执行器的释放机制。"""
        self.ctx.auto_battle_context.stop_auto_battle()
        self._active = False

    def handle_resume(self) -> None:
        """战斗保护允许新帧时才恢复原策略。"""
        if self._scope and self.ctx.controller.refresh_battle_input_scope():
            self.ctx.auto_battle_context.resume_auto_battle()
            self._active = True


def read_hunt_result(operation: GamepadOperation) -> bool | None:
    """仅挑战结果标题和通关目标明确时返回成败，未知画面返回 None。"""
    if operation.last_screenshot is None or not operation.round_by_find_area(
        operation.last_screenshot, '战斗画面', '手柄-挑战结果',
    ).is_success:
        return None
    area = operation.ctx.screen_loader.get_area('恶名狩猎', '手柄-通关目标')
    words = operation.ctx.ocr.run_ocr(operation.last_screenshot)
    row = [(item.center.x, text) for text, matches in words.items() for item in matches
           if area.rect.x1 <= item.center.x <= area.rect.x2 and area.rect.y1 <= item.center.y <= area.rect.y2]
    text = ''.join(text for _, text in sorted(row)).replace(' ', '')
    if '完成恶名狩猎' not in text:
        return None
    match = re.search(r'([01])/1', text)
    return None if match is None else match[1] == '1'


class GamepadHuntResultExit(GamepadOperation):
    """关闭已确认的挑战结算，等返回后再读取免费次数。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄恶名狩猎结算返回', timeout_seconds=40)
        self.won: bool | None = None

    @operation_node(name='退出结算', is_start_node=True, node_max_retry_times=8)
    def finish(self) -> OperationRoundResult:
        """成败都允许离开结算，未知结果不按键。"""
        self.won = read_hunt_result(self)
        if self.won is None:
            return self.round_retry('等待明确的恶名狩猎结果', wait=1)
        words = self.ctx.ocr.run_ocr(self.last_screenshot)
        exit_visible = any(text.replace(' ', '') in ('退出', '完成')
                           and any(item.center.x >= 1630 and item.center.y >= 980 for item in matches)
                           for text, matches in words.items())
        if not exit_visible:
            return self.round_retry('等待结算退出按钮', wait=1)
        self.ctx.auto_battle_context.stop_auto_battle()
        self.ctx.controller.resume_input()
        self.ctx.controller.btn_tap('east')
        return self.round_success(wait=1)

    @node_from(from_name='退出结算')
    @operation_node(name='等待挑战入口', node_max_retry_times=25)
    def wait_entry(self) -> OperationRoundResult:
        """只有入口免费次数可读才算完成结算返回。"""
        area = self.ctx.screen_loader.get_area('恶名狩猎', '手柄-页面文字')
        words = self.ctx.ocr.crop_and_run_ocr(self.last_screenshot, area.rect)
        text = ''.join(words).replace(' ', '')
        match = re.search(r'剩余奖励次数[:：]?(\d)/3', text)
        if match is not None:
            return self.round_success(data={'won': self.won, 'left_times': int(match[1])})
        if '深度追猎' in text and '无报酬模式' in text:
            return self.round_success(data={'won': self.won, 'left_times': 0})
        if self.node_retry_times >= 20:
            self.save_screenshot(prefix='macos_hunt_result_return_pending')
        return self.round_retry('等待恶名狩猎入口次数', wait=1)


class GamepadNotoriousHunt(GamepadOperation):
    """单场准备、移动、原自动战斗和结算连续执行。"""

    def __init__(self, ctx: ZContext, plan: ChargePlanItem, unrewarded: bool = False) -> None:
        super().__init__(ctx, op_name='手柄恶名狩猎完整单场', timeout_seconds=1100)
        self.plan: ChargePlanItem = plan
        self.unrewarded: bool = unrewarded
        self._before: int | None = None
        self._won: bool = False

    @operation_node(name='准备挑战', is_start_node=True, screenshot_before_round=False)
    def prepare(self) -> OperationRoundResult:
        """在出战前加载距离模型，避免战斗计时期间下载。"""
        self.ctx.lost_void.init_lost_void_det_model()
        op = GamepadHuntPrepare(self.ctx, self.plan, unrewarded=self.unrewarded)
        result = op.execute()
        self._before = op.left_times
        if self._before == 0 and not self.unrewarded:
            from zzz_od.application.notorious_hunt import notorious_hunt_const

            record = self.ctx.run_context.get_run_record(
                app_id=notorious_hunt_const.APP_ID, instance_idx=self.ctx.current_instance_idx,
            )
            record.left_times = 0
            return self.round_success('周期挑战无剩余次数')
        return self.round_by_op_result(result)

    @node_from(from_name='准备挑战', status='恶名狩猎当前编队准备就绪')
    @operation_node(name='进入挑战', screenshot_before_round=False)
    def deploy(self) -> OperationRoundResult:
        """沿用已验证的出战操作。"""
        return self.round_by_op_result(GamepadHuntDeploy(self.ctx, self.plan).execute())

    @node_from(from_name='进入挑战')
    @operation_node(name='接近目标', screenshot_before_round=False)
    def approach(self) -> OperationRoundResult:
        """原距离寻路结束后立即进入战斗。"""
        return self.round_by_op_result(GamepadHuntApproach(
            self.ctx, self.plan.notorious_hunt_buff_num,
        ).execute())

    @node_from(from_name='接近目标')
    @operation_node(name='战斗', screenshot_before_round=False)
    def fight(self) -> OperationRoundResult:
        """复用原自动战斗，明确失败也进入结算退出。"""
        result = GamepadHuntBattle(self.ctx, self.plan).execute()
        if result.status not in ('恶名狩猎胜利', '恶名狩猎失败'):
            return self.round_by_op_result(result)
        self._won = result.status == '恶名狩猎胜利'
        return self.round_success()

    @node_from(from_name='战斗')
    @operation_node(name='结算返回', screenshot_before_round=False)
    def finish(self) -> OperationRoundResult:
        """免费模式核对扣次才更新计划，无报酬模式只核对零次数。"""
        result = GamepadHuntResultExit(self.ctx).execute()
        if not result.success:
            return self.round_by_op_result(result)
        if not self._won or result.data['won'] is not True:
            return self.round_fail('恶名狩猎失败，已返回入口，未增加完成次数')
        left = result.data['left_times']
        if self.unrewarded:
            if self._before != 0 or left != 0:
                return self.round_fail('无报酬挑战次数状态不符，未更新计划')
            return self.round_success('恶名狩猎无报酬单场完成', data={'left_times': 0, 'won': True, 'unrewarded': True})
        if self._before is None or left != self._before - 1:
            return self.round_fail('胜利后免费次数变化不符，未更新计划')
        from one_dragon.base.operation.application import application_const
        from zzz_od.application.notorious_hunt import notorious_hunt_const

        config = self.ctx.run_context.get_config(
            app_id=notorious_hunt_const.APP_ID, instance_idx=self.ctx.current_instance_idx,
            group_id=application_const.DEFAULT_GROUP_ID,
        )
        record = self.ctx.run_context.get_run_record(
            app_id=notorious_hunt_const.APP_ID, instance_idx=self.ctx.current_instance_idx,
        )
        saved = next((item for item in config.plan_list if item.plan_id == self.plan.plan_id), None)
        if saved is not None:
            config.add_plan_run_times(self.plan)
            self.plan.run_times = saved.run_times
        else:
            self.plan.run_times += 1
        record.left_times = left
        return self.round_success('恶名狩猎单场完成', data={'left_times': left})


class GamepadHuntBackToWorld(GamepadOperation):
    """从已确认的恶名狩猎入口返回大世界。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄恶名狩猎返回街区', timeout_seconds=25)
        self._sent: bool = False
        self._deployment_back_sent: bool = False
        self._list_back_sent: bool = False

    @operation_node(name='返回街区', is_start_node=True, node_max_retry_times=20)
    def back(self) -> OperationRoundResult:
        """入口仅返回一次，过渡帧不重复输入。"""
        if self.round_by_find_area(self.last_screenshot, '大世界-普通', '快捷手册').is_success:
            return self.round_success()
        if not self._deployment_back_sent and all(
            self.round_by_find_area(self.last_screenshot, '实战模拟室', name).is_success
            for name in ('手柄-出战', '手柄-预备编队')
        ):
            self.ctx.controller.resume_input()
            self.ctx.controller.btn_tap('east')
            self._deployment_back_sent = True
            return self.round_retry('等待离开出战准备', wait=1)
        area = self.ctx.screen_loader.get_area('恶名狩猎', '手柄-页面文字')
        words = self.ctx.ocr.crop_and_run_ocr(self.last_screenshot, area.rect)
        text = ''.join(words).replace(' ', '')
        if not self._list_back_sent and all(word in text for word in ('当期剩余奖励次数', '奖励详情', '相关代理人')):
            self.ctx.controller.resume_input()
            self.ctx.controller.btn_tap('east')
            self._list_back_sent = True
            return self.round_retry('等待离开恶名狩猎列表', wait=1)
        if not self._sent and '挑战等级' in text and ('剩余奖励次数' in text or '深度追猎' in text):
            self.ctx.controller.resume_input()
            self.ctx.controller.btn_tap('east')
            self._sent = True
        return self.round_retry('等待返回街区', wait=1)


class GamepadHuntOpenRewards(GamepadOperation):
    """从挑战入口打开周期奖励，未确认奖励画面前不领取。"""

    def __init__(self, ctx: ZContext) -> None:
        super().__init__(ctx, op_name='手柄恶名狩猎周期奖励入口', timeout_seconds=20)

    @operation_node(name='打开周期奖励', is_start_node=True, node_max_retry_times=5)
    def open(self) -> OperationRoundResult:
        """X 对应实拍挑战入口左下方周期奖励图标。"""
        area = self.ctx.screen_loader.get_area('恶名狩猎', '手柄-页面文字')
        words = self.ctx.ocr.crop_and_run_ocr(self.last_screenshot, area.rect)
        text = ''.join(words).replace(' ', '')
        if '挑战等级' not in text or '周期剩余时间' not in text:
            return self.round_retry('等待挑战入口周期奖励按钮', wait=1)
        self.ctx.controller.resume_input()
        self.ctx.controller.btn_tap('west')
        return self.round_success(wait=1)

    @node_from(from_name='打开周期奖励')
    @operation_node(name='记录周期奖励')
    def inspect(self) -> OperationRoundResult:
        """保存实际奖励布局，不把入口成功当作已领取。"""
        name = self.save_screenshot(prefix='macos_hunt_rewards')
        return self.round_success('周期奖励已打开，尚未领取', data={
            'screenshot': debug_utils.get_debug_image_path(name),
        })
