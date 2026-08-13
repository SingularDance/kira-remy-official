# -*- coding: utf-8 -*-
"""思考模式能力：请求增强、响应解析、云朵气泡 UI。

不支持思考的供应商不会启用相关参数或 UI，避免报错。
"""

from __future__ import annotations

from collections.abc import Callable
from math import ceil
import re
import time

from PyQt5.QtCore import QPoint, QRect, QSize, Qt, QTimer
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPen,
    QRegion,
    QTextDocument,
)
from PyQt5.QtWidgets import QLabel, QTextEdit, QWidget

COMPLETION_MAX_TOKENS = 2048
NON_THINKING_MAX_TOKENS = 128
GENERIC_THOUGHT = "大脑在快速思考中..."
PLACEHOLDER_REASONING = frozenset({"...", "……", "嗯...", "嗯……"})
MIN_THINKING_DURATION_MS = 800
MAX_THINKING_DURATION_MS = 20000
MIN_TYPE_INTERVAL_MS = 40
MAX_TYPE_INTERVAL_MS = 80
HOLD_BASE_MS = 3000
HOLD_MS_PER_CHAR = 50
HOLD_MAX_MS = 20000
MIN_TEXT_WIDTH = 104
PREFERRED_TEXT_WIDTH = 140
MAX_TEXT_WIDTH = 420
MIN_BUBBLE_HEIGHT = 72
HORIZONTAL_PADDING = 28
TOP_PADDING = 20
BOTTOM_PADDING = 38
TEXT_GAP = 2
TAIL_HEIGHT = 28
HORIZONTAL_GAP = 6
VERTICAL_GAP = 4
HEAD_X_RATIO = 0.58
HEAD_Y_RATIO = 0.28
WIDTH_SEARCH_STEP = 8
ELAPSED_TICK_MS = 1000


def thinking_header_text(seconds: int) -> str:
    return f"正在思考（已思考{max(0, seconds)}秒...）"


def hold_duration_ms(text: str) -> int:
    return min(
        HOLD_MAX_MS,
        HOLD_BASE_MS + len(text or "") * HOLD_MS_PER_CHAR,
    )


def supports_thinking(provider: dict[str, object] | None) -> bool:
    if not isinstance(provider, dict):
        return False
    return bool(provider.get("supports_thinking", False))


def apply_thinking_request(
    provider: dict[str, object] | None,
    data: dict[str, object],
    enabled: bool = False,
) -> dict[str, object]:
    payload = dict(data)
    if not supports_thinking(provider):
        return payload
    payload["thinking"] = {
        "type": "enabled" if enabled else "disabled"
    }
    if not enabled:
        payload["max_tokens"] = NON_THINKING_MAX_TOKENS
        return payload
    payload["max_tokens"] = COMPLETION_MAX_TOKENS
    payload["stream"] = True
    return payload


def extract_reasoning(message: object) -> str:
    if not isinstance(message, dict):
        return ""
    value = message.get("reasoning_content")
    if not isinstance(value, str):
        return ""
    return normalize_reasoning(value)


def normalize_reasoning(text: str) -> str:
    cleaned = (text or "").strip()
    return "" if cleaned in PLACEHOLDER_REASONING else cleaned


def preview_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    return cleaned or GENERIC_THOUGHT


def type_interval_ms(text_length: int) -> int:
    safe_length = max(text_length, 1)
    duration = min(
        MAX_THINKING_DURATION_MS,
        max(MIN_THINKING_DURATION_MS, safe_length * 60),
    )
    interval = duration // safe_length
    return max(MIN_TYPE_INTERVAL_MS, min(MAX_TYPE_INTERVAL_MS, interval))


class ThinkingCloudBubble(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if parent is None:
            self.setWindowFlags(
                Qt.Tool
                | Qt.FramelessWindowHint
                | Qt.WindowStaysOnTopHint
            )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.PointingHandCursor)
        self._text = ""
        self._tail_on_right = False
        self._on_clicked: Callable[[], None] | None = None
        self._content_rect = QRect()
        self._canvas_ready = False

        self._header = QLabel(thinking_header_text(0), self)
        header_font = QFont("Microsoft YaHei", 8)
        self._header.setFont(header_font)
        self._header.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._header.setStyleSheet("""
            QLabel {
                color: #a5afb5;
                background-color: transparent;
                border: none;
            }
        """)

        self._body = QTextEdit(self)
        body_font = QFont("Microsoft YaHei", 9)
        self._body.setFont(body_font)
        self._body.setReadOnly(True)
        self._body.setAcceptRichText(False)
        self._body.setLineWrapMode(QTextEdit.WidgetWidth)
        self._body.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._body.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._body.document().setDocumentMargin(0)
        self._body.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._body.setCursor(Qt.PointingHandCursor)
        self._body.mousePressEvent = self._body_mouse_press
        self._body.setStyleSheet("""
            QTextEdit {
                color: #71808a;
                background-color: transparent;
                border: none;
                padding: 0;
            }
        """)
        self.hide()

    def set_click_handler(self, handler: Callable[[], None] | None) -> None:
        self._on_clicked = handler

    def _body_mouse_press(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.LeftButton
            and self._on_clicked is not None
        ):
            self._on_clicked()
            event.accept()
            return
        event.ignore()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.LeftButton
            and self._on_clicked is not None
            and self._content_rect.contains(event.pos())
        ):
            self._on_clicked()
            event.accept()
            return
        event.ignore()

    def set_elapsed_seconds(self, seconds: int) -> None:
        self._header.setText(thinking_header_text(seconds))
        if self._canvas_ready:
            self._relayout_labels()

    def header_width(self) -> int:
        return self._header.fontMetrics().horizontalAdvance(
            self._header.text(),
        )

    def set_visible_body(self, body: str) -> None:
        self._text = body or "……"

    def reset_canvas(self) -> None:
        self._canvas_ready = False
        self._content_rect = QRect()
        self.clearMask()

    def has_canvas(self) -> bool:
        return self._canvas_ready

    def ensure_canvas(self, width: int, height: int) -> None:
        """画布只增不减，避免播放中反复改系统窗口尺寸。"""
        width = max(width, MIN_TEXT_WIDTH + HORIZONTAL_PADDING * 2)
        height = max(height, MIN_BUBBLE_HEIGHT)
        if not self._canvas_ready:
            self.setFixedSize(width, height)
            self._canvas_ready = True
            return
        new_w = max(self.width(), width)
        new_h = max(self.height(), height)
        if new_w != self.width() or new_h != self.height():
            self.setFixedSize(new_w, new_h)

    def _resolve_text_width(self, text_width: int) -> int:
        return max(MIN_TEXT_WIDTH, text_width, self.header_width())

    def measure_height(self, text_width: int) -> int:
        text_width = self._resolve_text_width(text_width)
        body_height = self._text_height(self._text, text_width)
        header_height = self._header.fontMetrics().lineSpacing()
        return max(
            MIN_BUBBLE_HEIGHT,
            TOP_PADDING
            + header_height
            + TEXT_GAP
            + body_height
            + BOTTOM_PADDING,
        )

    def apply_content(
        self,
        text_width: int,
        tail_on_right: bool,
    ) -> QSize:
        """在固定画布内更新内容区，不改窗口大小（画布不够时由 ensure_canvas）。"""
        text_width = self._resolve_text_width(text_width)
        content_h = self.measure_height(text_width)
        if self._canvas_ready:
            content_h = min(content_h, self.height())
        content_w = text_width + HORIZONTAL_PADDING * 2
        self.ensure_canvas(content_w, content_h)
        self._tail_on_right = tail_on_right

        if tail_on_right:
            left = self.width() - content_w
        else:
            left = 0
        top = self.height() - content_h
        self._content_rect = QRect(left, top, content_w, content_h)

        self._body.setFixedWidth(text_width)
        self._body.setPlainText(self._text)
        self._relayout_labels()

        # 仅内容区可点，空白画布点击穿透观感更好
        self.setMask(QRegion(self._content_rect))
        self.update()
        return QSize(content_w, content_h)

    def _relayout_labels(self) -> None:
        if self._content_rect.isNull():
            return
        header_h = self._header.fontMetrics().lineSpacing()
        text_width = max(
            MIN_TEXT_WIDTH,
            self._content_rect.width() - HORIZONTAL_PADDING * 2,
        )
        self._header.setGeometry(
            self._content_rect.left() + HORIZONTAL_PADDING,
            self._content_rect.top() + TOP_PADDING,
            text_width,
            header_h,
        )
        body_top = (
            self._content_rect.top()
            + TOP_PADDING
            + header_h
            + TEXT_GAP
        )
        body_h = max(
            self._body.fontMetrics().lineSpacing(),
            self._content_rect.bottom()
            - BOTTOM_PADDING
            - body_top
            + 1,
        )
        self._body.setGeometry(
            self._content_rect.left() + HORIZONTAL_PADDING,
            body_top,
            text_width,
            body_h,
        )

    def _text_height(self, text: str, width: int) -> int:
        document = QTextDocument()
        document.setDefaultFont(self._body.font())
        document.setTextWidth(width)
        document.setPlainText(text)
        return max(
            self._body.fontMetrics().lineSpacing(),
            ceil(document.size().height()),
        )

    def paintEvent(self, event: QPaintEvent) -> None:
        if self._content_rect.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        bubble_rect = QRect(
            self._content_rect.left() + 4,
            self._content_rect.top() + 4,
            self._content_rect.width() - 8,
            self._content_rect.height() - TAIL_HEIGHT - 4,
        )
        painter.setBrush(QBrush(QColor(255, 255, 255, 232)))
        painter.setPen(QPen(QColor(60, 60, 60, 220), 1.8))
        painter.drawRoundedRect(bubble_rect, 16, 16)

        painter.setPen(QPen(QColor(60, 60, 60, 220), 1.4))
        bottom = self._content_rect.bottom()
        if self._tail_on_right:
            tail_x = self._content_rect.right() - 36
            offsets = (0, 11, 20)
        else:
            tail_x = self._content_rect.left() + 36
            offsets = (0, -11, -20)
        for offset, cy, r in (
            (offsets[0], bottom - 24, 5),
            (offsets[1], bottom - 12, 3.5),
            (offsets[2], bottom - 3, 2.2),
        ):
            painter.setBrush(QBrush(QColor(255, 255, 255, 232)))
            painter.drawEllipse(
                int(tail_x + offset - r),
                int(cy - r),
                int(r * 2),
                int(r * 2),
            )


class ThinkingController:
    def __init__(self, host: QWidget) -> None:
        self._host = host
        self._bubble = ThinkingCloudBubble()
        self._bubble.set_click_handler(self._skip_playback)
        self._type_timer = QTimer(host)
        self._type_timer.timeout.connect(self._show_next_character)
        self._hold_timer = QTimer(host)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self._notify_finished)
        self._elapsed_timer = QTimer(host)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)
        self._on_finished: Callable[[], None] | None = None
        self._avatar: QWidget | None = None
        self._full_text = ""
        self._text_index = 0
        self._hold_ms = 0
        self._streaming = False
        self._stream_text = ""
        self._think_started_at = 0.0
        self._display_started_at = 0.0
        self._locked_text_width = PREFERRED_TEXT_WIDTH
        self._suppress_raise = False
        self._skipped = False

    def bind_avatar(self, avatar: QWidget) -> None:
        self._avatar = avatar

    def set_menu_open(self, opened: bool) -> None:
        """右键菜单打开时避免思考窗盖住菜单。"""
        self._suppress_raise = opened
        if not self._bubble.isVisible():
            return
        if opened:
            self._bubble.clearFocus()
            self._bubble.lower()
        else:
            self._bubble.raise_()

    def show_preview(
        self,
        text: str,
        on_finished: Callable[[], None] | None = None,
        hold_ms: int | None = None,
    ) -> None:
        self._stop_animation()
        self._on_finished = on_finished
        self._full_text = preview_text(text)
        self._text_index = 0
        self._hold_ms = (
            hold_duration_ms(self._full_text)
            if hold_ms is None
            else hold_ms
        )
        self._locked_text_width = PREFERRED_TEXT_WIDTH
        self._skipped = False
        self._bubble.reset_canvas()
        self._start_elapsed_timer()
        self._bubble.set_visible_body("")
        self._bubble.show()
        self._update_position(force_raise=True)
        QTimer.singleShot(0, lambda: self._update_position(force_raise=True))
        self._type_timer.start(type_interval_ms(len(self._full_text)))

    def update_streaming_preview(self, text: str) -> None:
        if not self._streaming:
            self._type_timer.stop()
            self._hold_timer.stop()
            self._on_finished = None
            self._streaming = True
            self._text_index = 0
            self._hold_ms = 0
            self._full_text = ""
            self._locked_text_width = PREFERRED_TEXT_WIDTH
            self._skipped = False
            self._bubble.reset_canvas()
            if not self._elapsed_timer.isActive():
                self._start_elapsed_timer()

        self._stream_text = preview_text(text)
        if self._skipped:
            self._text_index = len(self._stream_text)
            self._bubble.set_visible_body(self._stream_text)
            self._bubble.show()
            self._update_position()
            return

        self._bubble.set_visible_body(
            self._stream_text[: self._text_index],
        )
        self._bubble.show()
        self._update_position()
        self._type_timer.setInterval(
            type_interval_ms(len(self._stream_text)),
        )
        if not self._type_timer.isActive():
            self._type_timer.start()

    def finish_streaming(
        self,
        on_finished: Callable[[], None],
        hold_ms: int | None = None,
    ) -> None:
        if not self._streaming:
            on_finished()
            return

        self._on_finished = on_finished
        display_text = self._stream_text
        self._hold_ms = (
            hold_duration_ms(display_text)
            if hold_ms is None
            else hold_ms
        )
        if self._skipped:
            self._notify_finished()
            return

        if self._text_index >= len(display_text):
            self._type_timer.stop()
            remaining = self._remaining_hold_ms(display_text)
            if remaining > 0:
                self._hold_timer.start(remaining)
            else:
                self._notify_finished()
            return

        self._type_timer.setInterval(
            type_interval_ms(len(display_text)),
        )
        if not self._type_timer.isActive():
            self._type_timer.start()

    def hide(self) -> None:
        self._stop_animation()
        self._on_finished = None
        self._bubble.hide()
        self._bubble.reset_canvas()
        self._bubble.set_visible_body("")

    def is_visible(self) -> bool:
        return self._bubble.isVisible()

    def on_resize(self) -> None:
        self.on_move()

    def on_move(self) -> None:
        if self._bubble.isVisible():
            self._update_position()

    def _start_elapsed_timer(self) -> None:
        now = time.monotonic()
        self._think_started_at = now
        self._display_started_at = now
        self._bubble.set_elapsed_seconds(0)
        self._elapsed_timer.start(ELAPSED_TICK_MS)

    def _remaining_hold_ms(self, text: str) -> int:
        budget = hold_duration_ms(text) if self._hold_ms <= 0 else self._hold_ms
        if self._display_started_at <= 0:
            return budget
        elapsed_ms = int(
            (time.monotonic() - self._display_started_at) * 1000
        )
        return max(0, budget - elapsed_ms)

    def _display_text(self) -> str:
        return self._stream_text if self._streaming else self._full_text

    def _skip_playback(self) -> None:
        if not self._bubble.isVisible() or self._skipped:
            return
        display_text = self._display_text()
        if not display_text:
            return
        self._skipped = True
        self._type_timer.stop()
        self._hold_timer.stop()
        self._text_index = len(display_text)
        self._bubble.set_visible_body(display_text)
        self._update_position()
        if self._streaming and self._on_finished is None:
            return
        self._notify_finished()

    def _tick_elapsed(self) -> None:
        if not self._bubble.isVisible():
            self._elapsed_timer.stop()
            return
        seconds = int(time.monotonic() - self._think_started_at)
        self._bubble.set_elapsed_seconds(seconds)
        self._update_position()

    def _show_next_character(self) -> None:
        display_text = self._display_text()
        if self._text_index >= len(display_text):
            self._type_timer.stop()
            if self._streaming and self._on_finished is None:
                return
            remaining = self._remaining_hold_ms(display_text)
            if remaining > 0:
                self._hold_timer.start(remaining)
            else:
                self._notify_finished()
            return

        self._text_index += 1
        self._bubble.set_visible_body(
            display_text[: self._text_index],
        )
        self._update_position()

    def _notify_finished(self) -> None:
        self._hold_timer.stop()
        callback = self._on_finished
        self._on_finished = None
        if callback is not None:
            self._streaming = False
            callback()

    def _stop_animation(self) -> None:
        self._type_timer.stop()
        self._hold_timer.stop()
        self._elapsed_timer.stop()
        self._full_text = ""
        self._stream_text = ""
        self._text_index = 0
        self._hold_ms = 0
        self._streaming = False
        self._think_started_at = 0.0
        self._display_started_at = 0.0
        self._locked_text_width = PREFERRED_TEXT_WIDTH
        self._skipped = False
        self._bubble.reset_canvas()
        self._bubble.set_elapsed_seconds(0)

    def _update_position(self, force_raise: bool = False) -> None:
        if self._avatar is None:
            return
        avatar_top_left = self._avatar.mapToGlobal(QPoint(0, 0))
        avatar_rect = QRect(avatar_top_left, self._avatar.size())
        head_x = avatar_rect.left() + int(
            avatar_rect.width() * HEAD_X_RATIO
        )
        head_y = avatar_rect.top() + int(
            avatar_rect.height() * HEAD_Y_RATIO
        )
        screen = QGuiApplication.screenAt(avatar_rect.center())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return

        screen_rect = screen.availableGeometry()
        on_right = self._prefer_right_side(head_x, screen_rect)
        x, y, _ = self._layout_from_anchor(
            head_x,
            head_y,
            screen_rect,
            on_right,
        )
        if self._bubble.pos() != QPoint(x, y):
            self._bubble.move(x, y)
        if force_raise and not self._suppress_raise:
            self._bubble.raise_()

    def _prefer_right_side(
        self,
        head_x: int,
        screen_rect: QRect,
    ) -> bool:
        right_space = screen_rect.right() - head_x - HORIZONTAL_GAP
        left_space = head_x - screen_rect.left() - HORIZONTAL_GAP
        min_need = MIN_TEXT_WIDTH + HORIZONTAL_PADDING * 2
        if right_space >= min_need:
            return True
        if left_space >= min_need:
            return False
        return right_space >= left_space

    def _layout_from_anchor(
        self,
        head_x: int,
        head_y: int,
        screen_rect: QRect,
        on_right: bool,
    ) -> tuple[int, int, bool]:
        """固定画布内长高；仅触顶时一次性加宽，避免逐字改窗闪烁。"""
        anchor_bottom = head_y + VERTICAL_GAP
        if on_right:
            anchor_edge = head_x + HORIZONTAL_GAP
            primary_span = max(0, screen_rect.right() - anchor_edge + 1)
            secondary_span = max(0, anchor_edge - screen_rect.left())
            tail_on_right = False
        else:
            anchor_edge = head_x - HORIZONTAL_GAP
            primary_span = max(0, anchor_edge - screen_rect.left() + 1)
            secondary_span = max(0, screen_rect.right() - anchor_edge)
            tail_on_right = True

        space_up = max(MIN_BUBBLE_HEIGHT, anchor_bottom - screen_rect.top())
        space_down = max(0, screen_rect.bottom() - anchor_bottom + 1)
        max_height = max(
            MIN_BUBBLE_HEIGHT,
            screen_rect.bottom() - screen_rect.top() + 1,
        )
        primary_text_max = self._text_width_budget(primary_span)
        total_text_max = self._text_width_budget(
            primary_span + secondary_span,
        )

        if self._locked_text_width <= 0:
            self._locked_text_width = min(
                PREFERRED_TEXT_WIDTH,
                primary_text_max,
            )
        self._locked_text_width = min(
            self._locked_text_width,
            primary_text_max,
        )
        text_width = max(MIN_TEXT_WIDTH, self._locked_text_width)
        content_h = self._bubble.measure_height(text_width)

        if content_h > space_up and primary_text_max > text_width:
            wider = self._fit_text_width(space_up, primary_text_max)
            if wider > text_width:
                text_width = wider
                self._locked_text_width = wider
                content_h = self._bubble.measure_height(text_width)

        canvas_h = min(max(content_h, space_up), max_height)
        if content_h > space_up:
            canvas_h = min(max(content_h, space_up), space_up + space_down)
            canvas_h = min(canvas_h, max_height)
            if content_h > canvas_h and total_text_max > text_width:
                wider = self._fit_text_width(canvas_h, total_text_max)
                if wider > text_width:
                    text_width = wider
                    self._locked_text_width = wider
                    content_h = self._bubble.measure_height(text_width)
                    canvas_h = min(max(content_h, canvas_h), max_height)

        canvas_w = text_width + HORIZONTAL_PADDING * 2
        if not self._bubble.has_canvas():
            canvas_h = max(canvas_h, min(space_up, max_height))
            canvas_w = max(
                canvas_w,
                min(
                    PREFERRED_TEXT_WIDTH + HORIZONTAL_PADDING * 2,
                    primary_span if primary_span > 0 else canvas_w,
                ),
            )

        self._bubble.ensure_canvas(canvas_w, canvas_h)
        self._bubble.apply_content(text_width, tail_on_right)

        if on_right:
            x = anchor_edge
        else:
            x = anchor_edge - self._bubble.width()
        y = anchor_bottom - self._bubble.height()

        x = max(
            screen_rect.left(),
            min(x, screen_rect.right() - self._bubble.width() + 1),
        )
        if y < screen_rect.top():
            y = screen_rect.top()
        y = min(y, screen_rect.bottom() - self._bubble.height() + 1)
        return x, y, tail_on_right

    def _text_width_budget(self, bubble_span: int) -> int:
        usable = bubble_span - HORIZONTAL_PADDING * 2
        return max(MIN_TEXT_WIDTH, min(MAX_TEXT_WIDTH, usable))

    def _fit_text_width(
        self,
        max_height: int,
        max_text_width: int,
    ) -> int:
        """在高度上限内找合适宽度（用于触顶后一次性加宽）。"""
        max_text_width = max(MIN_TEXT_WIDTH, max_text_width)
        preferred = min(PREFERRED_TEXT_WIDTH, max_text_width)
        if self._bubble.measure_height(preferred) <= max_height:
            return preferred
        if self._bubble.measure_height(max_text_width) > max_height:
            return max_text_width

        low = preferred
        high = max_text_width
        while low + WIDTH_SEARCH_STEP < high:
            mid = (low + high) // 2
            if self._bubble.measure_height(mid) <= max_height:
                high = mid
            else:
                low = mid
        return high
