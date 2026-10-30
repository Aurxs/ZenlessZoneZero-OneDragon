"""组合手柄输入与窗口采集，不导入或继承 Windows 控制器。"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from math import isfinite
from typing import TYPE_CHECKING

from one_dragon.base.controller.controller_base import (
    ControllerBase,
    ScreenshotWithTime,
)
from one_dragon.base.controller.gamepad_input import GamepadState, normalize_gamepad_key
from one_dragon.utils import cv2_utils
from one_dragon.utils.log_utils import log
from zzz_od.const import game_const
from zzz_od.controller.macos_battle_input_guard import MacBattleInputScope

if TYPE_CHECKING:
    from cv2.typing import MatLike

    from one_dragon.base.controller.drag_timing import DragTiming
    from one_dragon.base.controller.gamepad_input import GamepadInput, GamepadSide
    from one_dragon.base.controller.macos.macos_game_launcher import MacGameLauncher
    from one_dragon.base.controller.macos.macos_window_capture import MacWindowCapture
    from one_dragon.base.controller.macos.sck_frame_converter import CapturedFrame
    from one_dragon.base.geometry.point import Point
    from zzz_od.config.game_config import GameConfig
    from zzz_od.config.macos_config import MacOsConfig


class ZMacController(ControllerBase):
    """保留业务动作名称，全部输入经手柄兼容层执行。"""

    def __init__(
        self,
        game_config: GameConfig,
        macos_config: MacOsConfig,
        standard_width: int = 1920,
        standard_height: int = 1080,
        gamepad: GamepadInput | None = None,
        window_capture: MacWindowCapture | None = None,
        game_launcher: MacGameLauncher | None = None,
    ) -> None:
        """只构造服务，开始运行前才连接输入和申请窗口采集。"""
        super().__init__(max_screenshot_cnt=10)
        if (standard_width, standard_height) != (1920, 1080):
            raise ValueError('Mac 控制器目前只输出 1920×1080 画面')
        if not macos_config.bundle_id.strip():
            raise ValueError('请配置 PlayCover 客户端的 Bundle ID')
        if not isinstance(macos_config.capture_fps, int) or not 1 <= macos_config.capture_fps <= 60:
            raise ValueError('窗口采集帧率必须为 1 到 60 的整数')
        if not isfinite(macos_config.max_frame_age_seconds) or macos_config.max_frame_age_seconds <= 0:
            raise ValueError('最大帧龄必须为有限正数')
        self.game_config: GameConfig = game_config
        self.macos_config: MacOsConfig = macos_config
        self.standard_width: int = standard_width
        self.standard_height: int = standard_height
        self.action_keys: dict[str, str] = game_config.get_action_keys('xbox')
        self.gamepad_action_keys: dict[str, list[str]] = game_config.get_gamepad_action_keys('xbox')
        for key in self.action_keys.values():
            normalize_gamepad_key(key)
        for keys in self.gamepad_action_keys.values():
            for key in keys:
                normalize_gamepad_key(key)

        if gamepad is None:
            from one_dragon.base.controller.macos.ojd_gamepad_client import (
                OjdGamepadClient,
            )

            gamepad = OjdGamepadClient(
                ojd_path=macos_config.ojd_cli_path,
                key_press_time=game_config.xbox_key_press_time,
                auto_start=macos_config.ojd_auto_start,
            )
        if window_capture is None:
            from one_dragon.base.controller.macos.macos_window_capture import (
                MacWindowCapture,
            )

            window_capture = MacWindowCapture()
        self.gamepad: GamepadInput = gamepad
        self.window_capture: MacWindowCapture = window_capture
        if game_launcher is None:
            from one_dragon.base.controller.macos.macos_game_launcher import (
                MacGameLauncher,
            )

            game_launcher = MacGameLauncher(
                window_capture, macos_config.bundle_id, app_path=macos_config.app_path,
                window_title=macos_config.window_title,
                timeout_seconds=macos_config.launch_timeout_seconds,
            )
        self.game_launcher: MacGameLauncher = game_launcher
        self._started_game_this_run: bool = False
        self.is_moving: bool = False
        self._input_paused: bool = True
        self._monitor_stop: threading.Event | None = None
        self._monitor_thread: threading.Thread | None = None
        self._battle_input_scope: MacBattleInputScope | None = None
        self.run_generation: int = 0

    @property
    def battle_input_blocked(self) -> bool:
        """本场战斗标识消失后保持阻断，供业务流程停止自动战斗。"""
        scope = self._battle_input_scope
        return scope is not None and scope.blocked

    def begin_battle_input_scope(self, hud_check: Callable[[MatLike], bool]) -> None:
        """显式开启单场输入限制，最新帧不在战斗时不放行。"""
        if self._battle_input_scope is not None:
            raise RuntimeError('请先结束上一场战斗输入范围')
        self._battle_input_scope = MacBattleInputScope(hud_check)
        try:
            self.gamepad.reset()
            if not self._require_input_ready():
                raise RuntimeError('当前未识别到战斗标识，未放行 Mac 战斗输入')
        except BaseException:
            try:
                self.pause_input()
            finally:
                self._battle_input_scope = None
            raise

    def refresh_battle_input_scope(self) -> bool:
        """业务停止策略后显式复核 HUD；仅战斗恢复时才恢复输入。"""
        scope = self._battle_input_scope
        if scope is None:
            raise RuntimeError('尚未开启战斗输入范围')
        try:
            allowed = scope.refresh(self._require_fresh_frame())
        except Exception:
            self.pause_input()
            raise
        if not allowed:
            self.pause_input()
            return False
        self.resume_input()
        return True

    def end_battle_input_scope(self) -> None:
        """业务先停止战斗策略，再退出限制；菜单动作仍须显式恢复输入。"""
        self.pause_input()
        self._battle_input_scope = None

    def _require_battle_input_allowed(self, frame: CapturedFrame) -> bool:
        """限制生效时校验新帧，失败即清空底层待执行动作并保持暂停。"""
        scope = self._battle_input_scope
        if scope is None:
            return True
        try:
            allowed = scope.allows(frame)
        except Exception:
            self.pause_input()
            raise
        if not allowed:
            self.pause_input()
            return False
        return True

    @property
    def game_window_description(self) -> str:
        """返回目标窗口说明，不伪造 Windows 窗口对象。"""
        window = self.window_capture.window
        if window is None:
            return self.macos_config.bundle_id
        return f'{window.title or window.bundle_id} (PID {window.pid}, window {window.window_id})'

    @property
    def is_game_window_ready(self) -> bool:
        """返回窗口是否已绑定且采集没有报告错误。"""
        return self.window_capture.window is not None and self.window_capture.last_error is None

    @property
    def started_game_this_run(self) -> bool:
        """仅本次确实请求冷启动并找到窗口时为真，供登录准备区分等待策略。"""
        return self._started_game_this_run

    def init_before_context_run(self) -> bool:
        """绑定唯一目标窗口，拿到有效帧后再连接输入并恢复运行。"""
        self.run_generation += 1
        self.cleanup_after_app_shutdown()
        try:
            # 游戏启动时就需要能发现虚拟手柄；有效新帧出现前始终禁止按键。
            self.gamepad.connect()
            self.gamepad.suspend()
            window = self.game_launcher.ensure_window()
            self._started_game_this_run = self.game_launcher.started_game
            points = getattr(self.macos_config,'capture_top_inset_points',0)
            if self.macos_config.capture_auto_top_inset:
                self.window_capture.start(window, fps=self.macos_config.capture_fps, auto_top_inset=True)
            elif points:
                self.window_capture.start(window,fps=self.macos_config.capture_fps,top_inset_points=points)
            else:
                self.window_capture.start(
                    window, fps=self.macos_config.capture_fps,
                    top_inset_pixels=self.macos_config.capture_top_inset_pixels,
                )
            deadline = time.monotonic() + 2.0
            while self.window_capture.latest_frame(max_age_seconds=self.macos_config.max_frame_age_seconds) is None:
                # 首帧前的空白状态可自行恢复；流已停止或等候到期才终止初始化。
                if not self.window_capture.diagnostics().running or time.monotonic() >= deadline:
                    raise RuntimeError(self.window_capture.last_error or '尚未采集到有效游戏画面')
                time.sleep(0.02)
            self.resume_input()
            return True
        except Exception:
            self.cleanup_after_app_shutdown()
            log.error('Mac 控制器初始化失败', exc_info=True)
            return False

    def reset_input(self) -> None:
        """清空手柄状态，不改变暂停状态。"""
        self.is_moving = False
        self.gamepad.reset()

    def pause_input(self) -> None:
        """暂停并归零，拒绝稍晚到达的旧动作。"""
        self._input_paused = True
        self.is_moving = False
        try:
            self.gamepad.suspend()
        finally:
            self._stop_frame_monitor()

    def resume_input(self) -> None:
        """仅在连接和画面都有效时，从中立状态恢复。"""
        frame = self._require_fresh_frame()
        if not self._require_battle_input_allowed(frame):
            raise RuntimeError('战斗标识已消失，Mac 战斗输入已阻断')
        if not self.gamepad.is_connected:
            self.pause_input()
            raise RuntimeError('Mac 手柄输入未连接，请重新开始运行')
        self.gamepad.resume()
        self._input_paused = False
        self._start_frame_monitor()

    def cleanup_after_app_shutdown(self) -> None:
        """关闭输入并停止采集，实例切换后不保留旧窗口或旧按键。"""
        self._input_paused = True
        self._started_game_this_run = False
        self._battle_input_scope = None
        self.is_moving = False
        try:
            self.gamepad.close()
        finally:
            self._stop_frame_monitor()
            self.window_capture.stop()
            self.screenshot_history.clear()

    def _start_frame_monitor(self) -> None:
        """只在运行恢复后监测原始帧，保护长按等待期间的采集故障。"""
        self._stop_frame_monitor()
        stop = threading.Event()
        self._monitor_stop = stop
        self._monitor_thread = threading.Thread(
            target=self._monitor_frames, args=(stop,), name='zzz_macos_frame_monitor', daemon=True,
        )
        self._monitor_thread.start()

    def _stop_frame_monitor(self) -> None:
        """幂等停止监测；故障由监测线程触发时不等待自身。"""
        stop, thread = self._monitor_stop, self._monitor_thread
        self._monitor_stop = None
        self._monitor_thread = None
        if stop is not None:
            stop.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)

    def _monitor_frames(self, stop: threading.Event) -> None:
        """检查最新内容帧；画面过期或缩放后比例无效时暂停输入。"""
        interval = min(1 / self.macos_config.capture_fps, self.macos_config.max_frame_age_seconds / 2)
        try:
            while not stop.wait(interval):
                frame = self.window_capture.latest_frame(max_age_seconds=self.macos_config.max_frame_age_seconds)
                if frame is None and self.gamepad.is_connected and self.gamepad.state == GamepadState():
                    # 中立状态没有需要中断的长按；新动作仍会独立检查帧龄。
                    # 避免静止菜单的短暂回调延迟把整个会话永久锁在暂停状态。
                    continue
                if frame is None or not self.gamepad.is_connected:
                    self.pause_input()
                    log.error('Mac 输入已暂停：%s', self.window_capture.last_error or '窗口帧或输入连接失效')
                    return
                if not self._require_battle_input_allowed(frame):
                    return
        except Exception:
            self._input_paused = True
            self.gamepad.suspend()
            log.error('Mac 画面监测失败，输入已暂停', exc_info=True)

    def _require_fresh_frame(self) -> CapturedFrame:
        """没有有效新帧时暂停输入，不使用缓存旧图继续动作。"""
        frame = self.window_capture.latest_frame(max_age_seconds=self.macos_config.max_frame_age_seconds)
        if frame is None:
            self.pause_input()
            raise RuntimeError(self.window_capture.last_error or '没有有效的游戏画面，请重新开始运行')
        return frame

    def _require_input_ready(self) -> bool:
        """输入前检查暂停状态、帧龄与连接。"""
        if self.battle_input_blocked:
            return False
        if self._input_paused:
            raise RuntimeError('Mac 手柄输入已暂停')
        frame = self._require_fresh_frame()
        if not self._require_battle_input_allowed(frame):
            return False
        if not self.gamepad.is_connected:
            self.pause_input()
            raise RuntimeError('Mac 手柄输入已断开')
        return True

    def screenshot(self, independent: bool = False) -> tuple[float, MatLike | None]:
        """返回实际采集时间，并沿用 UID 遮挡与有限截图历史。"""
        frame = self.window_capture.latest_frame(max_age_seconds=self.macos_config.max_frame_age_seconds)
        if frame is None:
            self.pause_input()
            return time.time(), None
        image = self.fill_uid_black(frame.image)
        if self.max_screenshot_cnt > 0:
            self.screenshot_history.append(ScreenshotWithTime(image, frame.capture_time))
            self.screenshot_history = [
                item for item in self.screenshot_history[-self.max_screenshot_cnt:]
                if frame.capture_time - item.create_time <= self.screenshot_alive_seconds
            ]
        return frame.capture_time, image

    def get_screenshot(self, independent: bool = False) -> MatLike | None:
        """兼容直接取图的调用，同样不使用调用时间冒充采集时间。"""
        return self.screenshot(independent)[1]

    def fill_uid_black(self, screen: MatLike) -> MatLike:
        """遮挡移动端手柄布局右下角的 UID，复制图像以保留采集帧。"""
        return cv2_utils.mark_area_as_color(
            screen, pos=[1650, 1048, 270, 32],
            color=game_const.YOLO_DEFAULT_COLOR, new_image=True,
        )

    def btn_tap(self, key: str) -> None:
        """只接受已注册的手柄键，不回退键盘或鼠标。"""
        normalize_gamepad_key(key)
        if not self._require_input_ready():
            return
        self.gamepad.tap(key)

    def btn_press(self, key: str, press_time: float | None = None) -> None:
        """按住手柄键，保持其他按钮与摇杆状态。"""
        normalize_gamepad_key(key)
        if not self._require_input_ready():
            return
        self.gamepad.press(key, press_time)

    def btn_release(self, key: str) -> None:
        """暂停时仍允许释放；断线时只清理本地状态。"""
        normalize_gamepad_key(key)
        if self.gamepad.is_connected:
            self.gamepad.release(key)
        else:
            self.gamepad.reset()

    def set_gamepad_stick(self, side: GamepadSide, x: float, y: float) -> None:
        """提供手动摇杆入口，仍复用有效新帧和输入暂停保护。"""
        if x == 0 and y == 0:
            # 松开不应被旧帧挡住；暂停后的底层状态已归零。
            if self.gamepad.is_connected and not self._input_paused:
                self.gamepad.set_stick(side, 0, 0)
            return
        if self._require_input_ready():
            self.gamepad.set_stick(side, x, y)

    def _action_btn(self, action: str, press: bool, press_time: float | None, release: bool) -> None:
        """把既有业务动作交给 Xbox 配置对应的手柄键。"""
        key = self.action_keys[action]
        if press:
            self.btn_press(key, press_time)
        elif release:
            self.btn_release(key)
        else:
            self.btn_tap(key)

    def dodge(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """闪避。"""
        self._action_btn('dodge', press, press_time, release)

    def switch_next(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """切换角色到下一个。"""
        self._action_btn('switch_next', press, press_time, release)

    def switch_prev(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """切换角色到上一个。"""
        self._action_btn('switch_prev', press, press_time, release)

    def switch_backup(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """切换后援。"""
        self._action_btn('switch_backup', press, press_time, release)

    def normal_attack(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """普通攻击。"""
        self._action_btn('normal_attack', press, press_time, release)

    def special_attack(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """特殊攻击。"""
        self._action_btn('special_attack', press, press_time, release)

    def ultimate(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """终结技。"""
        self._action_btn('ultimate', press, press_time, release)

    def chain_left(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """左侧连携技。"""
        self._action_btn('chain_left', press, press_time, release)

    def chain_right(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """右侧连携技。"""
        self._action_btn('chain_right', press, press_time, release)

    def move_w(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """向前移动。"""
        self._action_btn('move_w', press, press_time, release)

    def move_s(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """向后移动。"""
        self._action_btn('move_s', press, press_time, release)

    def move_a(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """向左移动。"""
        self._action_btn('move_a', press, press_time, release)

    def move_d(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """向右移动。"""
        self._action_btn('move_d', press, press_time, release)

    def interact(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """交互。"""
        self._action_btn('interact', press, press_time, release)

    def lock(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """锁定敌人。"""
        self._action_btn('lock', press, press_time, release)

    def chain_cancel(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """取消连携技。"""
        self._action_btn('chain_cancel', press, press_time, release)

    def click(self, pos: Point | None = None, press_time: float = 0, pc_alt: bool = False,
              gamepad_key: str | None = None) -> bool:
        """仅执行明确配置的手柄动作，拒绝坐标点击。"""
        if not gamepad_key:
            raise NotImplementedError('Mac 手柄模式不支持坐标点击，请使用已建档的手柄导航')
        keys = self.gamepad_action_keys.get(gamepad_key)
        if not keys:
            raise ValueError(f'未配置手柄动作：{gamepad_key}')
        for key in keys:
            normalize_gamepad_key(key)
        if not self._require_input_ready():
            return False
        self.gamepad.tap_combo(keys)
        return True

    def drag_to(self, end: Point, start: Point | None = None, duration: float = 0.5,
                *, timing: DragTiming | None = None) -> None:
        """拒绝触屏和鼠标拖拽。"""
        raise NotImplementedError('Mac 手柄模式不支持拖拽')

    def scroll(self, down: int, pos: Point | None = None) -> None:
        """拒绝桌面滚轮输入。"""
        raise NotImplementedError('Mac 手柄模式不支持滚轮输入')

    def input_str(self, to_input: str, interval: float = 0.1) -> None:
        """拒绝通过桌面键盘输入文本。"""
        raise NotImplementedError('Mac 手柄模式不支持文本输入')

    def delete_all_input(self) -> None:
        """拒绝通过桌面键盘删除文本。"""
        raise NotImplementedError('Mac 手柄模式不支持文本删除')

    def mouse_move(self, game_pos: Point) -> None:
        """拒绝桌面鼠标移动。"""
        raise NotImplementedError('Mac 手柄模式不支持鼠标移动')

    def active_window(self) -> None:
        """明确拒绝自动激活窗口。"""
        raise NotImplementedError('Mac 自动运行不会激活游戏窗口')

    def close_game(self) -> None:
        """关闭客户端需要独立流程，当前不自动执行。"""
        raise NotImplementedError('Mac 控制器暂不支持关闭游戏')

    def enable_keyboard(self) -> None:
        """拒绝切回桌面键鼠输入。"""
        raise NotImplementedError('Mac 控制器只支持原生手柄输入')

    def enable_xbox(self) -> None:
        """保持当前 Xbox 配置映射，不切换底层设备。"""
        self.action_keys = self.game_config.get_action_keys('xbox')

    def enable_ds4(self) -> None:
        """尚未适配 DS4 配置时明确终止。"""
        raise NotImplementedError('Mac 控制器当前使用 Xbox 按键映射')

    def start_moving_forward(self) -> None:
        """开始持续向前移动。"""
        if not self.is_moving:
            self.move_w(press=True)
            self.is_moving = True

    def stop_moving_forward(self) -> None:
        """停止持续向前移动。"""
        self.is_moving = False
        self.move_w(release=True)

    def turn_by_distance(self, d: float) -> None:
        """根据 Mac 独立校准转向，不沿用 Windows 鼠标速度。"""
        self.move_mouse_relative(d, 0)

    def move_camera(self, x: float, y: float, press_time: float) -> None:
        """显式右摇杆转向，保留左摇杆状态并沿用新帧与暂停保护。"""
        if not self._require_input_ready():
            return
        self.gamepad.set_stick('right', x, y, press_time=press_time)

    def turn_vertical_by_distance(self, d: float) -> None:
        """按独立距离校准控制垂直镜头。"""
        self.move_mouse_relative(0, d)

    def move_mouse_relative(self, dx: float, dy: float) -> None:
        """兼容旧镜头动作名，实际只更新右摇杆，正 Y 向下。"""
        distance = max(abs(dx), abs(dy))
        if distance == 0:
            return
        speed = self.macos_config.turn_distance_per_second
        if not isfinite(distance) or not isfinite(speed) or speed <= 0:
            raise ValueError('请先校准 Mac 手柄的 turn_distance_per_second')
        if not self._require_input_ready():
            return
        amplitude = self.macos_config.turn_stick_amplitude
        self.gamepad.set_stick('right', dx / distance * amplitude, dy / distance * amplitude, press_time=distance / speed)

    def turn_by_angle_diff(self, angle_diff: float) -> None:
        """按 Mac 角速度校准转向，逆时针角度为正。"""
        if angle_diff == 0:
            return
        speed = self.macos_config.turn_degrees_per_second
        if not isfinite(angle_diff) or not isfinite(speed) or speed <= 0:
            raise ValueError('请先校准 Mac 手柄的 turn_degrees_per_second')
        if not self._require_input_ready():
            return
        self.gamepad.set_stick('right', -1.0 if angle_diff > 0 else 1.0, 0,
                              press_time=abs(angle_diff) / speed)
