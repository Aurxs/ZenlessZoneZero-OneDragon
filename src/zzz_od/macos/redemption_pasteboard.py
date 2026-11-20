"""暂存单枚兑换码给游戏自己的手柄粘贴键；不敲击系统键盘。"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


@contextmanager
def temporary_redemption_pasteboard(code: str) -> Iterator[None]:
    """写入前完整复制原项目；如果用户已更新剪贴板，不覆盖新内容。"""
    from AppKit import NSData, NSPasteboard, NSPasteboardItem, NSPasteboardTypeString
    from objc import autorelease_pool

    with autorelease_pool():
        pasteboard = NSPasteboard.generalPasteboard()
        if pasteboard is None:
            raise RuntimeError('无法访问系统剪贴板，未填写兑换码')
        original_change = pasteboard.changeCount()
        original = []
        for item in pasteboard.pasteboardItems() or ():
            copied = NSPasteboardItem.alloc().init()
            types = item.types()
            if not types:
                raise RuntimeError('剪贴板有无法无损恢复的项目，未填写兑换码')
            for item_type in types:
                data = item.dataForType_(item_type)
                if data is None or not copied.setData_forType_(NSData.dataWithData_(data), item_type):
                    raise RuntimeError('剪贴板有无法无损恢复的数据，未填写兑换码')
            original.append(copied)
        temporary = NSPasteboardItem.alloc().init()
        if not temporary.setString_forType_(code, NSPasteboardTypeString):
            raise RuntimeError('无法准备临时剪贴板，未填写兑换码')
        if pasteboard.changeCount() != original_change:
            raise RuntimeError('剪贴板刚被更新，未填写兑换码')

        temporary_change = pasteboard.clearContents()
        try:
            if not pasteboard.writeObjects_([temporary]):
                raise RuntimeError('无法写入临时剪贴板，未填写兑换码')
            if pasteboard.changeCount() != temporary_change:
                raise RuntimeError('剪贴板同时被更新，未填写兑换码')
            yield
        finally:
            if pasteboard.changeCount() == temporary_change:
                pasteboard.clearContents()
                if original and not pasteboard.writeObjects_(original):
                    raise RuntimeError('无法恢复原剪贴板，未提交兑换')
