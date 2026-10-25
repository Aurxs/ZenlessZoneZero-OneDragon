"""通过现有 OJD CLI 实现手柄兼容层，不修改 OJD 或系统输入驱动。"""

from __future__ import annotations

import contextlib
import json
import math
import os
import re
import select
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from one_dragon.base.controller.gamepad_input import (
    GamepadState,
    normalize_gamepad_key,
)

if TYPE_CHECKING:
    from typing import BinaryIO

    from one_dragon.base.controller.gamepad_input import GamepadSide

_OJD_VERSION = '0.6.0-alpha.1'
_MINIMUM_BUTTON_PRESS_TIME = 0.1
_BUTTONS: dict[str, str] = {
    'south': 'South', 'east': 'East', 'west': 'West', 'north': 'North',
    'left_shoulder': 'LeftShoulder', 'right_shoulder': 'RightShoulder',
    'back': 'Back', 'start': 'Start', 'left_stick_click': 'LeftStickClick',
    'right_stick_click': 'RightStickClick', 'guide': 'Guide', 'capture': 'Capture',
}
_DPAD: dict[str, str] = {
    'dpad_up': 'DpadUp', 'dpad_down': 'DpadDown',
    'dpad_left': 'DpadLeft', 'dpad_right': 'DpadRight',
}
_DIRECTIONS: dict[str, tuple[float, float]] = {
    'up': (0.0, -1.0), 'down': (0.0, 1.0),
    'left': (-1.0, 0.0), 'right': (1.0, 0.0),
}


class OjdGamepadError(RuntimeError):
    """OJD 前提检查、连接或状态发送失败。"""


class OjdGamepadClient:
    """持久 CLI 适配器；只有一个线程写完整状态，断连后不重放动作。

    CLI 没有创建成功或逐帧接受回执，is_connected 仅表示传输仍存活。
    本适配器不启动服务、不修改权限，也不注册进程级信号处理器。
    """

    def __init__(self, ojd_path: str = 'ojd', frame_interval: float = 0.05,
                 key_press_time: float = 0.1, combo_press_time: float = 0.5) -> None:
        self.ojd_path: str = ojd_path
        self.frame_interval: float = self._number(frame_interval, 0.008, 0.1)
        self.key_press_time: float = max(_MINIMUM_BUTTON_PRESS_TIME, self._number(key_press_time, 0.008))
        self.combo_press_time: float = self._number(combo_press_time, 0.0)
        self._condition: threading.Condition = threading.Condition()
        self._lifecycle: threading.Lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._connected: bool = False
        self._closing: bool = False
        self._suspended: bool = False
        self._last_error: str | None = None
        self._values: dict[str, bool | float | tuple[float, float]] = {}
        self._versions: dict[str, int] = {}
        self._deadlines: dict[str, float] = {}
        self._pending_holds: dict[str, tuple[int, int]] = {}
        self._owners: dict[str, str] = {}
        self._revision: int = 0
        self._sent_revision: int = 0
        self._epoch: int = 0

    @staticmethod
    def _number(value: float, minimum: float, maximum: float = math.inf) -> float:
        """检查有限数值，拒绝范围外的输入。"""
        if not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError(f'手柄参数超出范围：{value}')
        return value

    @property
    def is_connected(self) -> bool:
        """连接存活不等于游戏已接受输入。"""
        with self._condition:
            return self._connected and not self._closing and self._process is not None and self._process.poll() is None

    @property
    def last_error(self) -> str | None:
        """返回最近一次连接或发送失败的原因。"""
        with self._condition:
            return self._last_error

    @property
    def state(self) -> GamepadState:
        """在同一把锁内读取完整状态。"""
        with self._condition:
            return GamepadState(
                buttons=frozenset(key for key in _BUTTONS if self._values.get(key)),
                dpad=frozenset(key for key in _DPAD if self._values.get(key)),
                left_stick=self._values.get('left_stick', (0.0, 0.0)),
                right_stick=self._values.get('right_stick', (0.0, 0.0)),
                left_trigger=self._values.get('left_trigger', 0.0),
                right_trigger=self._values.get('right_trigger', 0.0),
            )

    def _preflight(self) -> str:
        """保留 ojd 符号链接名，检查固定 CLI 和已运行的服务。"""
        found = shutil.which(self.ojd_path)
        if found is None or Path(found).name != 'ojd':
            raise OjdGamepadError('请指定现有 ojd 命令或名为 ojd 的符号链接，不能直接启动 app 主程序')
        executable = str(Path(found).absolute())
        try:
            version = subprocess.run([executable, '--version'], capture_output=True, text=True, timeout=5, check=True)
            if re.search(r'(?<![\w.])0\.6\.0-alpha\.1(?![\w.+-])', version.stdout) is None:
                raise OjdGamepadError(f'仅支持 OJD {_OJD_VERSION}，实际为 {version.stdout.strip()!r}')
            status = subprocess.run(
                [executable, '--json', '--no-input', '--no-color', '--timeout', '2', 'status'],
                capture_output=True, text=True, timeout=5, check=True,
            )
            service = json.loads(status.stdout)['service']
            if service['state'] != 'Running' or service.get('version') != _OJD_VERSION:
                raise OjdGamepadError(f'OJD 服务必须运行且版本为 {_OJD_VERSION}')
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as error:
            raise OjdGamepadError(f'OJD 检查失败：{error}') from error
        return executable

    def connect(self) -> None:
        """建立一个持久 feed；显式重连总是从中立状态开始。"""
        with self._lifecycle:
            if self.is_connected:
                return
            if self._thread is not None and self._thread.is_alive():
                self._thread.join(timeout=6)
                if self._thread.is_alive():
                    raise OjdGamepadError('上一次 feed 尚未关闭')
            try:
                executable = self._preflight()
                errors = tempfile.TemporaryFile()  # noqa: SIM115 交给发送线程在退出时关闭
                process: subprocess.Popen[bytes] | None = None
                try:
                    process = subprocess.Popen(
                        [executable, '--json', '--no-input', '--no-color', '--timeout', '2',
                         'virtual', 'feed', '--as', 'game-controller-compatible'],
                        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors, bufsize=0,
                    )
                    assert process.stdin is not None
                    os.set_blocking(process.stdin.fileno(), False)
                except OSError:
                    errors.close()
                    if process is not None:
                        if process.stdin is not None:
                            process.stdin.close()
                        with contextlib.suppress(OSError):
                            process.kill()
                        process.wait(timeout=2)
                    raise
                with self._condition:
                    self._clear_locked()
                    self._process = process
                    self._connected = True
                    self._closing = False
                    self._last_error = None
                    self._sent_revision = 0
                    revision = self._revision
                    self._thread = threading.Thread(target=self._run, args=(process, errors),
                                                    name='ojd-gamepad-feed', daemon=True)
                    self._thread.start()
                self._wait_sent(revision)
            except (OSError, OjdGamepadError) as error:
                with self._condition:
                    self._last_error = str(error)
                raise OjdGamepadError(str(error)) from error

    def _require_connected_locked(self) -> None:
        """状态更新失败时明确报错，不自动重连。"""
        if not self._connected or self._closing or self._process is None or self._process.poll() is not None:
            raise OjdGamepadError(self._last_error or 'OJD feed 未连接或已断开')

    def _require_input_locked(self) -> None:
        """暂停与状态更新共用锁，禁止暂停后迟到的新动作。"""
        self._require_connected_locked()
        if self._suspended:
            raise OjdGamepadError('手柄输入已暂停')

    def _clear_locked(self) -> None:
        """清空动作并使所有旧期限和组合操作失效。"""
        self._values.clear()
        self._deadlines.clear()
        self._pending_holds.clear()
        self._owners.clear()
        self._versions.clear()
        self._epoch += 1
        self._revision += 1
        self._condition.notify_all()

    def _change_locked(self, group: str, value: bool | float | tuple[float, float],
                       owner: str, duration: float | None) -> tuple[int, int]:
        """为本次更新分配编号，新动作覆盖相同控制的旧期限。"""
        self._values[group] = value
        self._owners[group] = owner
        version = self._versions.get(group, 0) + 1
        self._versions[group] = version
        if duration is None:
            self._deadlines.pop(group, None)
            self._pending_holds.pop(group, None)
        else:
            self._deadlines[group] = time.monotonic() + duration
            # CLI 可能批量读取按下/释放；首帧须保留动作时长，且不排入长保持帧。
            self._pending_holds[group] = (version, max(8, min(100, math.ceil(duration * 1000))))
        self._revision += 1
        self._condition.notify_all()
        return self._revision, version

    def _release_locked(self, group: str) -> int:
        """只释放一个控制，不覆盖同时保持的其他控制。"""
        self._values.pop(group, None)
        self._owners.pop(group, None)
        self._deadlines.pop(group, None)
        self._pending_holds.pop(group, None)
        self._versions[group] = self._versions.get(group, 0) + 1
        self._revision += 1
        self._condition.notify_all()
        return self._revision

    def _wait_sent(self, revision: int) -> None:
        """等待状态写入管道；这不是 OJD 的接受回执。"""
        deadline = time.monotonic() + 1
        with self._condition:
            while self._sent_revision < revision:
                self._require_connected_locked()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._last_error = 'OJD 状态写入超时'
                    self._clear_locked()
                    self._closing = True
                    self._condition.notify_all()
                    raise OjdGamepadError(self._last_error)
                self._condition.wait(remaining)

    def _wait_hold(self, group: str, version: int, epoch: int) -> None:
        """只等本次期限；后来的 press 不会被旧调用释放。"""
        with self._condition:
            while self._versions.get(group) == version and self._epoch == epoch:
                if not self._connected or self._closing:
                    return
                self._condition.wait()
            revision = self._revision
            if not self._connected or self._closing:
                return
        self._wait_sent(revision)

    def _begin_key(self, key: str, duration: float | None,
                   hold_milliseconds: int = 8) -> tuple[str, int, int]:
        """合并一个按钮、方向键、扳机或摇杆方向的状态。"""
        key = normalize_gamepad_key(key)
        group = key
        value: bool | float | tuple[float, float] = True
        for side in ('left', 'right'):
            prefix = f'{side}_stick_'
            direction = key.removeprefix(prefix)
            if key.startswith(prefix) and direction in _DIRECTIONS:
                group, value = f'{side}_stick', _DIRECTIONS[direction]
        if key in ('left_trigger', 'right_trigger'):
            value = 1.0
        with self._condition:
            self._require_input_locked()
            revision, version = self._change_locked(group, value, key, duration)
            if hold_milliseconds > 8:
                self._pending_holds[group] = (version, hold_milliseconds)
            epoch = self._epoch
        self._wait_sent(revision)
        return group, version, epoch

    def press(self, key: str, press_time: float | None = None) -> None:
        """按住；有时长时由发送线程按单调时钟释放，调用方等待结束。"""
        duration = None if press_time is None else max(self.key_press_time, self._number(press_time, 0))
        group, version, epoch = self._begin_key(key, duration)
        if duration is not None:
            self._wait_hold(group, version, epoch)

    def tap(self, key: str) -> None:
        """使用当前最短时长点按。"""
        self.press(key, self.key_press_time)

    def release(self, key: str) -> None:
        """释放按键，旧摇杆方向的释放不会取消后来选择的方向。"""
        key = normalize_gamepad_key(key)
        with self._condition:
            self._require_connected_locked()
            group = next((group for group, owner in self._owners.items() if owner == key), None)
            if group is None:
                return
            revision = self._release_locked(group)
        self._wait_sent(revision)

    def _wait_combo(self, duration: float, epoch: int) -> bool:
        """组合键等待可被 reset、stop、close 或断线立即取消。"""
        deadline = time.monotonic() + self._number(duration, 0)
        with self._condition:
            while self._epoch == epoch and self._connected and not self._closing:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return True
                self._condition.wait(remaining)
            return False

    def tap_combo(self, keys: list[str]) -> None:
        """先按修饰键等待，再按动作键，最后按相反顺序释放本次按键。"""
        keys = [normalize_gamepad_key(key) for key in keys]
        held: list[tuple[str, int, int]] = []
        try:
            for index, key in enumerate(keys):
                hold = min(100, math.ceil(self.key_press_time * 1000)) if index == len(keys) - 1 else 8
                token = self._begin_key(key, None, hold)
                held.append(token)
                wait = self.combo_press_time if index < len(keys) - 1 else self.key_press_time
                if not self._wait_combo(wait, token[2]):
                    return
        finally:
            for group, version, epoch in reversed(held):
                with self._condition:
                    if self._versions.get(group) != version or self._epoch != epoch or not self._connected or self._closing:
                        continue
                    revision = self._release_locked(group)
                self._wait_sent(revision)

    def _set_axis(self, group: str, value: float | tuple[float, float], press_time: float | None) -> None:
        """在同一个状态写入流程中更新模拟量。"""
        duration = None if press_time is None else self._number(press_time, 0.008)
        with self._condition:
            self._require_input_locked()
            revision, version = self._change_locked(group, value, group, duration)
            epoch = self._epoch
        self._wait_sent(revision)
        if duration is not None:
            self._wait_hold(group, version, epoch)

    def set_stick(self, stick: GamepadSide, x: float, y: float,
                  press_time: float | None = None) -> None:
        """设置左右摇杆，正 Y 向下；其他控制保持原状态。"""
        if stick not in ('left', 'right'):
            raise ValueError(f'不支持的摇杆：{stick}')
        self._set_axis(f'{stick}_stick', (self._number(x, -1, 1), self._number(y, -1, 1)), press_time)

    def set_trigger(self, trigger: GamepadSide, value: float,
                    press_time: float | None = None) -> None:
        """设置左右扳机，范围 0 到 1。"""
        if trigger not in ('left', 'right'):
            raise ValueError(f'不支持的扳机：{trigger}')
        self._set_axis(f'{trigger}_trigger', self._number(value, 0, 1), press_time)

    def set_key_press_time(self, key_press_time: float) -> None:
        """点按至少保持实机已验证的 100 毫秒，不沿用 Windows 的 20 毫秒下限。"""
        self.key_press_time = max(_MINIMUM_BUTTON_PRESS_TIME, self._number(key_press_time, 0.008))

    def reset(self) -> None:
        """取消动作和期限，连接存活时优先写中立状态。"""
        with self._condition:
            self._clear_locked()
            revision = self._revision
            connected = self._connected and not self._closing
        if connected:
            self._wait_sent(revision)

    def stop(self) -> None:
        """归零并取消等待，允许随后显式发起新动作。"""
        self.reset()

    def suspend(self) -> None:
        """锁内禁止新动作、清空期限并释放；无需连接也能保持暂停状态。"""
        with self._condition:
            self._suspended = True
            self._clear_locked()
            revision = self._revision
            connected = self._connected and not self._closing
        if connected:
            self._wait_sent(revision)

    def resume(self) -> None:
        """写完中立状态才允许新动作，较新的暂停请求优先。"""
        with self._condition:
            self._require_connected_locked()
            self._suspended = True
            self._clear_locked()
            revision, epoch = self._revision, self._epoch
        self._wait_sent(revision)
        with self._condition:
            if self._epoch == epoch and self._connected and not self._closing:
                self._suspended = False

    def close(self) -> None:
        """发送中立状态、EOF 并等候关闭，不留下待重放的动作。"""
        with self._lifecycle:
            with self._condition:
                self._clear_locked()
                self._closing = True
                self._condition.notify_all()
                thread = self._thread
                process = self._process
            if thread is not None:
                thread.join(timeout=6)
                if thread.is_alive() and process is not None:
                    with contextlib.suppress(OSError):
                        process.kill()
                    thread.join(timeout=2)
            with self._condition:
                self._connected = False
                self._condition.notify_all()

    @staticmethod
    def _frame(state: GamepadState, hold_milliseconds: int = 8) -> dict[str, object]:
        """完整状态转换为 OJD 帧；普通刷新 8 毫秒，动作首帧另带短保持。"""
        return {
            'buttons': sorted(_BUTTONS[key] for key in state.buttons),
            'dpad': sorted(_DPAD[key] for key in state.dpad),
            'axes': {'LeftStickX': state.left_stick[0], 'LeftStickY': state.left_stick[1],
                     'RightStickX': state.right_stick[0], 'RightStickY': state.right_stick[1],
                     'LeftTrigger': state.left_trigger, 'RightTrigger': state.right_trigger},
            'holdMilliseconds': hold_milliseconds,
        }

    @staticmethod
    def _write(process: subprocess.Popen[bytes], frame: dict[str, object]) -> None:
        """限制写管道的时间，避免服务失效时无限阻塞释放。"""
        if process.poll() is not None:
            raise OjdGamepadError(f'OJD feed 已退出：{process.returncode}')
        assert process.stdin is not None
        payload = (json.dumps(frame, separators=(',', ':')) + '\n').encode()
        deadline = time.monotonic() + 0.25
        while payload:
            try:
                payload = payload[os.write(process.stdin.fileno(), payload):]
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise OjdGamepadError('OJD feed 管道写入超时') from None
                select.select([], [process.stdin], [], 0.01)

    def _run(self, process: subprocess.Popen[bytes], errors: BinaryIO) -> None:
        """唯一发送线程：刷新最新完整状态，过期动作在发送前归零。"""
        failure: str | None = None
        last_write = 0.0
        last_hold_seconds = 0.008
        try:
            while True:
                with self._condition:
                    if self._closing:
                        break
                    now = time.monotonic()
                    for group, deadline in list(self._deadlines.items()):
                        if deadline <= now:
                            self._release_locked(group)
                    revision = self._revision
                # 等当前短保持结束再发最新状态，不在 100ms 首帧后堆重复刷新。
                remaining = last_hold_seconds - (time.monotonic() - last_write)
                if remaining > 0:
                    with self._condition:
                        self._condition.wait(remaining)
                    continue
                with self._condition:
                    state = self.state
                    revision = self._revision
                    holds = self._pending_holds.copy()
                    hold_milliseconds = max((hold for _, hold in holds.values()), default=8)
                self._write(process, self._frame(state, hold_milliseconds))
                last_write = time.monotonic()
                last_hold_seconds = hold_milliseconds / 1000
                with self._condition:
                    for group, hold in holds.items():
                        if self._pending_holds.get(group) == hold:
                            self._pending_holds.pop(group)
                    self._sent_revision = max(self._sent_revision, revision)
                    self._condition.notify_all()
                    timeout = max(self.frame_interval, last_hold_seconds)
                    if self._deadlines:
                        timeout = min(timeout, max(0, min(self._deadlines.values()) - time.monotonic()))
                    self._condition.wait_for(lambda sent=revision: self._closing or self._revision != sent, timeout=timeout)
        except (OSError, OjdGamepadError) as error:
            failure = str(error)
        finally:
            with self._condition:
                if failure is not None:
                    self._last_error = failure
                self._clear_locked()
                self._closing = True
                self._connected = False
                self._condition.notify_all()
            with contextlib.suppress(OSError, OjdGamepadError):
                self._write(process, self._frame(GamepadState()))
            assert process.stdin is not None
            process.stdin.close()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
            errors.seek(0, os.SEEK_END)
            length = errors.tell()
            errors.seek(max(0, length - 4096))
            detail = errors.read().decode('utf-8', errors='replace').strip()
            errors.close()
            with self._condition:
                if failure is not None or process.returncode != 0:
                    self._last_error = f'{failure or "OJD feed 退出"}（{process.returncode}）{detail}'
                self._condition.notify_all()
