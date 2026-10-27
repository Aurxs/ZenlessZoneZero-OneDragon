import difflib
import sys
import time
from typing import ClassVar

from cv2.typing import MatLike

from one_dragon.base.config.config_item import get_config_item_from_enum
from one_dragon.base.geometry.point import Point
from one_dragon.base.matcher.match_result import MatchResult
from one_dragon.base.operation.application import application_const
from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from one_dragon.base.operation.operation_notify import NotifyTiming, node_notify
from one_dragon.base.operation.operation_round_result import OperationRoundResult
from one_dragon.utils import cv2_utils
from one_dragon.utils.i18_utils import gt
from one_dragon.utils.log_utils import log
from zzz_od.application.random_play import random_play_const
from zzz_od.application.random_play.random_play_config import (
    RANDOM_AGENT_NAME,
    RandomPlayConfig,
    RandomPlayTransportPoint,
)
from zzz_od.application.zzz_application import ZApplication
from zzz_od.context.zzz_context import ZContext
from zzz_od.game_data.agent import Agent, AgentEnum
from zzz_od.operation.back_to_normal_world import BackToNormalWorld
from zzz_od.operation.gamepad.focus import has_filled_highlight
from zzz_od.operation.gamepad.gamepad_operation import GamepadMenuDelayMixin
from zzz_od.operation.gamepad.shop import (
    business_card_titles,
    business_themes_complete,
    fail_shop_state,
    focused_business_card,
    focused_promoter_name,
    press_shop_action,
    read_shop_area,
    save_shop_frame,
    shop_name,
)
from zzz_od.operation.transport import Transport
from zzz_od.operation.turning.turn_compensation import AngleTurnCompensator
from zzz_od.operation.turning.turn_to_angle import turn_to_angle


class RandomPlayApp(GamepadMenuDelayMixin, ZApplication):

    """录像店营业:录像带店日常经营(宣传/营业/结算)。无消耗,产出菲林与丁尼。"""

    STATUS_ALL_VIDEO_CHOOSE: ClassVar[str] = '已选择全部录像带'
    STATUS_ALREADY_RUNNING: ClassVar[str] = '正在营业'
    STATUS_MACOS_SHOP_OPEN: ClassVar[str] = 'Mac 已在录像店经营页面'
    STATUS_MACOS_CONFIRM: ClassVar[str] = 'Mac 已在营业确认弹窗'
    STATUS_MACOS_STARTED: ClassVar[str] = 'Mac 已在营业成功弹窗'

    def __init__(self, ctx: ZContext):
        ZApplication.__init__(
            self,
            ctx=ctx,
            app_id=random_play_const.APP_ID,
            op_name=random_play_const.APP_NAME,
        )

        self.config: RandomPlayConfig = self.ctx.run_context.get_config(
            app_id=self.app_id,
            instance_idx=self.ctx.current_instance_idx,
            group_id=application_const.DEFAULT_GROUP_ID,
        )

    def handle_init(self) -> None:
        """
        执行前的初始化 由子类实现
        注意初始化要全面 方便一个指令重复使用
        """
        self._all_video_themes: list[str] = [
            '纪实', '怀旧', '冒险', '幻想', '喜剧', '动作', '惊悚', '悬疑',
            '访谈', '都市', '时尚', '灾难', '悲剧', '亲情', '广告', '爱情',
        ]
        self._need_video_themes: list[str] = []
        self._current_idx: int = 0
        self.turn_compensator: AngleTurnCompensator = AngleTurnCompensator(self.ctx.controller)
        self.retried_transport: bool = False
        self._macos_ledger_close_sent: bool = False
        self._macos_promoter_ready: bool = False
        self._macos_videos_ready: bool = False
        self._macos_last_card_frame_time: float = -1
        self._macos_selected_promoter: str | None = None
        self._macos_promoter_confirm_sent: bool = False

    def _macos_business_visible(self) -> bool:
        """经营标题与营业状态同时可见，且没有宣传员或上架子页时才恢复主页面。"""
        if self.last_screenshot is None:
            return False
        header = read_shop_area(self, '手柄-经营状况页')
        if header is None or not any(
            shop_name(text) == '经营状况' and matches.max is not None
            and has_filled_highlight(header[0], matches.max.rect, 'yellow')
            for text, matches in header[1].items()
        ):
            return False
        if any(self.round_by_find_area(self.last_screenshot, '影像店营业', name).is_success
               for name in ('选择宣传员', '上架筛选')):
            return False
        return any(self.round_by_find_area(self.last_screenshot, '影像店营业', name).is_success
                   for name in ('开始营业', '正在营业'))

    def _macos_check_prepared(self) -> bool:
        """营业前重新读取主界面的实际人物、三片及主题完成标记。"""
        titles = business_card_titles(self)
        valid_agents = {item.value.agent_name for item in AgentEnum} | {'邦布18'}
        self._macos_promoter_ready = titles[0] in valid_agents
        self._macos_videos_ready = all(titles[1:]) and business_themes_complete(self)
        return self._macos_promoter_ready and self._macos_videos_ready

    def _macos_confirm_visible(self, message: str) -> bool:
        """完整营业提示、黄色确认焦点和底部选择提示同时出现才确认弹窗。"""
        read = read_shop_area(self, '手柄-营业确认弹窗')
        if read is None:
            return False
        image, texts = read
        normalized = {shop_name(text).rstrip('!！?？'): matches for text, matches in texts.items()}
        confirm = normalized.get('确认')
        return message in normalized and '选择' in normalized and confirm is not None \
            and confirm.max is not None and has_filled_highlight(image, confirm.max.rect, 'yellow')

    def _macos_started_visible(self) -> bool:
        """经营成功有不同祝词，仍须同时确认按钮焦点与选择提示。"""
        return any(self._macos_confirm_visible(text) for text in (
            '诚信经营，丁尼为本', '丁尼广进，生意兴隆',
        ))

    def _macos_promoter_candidates(self) -> list[str]:
        """候选顺序沿用原应用的日期轮换。"""
        candidates = [self.config.agent_name_1, self.config.agent_name_2]
        if RANDOM_AGENT_NAME not in candidates and int(self.run_record.get_current_dt()[-1]) % 2:
            candidates.reverse()
        return candidates

    def _macos_choose_promoter(self) -> OperationRoundResult:
        """保留原配置顺序，指定人物先定位再复用原确认与主页核验。"""
        valid_agents = {item.value.agent_name for item in AgentEnum} | {'邦布18'}
        candidates = self._macos_promoter_candidates()
        if self._macos_business_visible():
            actual = business_card_titles(self)[0]
            if actual in valid_agents:
                if self._macos_selected_promoter is not None and actual != self._macos_selected_promoter:
                    return fail_shop_state(self, '影像店营业', '主页面宣传员与刚才确认的人物不同')
                if self._macos_selected_promoter is None and RANDOM_AGENT_NAME not in candidates and actual != candidates[0]:
                    return self._macos_open_card(0, '宣传员入口')
                self._macos_promoter_ready = True
                return self.round_success()
        if self._macos_promoter_confirm_sent:
            return self.round_retry('等待宣传员确认后的主页面', wait=1)
        if not self.round_by_find_area(
            self.last_screenshot, '影像店营业', '手柄-宣传员列表标题',
        ).is_success:
            return fail_shop_state(self, '影像店营业', '无法确认手柄宣传员列表')
        selected = focused_promoter_name(self, valid_agents)
        if selected is None:
            return fail_shop_state(self, '影像店营业', '无法确认合法宣传员的唯一卡片焦点')
        if RANDOM_AGENT_NAME not in candidates:
            if selected != candidates[0]:
                from zzz_od.operation.gamepad.promoter import GamepadFocusPromoter

                result = GamepadFocusPromoter(self.ctx, candidates, self.get_pos_by_avatar).execute()
                if not result.success:
                    return self.round_by_op_result(result)
                selected = result.data['agent_name']
                self.last_screenshot_time, self.last_screenshot = self.ctx.controller.screenshot()
                if focused_promoter_name(self, valid_agents) != selected:
                    return fail_shop_state(self, '影像店营业', '指定人物移焦后未确认同一焦点，未发送确认')
            from zzz_od.operation.gamepad.promoter import GamepadConfirmPromoter

            result = GamepadConfirmPromoter(self.ctx, selected).execute()
            if result.success:
                self._macos_selected_promoter = selected
                self._macos_promoter_confirm_sent = True
                self._macos_promoter_ready = True
            return self.round_by_op_result(result)
        self._macos_selected_promoter = selected
        result = press_shop_action(self, '影像店营业', '确认宣传员')
        if not result.is_success:
            return result
        self._macos_promoter_confirm_sent = True
        return self.round_retry(f'已确认{selected}，等待主页面', wait=0.5)

    def _macos_open_card(self, target: int, action_name: str) -> OperationRoundResult:
        """从当前黄框有限移至目标卡片，不能假设初始焦点就在宣传员。"""
        if not self._macos_business_visible():
            return fail_shop_state(self, '影像店营业', '无法确认经营主页，未选择卡片')
        current = focused_business_card(self)
        if current is None:
            return fail_shop_state(self, '影像店营业', '无法确认经营卡片唯一焦点')
        if current == target:
            return press_shop_action(self, '影像店营业', action_name)
        if self.last_screenshot_time <= self._macos_last_card_frame_time:
            return self.round_retry('等待卡片移焦后的新帧', wait=0.3)
        self._macos_last_card_frame_time = self.last_screenshot_time
        self.ctx.controller.btn_tap('dpad_right' if current < target else 'dpad_left')
        return self.round_retry(f'移至{action_name}', wait=0.5)

    @node_from(from_name='交互对话', success=False)
    @node_from(from_name='等待经营画面加载', success=False)
    @operation_node(name='传送', is_start_node=True)
    def transport(self) -> OperationRoundResult:
        if self.previous_node.name in {'交互对话', '等待经营画面加载'}:
            if sys.platform == 'darwin':
                return fail_shop_state(self, '影像店营业', self.previous_node.status or '进入手柄经营画面失败')
            if self.retried_transport:
                return self.round_fail(status='进入经营画面失败，重传送超限')
            self.retried_transport = True

        if sys.platform == 'darwin' and self.last_screenshot is not None:
            if self._macos_started_visible():
                return self.round_success(self.STATUS_MACOS_STARTED)
            if self._macos_confirm_visible('是否准备营业'):
                return self.round_success(self.STATUS_MACOS_CONFIRM)
            if self.round_by_find_area(self.last_screenshot, '影像店营业', '昨日账本').is_success \
                    or self._macos_business_visible():
                save_shop_frame(self, '影像店营业', '从当前经营页面恢复')
                return self.round_success(self.STATUS_MACOS_SHOP_OPEN)

        self.turn_compensator.clear_pending_sample()
        item = get_config_item_from_enum(RandomPlayTransportPoint, self.config.transport_point)
        if sys.platform == 'darwin':
            from zzz_od.operation.gamepad.transport import GamepadTransport

            if self.config.transport_point != RandomPlayTransportPoint.POINT_2.value.value:
                return self.round_fail(f'Mac 尚未支持录像店入口的转向移动：{item.value}')
            return self.round_by_op_result(
                GamepadTransport(self.ctx, item.area_name, item.tp_name).execute()
            )
        op = Transport(self.ctx, item.area_name, item.tp_name)
        return self.round_by_op_result(op.execute())

    @node_from(from_name='传送')
    @operation_node(name='移动交互', node_max_retry_times=10)
    def move_and_interact(self) -> OperationRoundResult:
        """
        录像店-柜台 / 布亚斯特城区-录像店营业点：转向正东后前移再交互
        澄辉坪-录像店营业点：传送落点已正对入口，直接交互
        :return:
        """
        if sys.platform != 'darwin' and self.config.transport_point in {
            RandomPlayTransportPoint.POINT_1.value.value,
            RandomPlayTransportPoint.POINT_3.value.value,
        }:
            result = turn_to_angle(self, target_angle=0, turn_status='转向正东')
            if not result.is_success:
                return result
            self.ctx.controller.move_w(press=True, press_time=1, release=True)

        time.sleep(1) # 防止交互无效 issue #2405 #2395 #2328
        self.ctx.controller.interact(press=True, press_time=0.2, release=True)

        return self.round_success(wait=1)

    @node_from(from_name='移动交互')
    @operation_node(name='交互对话', node_max_retry_times=10)
    def handle_interaction_dialog(self) -> OperationRoundResult:
        if sys.platform == 'darwin':
            from zzz_od.operation.gamepad.dialog import GamepadChooseDialogOption

            return self.round_by_op_result(
                GamepadChooseDialogOption(self.ctx, '查看经营状况').execute()
            )
        # 录像店-柜台交互后没有选项对话，直接交给经营画面加载节点
        if self.config.transport_point == RandomPlayTransportPoint.POINT_1.value.value:
            return self.round_success()

        # 录像店营业点交互后的选项对话框，优先选择“查看经营状况”
        area = self.ctx.screen_loader.get_area('影像店营业', '右侧选项区域')
        result = self.round_by_ocr_and_click(self.last_screenshot, '查看经营状况', area=area)
        if result.is_success:
            return self.round_success(status=result.status, wait=1)

        # (布亚斯特城区-录像店营业点)需要推进一次对话框，右侧选项区域才会出现“查看经营状况”
        result = self.round_by_click_area('影像店营业', '对话框标题')
        if result.is_success:
            return self.round_retry(status='继续对话', wait=1)
        return result

    @node_from(from_name='交互对话')
    @node_from(from_name='传送', status=STATUS_MACOS_SHOP_OPEN)
    @operation_node(name='等待经营画面加载', node_max_retry_times=10)
    def wait_run(self) -> OperationRoundResult:
        # 每日首次。点完关闭按钮后回到本节点重判，防止昨日账本残影或未关闭
        result = self.round_by_find_area(self.last_screenshot, '影像店营业', '昨日账本')
        if result.is_success:
            if sys.platform == 'darwin':
                if self._macos_ledger_close_sent:
                    save_shop_frame(self, '影像店营业', '等待账本关闭')
                    return self.round_retry('账本返回已发送，等待经营页面', wait=1)
                result = press_shop_action(self, '影像店营业', '关闭昨日账本')
                if not result.is_success:
                    return result
                self._macos_ledger_close_sent = True
                return self.round_retry(wait=1)
            self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '按钮-关闭')
            return self.round_retry(wait=1)
        if sys.platform == 'darwin':
            if self._macos_business_visible():
                save_shop_frame(self, '影像店营业', '经营主页面')
                return self.round_success()
            area = self.ctx.screen_loader.get_area('影像店营业', '手柄-经营状况页')
            if area is not None and self.round_by_find_area(
                self.last_screenshot, '影像店营业', '手柄-经营状况页',
            ).is_success:
                return self.round_success()
            return self.round_retry('等待手柄经营画面加载', wait=1)
        # 识别到"经营状况"就点击一下以保证在该分支。二次运行时，有极低概率"无人咨询"变成"咨询中"并被默认跳转
        result = self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '经营状况')
        if result.is_success:
            return self.round_success(wait=1)

        return self.round_retry(status='等待经营画面', wait=1)

    @node_from(from_name='等待经营画面加载')
    @operation_node(name='识别营业状态')
    def check_running(self) -> OperationRoundResult:
        if sys.platform == 'darwin':
            save_shop_frame(self, '影像店营业', '识别营业状态')
        result = self.round_by_find_area(self.last_screenshot, '影像店营业', '正在营业')
        if result.is_success:
            return self.round_success(RandomPlayApp.STATUS_ALREADY_RUNNING)
        result = self.round_by_find_area(self.last_screenshot, '影像店营业', '开始营业')
        if result.is_success:
            return self.round_success()

        return self.round_retry(status='等待营业状态', wait=1)

    @node_from(from_name='识别营业状态', status=STATUS_ALREADY_RUNNING)
    @node_from(from_name='点击宣传员入口', success=False)
    @operation_node(name='关闭经营页面')
    def close_business_page(self) -> OperationRoundResult:
        if sys.platform == 'darwin':
            if self.previous_node.name == '点击宣传员入口':
                return self.round_fail(self.previous_node.status or '手柄宣传员入口未完成')
            return press_shop_action(self, '影像店营业', '返回经营页面')
        return self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '返回',
                                                 retry_wait=1)

    @node_from(from_name='识别营业状态')
    @operation_node(name='点击宣传员入口')
    def click_promoter_entry(self) -> OperationRoundResult:
        """
        在经营状况页面 点击代理人的位置
        :return:
        """
        if sys.platform == 'darwin':
            actual = business_card_titles(self)[0]
            candidates = self._macos_promoter_candidates()
            if actual in {item.value.agent_name for item in AgentEnum} | {'邦布18'} and (RANDOM_AGENT_NAME in candidates or actual == candidates[0]):
                self._macos_promoter_ready = True
                return self.round_success()
            return self._macos_open_card(0, '宣传员入口')
        return self.round_by_click_area('影像店营业', '宣传员入口',
                                        retry_wait=1)

    @node_from(from_name='点击宣传员入口')
    @operation_node(name='选择宣传员')
    def choose_promoter(self) -> OperationRoundResult:
        """
        在经营状况页面 点击代理人的位置
        :return:
        """
        if sys.platform == 'darwin':
            return self._macos_choose_promoter()
        result = self.round_by_find_area(self.last_screenshot, '影像店营业', '选择宣传员')
        if not result.is_success:
            if sys.platform == 'darwin':
                return fail_shop_state(self, '影像店营业', '手柄宣传员列表尚未建档')
            return self.round_retry(status=result.status, wait_round_time=1)

        # 已经选择过了 直接返回
        result = self.round_by_find_area(self.last_screenshot, '影像店营业', '换下')
        if result.is_success:
            if sys.platform == 'darwin':
                result = press_shop_action(self, '影像店营业', '返回宣传员列表')
                if result.is_success:
                    self._macos_promoter_ready = True
                return result
            return self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '返回')

        target_agent_name_1 = self.config.agent_name_1
        target_agent_name_2 = self.config.agent_name_2
        dt = self.run_record.get_current_dt()
        idx = (int(dt[-1]) % 2) + 1

        if sys.platform == 'darwin':
            # 选人必须保留原配置；没有焦点证据时不能兜底到第一个人。
            return fail_shop_state(self, '影像店营业',
                f'手柄宣传员焦点尚未建档：{target_agent_name_1} / {target_agent_name_2}，顺位 {idx}'
            )

        if RANDOM_AGENT_NAME in (target_agent_name_1, target_agent_name_2):
            # 随机选择
            self.round_by_click_area('影像店营业', f'宣传员-{idx}', pre_delay=1)
            return self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '确认',
                                                     retry_wait=1)

        area = self.ctx.screen_loader.get_area('影像店营业', '宣传员列表')
        if idx == 1:
            candidates = [target_agent_name_1, target_agent_name_2]
        else:
            candidates = [target_agent_name_2, target_agent_name_1]

        # 依次尝试匹配每个候选代理人（名称 OCR → 头像匹配）
        for agent_name in candidates:
            if self._try_select_agent(agent_name, area):
                return self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '确认',
                                                         retry_wait=1)
            log.info(f'代理人匹配失败: {agent_name}')

        if self.node_retry_times >= 2:
            # 滚动多次仍未找到, 兜底选第一个位置
            log.info('滚动多次仍未找到, 选择默认位置')
            self.round_by_click_area('影像店营业', '宣传员-1')
            return self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '确认',
                                                     retry_wait=1)
        # 向下滚动并重试
        log.info('所有候选代理人匹配失败, 向下滚动重试')
        self.scroll_area('影像店营业', '宣传员列表')
        return self.round_retry(wait=0.5)

    def _try_select_agent(self, agent_name: str, area) -> bool:
        """尝试通过名称 OCR 或头像匹配选择代理人"""
        result = self.round_by_ocr_and_click(self.last_screenshot, agent_name, area=area,
                                             color_range=[(230, 230, 230), (255, 255, 255)])
        if result.is_success:
            return True

        mr = self.get_pos_by_avatar(self.last_screenshot, agent_name)
        if mr is not None:
            self.ctx.controller.click(mr.center)
            return True

        return False

    def get_pos_by_avatar(self, screen: MatLike, target_agent_name: str) -> MatchResult | None:
        """
        根据头像匹配
        @param screen: 游戏画面
        @param target_agent_name: 需要选择的代理人名称
        @return:
        """
        agent: Agent | None = None
        for agent_enum in AgentEnum:
            if agent_enum.value.agent_name == target_agent_name:
                agent = agent_enum.value
                break

        area = self.ctx.screen_loader.get_area('影像店营业', '宣传员列表')
        part = cv2_utils.crop_image_only(screen, area.rect)

        if agent is None:
            return None

        for template_id in agent.template_id_list:
            mr = self.ctx.tm.match_one_by_feature(part, 'predefined_team', f'avatar_{template_id}')
            if mr is None:
                return None

            mr.add_offset(area.left_top)
            return mr

    @node_from(from_name='选择宣传员')
    @operation_node(name='识别录像带主题')
    def check_video_theme(self) -> OperationRoundResult:
        if sys.platform == 'darwin':
            read = read_shop_area(self, '手柄-当日主题')
            if read is None:
                return fail_shop_state(self, '影像店营业', '当日录像带主题区域未配置')
            themes = sorted((matches.max.x, shop_name(text)) for text, matches in read[1].items()
                            if matches.max is not None and shop_name(text) in self._all_video_themes)
            if len(themes) != 3:
                return fail_shop_state(self, '影像店营业', '未完整识别当日三个主题，不补随机主题')
            self._need_video_themes = [name for _, name in themes]
            return self.round_success()
        result = self.round_by_find_area(self.last_screenshot, '影像店营业', '经营状况')
        if not result.is_success:
            return self.round_retry(status=result.status, wait=1)

        areas = [
            self.ctx.screen_loader.get_area('影像店营业', '录像带主题-1'),
            self.ctx.screen_loader.get_area('影像店营业', '录像带主题-2'),
            self.ctx.screen_loader.get_area('影像店营业', '录像带主题-3')
        ]

        target_list = [gt(i, 'game') for i in self._all_video_themes]
        for area in areas:
            part = cv2_utils.crop_image_only(self.last_screenshot, area.rect)
            ocr_result = self.ctx.ocr.run_ocr_single_line(part)

            results = difflib.get_close_matches(ocr_result, target_list, n=1)

            if results:
                idx = target_list.index(results[0])
                self._need_video_themes.append(self._all_video_themes[idx])

        # 识别不到 随便补充到3个主题
        for theme in self._all_video_themes:
            if len(self._need_video_themes) >= 3:
                break
            if theme in self._need_video_themes:
                continue
            self._need_video_themes.append(theme)

        log.info(f'所需主题 {self._need_video_themes}')
        return self.round_success()

    @node_from(from_name='识别录像带主题')
    @operation_node(name='点击录像带入口')
    def click_video_entry(self) -> OperationRoundResult:
        """
        在经营状况页面 点击录像带的位置
        :return:
        """
        if sys.platform == 'darwin':
            return self._macos_open_card(1, '录像带入口')
        return self.round_by_click_area('影像店营业', '录像带入口',
                                        retry_wait=1)

    @node_from(from_name='点击录像带入口')
    @operation_node(name='识别推荐上架')
    def check_recommended(self) -> OperationRoundResult:
        if sys.platform == 'darwin':
            if not self.round_by_find_area(
                self.last_screenshot, '影像店营业', '手柄-录像带列表标题',
            ).is_success:
                return fail_shop_state(self, '影像店营业', '无法确认手柄录像带列表')
            return press_shop_action(self, '影像店营业', '推荐上架')
        result = self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '推荐上架')

        if result.is_success:
            return self.round_success(status=result.status, wait=1)

        return self.round_by_find_area(self.last_screenshot, '影像店营业', '上架筛选', retry_wait=1)

    @node_from(from_name='识别推荐上架', status='上架筛选')
    @node_from(from_name='上架')
    @node_from(from_name='上架', success=False)
    @operation_node(name='上架筛选')
    def click_filter(self) -> OperationRoundResult:
        """
        在录像带画面 点击上架筛选
        :return:
        """
        if self._current_idx >= len(self._need_video_themes):
            if sys.platform == 'darwin':
                self._macos_videos_ready = True
            return self.round_success(status=RandomPlayApp.STATUS_ALL_VIDEO_CHOOSE)

        result = (
            press_shop_action(self, '影像店营业', '上架筛选')
            if sys.platform == 'darwin'
            else self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '上架筛选')
        )
        if result.is_success:
            self._current_idx += 1
            return self.round_success(result.status, wait=1)
        else:
            return self.round_retry(result.status, wait=1)

    @node_from(from_name='上架筛选')
    @operation_node(name='选择主题')
    def choose_theme(self) -> OperationRoundResult:
        """
        选择主题
        :return:
        """
        if sys.platform == 'darwin':
            theme = self._need_video_themes[self._current_idx - 1]
            return fail_shop_state(self, '影像店营业', f'手柄主题筛选焦点尚未建档：{theme}')
        area = self.ctx.screen_loader.get_area('影像店营业', '主题筛选')
        ocr_results = self.ctx.ocr.crop_and_run_ocr(self.last_screenshot, area.rect)

        target_list = [gt(i, 'game') for i in self._all_video_themes]
        current_target = self._need_video_themes[self._current_idx - 1]
        for ocr_str, mrl in ocr_results.items():
            if mrl.max is None:
                continue

            results = difflib.get_close_matches(ocr_str, target_list, n=1)

            if not results:
                continue

            idx = target_list.index(results[0])
            theme = self._all_video_themes[idx]
            if theme != current_target:
                continue

            target_point = area.left_top + mrl.max
            if self.ctx.controller.click(target_point):
                return self.round_success(wait=1)
            else:
                return self.round_retry(wait=0.5)

        # 找不到 往下滑动
        start = area.center
        end = start + Point(0, -100)
        self.ctx.controller.drag_to(start=start, end=end)
        return self.round_retry(status=f'未找到{current_target}', wait=1)

    @node_from(from_name='选择主题')
    @operation_node(name='上架')
    def choose_onshelf(self) -> OperationRoundResult:
        """
        上架
        :return:
        """
        result = self.round_by_find_area(self.last_screenshot, '影像店营业', '下架',)
        if result.is_success:  # 已经上架了
            return self.round_success()

        if sys.platform == 'darwin':
            return press_shop_action(self, '影像店营业', '上架')

        result = self.round_by_find_area(self.last_screenshot, '影像店营业', '上架')
        if not result.is_success:
            return self.round_wait(status=result.status, wait_round_time=1)

        # 这个点击是为了关闭筛选
        click1 = self.round_by_click_area('影像店营业', '上架')
        click2 = self.round_by_click_area('影像店营业', '上架', pre_delay=0.5)

        if click1.is_success and click2.is_success:
            return self.round_wait(wait=1)
        else:
            return self.round_retry(status=click1.status, wait_round_time=1)

    @node_from(from_name='识别推荐上架', status='推荐上架')
    @node_from(from_name='上架筛选', status=STATUS_ALL_VIDEO_CHOOSE)
    @operation_node(name='返回')
    def back(self) -> OperationRoundResult:
        if sys.platform == 'darwin':
            # X 推荐上架实拍直接返回主页面，此时 B 会退出店铺，不能再按。
            if self._macos_business_visible():
                if not self._macos_check_prepared():
                    return fail_shop_state(self, '影像店营业', '主页面未确认人物与三片准备完成')
                return self.round_success()
            if not self.round_by_find_area(
                self.last_screenshot, '影像店营业', '手柄-录像带列表标题',
            ).is_success:
                return fail_shop_state(self, '影像店营业', '推荐上架后页面未识别，未发送返回')
            return press_shop_action(self, '影像店营业', '返回录像带列表')
        result = self.round_by_find_area(self.last_screenshot, '影像店营业', '经营状况')
        if result.is_success:
            return self.round_success()

        return self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '返回',
                                                 retry_wait=1)

    @node_from(from_name='返回')
    @operation_node(name='开始营业')
    def start(self) -> OperationRoundResult:
        if sys.platform == 'darwin':
            if not self._macos_business_visible() or not self._macos_check_prepared():
                return fail_shop_state(self, '影像店营业', '宣传员和录像带未按原流程准备完成，未发送营业')
            return press_shop_action(self, '影像店营业', '开始营业')
        return self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '开始营业',
                                                 retry_wait=1)

    @node_from(from_name='开始营业')
    @node_from(from_name='传送', status=STATUS_MACOS_CONFIRM)
    @operation_node(name='确认营业')
    def confirm_business(self) -> OperationRoundResult:
        if sys.platform == 'darwin':
            if not self._macos_confirm_visible('是否准备营业'):
                return fail_shop_state(self, '影像店营业', '无法确认是否准备营业弹窗和确认焦点')
            save_shop_frame(self, '影像店营业', '确认营业前')
            self.ctx.controller.btn_tap('south')
            return self.round_success(wait=1)
        return self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '开始营业-确认',
                                                 retry_wait=1)

    @node_from(from_name='确认营业')
    @node_from(from_name='传送', status=STATUS_MACOS_STARTED)
    @operation_node(name='营业后确认')
    def confirm(self) -> OperationRoundResult:
        if sys.platform == 'darwin':
            from zzz_od.operation.gamepad.confirmation import (
                confirm_expected_single_dialog,
            )

            return confirm_expected_single_dialog(self)
        return self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '营业后确认',
                                                 retry_wait=1)

    @node_from(from_name='营业后确认')
    @node_from(from_name='关闭经营页面')
    @node_notify(when=NotifyTiming.PREVIOUS_DONE)
    @operation_node(name='返回大世界')
    def back_to_world(self) -> OperationRoundResult:
        if sys.platform == 'darwin':
            if self._macos_business_visible() and self.round_by_find_area(
                self.last_screenshot, '影像店营业', '正在营业',
            ).is_success:
                result = press_shop_action(self, '影像店营业', '返回经营页面')
                if not result.is_success:
                    return result
                return self.round_retry('等待返回大世界', wait=0.5)
            save_shop_frame(self, '影像店营业', '返回大世界')
            return self.round_by_find_area(
                self.last_screenshot, '大世界-普通', '快捷手册', retry_wait=1,
            )
        op = BackToNormalWorld(self.ctx)
        return self.round_by_op_result(op.execute())


def __debug():
    ctx = ZContext()
    ctx.init()
    ctx.run_context.start_running()
    app = RandomPlayApp(ctx)
    app.execute()


if __name__ == '__main__':
    __debug()
