"""使用当前 Mac 实例运行一次实战模拟室，主线程持续处理 Cocoa 采集事件。"""

from __future__ import annotations

import argparse
import json
import platform
import signal
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import FrameType

    from one_dragon.base.operation.operation_base import OperationResult
    from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem
    from zzz_od.context.zzz_context import ZContext


def run_single(
    ctx: ZContext,
    plan: ChargePlanItem,
    entry: Literal['world', 'simulation'],
    prepare_only: bool,
) -> OperationResult:
    """在同一次运行中复用手册导航与单次挑战，不更改已保存计划。"""
    from zzz_od.operation.gamepad.combat_simulation import GamepadCombatSimulation
    from zzz_od.operation.gamepad.transport_by_compendium import (
        GamepadTransportByCompendium,
    )

    if entry == 'world':
        result = GamepadTransportByCompendium(
            ctx, plan.tab_name, plan.category_name, plan.mission_type_name
        ).execute()
        if not result.success:
            return result
    return GamepadCombatSimulation(ctx, plan, prepare_only=prepare_only).execute()


def run_session(
    ctx: ZContext,
    plan: ChargePlanItem,
    entry: Literal['world', 'simulation'],
    prepare_only: bool,
    pump: Callable[[], None],
) -> OperationResult:
    """主线程绑定一次采集，工作线程执行操作，退出前停止并持续处理事件。"""
    if not ctx.run_context.start_running():
        raise RuntimeError('运行前控制器初始化失败')
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='mac_simulation')
    future = executor.submit(run_single, ctx, plan, entry, prepare_only)
    try:
        while not future.done():
            pump()
        return future.result()
    finally:
        ctx.run_context.stop_running()
        # 停止后让 Operation 完成清理，期间不能阻塞主线程采集事件。
        while not future.done():
            pump()
        executor.shutdown(wait=True)


def _interrupt(signum: int, frame: FrameType | None) -> None:
    """终止信号沿用中断清理路径。"""
    raise KeyboardInterrupt


def main() -> int:
    """读取现有实例配置，在当前桌面执行单次挑战。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--entry', choices=('world', 'simulation'), default='world')
    parser.add_argument('--prepare-only', action='store_true', help='只到当前编队出战页')
    parser.add_argument('--auto-battle', default='Mac全配队通用', help='已有自动战斗策略名称')
    args = parser.parse_args()
    if sys.platform != 'darwin' or platform.machine().lower() not in ('arm64', 'aarch64'):
        parser.error('此入口需要 Apple Silicon macOS 和原生 arm64 Python')

    import Foundation

    from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem
    from zzz_od.context.zzz_context import ZContext

    def pump() -> None:
        """每次最多处理十毫秒 Cocoa 事件，保持 SCK 回调可运行。"""
        Foundation.NSRunLoop.currentRunLoop().runUntilDate_(
            Foundation.NSDate.dateWithTimeIntervalSinceNow_(0.01)
        )

    signal.signal(signal.SIGTERM, _interrupt)
    ctx = ZContext()
    try:
        ctx.init()
        if not ctx.ready_for_application:
            raise RuntimeError(ctx.initialization_error or '上下文初始化失败')
        plan = ChargePlanItem(auto_battle_config=args.auto_battle, plan_times=1)
        result = run_session(ctx, plan, args.entry, args.prepare_only, pump)
        print(json.dumps({
            'success': result.success,
            'status': result.status,
            'completed_battles': plan.run_times,
        }, ensure_ascii=False), flush=True)
        return 0 if result.success else 1
    except KeyboardInterrupt:
        print(json.dumps({'success': False, 'status': '运行已中断'}, ensure_ascii=False), flush=True)
        return 130
    finally:
        ctx.after_app_shutdown()


if __name__ == '__main__':
    raise SystemExit(main())
