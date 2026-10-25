"""只读检查指定游戏窗口在当前或其他 Space 的采集，不连接手柄或切换桌面。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from one_dragon.base.controller.macos.macos_game_launcher import select_game_window
from one_dragon.base.controller.macos.macos_window_capture import MacWindowCapture

if TYPE_CHECKING:
    from one_dragon.base.controller.macos.sck_frame_converter import CapturedFrame


def frame_summary(frame: CapturedFrame | None) -> dict[str, Any] | None:
    """按真实像素生成摘要；相同摘要不能被解释为游戏仍在渲染。"""
    if frame is None:
        return None
    return {
        'sequence': frame.sequence,
        'capture_time': frame.capture_time,
        'monotonic_time': frame.monotonic_time,
        'raw_size': [frame.raw_width, frame.raw_height],
        'shape': list(frame.image.shape),
        'sha256': hashlib.sha256(frame.image.tobytes()).hexdigest(),
    }


def desktop_state(window_id: int) -> dict[str, Any]:
    """只读取前台身份及当前可见窗口，不采集其他应用的图像。"""
    import AppKit
    import Quartz

    app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    visible = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, 0) or []
    error, displays, count = Quartz.CGGetActiveDisplayList(16, None, None)
    return {
        'frontmost_bundle_id': None if app is None else str(app.bundleIdentifier()),
        'window_on_current_desktop': any(int(item[Quartz.kCGWindowNumber]) == window_id for item in visible),
        'active_display_ids': list(displays[:count]) if error == 0 else None,
    }


def main() -> int:
    """短时采集并逐秒记录诊断；退出时始终关闭本工具创建的流。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle-id', default='com.miHoYo.Nap')
    parser.add_argument('--window-title', default='绝区零')
    parser.add_argument('--duration', type=float, default=15)
    parser.add_argument('--top-inset-pixels', type=int, default=0)
    parser.add_argument('--output', type=Path, required=True, help='新建 JSONL，不覆盖已有证据')
    parser.add_argument('--save-frames', action='store_true', help='在日志旁保存首张及像素变化后的截图')
    args = parser.parse_args()
    if not math.isfinite(args.duration) or not 0 < args.duration <= 120:
        parser.error('观察时长必须在 0 到 120 秒之间')
    if args.top_inset_pixels < 0:
        parser.error('顶部裁剪像素必须非负')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    capture = MacWindowCapture()
    last_digest: str | None = None
    with args.output.open('x', encoding='utf-8') as output:
        def record(event: str, **values: Any) -> None:
            """写入单调时间和事件，不用日志时间替代像素时间。"""
            row = {'event': event, 'time': time.time(), 'monotonic_time': time.monotonic(), **values}
            output.write(json.dumps(row, ensure_ascii=False) + '\n')
            output.flush()

        try:
            windows = capture.list_windows(args.bundle_id)
            record('windows', windows=[asdict(window) for window in windows])
            window = select_game_window(windows, args.window_title)
            if window is None:
                raise RuntimeError('未发现唯一目标窗口；不启动、激活或移动游戏')
            record('selected', window=asdict(window), desktop=desktop_state(window.window_id))
            capture.start(window, top_inset_pixels=args.top_inset_pixels)
            deadline = time.monotonic() + args.duration
            index = 0
            while time.monotonic() < deadline:
                time.sleep(min(1, max(0, deadline - time.monotonic())))
                frame = capture.latest_frame(max_age_seconds=0.5)
                summary = frame_summary(frame)
                frame_path: str | None = None
                if args.save_frames and frame is not None and summary['sha256'] != last_digest:
                    from PIL import Image

                    path = args.output.with_name(f'{args.output.stem}-{index:03}.png')
                    # 保留采集实例内的原始像素；仅对落盘副本遮挡 UID。
                    pixels = frame.image.copy()
                    pixels[1048:1080, 1650:1920] = 0
                    Image.fromarray(pixels).save(path)
                    frame_path = str(path)
                last_digest = None if summary is None else summary['sha256']
                record(
                    'sample', frame=summary, screenshot=frame_path,
                    diagnostics=asdict(capture.diagnostics()),
                    desktop=desktop_state(window.window_id),
                )
                index += 1
            return 0
        except Exception as error:
            record('error', message=str(error), diagnostics=asdict(capture.diagnostics()))
            raise
        finally:
            capture.stop()
            record('stopped', diagnostics=asdict(capture.diagnostics()))


if __name__ == '__main__':
    raise SystemExit(main())
