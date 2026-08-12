# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 壁纸选择器弹窗

在缩略图网格中浏览并切换 Windows 桌面壁纸。
"""

import os
import random
import winreg

from PyQt5.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout,
    QPushButton, QScrollArea, QWidget, QGridLayout,
    QFileDialog
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QIcon

import config
import wallpaper_utils


class WallpaperPickerDialog(QDialog):
    """壁纸选择器 —— 4 列缩略图网格 + 文件夹设置 + 随机切换。"""

    THUMB_W = 160
    THUMB_H = 90
    COLS = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🖼️ 切换壁纸")
        self.setGeometry(200, 150, 780, 550)
        self.setWindowOpacity(0.95)
        self.setStyleSheet("""
            QDialog {
                background-color: rgba(255, 255, 255, 245);
                border-radius: 12px;
                border: 1px solid #DAAD69;
            }
            QLabel { color: #333333; font-family: Microsoft YaHei; }
            QPushButton {
                font-family: Microsoft YaHei;
                border-radius: 5px;
                padding: 8px 16px;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
        """)
        self._thumb_buttons = []       # (path, QPushButton)
        self._current_wallpaper = self._read_current_wallpaper()
        self.init_ui()
        self._load_thumbnails()

    # ============================================================
    #  UI 构建
    # ============================================================

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # 标题
        title = QLabel("🖼️ 切换壁纸")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #DAAD69;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # 当前文件夹路径
        folder = config.CONFIG.get("wallpaper_folder", "")
        self._folder_label = QLabel(
            f"📁 当前文件夹: {folder}" if folder else "📁 尚未设置壁纸文件夹"
        )
        self._folder_label.setStyleSheet("font-size: 12px; color: #666666;")
        self._folder_label.setWordWrap(True)
        layout.addWidget(self._folder_label)

        # 顶部按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        change_btn = QPushButton("📁 更换文件夹")
        change_btn.clicked.connect(self._on_change_folder)
        change_btn.setStyleSheet(self._btn_style("#333333"))
        btn_row.addWidget(change_btn)

        random_btn = QPushButton("🎲 随机切换")
        random_btn.clicked.connect(self._on_random)
        random_btn.setStyleSheet(self._btn_style("#DAAD69"))
        btn_row.addWidget(random_btn)

        btn_row.addStretch()

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet(self._btn_style("#888888"))
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

        # 缩略图滚动区域
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._grid_widget = QWidget()
        self._grid_widget.setStyleSheet("background: transparent;")
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setSpacing(10)
        self._grid.setContentsMargins(4, 4, 4, 4)
        self._scroll.setWidget(self._grid_widget)
        layout.addWidget(self._scroll, 1)

        self.setLayout(layout)

    # ============================================================
    #  缩略图加载
    # ============================================================

    def _load_thumbnails(self):
        """清空并重新加载所有缩略图。"""
        # 清除旧缩略图
        for _, btn in self._thumb_buttons:
            btn.deleteLater()
        self._thumb_buttons.clear()
        # 清空网格中的 widget（但保留 grid layout 本身）
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        folder = config.CONFIG.get("wallpaper_folder", "")
        self._folder_label.setText(
            f"📁 当前文件夹: {folder}" if folder else "📁 尚未设置壁纸文件夹"
        )

        if not folder:
            hint = QLabel("请点击「📁 更换文件夹」选择壁纸目录")
            hint.setStyleSheet("font-size: 14px; color: #999999; padding: 40px;")
            hint.setAlignment(Qt.AlignCenter)
            self._grid.addWidget(hint, 0, 0, 1, self.COLS)
            return

        images = wallpaper_utils.list_wallpapers(folder)
        if not images:
            hint = QLabel("文件夹中没有图片\n请选择包含 .jpg / .png / .bmp / .gif 的目录")
            hint.setStyleSheet("font-size: 14px; color: #999999; padding: 40px;")
            hint.setAlignment(Qt.AlignCenter)
            self._grid.addWidget(hint, 0, 0, 1, self.COLS)
            return

        for idx, path in enumerate(images):
            row, col = divmod(idx, self.COLS)
            btn = self._make_thumbnail(path)
            self._grid.addWidget(btn, row, col)
            self._thumb_buttons.append((path, btn))

    def _make_thumbnail(self, path):
        """为指定图片创建一个缩略图按钮。"""
        btn = QPushButton()
        btn.setFixedSize(170, 115)
        btn.setToolTip(os.path.basename(path))

        pixmap = QPixmap(path)
        if pixmap.isNull():
            btn.setText("⚠️")
            return btn

        scaled = pixmap.scaled(
            self.THUMB_W, self.THUMB_H,
            Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        btn.setIcon(QIcon(scaled))
        btn.setIconSize(scaled.size())

        # 当前壁纸高亮
        is_current = os.path.normcase(os.path.abspath(path)) == os.path.normcase(self._current_wallpaper)
        border_color = "#DAAD69" if is_current else "#cccccc"
        border_width = "2px" if is_current else "1px"

        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #f5f5f5;
                border: {border_width} solid {border_color};
                border-radius: 6px;
                padding: 4px;
            }}
            QPushButton:hover {{
                border: 2px solid #DAAD69;
                background-color: #fafafa;
            }}
        """)

        btn.clicked.connect(lambda checked, p=path: self._on_thumbnail_clicked(p))
        return btn

    # ============================================================
    #  事件处理
    # ============================================================

    def _on_thumbnail_clicked(self, path):
        """点击缩略图 → 切换壁纸 + 更新高亮 + 触发桌宠表情。"""
        try:
            try:
                wallpaper_utils.set_wallpaper_style_fill()
            except OSError:
                pass
            wallpaper_utils.set_wallpaper(path)
            self._current_wallpaper = os.path.normcase(os.path.abspath(path))
            self._update_highlights()
            # 触发桌宠切换壁纸表情
            parent = self.parent()
            if parent and hasattr(parent, "play_wallpaper_emotion"):
                parent.play_wallpaper_emotion()
        except Exception:
            pass

    def _on_random(self):
        """随机选一张壁纸并切换。"""
        folder = config.CONFIG.get("wallpaper_folder", "")
        images = wallpaper_utils.list_wallpapers(folder)
        if not images:
            return
        path = random.choice(images)
        self._on_thumbnail_clicked(path)

    def _on_change_folder(self):
        """弹出 QFileDialog 选择新壁纸文件夹。"""
        current = config.CONFIG.get("wallpaper_folder", "")
        folder = QFileDialog.getExistingDirectory(
            self, "选择壁纸文件夹", current or os.path.expanduser("~"))
        if folder:
            config.CONFIG["wallpaper_folder"] = folder
            config.save_config()
            try:
                wallpaper_utils.set_wallpaper_style_fill()
            except OSError:
                pass
            self._current_wallpaper = self._read_current_wallpaper()
            self._load_thumbnails()

    def _update_highlights(self):
        """刷新所有缩略图的边框高亮状态。"""
        for path, btn in self._thumb_buttons:
            is_current = os.path.normcase(os.path.abspath(path)) == os.path.normcase(self._current_wallpaper)
            border_color = "#DAAD69" if is_current else "#cccccc"
            border_width = "2px" if is_current else "1px"
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #f5f5f5;
                    border: {border_width} solid {border_color};
                    border-radius: 6px;
                    padding: 4px;
                }}
                QPushButton:hover {{
                    border: 2px solid #DAAD69;
                    background-color: #fafafa;
                }}
            """)

    # ============================================================
    #  工具
    # ============================================================

    @staticmethod
    def _read_current_wallpaper():
        """从注册表读取当前壁纸路径（用于高亮匹配）。"""
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Control Panel\Desktop", 0, winreg.KEY_READ)
            value, _ = winreg.QueryValueEx(key, "Wallpaper")
            winreg.CloseKey(key)
            return os.path.normcase(os.path.abspath(value))
        except Exception:
            return ""

    @staticmethod
    def _btn_style(bg_color):
        return f"""
            QPushButton {{
                background-color: {bg_color};
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                opacity: 0.85;
            }}
        """
