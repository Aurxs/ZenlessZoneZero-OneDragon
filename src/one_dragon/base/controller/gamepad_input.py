"""手柄输入兼容层的公共接口，不加载任何平台驱动。"""

from dataclasses import dataclass
from typing import Literal, Protocol

GamepadSide = Literal['left', 'right']

_KEYS: tuple[str, ...] = (
    'south', 'east', 'west', 'north', 'left_shoulder', 'right_shoulder',
    'left_trigger', 'right_trigger', 'back', 'start', 'left_stick_click',
    'right_stick_click', 'guide', 'capture', 'dpad_up', 'dpad_down',
    'dpad_left', 'dpad_right', 'left_stick_up', 'left_stick_down',
    'left_stick_left', 'left_stick_right', 'right_stick_up',
    'right_stick_down', 'right_stick_left', 'right_stick_right',
)
_ALIASES: dict[str, str] = {key: key for key in _KEYS}
_ALIASES.update({key.replace('_', ''): key for key in _KEYS})
_ALIASES.update({
    'xbox_a': 'south', 'xbox_b': 'east', 'xbox_x': 'west', 'xbox_y': 'north',
    'xbox_lb': 'left_shoulder', 'xbox_rb': 'right_shoulder',
    'xbox_lt': 'left_trigger', 'xbox_rt': 'right_trigger',
    'xbox_back': 'back', 'xbox_start': 'start', 'xbox_guide': 'guide',
    'xbox_l_thumb': 'left_stick_click', 'xbox_r_thumb': 'right_stick_click',
})
for _direction in ('up', 'down', 'left', 'right'):
    _ALIASES[f'xbox_dpad_{_direction}'] = f'dpad_{_direction}'
    _ALIASES[f'xbox_ls_{_direction}'] = f'left_stick_{_direction}'
    _ALIASES[f'xbox_rs_{_direction}'] = f'right_stick_{_direction}'


def normalize_gamepad_key(key: str) -> str:
    """把既有 Xbox 配置值或位置名称转成公共名称，例如 xbox_a → south。"""
    try:
        return _ALIASES[key.casefold()]
    except (AttributeError, KeyError) as error:
        raise ValueError(f'不支持的手柄按键：{key!r}') from error


@dataclass(frozen=True)
class GamepadState:
    """完整手柄状态；摇杆范围 -1 到 1，正 Y 向下，扳机范围 0 到 1。"""

    buttons: frozenset[str] = frozenset()
    dpad: frozenset[str] = frozenset()
    left_stick: tuple[float, float] = (0.0, 0.0)
    right_stick: tuple[float, float] = (0.0, 0.0)
    left_trigger: float = 0.0
    right_trigger: float = 0.0


class GamepadInput(Protocol):
    """业务控制器依赖的手柄接口，具体适配器负责状态合并和平台输出。"""

    key_press_time: float
    combo_press_time: float

    @property
    def is_connected(self) -> bool:
        """返回输入连接是否仍可用。"""
        ...

    @property
    def state(self) -> GamepadState:
        """返回当前完整状态的不可变快照。"""
        ...

    @property
    def last_error(self) -> str | None:
        """返回最近一次传输失败的原因。"""
        ...

    def connect(self) -> None:
        """建立连接，从中立状态开始。"""
        ...

    def tap(self, key: str) -> None:
        """按下并在最短按键时长后释放。"""
        ...

    def press(self, key: str, press_time: float | None = None) -> None:
        """按住按键；指定时长时等待本次动作结束。"""
        ...

    def release(self, key: str) -> None:
        """释放指定按键。"""
        ...

    def tap_combo(self, keys: list[str]) -> None:
        """依次按住组合键，结束时按相反顺序释放。"""
        ...

    def set_stick(self, stick: GamepadSide, x: float, y: float,
                  press_time: float | None = None) -> None:
        """更新一根摇杆；指定时长时等待后归零。"""
        ...

    def set_trigger(self, trigger: GamepadSide, value: float,
                    press_time: float | None = None) -> None:
        """更新一个扳机；指定时长时等待后归零。"""
        ...

    def set_key_press_time(self, key_press_time: float) -> None:
        """设置点按的最短时长。"""
        ...

    def reset(self) -> None:
        """取消已有动作并发送中立状态，保留连接。"""
        ...

    def stop(self) -> None:
        """停止当前动作并归零。"""
        ...

    def suspend(self) -> None:
        """归零并禁止新动作，防止暂停后迟到的输入继续保持。"""
        ...

    def resume(self) -> None:
        """先发送中立状态，再恢复接收新动作。"""
        ...

    def close(self) -> None:
        """取消动作、释放状态并关闭连接。"""
        ...
