"""Mac 无 Qt 窗口入口，复用当前账户、原应用调度和 Cocoa 采集事件循环。"""

from __future__ import annotations

import argparse
import json
import platform
import signal
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import FrameType

    from one_dragon.base.operation.application.application_run_context import (
        ApplicationRunResult,
    )
    from zzz_od.context.zzz_context import ZContext


def validate_request(ctx: ZContext, app_id: str) -> None:
    """在连接采集和手柄前拒绝未知、内部或尚未适配的任务。"""
    from one_dragon.base.config.game_account_config import GamePlatformEnum
    from zzz_od.macos.application_capabilities import (
        get_macos_one_dragon_unavailable_reason,
    )

    if ctx.game_account_config.platform != GamePlatformEnum.MACOS_PLAYCOVER.value.value:
        raise ValueError('请先在 GUI 账户管理中将当前账户设为 macOS PlayCover')
    if not ctx.run_context.is_app_registered(app_id) or (
        app_id != 'one_dragon' and not ctx.run_context.is_app_standalone_available(app_id)
    ):
        raise ValueError(f'未知或不可独立调用的任务：{app_id}')
    reason = ctx.get_application_unavailable_reason(app_id)
    if reason is None and app_id == 'one_dragon':
        reason = get_macos_one_dragon_unavailable_reason(ctx)
    if reason is not None:
        raise ValueError(reason)


def describe_request(ctx: ZContext, app_id: str) -> dict[str, object]:
    """预览已保存配置，不初始化模型、采集或输入，也不重置运行记录。"""
    from zzz_od.macos.application_capabilities import get_macos_app_limits

    app_ids = [app_id]
    if app_id == 'one_dragon':
        group = ctx.app_group_manager.get_one_dragon_group_config(ctx.current_instance_idx)
        app_ids = [item.app_id for item in group.app_list if item.enabled]
    return {
        'instance_idx': ctx.current_instance_idx,
        'app_id': app_id,
        'tasks': [{
            'app_id': item,
            'name': ctx.run_context.get_application_name(item),
            'limits': get_macos_app_limits(item),
        } for item in app_ids],
    }


def run_session(
    ctx: ZContext,
    app_id: str,
    pump: Callable[[], None],
    interrupted: Event,
) -> ApplicationRunResult:
    """工作线程运行原应用，主线程持续处理原生事件直到停止清理完成。"""
    from one_dragon.base.operation.application import application_const

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='mac_cli')
    future = executor.submit(
        ctx.run_context.run_application,
        app_id, ctx.current_instance_idx, application_const.DEFAULT_GROUP_ID,
    )
    try:
        while not future.done():
            # 初始化控制器期间仍处于 STOP；持续检查，避免启动完成后漏掉中断。
            if interrupted.is_set():
                ctx.run_context.stop_running()
            pump()
        return future.result()
    finally:
        ctx.run_context.stop_running()
        while not future.done():
            ctx.run_context.stop_running()
            pump()
        executor.shutdown(wait=True)


def summarize_result(ctx: ZContext, result: ApplicationRunResult) -> tuple[dict[str, object], int]:
    """应用组完成后核对启用任务记录，不能把子任务失败当成命令成功。"""
    from one_dragon.base.operation.application.application_run_context import (
        RunFinishReason,
    )
    from one_dragon.base.operation.application_run_record import AppRunRecord

    failed_apps: list[str] = []
    if result.app_id == 'one_dragon':
        group = ctx.app_group_manager.get_one_dragon_group_config(ctx.current_instance_idx)
        for item in group.app_list:
            if not item.enabled:
                continue
            record = ctx.run_context.get_run_record(item.app_id, ctx.current_instance_idx)
            if record is not None and record.run_status == AppRunRecord.STATUS_FAIL:
                failed_apps.append(item.app_id)
    success = result.finish_reason == RunFinishReason.COMPLETED and not failed_apps
    operation_result = ctx.run_context.last_application_result
    return {
        'success': success,
        'app_id': result.app_id,
        'instance_idx': result.instance_idx,
        'finish_reason': str(result.finish_reason),
        'status': operation_result.status if operation_result is not None else None,
        'failed_apps': failed_apps,
    }, 0 if success else 1


def main(argv: list[str] | None = None) -> int:
    """默认运行当前账户的一条龙；配置仍由原 GUI 或 YAML 管理。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', default='one_dragon', help='原任务 ID，默认 one_dragon')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--list', action='store_true', help='列出已注册任务及 Mac 支持情况，不操作游戏')
    mode.add_argument('--dry-run', action='store_true', help='检查入口限制并预览已启用任务，不操作游戏')
    args = parser.parse_args(argv)
    if sys.platform != 'darwin' or platform.machine().lower() not in ('arm64', 'aarch64'):
        parser.error('此入口需要 Apple Silicon macOS 和原生 arm64 Python')

    from zzz_od.context.zzz_context import ZContext

    interrupted = Event()

    def interrupt(signum: int, frame: FrameType | None) -> None:
        """只登记中断，让主循环完成停止和释放，重复信号不打断清理。"""
        interrupted.set()

    handlers = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGINT, signal.SIGTERM)}
    ctx: ZContext | None = None
    try:
        ctx = ZContext()
        # 预览只注册工厂，不调用会加载模型和刷新日记录的 init。
        ctx.register_application_factory()
        ctx.app_group_manager.set_default_apps(ctx.run_context.default_group_apps)
        if args.list:
            output: object = [{
                'app_id': app_id,
                'name': ctx.run_context.get_application_name(app_id),
                'unavailable_reason': ctx.get_application_unavailable_reason(app_id),
            } for app_id in ['one_dragon', *ctx.run_context.standalone_apps]]
        else:
            validate_request(ctx, args.app)
            if args.dry_run:
                output = describe_request(ctx, args.app)
            else:
                # init 会重新注册工厂；先清除预览注册，避免重复加入任务列表。
                ctx.run_context.clear_applications()
                ctx.init()
                if not ctx.ready_for_application:
                    raise RuntimeError(ctx.initialization_error or '上下文初始化失败')
                if interrupted.is_set():
                    raise KeyboardInterrupt

                import AppKit
                import Foundation

                # SCK 首次使用需要主线程先建立 NSApplication，但不创建任何窗口。
                if AppKit.NSApp() is None:
                    AppKit.NSApplication.sharedApplication().setActivationPolicy_(
                        AppKit.NSApplicationActivationPolicyProhibited,
                    )

                def pump() -> None:
                    """每次最多处理十毫秒原生事件，供采集和启动适配回调执行。"""
                    Foundation.NSRunLoop.currentRunLoop().runUntilDate_(
                        Foundation.NSDate.dateWithTimeIntervalSinceNow_(0.01),
                    )

                result = run_session(ctx, args.app, pump, interrupted)
                if interrupted.is_set():
                    raise KeyboardInterrupt
                output, exit_code = summarize_result(ctx, result)
                print(json.dumps(output, ensure_ascii=False), flush=True)
                return exit_code
        print(json.dumps(output, ensure_ascii=False, indent=2), flush=True)
        return 0
    except KeyboardInterrupt:
        print(json.dumps({'success': False, 'status': '运行已中断'}, ensure_ascii=False), flush=True)
        return 130
    except Exception as error:
        print(json.dumps({'success': False, 'status': str(error)}, ensure_ascii=False), flush=True)
        return 1
    finally:
        try:
            if ctx is not None:
                ctx.after_app_shutdown()
        finally:
            for sig, handler in handlers.items():
                signal.signal(sig, handler)


if __name__ == '__main__':
    raise SystemExit(main())
