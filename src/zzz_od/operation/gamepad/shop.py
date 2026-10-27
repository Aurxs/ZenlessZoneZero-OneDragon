"""商店节点的手柄动作，只接受已经核实的页面提示与按键。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np

from one_dragon.base.controller.gamepad_input import normalize_gamepad_key
from one_dragon.utils import debug_utils
from one_dragon.utils.log_utils import log
from zzz_od.operation.gamepad.focus import highlight_mask

if TYPE_CHECKING:
    from cv2.typing import MatLike

    from one_dragon.base.matcher.match_result import MatchResultList
    from one_dragon.base.operation.operation import Operation
    from one_dragon.base.operation.operation_round_result import OperationRoundResult


# 按页面分别登记实拍确认的键位，不能从 PC 点击位置或默认焦点推断。
SHOP_ACTION_KEYS: dict[tuple[str, str], str] = {
    ('影像店营业', '关闭昨日账本'): 'east',
    ('影像店营业', '宣传员入口'): 'south',
    ('影像店营业', '录像带入口'): 'south',
    ('影像店营业', '返回经营页面'): 'east',
    ('影像店营业', '开始营业'): 'west',
    ('影像店营业', '确认宣传员'): 'south',
    ('影像店营业', '返回宣传员列表'): 'east',
    ('影像店营业', '推荐上架'): 'west',
    ('影像店营业', '返回录像带列表'): 'east',
}
DAILY_CONFIRM_ACTIONS: frozenset[str] = frozenset({
    '开始营业', '开始营业-确认', '营业后确认', '点单', '对话框确认', '电量确认',
})


def focused_business_card(operation: Operation) -> int | None:
    """识别经营页四张卡片的唯一黄框，索引 0 为宣传员，1—3 为录像带。"""
    area = operation.ctx.screen_loader.get_area('影像店营业', '手柄-经营卡片')
    if area is None or operation.last_screenshot is None:
        return None
    rect = area.rect
    image = operation.last_screenshot[rect.y1:rect.y2, rect.x1:rect.x2]
    if not image.size:
        return None
    mask = highlight_mask(image, 'yellow')
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    focused: list[int] = []
    centers = (115, 351, 592, 833)
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if not (160 <= width <= 245 and 250 <= height <= 300 and 0 <= y <= 25):
            continue
        if cv2.contourArea(contour) / (width * height) < 0.85:
            continue
        inside = mask[y + 12:y + height - 12, x + 12:x + width - 12]
        if not inside.size or np.count_nonzero(inside) / inside.size > 0.15:
            continue
        index = min(range(4), key=lambda item: abs(centers[item] - x - width / 2))
        if abs(centers[index] - x - width / 2) < 30:
            focused.append(index)
    return focused[0] if len(focused) == 1 else None


def read_shop_area(
    operation: Operation, area_name: str,
) -> tuple[MatLike, dict[str, MatchResultList]] | None:
    """只识别店铺已经建档的整段区域，避免把小字框当成检测输入。"""
    area = operation.ctx.screen_loader.get_area('影像店营业', area_name)
    if area is None or operation.last_screenshot is None:
        return None
    rect = area.rect
    image = operation.last_screenshot[rect.y1:rect.y2, rect.x1:rect.x2]
    if not image.size:
        return None
    return image, operation.ctx.ocr.crop_and_run_ocr(operation.last_screenshot, rect)


def shop_name(text: str) -> str:
    """移除宣传员名两侧的装饰引号与空白。"""
    return ''.join(text.split()).strip('「」『』')


def promoter_name(text: str) -> str:
    """宣传页使用柚叶简称，配置仍沿原代理人全名。"""
    name = shop_name(text)
    return {'柚叶': '浮波柚叶'}.get(name, name)


def business_card_titles(operation: Operation) -> list[str | None]:
    """从主页面四列标题读取实际宣传员与影片，空卡不算准备完成。"""
    read = read_shop_area(operation, '手柄-卡片标题')
    titles: list[str | None] = [None] * 4
    if read is None:
        return titles
    centers = (135, 371, 612, 853)
    for text, matches in read[1].items():
        match = matches.max
        name = shop_name(text)
        if match is None or not 25 <= match.center.y <= 85 or len(name) < 2:
            continue
        if name in ('选择宣传员', 'EMPTY'):
            continue
        index = min(range(4), key=lambda item: abs(centers[item] - match.center.x))
        if abs(centers[index] - match.center.x) < 115:
            titles[index] = promoter_name(name) if index == 0 else name
    return titles


def business_themes_complete(operation: Operation) -> bool:
    """三项主题均出现实拍确认的蓝色完成标记，不能把未上架的黄色零当完成。"""
    area = operation.ctx.screen_loader.get_area('影像店营业', '手柄-主题完成标记')
    if area is None or operation.last_screenshot is None:
        return False
    rect = area.rect
    image = operation.last_screenshot[rect.y1:rect.y2, rect.x1:rect.x2]
    if not image.size:
        return False
    mask = highlight_mask(image, 'blue')
    return all(np.count_nonzero(mask[:, left:right]) >= 60
               for left, right in ((0, 75), (90, 185), (210, 285)))


def focused_promoter_name(operation: Operation, valid_names: set[str]) -> str | None:
    """黄框必须围住真实人物卡，且卡片名称是已知宣传员，不确认空卡。"""
    read = read_shop_area(operation, '手柄-宣传员列表')
    if read is None:
        return None
    image, results = read
    contours, _ = cv2.findContours(highlight_mask(image, 'yellow'), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    frames: list[tuple[int, int, int, int]] = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if 160 <= width <= 240 and 250 <= height <= 330 \
                and cv2.contourArea(contour) / (width * height) >= 0.85:
            frames.append((x, y, width, height))
    if len(frames) != 1:
        return None
    x, y, width, height = frames[0]
    names = {
        promoter_name(text) for text, matches in results.items()
        if matches.max is not None and promoter_name(text) in valid_names
        and x <= matches.max.center.x <= x + width
        and y + height - 70 <= matches.max.center.y <= y + height
    }
    if not names:
        detail = read_shop_area(operation, '手柄-宣传员详情名称')
        if detail is not None:
            names = {promoter_name(text) for text in detail[1] if promoter_name(text) in valid_names}
    return next(iter(names)) if len(names) == 1 else None


def save_shop_frame(operation: Operation, screen_name: str, stage: str) -> str | None:
    """保存当前关键帧并确认文件存在，失败时不能继续消耗每日机会。"""
    if operation.last_screenshot is None:
        return None
    file_name = operation.save_screenshot(prefix=f'Mac_{screen_name}_{stage}')
    if not file_name:
        return None
    path = Path(debug_utils.get_debug_image_path(file_name))
    if not path.is_file():
        return None
    log.info('商店关键帧 %s', path)
    return str(path)


def fail_shop_state(
    operation: Operation, screen_name: str, reason: str,
) -> OperationRoundResult:
    """未知店铺状态先留图，再保留具体失败原因。"""
    save_shop_frame(operation, screen_name, '未完成')
    return operation.round_fail(reason)


def press_shop_action(
    operation: Operation, screen_name: str, action_name: str,
) -> OperationRoundResult:
    """专属提示区域命中后点按一次，未知动作不发送输入。"""
    key = SHOP_ACTION_KEYS.get((screen_name, action_name))
    if key is None:
        return fail_shop_state(operation, screen_name, f'{screen_name}手柄动作尚未建档：{action_name}')
    area_name = f'手柄-{action_name}'
    area = operation.ctx.screen_loader.get_area(screen_name, area_name)
    if area is None or not area.can_match:
        return fail_shop_state(operation, screen_name, f'{screen_name}手柄提示尚未建档：{action_name}')
    if operation.last_screenshot is None:
        return operation.round_retry('截图无效', wait=1)
    found = operation.round_by_find_area(operation.last_screenshot, screen_name, area_name)
    if not found.is_success:
        save_shop_frame(operation, screen_name, f'{action_name}_提示未出现')
        return operation.round_retry(f'等待{screen_name}手柄提示：{action_name}', wait=1)
    if action_name in DAILY_CONFIRM_ACTIONS and operation.node_clicked:
        return fail_shop_state(operation, screen_name, f'{action_name}已发送，不重复确认每日操作')
    if save_shop_frame(operation, screen_name, f'{action_name}_操作前') is None:
        return operation.round_fail(f'未能保存{action_name}操作前画面')
    # 先记录发送意图；若输入或后续截图抛异常，重试时也不能重复确认。
    if action_name in DAILY_CONFIRM_ACTIONS:
        operation.node_clicked = True
    operation.ctx.controller.btn_tap(normalize_gamepad_key(key))
    operation.round_success(wait=1)
    operation.screenshot()
    if save_shop_frame(operation, screen_name, f'{action_name}_操作后') is None:
        return operation.round_fail(f'未能保存{action_name}操作后画面')
    return operation.round_success(action_name)
