"""用同一个交互图标的实际位移校准 Mac 右摇杆转向。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from one_dragon.base.operation.operation_node import operation_node
from one_dragon.utils import gpu_executor
from zzz_od.application.hollow_zero.lost_void.context.lost_void_detector import (
    LostVoidDetector,
)
from zzz_od.application.hollow_zero.lost_void.operation.lost_void_move_by_det import (
    LostVoidMoveByDet,
)
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation
from zzz_od.operation.gamepad.transport_by_compendium import (
    GamepadTransportByCompendium,
)

if TYPE_CHECKING:
    from one_dragon.base.geometry.point import Point
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class GamepadLostVoidCalibrateTurn(GamepadOperation):
    """只在唯一感叹号可追踪时短幅转向，不移动角色或触发交互。"""

    def __init__(self, ctx: ZContext, force: bool = False) -> None:
        super().__init__(ctx, op_name='手柄迷失之地转向校准', timeout_seconds=15)
        self._before_x: float | None = None
        self._direction: float = 0
        self._duration: float = 0.16
        self._amplitude: float = 0.5
        self.force: bool = force
        self._after_x: float | None = None
        self._forward_shift: float = 0
        self._menu_closed: bool = False

    @operation_node(name='校准图标转向', is_start_node=True, node_max_retry_times=5)
    def calibrate(self) -> OperationRoundResult:
        """一次输入后须读到同一唯一目标的方向正确位移，才保存本实例参数。"""
        if not self.force and self.ctx.macos_config.turn_distance_per_second > 0:
            return self.round_success('已有 Mac 转向校准')
        if self.last_screenshot is None:
            return self.round_retry('等待有效游戏截图', wait=1)
        if not self.ctx.lost_void.in_normal_world(self.last_screenshot):
            nav = GamepadTransportByCompendium(self.ctx, '作战', '周期征讨')
            nav.last_screenshot = self.last_screenshot
            area = nav._read_area('迷失之地-大世界', '手柄-战况返回')
            if area and all(nav._text_rect(area[1], word) is not None for word in ('重新开始', '退出战斗', '返回')):
                if not self._menu_closed:
                    self.ctx.controller.btn_tap('east')
                    self._menu_closed = True
                return self.round_retry('等待战况菜单关闭', wait=1)
            return self.round_retry('等待局内可追踪图标', wait=1)
        if self.ctx.lost_void.detector is None:
            self.ctx.lost_void.init_lost_void_det_model()
        frame = gpu_executor.submit(self.ctx.lost_void.detector.run, self.last_screenshot, run_time=self.last_screenshot_time).result()
        targets = [item for item in frame.results if item.detect_class.class_name == LostVoidDetector.CLASS_INTERACT]
        if len(targets) != 1:
            return self.round_retry('校准需要唯一感叹号，未发送转向', wait=1)
        x = float(targets[0].center[0])
        if self._before_x is None:
            if not self.ctx.run_context.is_context_running:
                return self.round_fail('运行已暂停，未发送校准输入')
            self._direction = 1.0 if x > 960 else -1.0
            # resume_input 会核对有效新帧和连接；校准脉冲仍经原手柄抽象层。
            self.ctx.controller.move_camera(self._direction * self._amplitude, 0, press_time=self._duration)
            self._before_x = x
            return self.round_retry('等待短幅转向后的同一图标', wait=0.6)
        moved = (self._before_x - x) * self._direction if self._after_x is None else (x - self._after_x) * self._direction
        if not 20 <= moved <= 700:
            return self.round_fail(f'Mac 转向校准位移不可信：{moved:.1f}像素，未保存')
        if self._after_x is None:
            self._forward_shift = moved
            self._after_x = x
            self.ctx.controller.move_camera(-self._direction * self._amplitude, 0, press_time=self._duration)
            return self.round_retry('等待反向校准与恢复原朝向', wait=0.6)
        error = abs(self._before_x - x)
        if error > 150 or abs(moved - self._forward_shift) / max(moved, self._forward_shift) > 0.35:
            return self.round_fail(f'双向校准不一致：正向{self._forward_shift:.1f}，反向{moved:.1f}，回差{error:.1f}，未覆盖原参数')
        speed = round((moved + self._forward_shift) / 2 / self._duration, 1)
        self.ctx.macos_config.turn_distance_per_second = speed
        self.ctx.macos_config.turn_stick_amplitude = self._amplitude
        self.save_screenshot(prefix='macos_lost_void_turn_calibrated')
        return self.round_success('Mac 转向校准已保存', data={'distance_per_second': speed, 'pixel_shift': moved, 'round_trip_error': error})


class GamepadLostVoidMoveByDet(LostVoidMoveByDet):
    """沿用目标、移动与脱困，仅将像素偏差转为有界右摇杆脉冲。"""

    def turn_to_target(self, target: Point, is_moving: bool = False, calibration_axis: str = 'x') -> bool:
        """短时低幅转向处理小偏差，避免原鼠标单位产生过短的满幅摇杆输入。"""
        speed = self.ctx.macos_config.turn_distance_per_second
        if speed <= 0:
            raise ValueError('请先完成 Mac 迷失之地转向校准')
        diff = target.x - self.ctx.controller.standard_width / 2
        if abs(diff) < (80 if is_moving else 70):
            return False
        duration = min(0.15, max(0.04, abs(diff) * 0.65 / speed))
        amplitude = self.ctx.macos_config.turn_stick_amplitude
        self.ctx.controller.move_camera(amplitude if diff > 0 else -amplitude, 0, press_time=duration)
        return True
