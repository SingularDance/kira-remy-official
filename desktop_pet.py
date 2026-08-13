# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 主窗口 RemyDesktopPet

核心桌宠逻辑：UI 初始化、拖拽交互、打字机效果、API 调用、
空闲检测、系统托盘、右键菜单。
"""

import json
import os
import random
import re
import subprocess
import threading
import time
import webbrowser

from PyQt5.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtCore import (
    Q_ARG,
    QMetaObject,
    QPropertyAnimation,
    QRect,
    QTimer,
    Qt,
    pyqtSlot,
)
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QMoveEvent,
    QPainter,
    QPen,
    QPixmap,
    QResizeEvent,
    QShowEvent,
)
import pyperclip
import requests

import config
from dialogs import (
    HistoryDialog, HelpDialog, SettingsDialog, MasterProfileDialog,
    NoteDialog, RPSDialog, Game2048Dialog, DiceDialog, APISettingsDialog,
    APISetupWizard, MysteryNumberManager, WallpaperPickerDialog
)
from thinking import (
    ThinkingController,
    apply_thinking_request,
    extract_reasoning,
    normalize_reasoning,
    supports_thinking,
)
from utils import (
    resource_path,
    smart_truncate,
    detect_emotion,
    is_image_file,
    image_to_data_uri,
)

# 超过该像素位移才算拖拽，避免单击微抖误触发打断
DRAG_THRESHOLD_PX = 8


class RemyDesktopPet(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)

        config.load_config()
        config.load_shortcuts()
        config.load_notes()
        config.load_conversation()
        config.load_stats()
        config.increment_stat("launch_count")

        # 首次启动：检查 API 配置
        api_cfg = config.CONFIG.get("api", {})
        if not api_cfg.get("primary_key"):
            QTimer.singleShot(300, self._show_api_setup)

        # 状态管理
        self.is_speaking = False
        self.is_typing = False
        self.is_waiting_for_click = False
        self.is_processing_message = False
        self.message_queue = []
        self.is_sleeping = False  # 睡眠状态
        self.last_idle_chat_time = 0  # 上次闲聊时间，防止连续触发（独立于交互计时器）
        self.last_emotion_shown = None  # 追踪上一次显示的表情，防止连续重复

        self.drag_pos = None
        self.drag_moved = False  # 追踪是否拖拽了头像
        self._press_global_pos = None
        self.is_drag_releasing = False  # 拖拽后正在播放台词，禁止新的拖拽
        self.last_drag_phrase = None  # 上一次拖拽触发的台词，防止连续重复
        self.emotion_queue = []  # 表情切换随机队列
        self.emotion_queue_index = 0  # 当前队列位置
        self.wallpaper_queue = []  # 壁纸切换表情随机队列
        self.wallpaper_queue_index = 0
        self.last_interaction_time = time.time()
        self._process_start_time = 0  # 用于防御性超时检测
        self._pending_reply = ""
        self._fade_hides_thinking = False
        self._api_in_flight = False
        self._request_seq = 0
        self._current_avatar = "Remy_Shut.png"
        self._screen_change_bound = False
        self.thinking = ThinkingController(self)
        self.fade_timer = QTimer()
        self.type_timer = QTimer()
        self.type_text = ""
        self.type_index = 0

        self.idle_timer = QTimer()
        self.idle_timer.timeout.connect(self.check_idle)
        self.idle_timer.start(30000)

        self.last_clipboard = ""
        self.clipboard_check_timer = QTimer()
        self.clipboard_check_timer.timeout.connect(self.check_clipboard)
        self.clipboard_check_timer.start(1000)

        self.init_ui()
        self.init_tray()
        self.mystery_number = MysteryNumberManager(self)

        QTimer.singleShot(500, self.show_welcome)
        self.setMinimumSize(200, 250)

    def show_welcome(self):
        self.show_typed_message("系统启动成功！我叫蕾咪~来自5000年后！", is_user=False)

    def init_ui(self):
        self.setAcceptDrops(True)
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.avatar_label = QLabel()
        self.avatar_label.setAlignment(Qt.AlignCenter)
        self.set_avatar("Remy_Shut.png")  # 默认使用闭口
        self.avatar_label.mousePressEvent = self.mouse_press_event
        self.avatar_label.mouseMoveEvent = self.mouse_move_event
        self.avatar_label.mouseReleaseEvent = self.mouse_release_event
        self.avatar_label.setFixedSize(200, 200)
        main_layout.addWidget(self.avatar_label)

        self.bubble_label = QLabel()
        self.bubble_label.setWordWrap(True)
        self.bubble_label.setAlignment(Qt.AlignCenter)
        self.bubble_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.bubble_label.setStyleSheet("""
            QLabel {
                background-color: rgba(255, 255, 255, 240);
                color: #1a1a1a;
                border-radius: 12px;
                padding: 10px 15px;
                font-size: 14px;
                font-family: Microsoft YaHei;
                border: 2px solid #DAAD69;
                min-height: 30px;
                max-width: 200px;
            }
        """)
        self.bubble_label.hide()
        self.bubble_label.mousePressEvent = self.on_bubble_click

        # 淡入淡出效果
        self.bubble_opacity = QGraphicsOpacityEffect()
        self.bubble_label.setGraphicsEffect(self.bubble_opacity)
        self.bubble_opacity.setOpacity(0.0)
        self._fade_anim = None  # 动画引用，防止被GC回收

        main_layout.addWidget(self.bubble_label)

        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(5, 5, 5, 5)

        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("对蕾咪说话...")
        self.input_box.setStyleSheet("""
            QLineEdit {
                background-color: rgba(255, 255, 255, 240);
                color: #1a1a1a;
                border: 1px solid #DAAD69;
                border-radius: 15px;
                padding: 6px 12px;
                font-size: 12px;
                font-family: Microsoft YaHei;
            }
            QLineEdit:focus {
                border: 2px solid #E0C080;
            }
            QLineEdit:disabled {
                opacity: 0.5;
            }
        """)
        # 回车键发送消息（已存在，但显式保留）
        self.input_box.returnPressed.connect(self.send_message)
        input_layout.addWidget(self.input_box)

        send_btn = QPushButton("发送")
        send_btn.clicked.connect(self.send_message)
        send_btn.setStyleSheet("""
            QPushButton {
                background-color: #DAAD69;
                color: #1a1a1a;
                border: 1px solid #DAAD69;
                border-radius: 15px;
                padding: 6px 15px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #E0C080;
            }
            QPushButton:disabled {
                opacity: 0.5;
            }
        """)
        input_layout.addWidget(send_btn)

        main_layout.addLayout(input_layout)
        self.setLayout(main_layout)

        self.thinking.bind_avatar(self.avatar_label)

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.setWindowOpacity(0.95)

    @pyqtSlot(str, int)
    def show_thinking_bubble(self, text: str, request_id: int) -> None:
        if request_id != self._request_seq:
            return
        self._enter_thinking_pose()
        self.thinking.show_preview(text)

    @pyqtSlot(str, int)
    def update_thinking_bubble(self, text: str, request_id: int) -> None:
        if request_id != self._request_seq:
            return
        if not self.thinking.is_visible():
            self._enter_thinking_pose()
        self.thinking.update_streaming_preview(text)

    @pyqtSlot(int)
    def hide_thinking_bubble(self, request_id: int) -> None:
        if request_id != self._request_seq:
            return
        self.thinking.hide()

    def _enter_thinking_pose(self) -> None:
        """思考中使用 Sleep 立绘（不进入真实睡眠状态）"""
        if not self.is_sleeping:
            self.set_avatar("Remy_Sleep.png")

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.thinking.on_resize()

    def moveEvent(self, event: QMoveEvent) -> None:
        super().moveEvent(event)
        self.thinking.on_move()

    def init_tray(self):
        """初始化系统托盘图标和菜单"""
        self.tray_icon = QSystemTrayIcon(self)

        icon_path = resource_path("Remybaby.ico")
        tray_icon_loaded = False

        # 尝试加载 ICO 文件（通过 QPixmap 更可靠，能处理 PNG 压缩的现代 ICO）
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            if not pixmap.isNull():
                # 缩放到系统托盘标准尺寸 32x32
                scaled = pixmap.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.tray_icon.setIcon(QIcon(scaled))
                tray_icon_loaded = True

        # 备用：绘制一个简单的 Remy 头像图标
        if not tray_icon_loaded:
            pixmap = QPixmap(32, 32)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(QColor(218, 173, 105), 2))
            painter.setBrush(QBrush(QColor(218, 173, 105)))
            painter.drawEllipse(4, 4, 24, 24)
            painter.setPen(QPen(QColor(51, 51, 51)))
            painter.setFont(QFont("Microsoft YaHei", 8))
            painter.drawText(QRect(0, 0, 32, 32), Qt.AlignCenter, "R")
            painter.end()
            self.tray_icon.setIcon(QIcon(pixmap))
        self.tray_icon.setToolTip("蕾咪 桌宠")

        # 创建托盘右键菜单
        tray_menu = QMenu()
        tray_menu.setStyleSheet("""
            QMenu {
                background-color: #ffffff;
                color: #333333;
                border: 1px solid #333333;
                border-radius: 8px;
                padding: 5px;
                font-family: Microsoft YaHei;
            }
            QMenu::item {
                padding: 8px 25px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #333333;
                color: white;
            }
            QMenu::separator {
                height: 1px;
                background-color: #333333;
                margin: 5px 10px;
            }
        """)

        show_action = tray_menu.addAction("显示/隐藏 蕾咪")
        show_action.triggered.connect(self.toggle_visibility)

        tray_menu.addSeparator()

        quit_action = tray_menu.addAction("❌ 退出")
        quit_action.triggered.connect(self.quit_app)

        self.tray_icon.setContextMenu(tray_menu)

        # 双击托盘图标显示/隐藏窗口
        self.tray_icon.activated.connect(self.on_tray_activated)

        self.tray_icon.show()

    def on_tray_activated(self, reason):
        """托盘图标激活事件：双击显示/隐藏"""
        if reason == QSystemTrayIcon.DoubleClick:
            self.toggle_visibility()

    def toggle_visibility(self):
        """切换窗口显示/隐藏"""
        if self.isVisible():
            self.thinking.hide()
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def quit_app(self):
        """完全退出程序"""
        self.thinking.hide()
        config.save_conversation()
        config.save_stats()
        self.tray_icon.hide()
        QApplication.quit()

    def set_avatar(self, image_path):
        """设置头像，支持情绪差分"""
        # 如果正在睡眠状态，强制使用睡眠头像
        if self.is_sleeping:
            image_path = "Remy_Sleep.png"
        self._current_avatar = image_path

        # 统计愤怒触发次数（所有显示 Remy_Angry.png 的路径都经过这里）
        if image_path == "Remy_Angry.png":
            config.increment_stat("angry_count")

        full_path = resource_path(image_path)
        if os.path.exists(full_path):
            pixmap = QPixmap(full_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.avatar_label.setPixmap(scaled)
                return
        # 备用头像
        pixmap = QPixmap(200, 200)
        pixmap.fill(QColor(250, 250, 250))
        painter = QPainter(pixmap)
        painter.setPen(QPen(QColor(218, 173, 105), 2))
        painter.setBrush(QBrush(QColor(218, 173, 105)))
        painter.drawEllipse(60, 60, 80, 80)
        painter.setPen(QPen(QColor(51, 51, 51)))
        painter.setFont(QFont("Microsoft YaHei", 20))
        painter.drawText(QRect(0, 0, 200, 200), Qt.AlignCenter, "Remy")
        painter.end()
        self.avatar_label.setPixmap(pixmap)

    def set_emotion_avatar(self, emotion):
        """根据情绪设置对应的头像，防止连续出现相同的表情"""
        if self.is_sleeping:
            return

        emotion_map = {
            'angry': 'Remy_Angry.png',
            'expect': 'Remy_Expect.png',
            'happy': 'Remy_Happy.png',
            'wronged': 'Remy_Wronged.png',
        }

        if emotion in emotion_map:
            # 检查是否和上一次表情相同 → 用 Remy_Open 替代
            if emotion == self.last_emotion_shown:
                self.set_avatar('Remy_Open.png')
                self.last_emotion_shown = 'open'
            else:
                self.set_avatar(emotion_map[emotion])
                self.last_emotion_shown = emotion
        else:
            # 无情绪或未知情绪，使用开口表情
            self.set_avatar('Remy_Open.png')
            self.last_emotion_shown = 'open'

    def mouse_press_event(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_moved = False  # 重置拖拽标记
            self._press_global_pos = event.globalPos()
            # 点击头像时唤醒（如果处于睡眠状态）
            if self.is_sleeping:
                self.wake_up()
            self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouse_release_event(self, event):
        """鼠标释放：区分点击和拖拽"""
        if event.button() == Qt.LeftButton:
            dragged = self.drag_moved
            if self.drag_moved:
                self.drag_release_emotion()
            else:
                self.random_emotion_click()
            self.drag_pos = None
            self._press_global_pos = None
            if dragged:
                # 跨屏拖动后修正 DPI/几何导致的错位
                QTimer.singleShot(0, self._restore_window_metrics)
                QTimer.singleShot(50, self._restore_window_metrics)
            event.accept()

    def mouse_move_event(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_pos is not None:
            if not self.drag_moved:
                # 单击时的微抖不视为拖拽，避免误打断思考
                if self._press_global_pos is not None:
                    delta = event.globalPos() - self._press_global_pos
                    if delta.manhattanLength() < DRAG_THRESHOLD_PX:
                        event.accept()
                        return
                # 确认拖拽 → 打断思考/请求，切换 Dangle
                self.drag_moved = True
                self._interrupt_dialogue()
                if not self.is_sleeping:
                    self.set_avatar("Remy_Dangle.png")
                self.drag_pos = (
                    event.globalPos() - self.frameGeometry().topLeft()
                )
            # 移动时唤醒
            if self.is_sleeping:
                self.wake_up()
            self.move(event.globalPos() - self.drag_pos)
            event.accept()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._bind_screen_change()

    def _bind_screen_change(self) -> None:
        handle = self.windowHandle()
        if handle is None or self._screen_change_bound:
            return
        handle.screenChanged.connect(self._on_screen_changed)
        self._screen_change_bound = True

    def _on_screen_changed(self, _screen) -> None:
        QTimer.singleShot(0, self._restore_window_metrics)
        QTimer.singleShot(50, self._restore_window_metrics)

    def _restore_window_metrics(self) -> None:
        """跨分辨率屏幕后强制恢复人物与窗口对齐。"""
        self.avatar_label.setFixedSize(200, 200)
        self.setMinimumSize(200, 250)
        self.set_avatar(self._current_avatar)
        layout = self.layout()
        if layout is not None:
            layout.activate()
        hint = self.sizeHint()
        width = max(200, hint.width())
        height = max(250, hint.height())
        self.resize(width, height)
        self.update()
        self.thinking.on_move()
        self.thinking.on_resize()

    def _interrupt_dialogue(self):
        """打断当前所有对话和动画，立即隐藏气泡，重置所有状态"""
        # 停止所有计时器
        if self.type_timer.isActive():
            self.type_timer.stop()
        if self.fade_timer.isActive():
            self.fade_timer.stop()
        # 停止淡入淡出动画
        if self._fade_anim is not None:
            self._fade_anim.stop()
        # 隐藏气泡
        self.bubble_label.hide()
        self.bubble_label.setText("")
        self.thinking.hide()
        self._pending_reply = ""
        # 作废进行中的 API，避免返回后再次弹出思考/回复
        self._request_seq += 1
        self._api_in_flight = False
        self.input_box.setEnabled(True)
        # 清空消息队列
        self.message_queue.clear()
        # 重置所有状态
        self.is_speaking = False
        self.is_typing = False
        self.is_waiting_for_click = False
        self.is_processing_message = False
        self.is_drag_releasing = False

    def drag_release_emotion(self):
        """拖拽松开时随机选择 Remy_Angry/Remy_Wronged/Remy_Happy 并说硬编码台词"""
        self.last_interaction_time = time.time()

        # 随机选择三种表情之一，且不与上一次拖拽台词相同
        available = list(config.DRAG_RELEASE_PHRASES.keys())
        if self.last_drag_phrase is not None and len(available) > 1:
            filtered = [k for k in available if k != self.last_drag_phrase]
            if filtered:
                available = filtered
        chosen = random.choice(available)
        self.last_drag_phrase = chosen
        phrase = config.DRAG_RELEASE_PHRASES[chosen]

        # 标记为拖拽松台词，避免挡住用户随后发送的对话
        self.is_drag_releasing = True
        self.show_typed_message(phrase, is_user=False, override_avatar=chosen)

    def random_emotion_click(self):
        """点击头像时按随机队列顺序切换表情并说对应的硬编码台词"""
        # 说话/打字/处理中，或思考/请求中，单击不打断
        if (
            self.is_speaking
            or self.is_typing
            or self.is_processing_message
            or self._api_in_flight
            or self.thinking.is_visible()
        ):
            return

        self.last_interaction_time = time.time()

        # 如果队列为空或已播完一轮，重新随机排列
        if not self.emotion_queue or self.emotion_queue_index >= len(self.emotion_queue):
            self.emotion_queue = list(config.EMOTION_PHRASES.keys())
            random.shuffle(self.emotion_queue)
            self.emotion_queue_index = 0

        # 按顺序从队列中取出当前表情
        chosen = self.emotion_queue[self.emotion_queue_index]
        self.emotion_queue_index += 1
        phrase = config.EMOTION_PHRASES[chosen]

        # 显示台词，由 show_typed_message 在淡入时同步切换头像
        self.show_typed_message(phrase, is_user=False, override_avatar=chosen)

    def wake_up(self):
        """从睡眠状态唤醒"""
        if self.is_sleeping:
            self.is_sleeping = False
            self.set_avatar('Remy_Shut.png')
            self.last_interaction_time = time.time()
            self.show_typed_message("嗯...？你找我吗？", is_user=False)

    def show_typed_message(self, text, is_user=False, override_avatar=None, skip_wake=False):
        """显示打字机效果的消息 - 支持消息队列和情绪检测
        override_avatar 不为 None 时，使用指定头像并跳过情绪检测
        skip_wake 为 True 时，睡眠状态下不唤醒（用于睡眠提示消息自身）"""
        # 如果正在处理消息，加入队列
        if self.is_processing_message:
            self.message_queue.append((text, is_user))
            return

        # 唤醒（睡眠提示消息自身除外）
        if self.is_sleeping and not skip_wake:
            self.wake_up()

        # 开始处理新消息
        self.is_processing_message = True

        if self.type_timer.isActive():
            self.type_timer.stop()
        if self.fade_timer.isActive():
            self.fade_timer.stop()

        if not is_user and len(text) > 37:
            text = smart_truncate(text)

        # 检测情绪（仅对Remy的消息，且未手动指定头像时）
        if not is_user and override_avatar is None:
            emotion = detect_emotion(text)
            self.set_emotion_avatar(emotion)  # emotion为None时也会统一处理
        elif override_avatar is not None:
            # 使用调用方指定的头像（与淡入同步）
            self.set_avatar(override_avatar)

        # 设置样式
        if is_user:
            self.bubble_label.setStyleSheet("""
                QLabel {
                    background-color: rgba(245, 245, 245, 240);
                    color: #1a1a1a;
                    border-radius: 12px;
                    padding: 10px 15px;
                    font-size: 14px;
                    font-family: Microsoft YaHei;
                    border: 2px solid #555555;
                    min-height: 30px;
                    max-width: 200px;
                }
            """)
            # 用户消息时使用闭口
            self.set_avatar('Remy_Shut.png')
            self.is_speaking = False
        else:
            self.bubble_label.setStyleSheet("""
                QLabel {
                    background-color: rgba(255, 255, 255, 240);
                    color: #1a1a1a;
                    border-radius: 12px;
                    padding: 10px 15px;
                    font-size: 14px;
                    font-family: Microsoft YaHei;
                    border: 2px solid #DAAD69;
                    min-height: 30px;
                    max-width: 200px;
                }
            """)
            # Remy说话时已经在上面切换了头像
            self.is_speaking = True

        # 显示打字效果
        if len(text) > 0:
            self.bubble_label.setText(text[0])
        else:
            self.bubble_label.setText("")

        self.bubble_label.show()
        # 停止之前的动画，防止冲突
        if self._fade_anim is not None:
            self._fade_anim.stop()
        # 淡入动画
        self._fade_anim = QPropertyAnimation(self.bubble_opacity, b"opacity")
        self._fade_anim.setDuration(300)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

        self.type_text = text
        self.type_index = 1
        self.is_typing = True
        self.is_waiting_for_click = False

        if len(text) <= 1:
            self.is_typing = False
            if self.is_speaking:
                self.fade_timer.singleShot(2000, self.finish_speaking)
            else:
                self.fade_timer.singleShot(1500, self.finish_message)
            return

        try:
            self.type_timer.timeout.disconnect()
        except (TypeError, RuntimeError):
            pass
        self.type_timer.timeout.connect(self.type_char)
        self.type_timer.start(80)

    def type_char(self):
        if self.type_index < len(self.type_text):
            self.bubble_label.setText(self.type_text[:self.type_index + 1])
            self.type_index += 1
        else:
            self.type_timer.stop()
            self.is_typing = False

            if self.is_speaking:
                self.is_waiting_for_click = True
                if self.fade_timer.isActive():
                    self.fade_timer.stop()
                self.fade_timer.singleShot(2000, self.finish_speaking)
            else:
                if self.fade_timer.isActive():
                    self.fade_timer.stop()
                self.fade_timer.singleShot(1500, self.finish_message)

    def on_bubble_click(self, event):
        if self.is_typing:
            self.type_timer.stop()
            self.bubble_label.setText(self.type_text)
            self.is_typing = False
            if self.is_speaking:
                if self.fade_timer.isActive():
                    self.fade_timer.stop()
                self.fade_timer.singleShot(2000, self.finish_speaking)
            else:
                if self.fade_timer.isActive():
                    self.fade_timer.stop()
                self.fade_timer.singleShot(1500, self.finish_message)
        elif self.is_waiting_for_click:
            if self.fade_timer.isActive():
                self.fade_timer.stop()
            if self.is_speaking:
                self.finish_speaking()
            else:
                self.finish_message()

    def finish_speaking(self):
        """完成Remy的回复显示"""
        self.is_speaking = False
        self.is_waiting_for_click = False
        self.is_drag_releasing = False

        self.is_processing_message = False

        if self.fade_timer.isActive():
            self.fade_timer.stop()
        # 延迟后淡出气泡（同时还原头像）；与思考气泡一起隐藏
        self._fade_hides_thinking = True
        self.fade_timer.singleShot(2000, self.fade_out_bubble)

        self.process_next_message()

    def finish_message(self):
        """完成用户消息显示"""
        self.is_typing = False
        self.is_waiting_for_click = False

        self.is_processing_message = False

        if self.fade_timer.isActive():
            self.fade_timer.stop()
        # 用户气泡淡出时不打断思考气泡
        self._fade_hides_thinking = False
        self.fade_timer.singleShot(1500, self.fade_out_bubble)

        self.process_next_message()

    def process_next_message(self):
        if self.message_queue:
            next_msg, next_is_user = self.message_queue.pop(0)
            QTimer.singleShot(100, lambda: self.show_typed_message(next_msg, next_is_user))

    def fade_out_bubble(self):
        """淡出气泡并同步还原头像为闭口（睡眠状态则保持睡眠头像）"""
        if not self.is_processing_message and not self.is_speaking and not self.is_typing and not self.is_waiting_for_click:
            # 思考中保持 Sleep 立绘；真实睡眠也不覆盖
            if not self.is_sleeping and not self.thinking.is_visible():
                self.set_avatar('Remy_Shut.png')

            # 淡出动画
            self._fade_anim = QPropertyAnimation(self.bubble_opacity, b"opacity")
            self._fade_anim.setDuration(300)
            self._fade_anim.setStartValue(1.0)
            self._fade_anim.setEndValue(0.0)
            self._fade_anim.finished.connect(self._on_fade_out_finished)
            self._fade_anim.start()

    def _on_fade_out_finished(self):
        """淡出动画完成后的清理"""
        if self._fade_hides_thinking:
            self.thinking.hide()
            self._fade_hides_thinking = False
        self.bubble_label.hide()
        self.bubble_label.setText("")
        self.is_drag_releasing = False  # 解除拖拽保护
        if not self.message_queue:
            self.is_processing_message = False

    def send_message(self):
        user_input = self.input_box.text().strip()
        if not user_input:
            return

        busy = (
            self.is_speaking
            or self.is_typing
            or self.is_processing_message
            or self.is_drag_releasing
            or self._api_in_flight
            or self.thinking.is_visible()
        )
        if busy:
            stuck = (
                self._process_start_time
                and time.time() - self._process_start_time > 30
            )
            if stuck:
                print("[Remy Debug] Force resetting stuck processing flag!")
            self._interrupt_dialogue()

        # 唤醒（如果处于睡眠状态）
        if self.is_sleeping:
            self.wake_up()

        self.input_box.clear()
        self.input_box.setEnabled(False)
        self.last_interaction_time = time.time()
        self._request_seq += 1
        request_id = self._request_seq
        self._api_in_flight = True

        # 记录处理开始时间，用于防御性超时检测
        self._process_start_time = time.time()

        display_input = user_input[:30] + ("..." if len(user_input) > 30 else "")
        self.show_typed_message(display_input, is_user=True)

        config.CONVERSATION_HISTORY.append({
            "time": config.get_timestamp(),
            "role": "调查员",
            "content": user_input
        })
        config.save_conversation()

        threading.Thread(
            target=self.call_api,
            args=(user_input, request_id,),
            daemon=True,
        ).start()

        """调用 AI API，支持主备线路自动故障切换"""
    def call_api(self, user_input: str, request_id: int, extra_content=None) -> None:
        """调用 AI API，支持主备线路自动故障切换。

        extra_content：可选。识图等场景需要在不污染历史的前提下，
        额外追加一条用户消息（通常是「图片内容描述 + 人设指令」）。
        """
        try:
            messages = [{"role": "system", "content": config.get_system_prompt()}]
            for entry in config.CONVERSATION_HISTORY[-20:]:
                if (
                    entry["role"] == "Remy"
                    and entry["content"].strip() == "嗯……"
                ):
                    continue
                role = "user" if entry["role"] == "调查员" else "assistant"
                messages.append({"role": role, "content": entry["content"]})

            if extra_content:
                messages.append({"role": "user", "content": extra_content})

            api_cfg = config.CONFIG.get("api", {})
            thinking_enabled = api_cfg.get("thinking_enabled") is True

            # 尝试主线路和备用线路
            for attempt in range(2):
                if attempt == 0:
                    provider_id = api_cfg.get("primary", "")
                    api_key = api_cfg.get("primary_key", "")
                    label = "主线路"
                else:
                    provider_id = api_cfg.get("backup", "")
                    api_key = api_cfg.get("backup_key", "")
                    if not api_key:
                        break
                    label = "备用线路"

                if not api_key:
                    continue

                provider = config.API_PROVIDERS.get(provider_id)
                if not provider:
                    continue

                url = provider["url"]
                model = provider["model"]

                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                data = apply_thinking_request(
                    provider,
                    {
                        "model": model,
                        "messages": messages,
                        "temperature": 0.8,
                        "max_tokens": 48,
                    },
                    enabled=thinking_enabled,
                )
                reasoning_streamed = (
                    thinking_enabled and supports_thinking(provider)
                )
                timeout = 60 if reasoning_streamed else 30
                if self._request_seq != request_id:
                    return
                if reasoning_streamed:
                    QMetaObject.invokeMethod(
                        self,
                        "show_thinking_bubble",
                        Qt.QueuedConnection,
                        Q_ARG(str, "大脑在快速思考中..."),
                        Q_ARG(int, request_id),
                    )
                else:
                    QMetaObject.invokeMethod(
                        self,
                        "hide_thinking_bubble",
                        Qt.QueuedConnection,
                        Q_ARG(int, request_id),
                    )

                print(f"[Remy Debug] [{label}] Calling API: {url}")
                print(f"[Remy Debug] [{label}] Model: {model}, Messages count: {len(messages)}")

                response: requests.Response | None = None
                try:
                    response = requests.post(
                        url,
                        headers=headers,
                        json=data,
                        timeout=timeout,
                        stream=reasoning_streamed,
                    )
                    if self._request_seq != request_id:
                        return
                    print(f"[Remy Debug] [{label}] API response status: {response.status_code}")

                    if response.status_code == 200:
                        if reasoning_streamed:
                            reasoning, reply = self._consume_stream_response(
                                response,
                                request_id,
                            )
                        else:
                            result = json.loads(response.text)
                            message = result["choices"][0]["message"]
                            reply = message.get("content") or ""
                            reasoning = extract_reasoning(message)
                        if self._request_seq != request_id:
                            return
                        print(f"[Remy Debug] [{label}] API reply: {reply}")

                        QMetaObject.invokeMethod(
                            self,
                            "_on_api_success",
                            Qt.QueuedConnection,
                            Q_ARG(str, reply),
                            Q_ARG(str, reasoning),
                            Q_ARG(bool, attempt == 1),
                            Q_ARG(str, provider["name"]),
                            Q_ARG(bool, reasoning_streamed),
                            Q_ARG(int, request_id),
                        )
                        return
                    else:
                        print(f"[Remy Debug] [{label}] API error body: {response.text[:500]}")
                        if attempt == 0:
                            print("[Remy Debug] 主线路失败，尝试备用线路...")
                            continue

                except Exception as inner_e:
                    if self._request_seq != request_id:
                        return
                    print(f"[Remy Debug] [{label}] API exception: {type(inner_e).__name__}: {inner_e}")
                    if attempt == 0:
                        print("[Remy Debug] 主线路异常，尝试备用线路...")
                        continue
                finally:
                    if response is not None:
                        response.close()

            # 两条线路都失败
            if self._request_seq != request_id:
                return
            raise Exception("所有API线路均失败，请检查网络连接和API Key配置")

        except Exception as e:
            if self._request_seq != request_id:
                return
            print(f"[Remy Debug] API fatal error: {type(e).__name__}: {e}")
            QMetaObject.invokeMethod(
                self,
                "_on_api_error",
                Qt.QueuedConnection,
                Q_ARG(str, str(e)),
                Q_ARG(int, request_id),
            )

    def _consume_stream_response(
        self,
        response: requests.Response,
        request_id: int,
    ) -> tuple[str, str]:
        reasoning_parts: list[str] = []
        reply_parts: list[str] = []

        for raw_line in response.iter_lines(decode_unicode=True):
            if self._request_seq != request_id:
                break
            if not raw_line:
                continue
            if isinstance(raw_line, bytes):
                line = raw_line.decode("utf-8", errors="replace")
            else:
                line = str(raw_line)
            if not line.startswith("data:"):
                continue

            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue

            if not isinstance(chunk, dict):
                continue
            choices = chunk.get("choices", [])
            if not isinstance(choices, list) or not choices:
                continue
            choice = choices[0]
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta", {})
            if not isinstance(delta, dict):
                continue

            reasoning_piece = delta.get("reasoning_content") or ""
            reply_piece = delta.get("content") or ""
            if isinstance(reasoning_piece, str) and reasoning_piece:
                reasoning_parts.append(reasoning_piece)
                reasoning = "".join(reasoning_parts)
                QMetaObject.invokeMethod(
                    self,
                    "update_thinking_bubble",
                    Qt.QueuedConnection,
                    Q_ARG(str, reasoning),
                    Q_ARG(int, request_id),
                )
            if isinstance(reply_piece, str) and reply_piece:
                reply_parts.append(reply_piece)

        return "".join(reasoning_parts), "".join(reply_parts)

    # ============================================================
    # 【识图】拖拽图片 → 视觉代理 → DeepSeek 人设回复
    # ============================================================
    def dragEnterEvent(self, event):
        """外部文件拖入：仅接受本地图片"""
        mime = event.mimeData()
        if mime.hasUrls():
            for url in mime.urls():
                path = url.toLocalFile()
                if path and is_image_file(path):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        """拖入图片后触发识图"""
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and is_image_file(path):
                self.on_image_dropped(path)
                return

    def on_image_dropped(self, image_path):
        """拖入图片入口：镜像 send_message 的守卫/唤醒/气泡/线程流程"""
        if (
            self.is_speaking
            or self.is_typing
            or self.is_processing_message
            or self._api_in_flight
        ):
            return
        if self.is_sleeping:
            self.wake_up()

        self.input_box.setEnabled(False)
        self.last_interaction_time = time.time()
        self._request_seq += 1
        request_id = self._request_seq
        self._api_in_flight = True
        self._process_start_time = time.time()

        self.show_typed_message("📷 [图片]", is_user=True)

        config.CONVERSATION_HISTORY.append({
            "time": config.get_timestamp(),
            "role": "调查员",
            "content": "[图片]"
        })
        config.save_conversation()

        threading.Thread(
            target=self.call_vision_api, args=(image_path, request_id), daemon=True
        ).start()

    def call_vision_api(self, image_path, request_id):
        """后台线程：图片 → 视觉描述 → DeepSeek 人设回复"""
        try:
            if self._request_seq != request_id:
                return
            data_uri = image_to_data_uri(image_path)
            description = self._request_vision_description(data_uri)
            if self._request_seq != request_id:
                return
            persona_msg = (
                f"（调查员给蕾咪看了一张图，内容是：{description}）"
                "请用蕾咪的语气，简单说说你看到了什么。"
            )
            self.call_api("", request_id, extra_content=persona_msg)
        except Exception as e:
            if self._request_seq != request_id:
                return
            print(f"[Remy Debug] Vision error: {type(e).__name__}: {e}")
            QMetaObject.invokeMethod(
                self, "_on_api_error",
                Qt.QueuedConnection,
                Q_ARG(str, str(e)),
                Q_ARG(int, request_id),
            )

    def _request_vision_description(self, data_uri):
        """调用视觉供应商，把图片转成客观文字描述"""
        api_cfg = config.CONFIG.get("api", {})
        provider_id = api_cfg.get("vision_provider", "")
        api_key = api_cfg.get("vision_key", "")
        provider = config.API_PROVIDERS.get(provider_id)
        if not provider or not api_key:
            raise Exception("未配置识图 Key，请在「API 设置」中填写视觉模型的密钥")

        messages = [{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "请客观、详细地用中文描述这张图片的内容（主要物体、场景、文字等），不要加入主观评价。",
                },
                {
                    "type": "image_url",
                    "image_url": {"url": data_uri},
                },
            ],
        }]
        data = {
            "model": provider["model"],
            "messages": messages,
            "max_tokens": 1024,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        print(f"[Remy Debug] [识图] Calling vision API: {provider['url']}")
        response = requests.post(
            provider["url"],
            headers=headers,
            json=data,
            timeout=60,
        )
        print(f"[Remy Debug] [识图] Vision API status: {response.status_code}")
        if response.status_code != 200:
            raise Exception(f"识图接口返回 {response.status_code}")
        result = json.loads(response.text)
        content = result["choices"][0]["message"].get("content") or ""
        if not content.strip():
            raise Exception("识图接口未返回描述")
        return content.strip()

    def _prepare_reply_text(self, reply: str, used_fallback: bool) -> str:
        reply = re.sub(r'\([^)]*\)', '', reply or "")
        reply = re.sub(r'（[^）]*）', '', reply)
        reply = reply.strip()
        if not reply:
            reply = "嗯……"
        if used_fallback:
            reply = f"（备用线路）{reply}"
        return smart_truncate(reply, max_chars=37)

    def _deliver_pending_reply(self) -> None:
        reply = self._pending_reply
        self._pending_reply = ""
        if reply:
            self.show_typed_message(reply, is_user=False)

    @pyqtSlot(str, str, bool, str, bool, int)
    def _on_api_success(
        self,
        reply: str,
        reasoning: str,
        used_fallback: bool,
        provider_name: str,
        reasoning_streamed: bool,
        request_id: int,
    ) -> None:
        """API 调用成功，处理回复"""
        if request_id != self._request_seq:
            return
        try:
            print(f"[Remy Debug] API success via {provider_name}, fallback={used_fallback}")

            reply = self._prepare_reply_text(reply, used_fallback)
            reasoning = normalize_reasoning(reasoning)

            # 统计"喜欢你"出现次数（精确匹配这三个字）
            like_hits = reply.count("喜欢你")
            if like_hits:
                config.increment_stat("like_count", like_hits)

            config.CONVERSATION_HISTORY.append({
                "time": config.get_timestamp(),
                "role": "Remy",
                "content": reply
            })
            config.save_conversation()

            self._pending_reply = reply
            if reasoning:
                self._enter_thinking_pose()
                if reasoning_streamed:
                    self.thinking.update_streaming_preview(reasoning)
                    self.thinking.finish_streaming(
                        self._deliver_pending_reply,
                    )
                else:
                    self.thinking.show_preview(
                        reasoning,
                        on_finished=self._deliver_pending_reply,
                    )
            else:
                self.thinking.hide()
                self._deliver_pending_reply()
        except Exception as e:
            print(f"[Remy Debug] Parse exception: {type(e).__name__}: {e}")
            self._api_in_flight = False
            self.thinking.hide()
            self._pending_reply = ""
            self.show_typed_message(f"⚠️ 解析失败: {str(e)[:30]}", is_user=False)
        else:
            self._api_in_flight = False
        finally:
            self.input_box.setEnabled(True)

    @pyqtSlot(str, int)
    def _on_api_error(self, error_msg: str, request_id: int) -> None:
        if request_id != self._request_seq:
            return
        print(f"[Remy Debug] Network error: {error_msg}")
        self._api_in_flight = False
        self.thinking.hide()
        self._pending_reply = ""
        self.show_typed_message(f"⚠️ 网络错误: {error_msg[:30]}", is_user=False)
        self.input_box.setEnabled(True)

    def check_idle(self):
        """检查空闲状态 - 5分钟闲聊，10分钟无交互进入睡眠"""
        if self.is_speaking or self.is_typing or self.is_processing_message:
            return

        idle_seconds = time.time() - self.last_interaction_time

        # 10分钟无交互进入睡眠
        if idle_seconds > 600:  # 600秒 = 10分钟
            if not self.is_sleeping:
                self.is_sleeping = True
                self.last_interaction_time = time.time()  # 防止连续触发
                self.set_avatar('Remy_Sleep.png')
                # 显示睡眠提示（skip_wake=True 防止消息自身唤醒蕾咪）
                self.show_typed_message("好困……蕾咪先睡一会儿……", is_user=False, skip_wake=True)

        # 5分钟闲聊逻辑（但只在非睡眠状态）
        elif not self.is_sleeping and idle_seconds > 300:
            # 用独立变量控制闲聊间隔，不重置 last_interaction_time
            # 否则 10 分钟睡眠计时器会被每 5 分钟归零，永远无法触发
            if time.time() - self.last_idle_chat_time < 300:
                return
            self.last_idle_chat_time = time.time()

            idle_messages = [
                "你还在忙吗？都好久没理蕾咪了……",
                "哼，蕾咪就知道你又沉迷工作了！",
                "喂，蕾咪在这里很无聊诶……",
                "要不要休息一下？蕾咪给你泡杯茶？",
                "你该不会把蕾咪忘了吧！",
                "这个时代的人真是工作狂……"
            ]
            msg = random.choice(idle_messages)

            config.CONVERSATION_HISTORY.append({
                "time": config.get_timestamp(),
                "role": "Remy",
                "content": msg
            })
            config.save_conversation()

            QTimer.singleShot(0, lambda: self.show_typed_message(msg, is_user=False))

    def check_clipboard(self):
        try:
            current = pyperclip.paste()
            if current and current != self.last_clipboard and not self.is_processing_message:
                self.last_clipboard = current
                if not self.is_sleeping:
                    if len(current) < 30:
                        msg = f"📋 你复制了: {current[:20]}..."
                    else:
                        msg = f"📋 复制了 {len(current)} 字文本"
                    QTimer.singleShot(0, lambda: self.show_typed_message(msg, is_user=False))
        except Exception:
            pass

    def show_context_menu(self, pos):
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #ffffff;
                color: #333333;
                border: 1px solid #333333;
                border-radius: 8px;
                padding: 5px;
                font-family: Microsoft YaHei;
            }
            QMenu::item {
                padding: 8px 25px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #333333;
                color: white;
            }
            QMenu::separator {
                height: 1px;
                background-color: #333333;
                margin: 5px 10px;
            }
        """)

        menu.addAction("💬 发送消息").triggered.connect(lambda: self.input_box.setFocus())
        menu.addSeparator()
        menu.addAction("📜 历史记录").triggered.connect(self.open_history)
        menu.addAction("📖 帮助/说明").triggered.connect(self.open_help)
        menu.addAction("⚙️ 核心设定").triggered.connect(self.open_settings)
        menu.addAction("🔑 API 设置").triggered.connect(self.open_api_settings)
        menu.addAction("👤 调查员档案").triggered.connect(self.open_master_profile)
        menu.addSeparator()
        menu.addAction("📝 记一笔").triggered.connect(self.open_note)
        menu.addAction("🍀 显示神秘小数字").triggered.connect(self.show_mystery_number)

        game_menu = menu.addMenu("🎮 小游戏")
        game_menu.addAction("🔢 2048").triggered.connect(self.open_2048)
        game_menu.addAction("✊ 猜拳").triggered.connect(self.open_rps)
        game_menu.addAction("🎲 掷骰子").triggered.connect(self.open_dice)

        menu.addAction("🖼️ 切换壁纸").triggered.connect(self.open_wallpaper_picker)

        menu.addSeparator()
        app_menu = menu.addMenu("🚀 管家服务")
        for app in config.SHORTCUTS.get("apps", []):
            app_menu.addAction(f"▶ {app['name']}").triggered.connect(
                lambda checked, n=app['name'], p=app['path']: self.launch_app(n, p)
            )

        bookmark_menu = menu.addMenu("🔖 传送门")
        for bm in config.SHORTCUTS.get("bookmarks", []):
            bookmark_menu.addAction(f"🌐 {bm['name']}").triggered.connect(
                lambda checked, u=bm['url']: self.open_bookmark(u)
            )

        menu.addSeparator()
        menu.addAction("❌ 退出").triggered.connect(self.quit_app)

        self.thinking.set_menu_open(True)
        # 确保菜单不低于置顶的思考窗
        menu.setWindowFlags(
            menu.windowFlags() | Qt.WindowStaysOnTopHint
        )
        try:
            menu.exec_(self.mapToGlobal(pos))
        finally:
            self.thinking.set_menu_open(False)

    def open_history(self):
        dialog = HistoryDialog(self)
        dialog.exec_()

    def open_help(self):
        dialog = HelpDialog(self)
        dialog.exec_()

    def open_settings(self):
        dialog = SettingsDialog(self)
        dialog.exec_()

    def open_master_profile(self):
        dialog = MasterProfileDialog(self)
        dialog.exec_()

    def open_note(self):
        dialog = NoteDialog(self)
        dialog.exec_()

    def open_2048(self):
        dialog = Game2048Dialog(self)
        dialog.exec_()
        if getattr(dialog, "score", 0) > 0:
            config.update_stat("last_2048_score", dialog.score)

    def _show_api_setup(self):
        """首次启动弹出 API 配置向导"""
        dialog = APISetupWizard(self)
        dialog.exec_()

    def open_api_settings(self):
        """右键菜单 → API 设置"""
        dialog = APISettingsDialog(self)
        dialog.exec_()

    def open_rps(self):
        dialog = RPSDialog(self)
        dialog.exec_()

    def open_dice(self):
        dialog = DiceDialog(self)
        dialog.exec_()

    def show_mystery_number(self):
        """右键菜单 → 显示神秘小数字"""
        self.mystery_number.show_number()

    def play_wallpaper_emotion(self):
        """切换壁纸时按随机队列顺序播放表情 + 硬编码台词（强行打断当前对话）。"""
        self._interrupt_dialogue()

        # 队列为空或已播完一轮 → 重新随机排列
        if not self.wallpaper_queue or self.wallpaper_queue_index >= len(self.wallpaper_queue):
            self.wallpaper_queue = list(config.WALLPAPER_PHRASES.keys())
            random.shuffle(self.wallpaper_queue)
            self.wallpaper_queue_index = 0

        chosen = self.wallpaper_queue[self.wallpaper_queue_index]
        self.wallpaper_queue_index += 1
        phrase = config.WALLPAPER_PHRASES[chosen]
        self.show_typed_message(phrase, is_user=False, override_avatar=chosen)

    def open_wallpaper_picker(self):
        """右键菜单 → 切换壁纸（弹窗预览）"""
        dialog = WallpaperPickerDialog(self)
        dialog.exec_()

    def launch_app(self, name, path):
        try:
            subprocess.Popen(path, shell=True)
            self.show_typed_message(f"🚀 蕾咪正在启动 {name}...", is_user=False)
        except Exception:
            self.show_typed_message("⚠️ 蕾咪启动失败", is_user=False)

    def open_bookmark(self, url):
        try:
            webbrowser.open(url)
            self.show_typed_message("🌐 蕾咪正在打开...", is_user=False)
        except Exception:
            self.show_typed_message("⚠️ 蕾咪打开失败", is_user=False)

    def closeEvent(self, event):
        """关闭窗口时隐藏到系统托盘，而不是退出程序"""
        self.thinking.hide()
        self.hide()
        self.tray_icon.showMessage(
            "Remy 桌宠",
            "蕾咪已最小化到系统托盘，右键托盘图标可退出",
            QSystemTrayIcon.Information,
            2000
        )
        event.ignore()
