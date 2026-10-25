#!/usr/bin/env python3
"""独立验证固定版本 OJD；默认只读，显式选择动作才创建虚拟手柄。"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import selectors
import shutil
import signal
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Any

EXPECTED_VERSION = '0.6.0-alpha.1'
BUTTONS = (
    'South', 'East', 'West', 'North', 'LeftShoulder', 'RightShoulder',
    'LeftTrigger', 'RightTrigger', 'Back', 'Start', 'LeftStickClick',
    'RightStickClick', 'Guide', 'Capture',
)
AXES = (
    'LeftStickX', 'LeftStickY', 'RightStickX', 'RightStickY',
    'LeftTrigger', 'RightTrigger',
)
FRAME_MS = 50


class ProbeError(Exception):
    """探测前提或 CLI 执行失败。"""


class JsonLog:
    """为每条记录附加墙钟和进程内单调时钟。"""

    def __init__(self) -> None:
        self.started: float = time.monotonic()

    def emit(self, event: str, **fields: Any) -> None:
        """向标准输出写一条 JSON，便于与观察器日志比对。"""
        print(json.dumps({
            'time': datetime.now(UTC).isoformat(timespec='milliseconds'),
            'elapsed_seconds': round(time.monotonic() - self.started, 6),
            'event': event,
            **fields,
        }, ensure_ascii=False), flush=True)


class StopRequest:
    """将中断转成停止请求，使退出仍经过释放流程。"""

    def __init__(self) -> None:
        self.signum: int | None = None

    def handle(self, signum: int, frame: FrameType | None) -> None:
        """信号处理器只记下信号，不在其中操作管道。"""
        self.signum = signum


def finite_range(value: str, low: float, high: float) -> float:
    """拒绝 NaN、无穷及越界参数。"""
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise argparse.ArgumentTypeError(f'数值必须在 {low} 到 {high} 之间')
    return number


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """读取有限动作参数；不指定 action 时仅查询版本与状态。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ojd', default='ojd', help='OJD CLI 路径，默认从 PATH 查找')
    parser.add_argument('--action', choices=('neutral', 'tap', 'stick', 'combo'))
    parser.add_argument('--duration', type=lambda v: finite_range(v, 0.008, 600), default=1.0,
                        help='保持秒数，默认 1；neutral 最多 600，其他动作最多 10')
    parser.add_argument('--delay', type=lambda v: finite_range(v, 0, 30), default=0.0,
                        help='发送前等待秒数，最多 30，便于手动切换前台应用')
    parser.add_argument('--button', action='append', choices=BUTTONS,
                        help='tap/combo 按钮，可重复指定，默认 South')
    parser.add_argument('--stick', choices=('left', 'right'), default='left')
    parser.add_argument('--x', type=lambda v: finite_range(v, -1, 1), default=0.5)
    parser.add_argument('--y', type=lambda v: finite_range(v, -1, 1), default=0.0,
                        help='OJD 坐标：正值向下')
    args = parser.parse_args(argv)
    if args.action != 'neutral' and args.duration > 10:
        parser.error('只有 --action neutral 可使用超过 10 秒的 duration')
    return args


def resolve_ojd(value: str) -> str:
    """保留 ojd 链接名，避免发行包按可执行文件名进入 GUI。"""
    found = shutil.which(value)
    if found is None:
        raise ProbeError(f'找不到 OJD CLI：{value}；用 --ojd 指定路径')
    path = Path(found).absolute()
    if path.name != 'ojd':
        raise ProbeError('OJD CLI 入口必须名为 ojd；请指定官方 ojd 符号链接，不能直接调用 app 主程序')
    return str(path)


def read_command(command: list[str], log: JsonLog, name: str) -> subprocess.CompletedProcess[str]:
    """以有限超时读取 CLI 输出。"""
    result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
    log.emit(name, command=command, returncode=result.returncode,
             stdout=result.stdout.strip(), stderr=result.stderr.strip())
    if result.returncode != 0:
        raise ProbeError(f'{name} 失败，退出码 {result.returncode}')
    return result


def preflight(ojd: str, log: JsonLog, require_running: bool) -> bool:
    """解析服务状态；退出码零不等于服务正在运行。"""
    version = read_command([ojd, '--version'], log, 'version').stdout.strip()
    matched = re.search(r'(?<![\w.])0\.6\.0-alpha\.1(?![\w.+-])', version)
    if matched is None:
        raise ProbeError(f'本工具仅核对过 OJD {EXPECTED_VERSION}，实际为 {version!r}')
    result = read_command(
        [ojd, '--json', '--no-input', '--no-color', '--timeout', '2', 'status'],
        log, 'status_command',
    )
    try:
        report = json.loads(result.stdout)
        service = report['service']
        state = service['state']
    except (ValueError, KeyError, TypeError) as error:
        raise ProbeError('status 未返回预期的 service.state JSON') from error
    running = state == 'Running'
    log.emit('service_state', state=state, running=running, report=report)
    if require_running and not running:
        raise ProbeError('OJD 服务未运行；本工具不会自动启动服务')
    if require_running and service.get('version') != EXPECTED_VERSION:
        raise ProbeError(f'服务版本必须为 {EXPECTED_VERSION}，实际为 {service.get("version")!r}')
    return running


def make_frame(args: argparse.Namespace, neutral: bool = False) -> dict[str, Any]:
    """始终发送完整按钮、方向键、双摇杆和扳机状态。"""
    axes = dict.fromkeys(AXES, 0.0)
    buttons: list[str] = []
    if not neutral:
        if args.action in ('tap', 'combo'):
            buttons = sorted(set(args.button or ['South']))
        if args.action in ('stick', 'combo'):
            prefix = 'LeftStick' if args.stick == 'left' else 'RightStick'
            axes[f'{prefix}X'] = args.x
            axes[f'{prefix}Y'] = args.y
    return {'buttons': buttons, 'dpad': [], 'axes': axes, 'holdMilliseconds': FRAME_MS}


class Feed:
    """管理一个 CLI 子进程，持续读取输出并限制写入等待。"""

    def __init__(self, command: list[str], log: JsonLog) -> None:
        self.log: JsonLog = log
        self.process: subprocess.Popen[bytes] = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0,
        )
        self.selector: selectors.BaseSelector = selectors.DefaultSelector()
        self.buffers: dict[str, bytes] = {'stdout': b'', 'stderr': b''}
        self.frames_written: int = 0
        for name in ('stdout', 'stderr'):
            stream = getattr(self.process, name)
            os.set_blocking(stream.fileno(), False)
            self.selector.register(stream, selectors.EVENT_READ, name)
        assert self.process.stdin is not None
        os.set_blocking(self.process.stdin.fileno(), False)
        log.emit('feed_process_started', command=command, pid=self.process.pid,
                 device_created='unverified', note='CLI JSON 只反馈震动；进程存活或写入成功不能证明设备创建')

    def drain(self, timeout: float = 0.0) -> None:
        """排空两条输出管道，避免子进程被日志堵住。"""
        for key, _ in self.selector.select(timeout):
            chunk = os.read(key.fileobj.fileno(), 65536)
            name = key.data
            if not chunk:
                self.selector.unregister(key.fileobj)
                if self.buffers[name]:
                    self.log.emit('cli_output', stream=name,
                                  line=self.buffers[name].decode('utf-8', errors='replace'))
                    self.buffers[name] = b''
                continue
            self.buffers[name] += chunk
            while b'\n' in self.buffers[name]:
                line, self.buffers[name] = self.buffers[name].split(b'\n', 1)
                self.log.emit('cli_output', stream=name, line=line.decode('utf-8', errors='replace'))

    def write(self, frame: dict[str, Any], label: str) -> None:
        """只向 stdin 写协议帧；不发送 endpoint 心跳消息。"""
        if self.process.poll() is not None:
            raise ProbeError(f'feed 已退出：{self.process.returncode}')
        assert self.process.stdin is not None
        payload = (json.dumps(frame, separators=(',', ':')) + '\n').encode()
        deadline = time.monotonic() + 0.25
        while payload:
            try:
                count = os.write(self.process.stdin.fileno(), payload)
                payload = payload[count:]
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ProbeError('feed stdin 写入超时') from None
                self.drain(0.01)
        self.frames_written += 1
        self.log.emit('frame_written', label=label, frame=frame, accepted='unverified')

    def close(self) -> int:
        """EOF 后等短帧排完并关闭 feed；超时才终止子进程。"""
        assert self.process.stdin is not None
        self.process.stdin.close()
        deadline = time.monotonic() + 4
        while self.process.poll() is None and time.monotonic() < deadline:
            self.drain(0.02)
        if self.process.poll() is None:
            self.log.emit('cleanup_timeout', note='EOF 清理超时，向 CLI 发送 SIGTERM')
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.log.emit('cleanup_timeout', note='SIGTERM 超时，终止 CLI；设备释放须独立观察')
                self.process.kill()
                self.process.wait(timeout=2)
        drain_deadline = time.monotonic() + 0.25
        while self.selector.get_map() and time.monotonic() < drain_deadline:
            self.drain(0.02)
        for name, pending in self.buffers.items():
            if pending:
                self.log.emit('cli_output', stream=name,
                              line=pending.decode('utf-8', errors='replace'))
        self.selector.close()
        for stream in (self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()
        return self.process.returncode


def run_feed(args: argparse.Namespace, ojd: str, log: JsonLog, stop: StopRequest) -> int:
    """用短帧执行有限动作，所有退出路径先尝试中立帧再 EOF。"""
    deadline = time.monotonic() + args.delay
    log.emit('action_scheduled', action=args.action, delay_seconds=args.delay,
             duration_seconds=args.duration)
    while time.monotonic() < deadline and stop.signum is None:
        time.sleep(min(0.02, max(0, deadline - time.monotonic())))
    if stop.signum is not None:
        return 128 + stop.signum
    command = [ojd, '--json', '--no-input', '--no-color', '--timeout', '2',
               'virtual', 'feed', '--as', 'game-controller-compatible']
    feed = Feed(command, log)
    neutral_written = False
    failure: str | None = None
    try:
        feed.write(make_frame(args, neutral=True), 'initial_neutral')
        deadline = time.monotonic() + args.duration
        next_frame = time.monotonic()
        while time.monotonic() < deadline and stop.signum is None:
            if time.monotonic() >= next_frame:
                feed.write(make_frame(args), args.action)
                next_frame = time.monotonic() + FRAME_MS / 1000
            feed.drain(min(0.01, max(0, deadline - time.monotonic())))
            if feed.process.poll() is not None:
                raise ProbeError(f'feed 提前退出：{feed.process.returncode}')
    except (OSError, ProbeError) as error:
        failure = str(error)
        log.emit('error', message=failure)
    finally:
        try:
            frame = make_frame(args, neutral=True)
            frame['holdMilliseconds'] = 8
            feed.write(frame, 'final_neutral')
            neutral_written = True
        except (OSError, ProbeError) as error:
            log.emit('release_write_failed', message=str(error), note='继续 EOF/进程清理')
        returncode = feed.close()
        log.emit('feed_summary', cli_returncode=returncode,
                 frames_written=feed.frames_written, neutral_frame_written=neutral_written,
                 device_created='unverified', release_observed='unverified',
                 note='请同时用 GameController 观察器及游戏画面验证创建、输入与释放')
    if stop.signum is not None:
        return 128 + stop.signum
    return 0 if failure is None and neutral_written and returncode == 0 else 1


def main(argv: list[str] | None = None) -> int:
    """独立入口，不导入项目上下文或键鼠模块。"""
    args = parse_args(argv)
    log = JsonLog()
    stop = StopRequest()
    previous = {number: signal.signal(number, stop.handle) for number in (signal.SIGINT, signal.SIGTERM)}
    result = 1
    try:
        ojd = resolve_ojd(args.ojd)
        running = preflight(ojd, log, require_running=args.action is not None)
        if stop.signum is not None:
            result = 128 + stop.signum
        elif args.action is None:
            result = 0
            log.emit('read_only_summary', service_running=running, input_sent=False)
        else:
            result = run_feed(args, ojd, log, stop)
    except (OSError, ProbeError, subprocess.TimeoutExpired) as error:
        log.emit('error', message=str(error))
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
        log.emit('summary', returncode=result, interrupted_signal=stop.signum)
    return result


if __name__ == '__main__':
    raise SystemExit(main())
