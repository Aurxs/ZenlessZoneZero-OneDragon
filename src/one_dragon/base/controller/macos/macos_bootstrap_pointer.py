"""启动阶段向明确绑定的 Mac 游戏窗口投递有限点击。"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any

from one_dragon.base.controller.macos.macos_window_capture import (
    MacCaptureError,
    MacWindowCapture,
    _native_api,
)
from one_dragon.base.controller.macos.main_thread_dispatch import (
    MacMainThreadError,
    perform_on_main_thread,
)
from one_dragon.utils.log_utils import log

if TYPE_CHECKING:
    from collections.abc import Callable

    from one_dragon.base.controller.macos.macos_window_capture import MacWindow


class MacBootstrapError(MacCaptureError):
    """启动点击的权限、窗口绑定或坐标检查失败。"""


def _foreground_api() -> Any:
    """只有明确开启前台启动点击时才加载 AppKit。"""
    import AppKit

    return AppKit


@dataclass(frozen=True)
class MacBootstrapWindow:
    """本次读取的窗口身份、全局逻辑点边界与像素缩放比例。"""

    bundle_id: str
    pid: int
    window_id: int
    left: float
    top: float
    width: float
    height: float
    pixels_per_point: float
    on_screen: bool = True


@dataclass(frozen=True)
class MacForegroundSnapshot:
    """主线程一次读取的活动状态，工作线程不保留可变的 AppKit 进程对象。"""

    target_pid: int
    target_bundle_id: str | None
    target_active: bool
    current_pid: int | None
    current_bundle_id: str | None


def _validate_binding(window: MacWindow, top_inset_pixels: int) -> None:
    """拒绝不完整的窗口身份和未经明确配置的裁剪值。"""
    if not isinstance(window.bundle_id, str) or not window.bundle_id.strip():
        raise ValueError('启动点击必须明确绑定 bundle ID')
    if (
        type(window.pid) is not int
        or window.pid <= 0
        or type(window.window_id) is not int
        or window.window_id <= 0
    ):
        raise ValueError('启动点击必须明确绑定有效 PID 和窗口 ID')
    if type(top_inset_pixels) is not int or top_inset_pixels < 0:
        raise ValueError('顶部标题栏像素必须是非负整数')


def game_point_to_screen(
    window: MacWindow,
    current: MacBootstrapWindow,
    x: float,
    y: float,
    *,
    top_inset_pixels: int = 0,
) -> tuple[float, float]:
    """把标准游戏内容坐标换成当前窗口内的全局逻辑点，拒绝猜测裁剪。"""
    _validate_binding(window, top_inset_pixels)
    if (current.bundle_id, current.pid, current.window_id) != (
        window.bundle_id,
        window.pid,
        window.window_id,
    ):
        raise MacBootstrapError('目标窗口身份已改变，需要重新枚举并绑定窗口')
    if not current.on_screen:
        raise MacBootstrapError('目标窗口当前不在屏幕上，不能投递启动点击')
    if (
        not all(
            math.isfinite(value)
            for value in (
                current.left,
                current.top,
                current.width,
                current.height,
                current.pixels_per_point,
            )
        )
        or min(current.width, current.height, current.pixels_per_point) <= 0
    ):
        raise MacBootstrapError('目标窗口边界或像素缩放比例无效')
    if not (math.isfinite(x) and math.isfinite(y) and 0 <= x < 1920 and 0 <= y < 1080):
        raise MacBootstrapError('启动点击坐标必须在 1920×1080 游戏内容范围内')

    top_inset_points = top_inset_pixels / current.pixels_per_point
    content_height = current.height - top_inset_points
    if content_height <= 0 or not math.isclose(
        current.width / content_height, 16 / 9, rel_tol=0.002
    ):
        raise MacBootstrapError(
            '目标窗口去除已配置标题栏后不是 16:9，不能猜测游戏内容区'
        )
    point = (
        current.left + x / 1920 * current.width,
        current.top + top_inset_points + y / 1080 * content_height,
    )
    if not (
        current.left <= point[0] < current.left + current.width
        and current.top + top_inset_points <= point[1] < current.top + current.height
    ):
        raise MacBootstrapError('换算后的启动点击超出当前游戏内容区')
    return point


class MacBootstrapPointer:
    """只供启动 Operation 使用，不接管普通控制器的坐标操作。"""

    def __init__(
        self,
        window: MacWindow,
        *,
        top_inset_pixels: int = 0,
        window_capture: MacWindowCapture | None = None,
        foreground: bool = False,
    ) -> None:
        """绑定已选定的窗口；构造时不加载原生框架或投递输入。"""
        _validate_binding(window, top_inset_pixels)
        if type(foreground) is not bool:
            raise ValueError('前台启动点击选项必须是布尔值')
        self._window: MacWindow = window
        self._top_inset_pixels: int = top_inset_pixels
        self._foreground: bool = foreground
        self._capture: MacWindowCapture = (
            window_capture if window_capture is not None else MacWindowCapture()
        )
        self._lock: threading.Lock = threading.Lock()

    def _read_window(self) -> MacBootstrapWindow:
        """每次从 SCK 和 CGWindowList 重新核对身份、屏幕位置与完整尺寸。"""
        _, _, _, quartz, sck, _ = _native_api()
        selected_windows: list[Any] = []
        for candidate in self._capture._shareable_windows():
            app = candidate.owningApplication()
            if (
                app is not None
                and app.bundleIdentifier() == self._window.bundle_id
                and int(app.processID()) == self._window.pid
                and int(candidate.windowID()) == self._window.window_id
            ):
                selected_windows.append(candidate)
        if not selected_windows:
            raise MacBootstrapError('目标窗口已消失或重建，需要重新枚举并绑定窗口')
        if len(selected_windows) != 1:
            raise MacBootstrapError('SCK 中没有唯一匹配的目标窗口，未发送启动点击')
        selected = selected_windows[0]
        entries = quartz.CGWindowListCopyWindowInfo(
            quartz.kCGWindowListOptionIncludingWindow,
            self._window.window_id,
        )
        entries = [
            entry
            for entry in (entries or [])
            if (
                entry.get(quartz.kCGWindowNumber) == self._window.window_id
                and entry.get(quartz.kCGWindowOwnerPID) == self._window.pid
            )
        ]
        if len(entries) != 1:
            raise MacBootstrapError('CGWindowList 中没有唯一匹配的目标窗口')
        entry = entries[0]
        if (
            not selected.isOnScreen()
            or not entry.get(quartz.kCGWindowIsOnscreen, False)
            or entry.get(quartz.kCGWindowLayer, -1) != 0
        ):
            raise MacBootstrapError(
                '目标窗口未显示或不是普通游戏窗口，不能投递启动点击'
            )
        bounds = entry.get(quartz.kCGWindowBounds, {})
        coordinates = tuple(
            float(bounds.get(key, math.nan)) for key in ('X', 'Y', 'Width', 'Height')
        )
        frame = selected.frame()
        sck_coordinates = (
            frame.origin.x,
            frame.origin.y,
            frame.size.width,
            frame.size.height,
        )
        if not all(
            math.isclose(cg, sc, rel_tol=0, abs_tol=0.5)
            for cg, sc in zip(coordinates, sck_coordinates, strict=True)
        ):
            raise MacBootstrapError(
                '窗口位置在读取期间改变或两个来源不一致，请重新截图后重试'
            )
        content_filter = sck.SCContentFilter.alloc().initWithDesktopIndependentWindow_(
            selected
        )
        content = content_filter.contentRect()
        if not (
            math.isclose(content.size.width, frame.size.width, rel_tol=0, abs_tol=0.5)
            and math.isclose(
                content.size.height, frame.size.height, rel_tol=0, abs_tol=0.5
            )
        ):
            raise MacBootstrapError(
                '采集内容区与完整窗口尺寸不同，不能猜测启动点击偏移'
            )
        return MacBootstrapWindow(
            self._window.bundle_id,
            self._window.pid,
            self._window.window_id,
            *coordinates,
            float(content_filter.pointPixelScale()),
        )

    def resolve_point(self, x: float, y: float) -> tuple[float, float]:
        """只读预检当前窗口坐标；不检查投递权限，也不发送事件。"""
        return game_point_to_screen(
            self._window,
            self._read_window(),
            x,
            y,
            top_inset_pixels=self._top_inset_pixels,
        )

    def click(self, x: float, y: float, *, press_seconds: float = 0.05) -> bool:
        """投递一次左键点击；前台模式短暂占用鼠标，响应仍须截图确认。"""
        if not math.isfinite(press_seconds) or not 0 <= press_seconds <= 0.25:
            raise ValueError('启动点击按住时间必须在 0 到 0.25 秒之间')
        if self._foreground and not 0.05 <= press_seconds <= 0.1:
            raise ValueError('前台启动点击按住时间必须在 0.05 到 0.1 秒之间')
        with self._lock:
            _, _, _, quartz, _, _ = _native_api()
            if not quartz.CGPreflightPostEventAccess():
                raise MacBootstrapError(
                    '当前进程缺少辅助功能或事件投递权限，未发送启动点击'
                )
            if self._foreground:
                return self._click_foreground(quartz, x, y, press_seconds)
            point = self.resolve_point(x, y)
            events = self._create_mouse_events(quartz, point)
            try:
                quartz.CGEventPostToPid(self._window.pid, events[0])
                time.sleep(press_seconds)
            finally:
                quartz.CGEventPostToPid(self._window.pid, events[1])
            return True

    def _create_mouse_events(
        self, quartz: Any, point: tuple[float, float],
    ) -> tuple[Any, Any]:
        """先完整创建按下和松开事件，失败时不发送半次点击。"""
        source = quartz.CGEventSourceCreate(quartz.kCGEventSourceStatePrivate)
        if source is None:
            raise MacBootstrapError('无法创建独立的启动点击事件源')
        events = tuple(
            quartz.CGEventCreateMouseEvent(
                source, event_type, point, quartz.kCGMouseButtonLeft,
            )
            for event_type in (quartz.kCGEventLeftMouseDown, quartz.kCGEventLeftMouseUp)
        )
        if any(event is None for event in events):
            raise MacBootstrapError('无法创建启动点击的按下与松开事件，未发送点击')
        for event in events:
            quartz.CGEventSetFlags(event, 0)
            quartz.CGEventSetIntegerValueField(event, quartz.kCGMouseEventClickState, 1)
            quartz.CGEventSetIntegerValueField(
                event, quartz.kCGMouseEventWindowUnderMousePointer, self._window.window_id,
            )
            quartz.CGEventSetIntegerValueField(
                event, quartz.kCGMouseEventWindowUnderMousePointerThatCanHandleThisEvent,
                self._window.window_id,
            )
        return events[0], events[1]

    @staticmethod
    def _cursor_position(quartz: Any) -> tuple[float, float]:
        """读取实际光标位置；无法确认时不能覆盖用户位置。"""
        event = quartz.CGEventCreate(None)
        if event is None:
            raise MacBootstrapError('无法读取当前鼠标位置，未执行前台启动点击')
        point = quartz.CGEventGetLocation(event)
        position = (float(point.x), float(point.y))
        if not all(math.isfinite(value) for value in position):
            raise MacBootstrapError('当前鼠标位置无效，未执行前台启动点击')
        return position

    @staticmethod
    def _warp_cursor(quartz: Any, point: tuple[float, float]) -> None:
        """移动失败时停止，不在不明确的位置继续点击。"""
        result = quartz.CGWarpMouseCursorPosition(point)
        if result is not None and result != 0:
            raise MacBootstrapError(f'移动启动点击鼠标位置失败：{result}')

    def _foreground_snapshot(
        self, appkit: Any, target_pid: int, deadline: float | None = None,
    ) -> MacForegroundSnapshot:
        """在主线程重新获取进程对象并读取状态，避免后台线程读取旧活动属性。"""
        snapshots: list[MacForegroundSnapshot] = []

        def read() -> None:
            """所有动态 AppKit 属性都在同一次主线程回调里读取。"""
            target = appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_(target_pid)
            current = appkit.NSWorkspace.sharedWorkspace().frontmostApplication()
            snapshots.append(MacForegroundSnapshot(
                target_pid,
                target.bundleIdentifier() if target is not None else None,
                bool(target is not None and target.isActive()),
                int(current.processIdentifier()) if current is not None else None,
                current.bundleIdentifier() if current is not None else None,
            ))

        self._perform_on_main_thread(read, deadline if deadline is not None else time.monotonic() + 1)
        if not snapshots:
            raise MacBootstrapError('主线程未返回前台状态，未发送启动点击')
        return snapshots[0]

    def _is_game_foreground(self, appkit: Any) -> bool:
        """每次使用主线程的新状态，同时确认游戏应用身份和实际前台 PID。"""
        state = self._foreground_snapshot(appkit, self._window.pid)
        return bool(
            state.target_bundle_id == self._window.bundle_id and state.target_active
            and state.current_pid == self._window.pid
        )

    @staticmethod
    def _perform_on_main_thread(action: Callable[[], None], deadline: float) -> None:
        """GUI 工作线程只等待剩余预算，超时回调不能稍后再抢焦点。"""
        try:
            perform_on_main_thread(action, deadline, operation_name='激活游戏')
        except MacMainThreadError as error:
            raise MacBootstrapError(str(error)) from error

    def _activate_application(
        self, appkit: Any, target_pid: int, target_bundle_id: str | None,
        expected_current_pid: int | None,
    ) -> bool:
        """直接请求无效时，对同一已运行应用单次请求打开，仍核对原 PID。"""
        deadline = time.monotonic() + 1
        errors: list[str] = []

        def request(use_workspace: bool) -> None:
            """主线程获取新目标，用户切走或目标重建后不再抢焦点。"""
            target = appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_(target_pid)
            workspace = appkit.NSWorkspace.sharedWorkspace()
            current = workspace.frontmostApplication()
            current_pid = int(current.processIdentifier()) if current is not None else None
            if target is None or target.bundleIdentifier() != target_bundle_id:
                errors.append('绑定的应用进程已退出或身份改变')
                return
            if current_pid not in (expected_current_pid, target_pid):
                return
            if use_workspace:
                url = target.bundleURL()
                if url is None:
                    errors.append('绑定的应用没有可用于激活的应用地址')
                    return
                configuration = appkit.NSWorkspaceOpenConfiguration.configuration()
                configuration.setActivates_(True)
                configuration.setCreatesNewApplicationInstance_(False)
                configuration.setAllowsRunningApplicationSubstitution_(False)
                configuration.setPromptsUserIfNeeded_(False)
                configuration.setAddsToRecentItems_(False)

                def completed(app: Any, error: Any) -> None:
                    """打开已有应用的完成结果不得指向新 PID。"""
                    if error is not None:
                        errors.append('系统拒绝激活已有应用')
                    elif app is None or int(app.processIdentifier()) != target_pid:
                        errors.append('系统激活返回的 PID 与绑定进程不一致')

                workspace.openApplicationAtURL_configuration_completionHandler_(url, configuration, completed)
                log.info('Mac 前台请求 mode=workspace target_pid=%s current_pid=%s', target_pid, current_pid)
                return
            application = appkit.NSApplication.sharedApplication()
            yield_activation = getattr(application, 'yieldActivationToApplication_', None)
            if application.isActive() and callable(yield_activation):
                yield_activation(target)
            accepted = target.activateWithOptions_(appkit.NSApplicationActivateIgnoringOtherApps)
            log.info(
                'Mac 前台请求 mode=direct target_pid=%s current_pid=%s accepted=%s',
                target_pid, current_pid, bool(accepted),
            )

        last_state: MacForegroundSnapshot | None = None
        for use_workspace in (False, True):
            if time.monotonic() >= deadline:
                break
            self._perform_on_main_thread(partial(request, use_workspace), deadline)
            phase_deadline = deadline if use_workspace else min(deadline, time.monotonic() + 0.35)
            while time.monotonic() < phase_deadline:
                last_state = self._foreground_snapshot(appkit, target_pid, deadline)
                if errors:
                    raise MacBootstrapError(errors[0])
                if (
                    last_state.target_bundle_id == target_bundle_id and last_state.target_active
                    and last_state.current_pid == target_pid
                ):
                    return True
                if last_state.current_pid not in (expected_current_pid, target_pid):
                    log.warning(
                        'Mac 激活期间前台改变 target_pid=%s current_pid=%s target_active=%s',
                        target_pid, last_state.current_pid, last_state.target_active,
                    )
                    return False
                time.sleep(0.02)
        if last_state is not None:
            log.warning(
                'Mac 前台确认失败 target_pid=%s current_pid=%s target_active=%s',
                target_pid, last_state.current_pid, last_state.target_active,
            )
        return False

    def _click_foreground(
        self, quartz: Any, x: float, y: float, press_seconds: float,
    ) -> bool:
        """准确激活目标后单击一次，用户介入时不覆盖其焦点或鼠标位置。"""
        appkit = _foreground_api()
        previous = self._foreground_snapshot(appkit, self._window.pid)
        previous_cursor = self._cursor_position(quartz)
        if previous.target_bundle_id != self._window.bundle_id:
            raise MacBootstrapError('无法找到绑定的游戏进程，未执行前台启动点击')
        point: tuple[float, float] | None = None
        warped = False
        try:
            if not previous.target_active or previous.current_pid != self._window.pid:
                if not self._activate_application(
                    appkit, self._window.pid, self._window.bundle_id, previous.current_pid,
                ):
                    raise MacBootstrapError('游戏进程未成为前台应用，未执行启动点击')
            if not self._is_game_foreground(appkit):
                raise MacBootstrapError('游戏进程未成为前台应用，未执行启动点击')

            # 激活可能改变窗口位置，必须在激活后重新枚举并换算。
            point = self.resolve_point(x, y)
            events = self._create_mouse_events(quartz, point)
            if not self._is_game_foreground(appkit):
                raise MacBootstrapError('前台应用已改变，未执行启动点击')
            warped = True
            self._warp_cursor(quartz, point)
            time.sleep(0.05)
            if not self._is_game_foreground(appkit):
                raise MacBootstrapError('前台应用已改变，未执行启动点击')
            if math.dist(self._cursor_position(quartz), point) > 2:
                raise MacBootstrapError('用户已移动鼠标，未执行启动点击')
            if math.dist(self.resolve_point(x, y), point) > 0.5:
                raise MacBootstrapError('窗口位置已改变，未执行启动点击')
            if not quartz.CGPreflightPostEventAccess():
                raise MacBootstrapError('事件投递权限已失效，未发送启动点击')
            try:
                quartz.CGEventPost(quartz.kCGHIDEventTap, events[0])
                time.sleep(press_seconds)
            finally:
                quartz.CGEventPost(quartz.kCGHIDEventTap, events[1])
            time.sleep(0.15)
            return True
        finally:
            try:
                if warped and point is not None and math.dist(self._cursor_position(quartz), point) <= 2:
                    self._warp_cursor(quartz, previous_cursor)
            finally:
                if (
                    previous.current_pid is not None
                    and previous.current_pid != self._window.pid
                    and self._is_game_foreground(appkit)
                ):
                    restored = self._activate_application(
                        appkit, previous.current_pid, previous.current_bundle_id, self._window.pid,
                    )
                    if not restored and self._is_game_foreground(appkit):
                        raise MacBootstrapError('启动点击结束，但无法恢复此前活动的应用')
