"""把 ScreenCaptureKit 的 BGRA 缓冲转换为项目使用的 RGB 图片。"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class CapturedFrame:
    """保留实际采集时间与原始像素尺寸的一帧图片。"""

    image: NDArray[np.uint8]
    sequence: int
    capture_time: float
    monotonic_time: float
    raw_width: int
    raw_height: int
    pixel_scale: float = 1.0  # 原窗口逻辑点到当前输出像素的完整缩放。


def bgra_buffer_to_rgb(
    data: object,
    width: int,
    height: int,
    bytes_per_row: int,
    *,
    content_rect: tuple[float, float, float, float] | None = None,
    scale_factor: float = 1.0,
) -> NDArray[np.uint8]:
    """去除每行填充和内容区之外的像素，并复制数据脱离原生缓冲。

    SCK 的 contentRect 是输出 surface 内的点坐标；乘显示缩放得到像素。
    内容缩放已经反映在该矩形中，不再重复乘 contentScale。
    """
    if width <= 0 or height <= 0 or bytes_per_row < width * 4:
        raise ValueError('采集缓冲的尺寸或每行字节数无效')
    pixels = np.frombuffer(data, dtype=np.uint8, count=height * bytes_per_row)
    bgra = pixels.reshape(height, bytes_per_row)[:, :width * 4].reshape(height, width, 4)
    if content_rect is not None:
        if not math.isfinite(scale_factor) or scale_factor <= 0:
            raise ValueError('采集帧的点与像素缩放比例无效')
        x, y, rect_width, rect_height = content_rect
        if not all(math.isfinite(value) for value in content_rect):
            raise ValueError('采集内容区坐标无效')
        left, top = round(x * scale_factor), round(y * scale_factor)
        right = round((x + rect_width) * scale_factor)
        bottom = round((y + rect_height) * scale_factor)
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            raise ValueError('采集内容区超出原始像素范围')
        bgra = bgra[top:bottom, left:right]
    return cv2.cvtColor(bgra, cv2.COLOR_BGRA2RGB)


def normalize_game_frame(
    image: NDArray[np.uint8],
    *,
    content_rect: tuple[int, int, int, int] | None = None,
    top_inset_pixels: int = 0,
) -> NDArray[np.uint8]:
    """把明确的 16:9 游戏内容转成 1080p，拒绝拉伸其他比例。

    content_rect 是去除 SCK 填充后的图片内、已经确认的游戏区像素坐标。
    top_inset_pixels 只去掉已确认的顶部标题栏，保留每帧剩余完整宽高；
    非零时不能与 content_rect 同时使用。
    不自动猜测标题栏或黑边；未指定时要求整张内容区为 16:9。
    """
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError('游戏截图必须是 RGB uint8 图片')
    if type(top_inset_pixels) is not int or top_inset_pixels < 0:
        raise ValueError('顶部裁剪像素必须是非负整数')
    if top_inset_pixels and content_rect is not None:
        raise ValueError('顶部裁剪和固定游戏内容区不能同时使用')
    if top_inset_pixels >= image.shape[0]:
        raise ValueError('顶部裁剪像素超出截图高度')
    if top_inset_pixels:
        image = image[top_inset_pixels:, :]
    if content_rect is not None:
        x, y, width, height = content_rect
        if not (0 <= x < x + width <= image.shape[1] and 0 <= y < y + height <= image.shape[0]):
            raise ValueError('已配置的游戏内容区超出截图范围')
        image = image[y:y + height, x:x + width]
    height, width = image.shape[:2]
    if height == 0 or not math.isclose(width / height, 16 / 9, rel_tol=0.002):
        raise ValueError(f'游戏内容区为 {width}×{height}，需要先确认 16:9 内容区，不能直接拉伸')
    if (width, height) == (1920, 1080):
        return image.copy()
    interpolation = cv2.INTER_AREA if width > 1920 else cv2.INTER_LINEAR
    return cv2.resize(image, (1920, 1080), interpolation=interpolation)


def capture_timestamps(
    display_time: int,
    current_host_time: int,
    host_frequency: float,
    *,
    epoch_now: float,
    monotonic_now: float,
) -> tuple[float, float]:
    """将 SCK 的 mach 采集时间转换为 epoch 与 Python 单调时间。

    用同一 host 时钟上的时间差换算，不能把系统启动时长直接当 epoch。
    """
    if display_time <= 0 or host_frequency <= 0 or not math.isfinite(host_frequency):
        raise ValueError('采集帧缺少有效的 host 时间')
    age = (current_host_time - display_time) / host_frequency
    if age < 0:
        raise ValueError('采集帧时间晚于当前 host 时间')
    return epoch_now - age, monotonic_now - age
