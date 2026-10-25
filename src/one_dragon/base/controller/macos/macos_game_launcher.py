"""只在游戏未运行时启动已安装应用，并限时等待可绑定的唯一窗口。"""

from __future__ import annotations

import math
import plistlib
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from one_dragon.base.controller.macos.main_thread_dispatch import perform_on_main_thread

if TYPE_CHECKING:
    from one_dragon.base.controller.macos.macos_window_capture import (
        MacWindow,
        MacWindowCapture,
    )


class MacGameLaunchError(RuntimeError):
    """应用身份、启动请求或窗口等待失败。"""


def _launch_api() -> tuple[Any, Any]:
    """只在需要查询进程或启动应用时加载原生框架。"""
    import AppKit
    import Foundation

    return AppKit, Foundation


def select_game_window(windows: list[MacWindow], window_title: str) -> MacWindow | None:
    """保留严格标题与唯一最大正常窗口的既有选择规则。"""
    if window_title:
        candidates = [window for window in windows if window.title == window_title]
    else:
        candidates = [window for window in windows if window.width >= 320 and window.height >= 180]
        if candidates:
            largest = max(window.width * window.height for window in candidates)
            candidates = [window for window in candidates if window.width * window.height == largest]
    if len(candidates) > 1:
        raise MacGameLaunchError('无法确定唯一游戏窗口，请配置唯一窗口标题')
    if not candidates:
        return None
    window = candidates[0]
    if window.width < 320 or window.height < 180:
        raise MacGameLaunchError('目标窗口尺寸过小，请打开正常尺寸的游戏窗口')
    return window


class MacGameLauncher:
    """不创建采集或输入服务，也不重启、关闭已有游戏进程。"""

    def __init__(
        self, window_capture: MacWindowCapture, bundle_id: str, app_path: str = '',
        window_title: str = '', timeout_seconds: float = 45,
    ) -> None:
        if not bundle_id.strip() or '/' in bundle_id or '\\' in bundle_id:
            raise ValueError('启动游戏必须配置有效的应用标识')
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 120:
            raise ValueError('启动游戏等待时间必须在 0 到 120 秒之间')
        self.window_capture: MacWindowCapture = window_capture
        self.bundle_id: str = bundle_id
        self.app_path: str = app_path
        self.window_title: str = window_title
        self.timeout_seconds: float = timeout_seconds
        self.started_game: bool = False
        self._launch_requested: bool = False
        self._launch_error: str | None = None
        self._expected_pid: int | None = None
        self._request_generation: int = 0

    def _find_window(self) -> MacWindow | None:
        """每轮重新枚举，不缓存窗口 ID 或位置。"""
        return select_game_window(self.window_capture.list_windows(self.bundle_id), self.window_title)

    def _running_process_ids(self) -> list[int]:
        """按明确应用标识查询进程，不使用名称模糊匹配。"""
        appkit, _ = _launch_api()
        apps = appkit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(self.bundle_id)
        return sorted({
            int(app.processIdentifier()) for app in apps
            if app.bundleIdentifier() == self.bundle_id and not app.isTerminated()
        })

    def _resolve_app_path(self) -> Path:
        """只接受身份匹配且可执行文件位于包内的已安装应用。"""
        path = Path(self.app_path).expanduser() if self.app_path.strip() else (
            Path.home() / 'Library' / 'Containers' / 'io.playcover.PlayCover'
            / 'Applications' / f'{self.bundle_id}.app'
        )
        if not path.is_absolute() or path.suffix != '.app' or not path.is_dir():
            raise MacGameLaunchError('未找到已安装的 PlayCover 游戏应用，请在账户设置填写完整 .app 路径')
        path = path.resolve()
        info_path = path / 'Info.plist'
        macos_layout = False
        if not info_path.is_file():
            info_path = path / 'Contents' / 'Info.plist'
            macos_layout = True
        try:
            with info_path.open('rb') as stream:
                info = plistlib.load(stream)
        except (OSError, ValueError, plistlib.InvalidFileException) as error:
            raise MacGameLaunchError(f'无法读取游戏应用信息：{error}') from error
        if info.get('CFBundleIdentifier') != self.bundle_id:
            raise MacGameLaunchError('游戏应用路径中的 Bundle ID 与配置不一致，未启动应用')
        executable_name = info.get('CFBundleExecutable', '')
        if not isinstance(executable_name, str) or not executable_name or Path(executable_name).name != executable_name:
            raise MacGameLaunchError('游戏应用缺少明确的包内可执行文件')
        executable = path / 'Contents' / 'MacOS' / executable_name if macos_layout else path / executable_name
        if not executable.is_file() or not executable.resolve().is_relative_to(path):
            raise MacGameLaunchError('游戏应用可执行文件缺失或不在已安装应用内')
        return path

    def _request_launch(self, path: Path, deadline: float) -> None:
        """主线程只发送一次系统启动请求，默认不激活、不替换已有实例。"""
        appkit, foundation = _launch_api()
        generation = self._request_generation

        def completed(app: Any, error: Any) -> None:
            """异步回调仅记录身份或错误，不操作游戏画面。"""
            if generation != self._request_generation:
                return
            if error is not None:
                self._launch_error = str(error.localizedDescription())
            elif app is None or app.bundleIdentifier() != self.bundle_id:
                self._launch_error = '系统返回的启动进程与游戏应用标识不一致'
            else:
                self._expected_pid = int(app.processIdentifier())

        def launch() -> None:
            """派发期间若游戏已被启动，则直接复用，不再发启动请求。"""
            pids = self._running_process_ids()
            if len(pids) > 1:
                raise MacGameLaunchError('存在多个同标识游戏进程，未启动或重启任何应用')
            if pids:
                self._expected_pid = pids[0]
                return
            config = appkit.NSWorkspaceOpenConfiguration.configuration()
            config.setActivates_(False)
            config.setCreatesNewApplicationInstance_(False)
            config.setAllowsRunningApplicationSubstitution_(False)
            config.setPromptsUserIfNeeded_(False)
            config.setAddsToRecentItems_(False)
            self._launch_requested = True
            appkit.NSWorkspace.sharedWorkspace().openApplicationAtURL_configuration_completionHandler_(
                foundation.NSURL.fileURLWithPath_(str(path)), config, completed,
            )

        perform_on_main_thread(launch, min(deadline, time.monotonic() + 1), operation_name='启动游戏')

    @staticmethod
    def _wait_tick() -> None:
        """命令行主线程处理 Cocoa 事件；GUI 工作线程只短暂等待。"""
        if threading.current_thread() is threading.main_thread():
            _, foundation = _launch_api()
            foundation.NSRunLoop.currentRunLoop().runUntilDate_(
                foundation.NSDate.dateWithTimeIntervalSinceNow_(0.1),
            )
        else:
            time.sleep(0.1)

    def ensure_window(self) -> MacWindow:
        """已有进程只等待；无进程才启动一次，失败不关闭或重启应用。"""
        self.started_game = False
        self._request_generation += 1
        self._launch_requested = False
        self._launch_error = None
        self._expected_pid = None
        deadline = time.monotonic() + self.timeout_seconds
        window = self._find_window()
        if window is not None:
            return window
        pids = self._running_process_ids()
        if len(pids) > 1:
            raise MacGameLaunchError('存在多个同标识游戏进程，未启动或重启任何应用')
        if pids:
            self._expected_pid = pids[0]
        else:
            self._request_launch(self._resolve_app_path(), deadline)
        while time.monotonic() < deadline:
            if self._launch_error is not None:
                raise MacGameLaunchError(f'启动游戏失败：{self._launch_error}')
            window = self._find_window()
            if window is not None:
                if self._expected_pid is not None and window.pid != self._expected_pid:
                    raise MacGameLaunchError('启动后窗口所属进程已改变，请重新开始准备游戏')
                self.started_game = self._launch_requested
                return window
            self._wait_tick()
        raise MacGameLaunchError(
            f'等待唯一游戏窗口超时（{self.timeout_seconds:g}秒）；已有或刚启动的应用保持运行，未重复启动'
        )
