"""先确认输入模式，再用有限启动点击切入原生手柄界面。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, ClassVar

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.operation.operation import Operation
from one_dragon.base.operation.operation_node import operation_node
from one_dragon.utils.log_utils import log

if TYPE_CHECKING:
    from one_dragon.base.controller.macos.macos_bootstrap_pointer import (
        MacBootstrapPointer,
    )
    from one_dragon.base.matcher.match_result import MatchResultList
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class MacBootstrapGameSession(Operation):
    """只准备已打开的会话，成功前必须看见手柄大世界。"""

    SCREEN_NAME: ClassVar[str] = 'Mac启动'

    def __init__(
        self, ctx: ZContext, pointer: MacBootstrapPointer | None = None,
    ) -> None:
        """构造不访问原生窗口，不发送输入；指针在确认触屏路径后才创建。"""
        super().__init__(
            ctx, op_name='准备 Mac 手柄游戏会话', need_check_game_win=False,
            timeout_seconds=35,
        )
        self._injected_pointer: MacBootstrapPointer | None = pointer
        self._pointer: MacBootstrapPointer | None = pointer
        self._sent_actions: set[str] = set()
        self._last_action_time: float = 0
        self._unknown_frames: int = 0
        self._gamepad_confirmed: bool = False
        self._area_ocr: dict[str, dict[str, MatchResultList]] = {}

    def handle_init(self) -> None:
        """每次顶层应用重新识别模式，不沿用上次运行的确认结果。"""
        self._pointer = self._injected_pointer
        self._sent_actions.clear()
        self._last_action_time = 0
        self._unknown_frames = 0
        self._gamepad_confirmed = False
        self._area_ocr.clear()

    def _read_area(self, name: str) -> dict[str, MatchResultList]:
        """只读取平台已建档区域，每轮每个区域最多识别一次。"""
        if name not in self._area_ocr:
            area = self.ctx.screen_loader.get_area(self.SCREEN_NAME, name)
            if area is None:
                raise ValueError(f'缺少 Mac 启动区域：{name}')
            if self.last_screenshot is None:
                return {}
            self._area_ocr[name] = self.ctx.ocr.crop_and_run_ocr(
                self.last_screenshot, area.rect,
            )
        return self._area_ocr[name]

    def _text_rect(self, area_name: str, target: str) -> Rect | None:
        """完整匹配目标文字，返回游戏内容中的坐标。"""
        area = self.ctx.screen_loader.get_area(self.SCREEN_NAME, area_name)
        if area is None:
            raise ValueError(f'缺少 Mac 启动区域：{area_name}')
        for text, matches in self._read_area(area_name).items():
            if target in text.replace(' ', '') and matches.max is not None:
                rect = matches.max.rect
                return Rect(
                    rect.x1 + area.x1, rect.y1 + area.y1,
                    rect.x2 + area.x1, rect.y2 + area.y1,
                )
        return None

    def _has_text(self, area_name: str, target: str) -> bool:
        """检查固定区域是否出现完整目标文字。"""
        return self._text_rect(area_name, target) is not None

    def _area_found(self, name: str) -> bool:
        """模板或文字标识沿用框架匹配，不把无匹配能力的点击区当证据。"""
        return self.round_by_find_area(
            self.last_screenshot, self.SCREEN_NAME, name,
        ).is_success

    def _wait_after_action(self, action: str) -> OperationRoundResult:
        """同一步不连点；五秒仍未变化时明确停止。"""
        if time.time() - self._last_action_time >= 5:
            return self.round_fail(f'{action}后画面没有按预期变化，已停止准备')
        return self.round_wait(f'等待{action}后的新画面', wait=0.4)

    def _send_action(
        self, action: str, *, area_name: str | None = None,
        target: str | None = None, gamepad_key: str | None = None,
    ) -> OperationRoundResult:
        """每个有副作用的步骤最多执行一次，只使用已确认的区域或手柄键。"""
        if not self.ctx.run_context.is_context_running:
            return self.round_fail('准备已暂停或停止，未发送启动输入')
        if action in self._sent_actions:
            return self._wait_after_action(action)
        self._sent_actions.add(action)
        # 画面可能在鼠标恢复前已经更新，不能要求静态 UI 再生成一帧。
        self._last_action_time = time.time()
        try:
            if gamepad_key is not None:
                self.ctx.controller.btn_tap(gamepad_key)
            else:
                if area_name is None:
                    return self.round_fail('启动点击没有指定区域')
                area = self.ctx.screen_loader.get_area(self.SCREEN_NAME, area_name)
                if area is None:
                    return self.round_fail(f'缺少 Mac 启动区域：{area_name}')
                rect = area.rect if target is None else self._text_rect(area_name, target)
                if rect is None:
                    return self.round_fail(f'启动点击未找到目标：{target}')
                if self._pointer is None:
                    from one_dragon.base.controller.macos.macos_bootstrap_pointer import (
                        MacBootstrapPointer,
                    )

                    controller = self.ctx.controller
                    self._pointer = MacBootstrapPointer(
                        controller.window_capture.window,
                        window_capture=controller.window_capture,
                        top_inset_pixels=controller.macos_config.capture_top_inset_pixels,
                        foreground=True,
                    )
                if not self._pointer.click(rect.center.x, rect.center.y):
                    return self.round_fail(f'{action}的定向点击未完成')
        except Exception as error:
            log.error('Mac 启动动作失败：%s', action, exc_info=True)
            return self.round_fail(f'{action}失败：{error}')
        self._unknown_frames = 0
        return self.round_wait(f'已{action}，等待截图确认', wait=0.8)

    @operation_node(
        name='准备手柄会话', is_start_node=True, screenshot_before_round=False,
        timeout_seconds=35,
    )
    def prepare_session(self) -> OperationRoundResult:
        """按当帧证据推进，未知画面等待有限次数后失败。"""
        if not self.ctx.is_game_window_ready:
            return self.round_fail('未连接 Mac 游戏窗口，请先在 PlayCover 中打开游戏')
        if not self.ctx.controller.gamepad.is_connected:
            return self.round_fail('Mac 手柄连接不可用，未执行启动点击')
        self.screenshot()
        if self.last_screenshot is None:
            return self.round_fail('Mac 游戏截图不可用，未执行启动点击')
        if self.last_screenshot.shape != (1080, 1920, 3):
            return self.round_fail('Mac 启动截图不是标准 1920×1080，未执行启动点击')
        if self.last_screenshot_time <= self._last_action_time:
            return self._wait_after_action('启动动作')
        self._area_ocr.clear()
        try:
            return self._prepare_from_screen()
        except ValueError as error:
            return self.round_fail(str(error))

    def _prepare_from_screen(self) -> OperationRoundResult:
        """只处理已建档的触屏设置路径和手柄返回路径。"""
        if self.round_by_find_area(
            self.last_screenshot, '大世界-普通', '快捷手册',
        ).is_success:
            if self._has_text('大世界-手柄提示', 'LT'):
                return self.round_success('已截图确认手柄大世界')

        if self._area_found('大世界-触屏操作') and self._area_found('大世界-菜单'):
            return self._send_action('打开触屏菜单', area_name='大世界-菜单')

        if self._has_text('输入-UI布局', 'UI布局'):
            if self._has_text('输入-当前布局', '手柄'):
                self._gamepad_confirmed = True
                return self._send_action('返回设置上一级', gamepad_key='east')
            if self._has_text('输入-当前布局', '触屏'):
                if self._has_text('输入-布局选项', '手柄'):
                    return self._send_action(
                        '选择手柄布局', area_name='输入-布局选项', target='手柄',
                    )
                if self._has_text('输入-布局选项', '触屏'):
                    return self.round_fail('UI 布局没有手柄选项，请检查手柄是否被游戏识别')
                return self._send_action(
                    '展开UI布局', area_name='输入-当前布局', target='触屏',
                )

        if self._has_text('设置-侧栏', '声音/触觉'):
            if (
                self._gamepad_confirmed or self._has_text('手柄-返回提示', 'B')
                or self._has_text('设置-侧栏', '手柄按键')
            ):
                self._gamepad_confirmed = True
                return self._send_action('返回设置上一级', gamepad_key='east')
            return self._send_action('打开输入设置', area_name='设置-输入', target='输入')

        if self._has_text('菜单-底部', '仓库') and self._has_text('菜单-底部', '更多'):
            if self._gamepad_confirmed or self._has_text('手柄-返回提示', 'B'):
                self._gamepad_confirmed = True
                return self._send_action('返回大世界', gamepad_key='east')
            return self._send_action('打开触屏设置', area_name='菜单-设置')

        self._unknown_frames += 1
        if self._unknown_frames >= 8:
            return self.round_fail('未识别到已支持的 Mac 启动画面，已停止且未猜测点击')
        return self.round_wait('等待已建档的 Mac 启动画面', wait=0.4)
