"""原生手柄画面的填充高亮与整行边框识别。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import cv2
import numpy as np

from one_dragon.base.geometry.rectangle import Rect

if TYPE_CHECKING:
    from cv2.typing import MatLike


def highlight_mask(image: MatLike, color: Literal['yellow', 'blue']) -> MatLike:
    """按 RGB 截图生成黄色或蓝色高亮掩码。"""
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    lower, upper = (
        ((20, 80, 90), (45, 255, 255))
        if color == 'yellow'
        else ((95, 80, 80), (125, 255, 255))
    )
    return cv2.inRange(hsv, lower, upper)


def has_filled_highlight(
    image: MatLike, text_rect: Rect, color: Literal['yellow', 'blue']
) -> bool:
    """要求文字周围有大块填充，文字本身或角落 NEW 标记不能算选中。"""
    height, width = image.shape[:2]
    pad_x, pad_y = text_rect.width // 2, text_rect.height // 2
    crop = image[
        max(0, text_rect.y1 - pad_y):min(height, text_rect.y2 + pad_y),
        max(0, text_rect.x1 - pad_x):min(width, text_rect.x2 + pad_x),
    ]
    return bool(crop.size and np.count_nonzero(highlight_mask(crop, color)) / crop.shape[0] / crop.shape[1] >= 0.35)


def find_yellow_frames(image: MatLike) -> list[Rect]:
    """寻找副本行的大矩形边框，排除小按钮和孤立色块。"""
    contours, _ = cv2.findContours(
        highlight_mask(image, 'yellow'), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    frames: list[Rect] = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if width < 450 or height < 100 or height > 450:
            continue
        if cv2.contourArea(contour) / (width * height) < 0.75:
            continue
        frames.append(Rect(x, y, x + width, y + height))
    return frames


def text_inside_frame(text_rect: Rect, frames: list[Rect]) -> bool:
    """仅当完整文字框被整行边框包住时确认副本焦点。"""
    return any(
        frame.x1 < text_rect.x1 < text_rect.x2 < frame.x2
        and frame.y1 < text_rect.y1 < text_rect.y2 < frame.y2
        for frame in frames
    )
