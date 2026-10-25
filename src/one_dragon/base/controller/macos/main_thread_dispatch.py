"""将有限的 AppKit 操作派到主线程，超时后不执行迟到请求。"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


class MacMainThreadError(RuntimeError):
    """主线程操作未及时完成或执行失败。"""


def _main_operation_queue() -> Any:
    """实际请求系统操作时才加载 Foundation。"""
    import Foundation

    return Foundation.NSOperationQueue.mainQueue()


def perform_on_main_thread(
    action: Callable[[], None], deadline: float, *, operation_name: str,
) -> None:
    """主线程直接执行；工作线程等待剩余预算，超时取消未执行回调。"""
    if threading.current_thread() is threading.main_thread():
        action()
        return
    done = threading.Event()
    cancelled = threading.Event()
    errors: list[Exception] = []

    def perform() -> None:
        """迟到回调只结束等待，不再改变系统状态。"""
        try:
            if not cancelled.is_set() and time.monotonic() < deadline:
                action()
        except Exception as error:
            errors.append(error)
        finally:
            done.set()

    _main_operation_queue().addOperationWithBlock_(perform)
    if not done.wait(max(0, deadline - time.monotonic())):
        cancelled.set()
        raise MacMainThreadError(f'等待主线程{operation_name}超时')
    if errors:
        raise MacMainThreadError(f'主线程{operation_name}失败：{errors[0]}') from errors[0]
