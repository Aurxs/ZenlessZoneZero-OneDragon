"""修正移动端 NPC 武备标记与副本入口的图形混淆。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2

from one_dragon.yolo.detect_utils import DetectFrameResult, DetectObjectResult

if TYPE_CHECKING:
    from one_dragon.base.matcher.template_matcher import TemplateMatcher
    from one_dragon.yolo.detect_utils import DetectClass


def correct_npc_gear_markers(
    frame: DetectFrameResult,
    matcher: TemplateMatcher,
    interact_class: DetectClass,
    ignore_interact: bool = False,
) -> DetectFrameResult:
    """只改模型误认的盾牌，保留真实入口及原忽略感叹号的语义。"""
    corrected: list[DetectObjectResult] = []
    template = matcher.template_loader.get_template('ios_gamepad', 'lost_void_npc_gear')
    if template is None:
        return frame
    height, width = template.raw.shape[:2]
    for item in frame.results:
        is_npc = False
        if item.detect_class.class_name == '0003-战斗-武备':
            crop = frame.raw_image[max(0, item.y1):item.y2, max(0, item.x1):item.x2]
            if crop.size:
                normalized = cv2.resize(crop, (width, height), interpolation=cv2.INTER_LINEAR)
                is_npc = matcher.match_template(normalized, 'ios_gamepad', 'lost_void_npc_gear', threshold=0.8).max is not None
        if not is_npc:
            corrected.append(item)
        elif not ignore_interact:
            corrected.append(DetectObjectResult([item.x1, item.y1, item.x2, item.y2], item.score, interact_class))
    return DetectFrameResult(frame.raw_image, corrected, frame.run_time)
