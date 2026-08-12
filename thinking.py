# -*- coding: utf-8 -*-
"""思考模式能力：请求增强、响应解析、云朵气泡 UI。

不支持思考的供应商不会启用相关参数或 UI，避免报错。
"""

from __future__ import annotations

from collections.abc import Callable
from math import ceil
import re

from PyQt5.QtCore import QRect, QSize, Qt, QTimer
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QPaintEvent,
    QPainter,
    QPen,
    QTextDocument,
)
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

PREVIEW_MS = 1600
COMPLETION_MAX_TOKENS = 2048
NON_THINKING_MAX_TOKENS = 128
MAX_PREVIEW_CHARS = 50
GENERIC_THOUGHT = "大脑在快速思考中..."
MIN_THINKING_DURATION_MS = 800
MAX_THINKING_DURATION_MS = 2400
MIN_TYPE_INTERVAL_MS = 26
MAX_TYPE_INTERVAL_MS = 68
MIN_TEXT_WIDTH = 104
MAX_TEXT_WIDTH = 224
MIN_BUBBLE_HEIGHT = 96
MAX_BODY_HEIGHT = 108
HORIZONTAL_PADDING = 28
TOP_PADDING = 20
BOTTOM_PADDING = 38
TEXT_GAP = 2
TAIL_HEIGHT = 28
TOP_GAP = 8
MIN_THINKING_WINDOW_WIDTH = 240


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
    return value.strip()


def preview_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return GENERIC_THOUGHT
    if len(cleaned) <= MAX_PREVIEW_CHARS:
        return cleaned
    return cleaned[: MAX_PREVIEW_CHARS - 1] + "…"


def type_interval_ms(text_length: int) -> int:
    safe_length = max(text_length, 1)
    duration = min(
        MAX_THINKING_DURATION_MS,
        max(MIN_THINKING_DURATION_MS, safe_length * 35),
    )
    interval = duration // safe_length
    return max(MIN_TYPE_INTERVAL_MS, min(MAX_TYPE_INTERVAL_MS, interval))


class ThinkingCloudBubble(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._text = ""
        self._max_text_width = MAX_TEXT_WIDTH

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            HORIZONTAL_PADDING,
            TOP_PADDING,
            HORIZONTAL_PADDING,
            BOTTOM_PADDING,
        )
        layout.setSpacing(TEXT_GAP)

        self._header = QLabel("内心在想", self)
        header_font = QFont("Microsoft YaHei", 8)
        self._header.setFont(header_font)
        self._header.setStyleSheet("""
            QLabel {
                color: #a5afb5;
                background-color: transparent;
                border: none;
            }
        """)
        layout.addWidget(self._header)

        self._body = QLabel("……", self)
        body_font = QFont("Microsoft YaHei", 9)
        self._body.setFont(body_font)
        self._body.setWordWrap(True)
        self._body.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._body.setStyleSheet("""
            QLabel {
                color: #71808a;
                background-color: transparent;
                border: none;
            }
        """)
        layout.addWidget(self._body, 1)
        self.hide()

    def set_max_width(self, width: int) -> None:
        available_width = width - HORIZONTAL_PADDING * 2
        self._max_text_width = max(
            MIN_TEXT_WIDTH,
            min(MAX_TEXT_WIDTH, available_width),
        )
        self._resize_to_text()

    def set_body(self, body: str) -> None:
        self._text = body or "……"
        self._resize_to_text()

    def prepare_body(self, body: str) -> str:
        self._text = body or "……"
        self._resize_to_text()
        return self._body.text()

    def set_visible_body(self, body: str) -> None:
        self._body.setText(body or "……")

    def sizeHint(self) -> QSize:
        return QSize(self.width(), self.height())

    def _resize_to_text(self) -> None:
        text_width = self._text_width(self._text)
        body_text = self._fit_text(self._text, text_width)
        body_height = self._text_height(body_text, text_width)
        header_height = self._header.fontMetrics().lineSpacing()
        bubble_height = max(
            MIN_BUBBLE_HEIGHT,
            TOP_PADDING
            + header_height
            + TEXT_GAP
            + body_height
            + BOTTOM_PADDING,
        )

        self._body.setFixedWidth(text_width)
        self._body.setFixedHeight(body_height)
        self._body.setText(body_text)
        self.setFixedSize(
            text_width + HORIZONTAL_PADDING * 2,
            bubble_height,
        )

    def _text_width(self, text: str) -> int:
        metrics = QFontMetrics(self._body.font())
        line_widths = [
            metrics.horizontalAdvance(line)
            for line in text.splitlines()
        ]
        content_width = max(line_widths or [MIN_TEXT_WIDTH])
        return max(
            MIN_TEXT_WIDTH,
            min(self._max_text_width, content_width),
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

    def _fit_text(self, text: str, width: int) -> str:
        if self._text_height(text, width) <= MAX_BODY_HEIGHT:
            return text

        low = 1
        high = len(text)
        while low < high:
            middle = (low + high + 1) // 2
            candidate = text[:middle].rstrip() + "…"
            if self._text_height(candidate, width) <= MAX_BODY_HEIGHT:
                low = middle
            else:
                high = middle - 1
        return text[:low].rstrip() + "…"

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        width = self.width()
        height = self.height()
        bubble_rect = QRect(
            4,
            4,
            width - 8,
            height - TAIL_HEIGHT - 4,
        )
        painter.setBrush(QBrush(QColor(255, 255, 255, 232)))
        painter.setPen(QPen(QColor(60, 60, 60, 220), 1.8))
        painter.drawRoundedRect(bubble_rect, 16, 16)

        painter.setPen(QPen(QColor(60, 60, 60, 220), 1.4))
        tail_x = width * 0.3
        for cx, cy, r in (
            (tail_x, height - 24, 5),
            (tail_x + 11, height - 12, 3.5),
            (tail_x + 20, height - 3, 2.2),
        ):
            painter.setBrush(QBrush(QColor(255, 255, 255, 232)))
            painter.drawEllipse(
                int(cx - r),
                int(cy - r),
                int(r * 2),
                int(r * 2),
            )


class ThinkingController:
    def __init__(self, host: QWidget) -> None:
        self._host = host
        self._bubble = ThinkingCloudBubble(host)
        self._type_timer = QTimer(host)
        self._type_timer.timeout.connect(self._show_next_character)
        self._hold_timer = QTimer(host)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self._notify_finished)
        self._on_finished: Callable[[], None] | None = None
        self._avatar: QWidget | None = None
        self._base_min_height = 250
        self._base_height = self._base_min_height
        self._top_margin = 0
        self._expanded = False
        self._resizing = False
        self._base_width = 200
        self._width_expanded = False
        self._full_text = ""
        self._text_index = 0
        self._hold_ms = 0

    def bind_avatar(self, avatar: QWidget) -> None:
        self._avatar = avatar

    def show_waiting(self) -> None:
        self.show_preview("大脑在快速思考中...")

    def show_preview(
        self,
        text: str,
        on_finished: Callable[[], None] | None = None,
        hold_ms: int = 0,
    ) -> None:
        self._stop_animation()
        self._on_finished = on_finished
        self._set_window_width(True)
        self._bubble.set_max_width(self._host.width() - 8)
        self._full_text = self._bubble.prepare_body(preview_text(text))
        self._text_index = 0
        self._hold_ms = hold_ms
        self._set_layout_space(True)
        self._bubble.set_visible_body("")
        self._bubble.show()
        self._update_position()
        QTimer.singleShot(0, self._update_position)
        self._type_timer.start(type_interval_ms(len(self._full_text)))

    def update_streaming_preview(
        self,
        text: str,
    ) -> None:
        self._stop_animation()
        self._on_finished = None
        self._set_window_width(True)
        self._bubble.set_max_width(self._host.width() - 8)
        self._bubble.set_body(preview_text(text))
        self._set_layout_space(True)
        self._bubble.show()
        self._update_position()

    def hide(self) -> None:
        self._stop_animation()
        self._on_finished = None
        self._bubble.hide()
        self._bubble.set_body("")
        self._set_layout_space(False)
        self._set_window_width(False)

    def is_visible(self) -> bool:
        return self._bubble.isVisible()

    def on_resize(self) -> None:
        if self._bubble.isVisible():
            self._update_position()

    def _show_next_character(self) -> None:
        if self._text_index >= len(self._full_text):
            self._type_timer.stop()
            if self._hold_ms > 0:
                self._hold_timer.start(self._hold_ms)
            else:
                self._notify_finished()
            return

        self._text_index += 1
        self._bubble.set_visible_body(
            self._full_text[: self._text_index],
        )

    def _notify_finished(self) -> None:
        self._hold_timer.stop()
        callback = self._on_finished
        self._on_finished = None
        if callback is not None:
            callback()

    def _stop_animation(self) -> None:
        self._type_timer.stop()
        self._hold_timer.stop()
        self._full_text = ""
        self._text_index = 0
        self._hold_ms = 0

    def _set_layout_space(self, enabled: bool) -> None:
        layout = self._host.layout()
        if layout is None or self._resizing:
            return

        self._resizing = True
        try:
            if enabled:
                required_margin = self._bubble.height() + TOP_GAP
                if not self._expanded:
                    self._base_height = max(
                        self._host.height(),
                        self._base_min_height,
                    )
                    layout.setContentsMargins(0, required_margin, 0, 0)
                    self._host.setMinimumHeight(
                        self._base_height + required_margin,
                    )
                    self._host.resize(
                        self._host.width(),
                        self._base_height + required_margin,
                    )
                    self._host.move(
                        self._host.x(),
                        self._host.y() - required_margin,
                    )
                    self._expanded = True
                else:
                    margin_delta = required_margin - self._top_margin
                    if margin_delta:
                        layout.setContentsMargins(0, required_margin, 0, 0)
                        self._host.setMinimumHeight(
                            self._base_height + required_margin,
                        )
                        self._host.resize(
                            self._host.width(),
                            self._host.height() + margin_delta,
                        )
                        self._host.move(
                            self._host.x(),
                            self._host.y() - margin_delta,
                        )
                self._top_margin = required_margin
                return

            if not self._expanded:
                return
            current_geometry = self._host.geometry()
            layout.setContentsMargins(0, 0, 0, 0)
            self._host.setMinimumHeight(self._base_min_height)
            self._host.resize(
                current_geometry.width(),
                self._base_height,
            )
            self._host.move(
                current_geometry.x(),
                current_geometry.y() + self._top_margin,
            )
            self._top_margin = 0
            self._expanded = False
        finally:
            self._resizing = False

    def _set_window_width(self, enabled: bool) -> None:
        if enabled:
            if self._width_expanded:
                return
            self._base_width = self._host.width()
            target_width = max(
                self._base_width,
                MIN_THINKING_WINDOW_WIDTH,
            )
            if target_width == self._base_width:
                return
            self._host.resize(target_width, self._host.height())
            self._width_expanded = True
            return

        if not self._width_expanded:
            return
        self._host.resize(self._base_width, self._host.height())
        self._width_expanded = False

    def _update_position(self) -> None:
        if self._avatar is None:
            return
        avatar_geo = self._avatar.geometry()
        bubble_w = self._bubble.width()
        x = max(4, avatar_geo.left() + 4)
        y = 2
        if x + bubble_w > self._host.width() - 4:
            x = max(
                4,
                min(
                    avatar_geo.right() - bubble_w,
                    self._host.width() - bubble_w - 4,
                ),
            )
        self._bubble.move(x, y)
        self._bubble.raise_()
