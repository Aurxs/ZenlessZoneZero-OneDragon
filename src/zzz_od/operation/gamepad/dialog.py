"""根据右侧选项文字和唯一填充高亮选择原生手柄对话。"""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING

from one_dragon.base.operation.operation_node import operation_node
from one_dragon.utils.i18_utils import gt
from zzz_od.operation.gamepad.focus import has_filled_highlight
from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation
from zzz_od.operation.gamepad.shop import save_shop_frame

if TYPE_CHECKING:
    from one_dragon.base.matcher.match_result import MatchResult
    from one_dragon.base.operation.operation_round_result import OperationRoundResult
    from zzz_od.context.zzz_context import ZContext


class GamepadChooseDialogOption(GamepadOperation):
    """逐帧移动选项，只报告已经确认的目标，不判断调用方业务完成。"""

    def __init__(self, ctx: ZContext, option: str, prompt_threshold: float = 0.85) -> None:
        """使用调用方指定的完整选项，不默认选择当前行。"""
        super().__init__(ctx, op_name=f'手柄对话选择 {option}', timeout_seconds=25)
        self.option: str = option
        self.prompt_threshold: float = prompt_threshold
        self.evidence: dict[str, str] = {}
        self._confirm_sent: bool = False
        self._completed: bool = False
        self._moves: int = 0
        self._confirm_attempts: int = 0
        self._last_action_frame_time: float = -1

    def handle_init(self) -> None:
        """重复执行时重新识别当前帧，不沿用上次焦点。"""
        self.evidence = {}
        self._confirm_sent = False
        self._completed = False
        self._moves = 0
        self._confirm_attempts = 0
        self._last_action_frame_time = -1

    @staticmethod
    def _normalized(text: str) -> str:
        """统一全角半角并移除空白，仍完整匹配，不删词或模糊选分支。"""
        return ''.join(unicodedata.normalize('NFKC', text).split())

    def _save(self, stage: str) -> bool:
        """保存选项前后及未知状态，操作前无法留图时不确认。"""
        path = save_shop_frame(self, '手柄对话', stage)
        if path is not None:
            self.evidence[stage] = path
        return path is not None

    def _fail(self, reason: str) -> OperationRoundResult:
        """未知对话只保存当前帧，不盲目推进或退出。"""
        self._save('选项未完成')
        return self.round_fail(reason, data={'option': self.option, 'evidence': dict(self.evidence)})

    @staticmethod
    def _same_row(first: MatchResult, second: MatchResult) -> bool:
        """按文字行中心比对，不要求单字 A 与中文有相同高度。"""
        return abs(first.center.y - second.center.y) <= max(40, first.h, second.h)

    @operation_node(name='选择对话选项', is_start_node=True, node_max_retry_times=15)
    def choose_option(self) -> OperationRoundResult:
        """唯一当前行与目标都可见后逐行移焦，A 提示同排时只确认一次。"""
        if self._completed:
            return self.round_success(f'已选择{self.option}', data={
                'option': self.option, 'evidence': dict(self.evidence),
            })
        if self._confirm_sent:
            return self._fail('对话确认已尝试发送，结果未留图，不重复确认')
        if self.last_screenshot is None:
            return self._fail('对话截图无效，未发送输入')
        area = self.ctx.screen_loader.get_area('大世界', '手柄-对话选项带')
        if area is None:
            return self._fail('手柄对话选项带尚未建档')
        rect = area.rect
        image = self.last_screenshot[rect.y1:rect.y2, rect.x1:rect.x2]
        if not image.size:
            return self._fail('手柄对话选项带为空')
        results = self.ctx.ocr.crop_and_run_ocr(self.last_screenshot, rect)
        options: list[tuple[str, MatchResult]] = [
            (self._normalized(text), matches.max)
            for text, matches in results.items()
            if self._normalized(text) not in ('', 'A') and matches.max is not None
            and matches.max.x >= 100
        ]
        target_name = self._normalized(gt(self.option, 'game'))
        targets = [match for name, match in options if name == target_name]
        if not targets and self._confirm_attempts:
            self._completed = True
            return self.round_success(f'已选择{self.option}', data={
                'option': self.option, 'evidence': dict(self.evidence),
            })
        if len(targets) != 1:
            return self._fail(f'无法确认完整对话选项：{self.option}')
        target = targets[0]
        selected = [
            (name, match) for name, match in options
            if abs(match.x - target.x) <= 40
            if has_filled_highlight(image, match.rect, 'yellow')
        ]
        if len(selected) != 1:
            return self._fail(f'无法确认目标与唯一对话焦点：{self.option}')
        selected_name, current = selected[0]
        if selected_name != target_name:
            if self._moves >= 10:
                return self._fail(f'对话移焦次数超限：{self.option}')
            if self.last_screenshot_time <= self._last_action_frame_time:
                return self.round_retry('等待对话移焦后的新帧', wait=0.3)
            self._last_action_frame_time = self.last_screenshot_time
            self.ctx.controller.btn_tap('dpad_down' if target.center.y > current.center.y else 'dpad_up')
            self._moves += 1
            return self.round_retry(f'等待对话焦点移至{self.option}', wait=0.5)

        prompts = [
            matches.max for text, matches in results.items()
            if self._normalized(text) == 'A' and matches.max is not None
        ]
        if not prompts:
            # 小图标在整段 OCR 中偶尔被漏检，用同一实拍 A 图标补充定位。
            prompts = list(self.ctx.tm.match_template(image, 'ios_gamepad', 'dialog_a', threshold=self.prompt_threshold))
        if not any(prompt.x + prompt.w < current.x and self._same_row(prompt, current) for prompt in prompts):
            return self._fail('目标已高亮但同排 A 提示缺失，未确认')
        if not self._save('选项确认前'):
            return self.round_fail('未能保存对话确认前画面')
        if self._confirm_attempts >= 3:
            return self._fail('同一对话选项确认后仍未退出')
        # 先记录发送意图，异常重试不能再次确认可能消耗每日机会的选项。
        self._confirm_sent = True
        self._confirm_attempts += 1
        self.ctx.controller.btn_tap('south')
        self.round_success(wait=0.8)
        self.screenshot()
        if not self._save('选项确认后'):
            return self.round_fail('未能保存对话确认后画面')
        # 交互动画中 A 可能只补全台词。新帧仍完整显示同一选项和焦点才再次确认。
        self._confirm_sent = False
        return self.round_retry('等待对话选项关闭', wait=0.5)


class GamepadReconnect(GamepadOperation):
    """仅确认已识别的服务器超时弹窗，不重新登录或处理账号验证。"""

    def __init__(self, ctx: ZContext) -> None:
        """一次确认后等待弹窗消失，业务页面由调用方重新识别。"""
        super().__init__(ctx, op_name='手柄继续服务器连接', timeout_seconds=20)
        self._sent: bool = False

    def handle_init(self) -> None:
        self._sent = False

    @operation_node(name='确认继续连接', is_start_node=True, node_max_retry_times=12)
    def reconnect(self) -> OperationRoundResult:
        """完整超时文案和继续连接黄色焦点同时成立才发送 A。"""
        if self.last_screenshot is None:
            return self.round_retry('等待网络弹窗截图', wait=1)
        words = self.ctx.ocr.run_ocr(self.last_screenshot)
        timeout = any('服务器连接超时' in text.replace(' ', '') for text in words)
        if not timeout:
            return self.round_success('连接弹窗已关闭，须重新识别业务页面') if self._sent else self.round_fail('未识别到服务器连接超时弹窗')
        if self._sent:
            return self.round_retry('等待服务器连接，不重复确认', wait=1)
        choices = [match for text, matches in words.items() if text.replace(' ', '') == '继续连接'
                   for match in matches if has_filled_highlight(self.last_screenshot, match.rect, 'yellow')]
        if len(choices) != 1:
            return self.round_fail('继续连接未处于唯一高亮，未发送输入')
        self.ctx.controller.btn_tap('south')
        self._sent = True
        return self.round_retry('已请求继续连接', wait=1)
