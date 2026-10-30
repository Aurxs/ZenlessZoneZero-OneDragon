"""Mac 运行内存采样；仅查询计数，不读取进程内存或操作游戏。"""

from __future__ import annotations

import ctypes
import json
import math
import os
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from one_dragon.utils.log_utils import log

if TYPE_CHECKING:
    from zzz_od.context.zzz_context import ZContext


# macOS SDK 的公开 rusage_info_v4 布局，固定版本避免依赖开发机 SDK 文件。
_RUSAGE_FIELDS = [
    'user_time', 'system_time', 'pkg_idle_wkups', 'interrupt_wkups', 'pageins', 'wired_size',
    'resident_size', 'phys_footprint', 'proc_start_abstime', 'proc_exit_abstime',
    'child_user_time', 'child_system_time', 'child_pkg_idle_wkups', 'child_interrupt_wkups',
    'child_pageins', 'child_elapsed_abstime', 'diskio_bytesread', 'diskio_byteswritten',
    'cpu_time_qos_default', 'cpu_time_qos_maintenance', 'cpu_time_qos_background',
    'cpu_time_qos_utility', 'cpu_time_qos_legacy', 'cpu_time_qos_user_initiated',
    'cpu_time_qos_user_interactive', 'billed_system_time', 'serviced_system_time',
    'logical_writes', 'lifetime_max_phys_footprint', 'instructions', 'cycles', 'billed_energy',
    'serviced_energy', 'interval_max_phys_footprint', 'runnable_time',
]


class _RusageInfoV4(ctypes.Structure):
    """系统返回的资源计数，所有内存字段均为字节。"""

    _fields_ = [('uuid', ctypes.c_uint8 * 16)] + [
        (name, ctypes.c_uint64) for name in _RUSAGE_FIELDS
    ]


class _TaskInfo(ctypes.Structure):
    """proc_taskinfo 的公开布局，仅使用原生线程数。"""

    _fields_ = [('sizes_and_times', ctypes.c_uint64 * 6), ('counts', ctypes.c_int32 * 12)]


class MacProcessMemoryReader:
    """通过 libproc 查询内存账本，不获取 task port 或挂起目标进程。"""

    def __init__(self) -> None:
        self._libproc = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
        self._libproc.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
        self._libproc.proc_pid_rusage.restype = ctypes.c_int
        self._libproc.proc_pidinfo.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int,
        ]
        self._libproc.proc_pidinfo.restype = ctypes.c_int

    def read(self, pid: int) -> dict[str, int]:
        """RSS 不含已压缩/换出页；footprint 记录系统对该进程的内存计费。"""
        usage = _RusageInfoV4()
        if self._libproc.proc_pid_rusage(pid, 4, ctypes.byref(usage)) != 0:
            raise OSError(ctypes.get_errno(), f'无法读取进程 {pid} 的内存计数')
        result = {
            'pid': pid,
            'rss_bytes': usage.resident_size,
            'footprint_bytes': usage.phys_footprint,
            'peak_footprint_bytes': usage.lifetime_max_phys_footprint,
            'pageins': usage.pageins,
        }
        task = _TaskInfo()
        if self._libproc.proc_pidinfo(pid, 4, 0, ctypes.byref(task), ctypes.sizeof(task)) == ctypes.sizeof(task):
            result['native_threads'] = task.counts[9]
        return result


def _image_bytes(images: list[object]) -> int:
    """相同数组引用只计一次，不复制像素或遍历数组内容。"""
    unique = {id(image): image for image in images if image is not None}
    return sum(int(getattr(image, 'nbytes', 0)) for image in unique.values())


def context_memory_details(ctx: ZContext) -> dict[str, object]:
    """只读取已存在的对象，避免触发懒加载、模型推理或窗口枚举。"""
    controller = ctx.controller
    capture = getattr(controller, 'window_capture', None)
    window = getattr(capture, 'window', None)
    history = list(getattr(controller, 'screenshot_history', ()))
    battle = ctx.auto_battle_context
    lost_void = ctx.__dict__.get('lost_void')
    detector = getattr(lost_void, 'detector', None)
    flash = getattr(battle.dodge_context, '_flash_model', None)
    ocr = getattr(ctx.ocr, '_model', None)
    run = ctx.run_context
    application = run.current_application
    node = getattr(application, '_current_node', None)
    result: dict[str, object] = {
        'instance_idx': ctx.current_instance_idx,
        'app_id': run.current_app_id,
        'node': getattr(node, 'cn', None),
        'run_state': getattr(getattr(run, '_run_state', None), 'value', None),
        'game_pid': getattr(window, 'pid', None),
        'capture_sequence': getattr(capture, '_sequence', None),
        'capture_raw_size': getattr(capture, '_raw_size', None),
        'screenshot_history_count': len(history),
        'screenshot_history_bytes': _image_bytes([item.image for item in history]),
        'auto_op_cache_count': len(battle._op_cache),
        'python_threads': threading.active_count(),
        'run_event_listener_count': sum(len(items) for items in list(
            getattr(getattr(run, 'event_bus', None), 'callbacks', {}).values(),
        )),
        'context_event_listener_count': sum(len(items) for items in list(
            getattr(ctx, 'callbacks', {}).values(),
        )),
    }
    models = {'lost_void': detector, 'flash': flash}
    sessions = {}
    for name, model in models.items():
        frames = list(getattr(model, 'run_result_history', ()))
        result[f'{name}_history_count'] = len(frames)
        result[f'{name}_history_bytes'] = _image_bytes([frame.raw_image for frame in frames])
        sessions[name] = id(model.session) if model is not None else None
    for name in ['det', 'rec']:
        child = getattr(ocr, 'text_detector' if name == 'det' else 'text_recognizer', None)
        session = getattr(child, f'{name}_onnx_session', None)
        sessions[f'ocr_{name}'] = id(session) if session is not None else None
    result['session_ids'] = sessions

    # 仅查看已导入的线程池，不为采样导入模块或改变队列。
    queues = {}
    for module_name, attribute in [
        ('one_dragon.utils.gpu_executor', '_executor'),
        ('zzz_od.auto_battle.auto_battle_context', '_battle_state_check_executor'),
        ('zzz_od.auto_battle.auto_battle_agent_context', '_battle_agent_context_executor'),
        ('zzz_od.auto_battle.auto_battle_target_context', '_target_context_executor'),
        ('one_dragon.base.conditional_operation.state_record_service', '_state_record_service_executor'),
    ]:
        executor = getattr(sys.modules.get(module_name), attribute, None)
        queue = getattr(executor, '_work_queue', None)
        if queue is not None:
            queues[attribute] = queue.qsize()
    result['pending_queues'] = queues
    return result


class MacMemoryMonitor:
    """每十五秒落盘一条采样，不在内存保留历史，不改变战斗时序。"""

    def __init__(
        self,
        output_dir: Path,
        details: Callable[[], dict[str, object]],
        interval_seconds: float = 15,
    ) -> None:
        if not math.isfinite(interval_seconds) or interval_seconds < 1:
            raise ValueError('内存采样间隔必须至少为一秒')
        self.output_path: Path = output_dir / f'{datetime.now():%Y%m%d_%H%M%S}_{os.getpid()}.jsonl'
        self._details = details
        self._interval_seconds = interval_seconds
        self._reader = MacProcessMemoryReader()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def sample(self, phase: str) -> None:
        """写入当前账本和有限对象计数；采样失败不能影响任务。"""
        try:
            data: dict[str, object] = {
                'time': datetime.now().astimezone().isoformat(timespec='seconds'),
                'monotonic_seconds': time.monotonic(),
                'phase': phase,
                'process': self._reader.read(os.getpid()),
                'argv': sys.argv[:2],
            }
            data['details'] = details = self._details()
            game_pid = details.get('game_pid')
            if isinstance(game_pid, int) and game_pid > 0:
                try:
                    data['game'] = self._reader.read(game_pid)
                except OSError as error:
                    data['game_error'] = str(error)
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            with self.output_path.open('a', encoding='utf-8') as output:
                output.write(json.dumps(data, ensure_ascii=False) + '\n')
        except Exception:
            log.warning('Mac 内存采样失败，本次忽略', exc_info=True)

    def start(self) -> None:
        """同一上下文只启动一次，先记录模型初始化前基线。"""
        if self._thread is not None:
            return
        self.sample('start')
        self._thread = threading.Thread(target=self._run, name='od_memory_monitor', daemon=True)
        self._thread.start()
        log.info('Mac 内存监测日志 %s，间隔 %.0f 秒', self.output_path, self._interval_seconds)

    def _run(self) -> None:
        """等待在独立线程进行，不占用 GPU executor 或 Cocoa 主线程。"""
        while not self._stop.wait(self._interval_seconds):
            self.sample('periodic')

    def stop(self) -> None:
        """结束采样并记录退出点，可重复调用。"""
        if self._stop.is_set():
            return
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1)
        self.sample('shutdown')
