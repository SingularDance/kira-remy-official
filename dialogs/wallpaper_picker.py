# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 壁纸选择器弹窗

两个页签：
- 「本地壁纸」：在缩略图网格中浏览本机文件夹并切换 Windows 桌面壁纸。
- 「社区壁纸」：从社区壁纸站（http://8.153.169.59）拉取缩略图预览，
  点击后下载大图、转成 PNG 缓存到本地再设为壁纸。
"""

import json
import os
import random
import webbrowser

from PyQt5.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout,
    QPushButton, QScrollArea, QWidget, QGridLayout,
    QFileDialog, QMessageBox, QTabWidget
)
from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtGui import QPixmap, QIcon, QImage
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

import community_wallpaper
import config
import utils
import wallpaper_utils


class WallpaperPickerDialog(QDialog):
    """壁纸选择器 —— 本地/社区两个页签，各 4 列缩略图网格。"""

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
            QLabel { color: #333333; font-family: 'Microsoft YaHei', 'PingFang SC', 'Hiragino Sans GB', sans-serif; }
            QPushButton {
                font-family: 'Microsoft YaHei', 'PingFang SC', 'Hiragino Sans GB', sans-serif;
                border-radius: 5px;
                padding: 8px 16px;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
        """)

        self._thumb_buttons = []            # 本地：(path, QPushButton)
        self._comm_thumb_buttons = []       # 社区：(item, QPushButton)
        self._current_wallpaper = self._read_current_wallpaper()

        # 社区壁纸状态
        self._community_items = []          # 已拉到的归一化 item（按顺序）
        self._community_total = None        # 服务端给的总数；拿不到则为 None
        self._community_loading = False
        self._community_loaded = False      # 是否已开始过拉取（惰性加载）
        self._last_page_full = False        # 上一页是否拉满 PAGE_SIZE（用于无 total 时判断有无更多）

        # 社区壁纸网络（异步，无需线程，依赖 Qt 事件循环）
        self._nam = QNetworkAccessManager(self)
        self._nam.finished.connect(self._on_nam_finished)

        self.init_ui()
        # 延迟加载本地缩略图，让弹窗先渲染出来
        QTimer.singleShot(30, self._load_thumbnails)
        # 切页时惰性拉取社区壁纸（首次切换到社区页才发请求）
        self._tabs.currentChanged.connect(self._on_tab_changed)
        # 默认展示「社区壁纸」页签
        self._tabs.setCurrentIndex(self._community_tab_index)

    # ============================================================
    #  UI 构建
    # ============================================================

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # 顶部标题行：标题居中，右上角放一个不占主体空间的小按钮
        header = QGridLayout()
        header.setColumnStretch(0, 1)
        header.setColumnStretch(1, 0)
        header.setColumnStretch(2, 1)

        title = QLabel("🖼️ 切换壁纸")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #DAAD69;")
        title.setAlignment(Qt.AlignCenter)
        header.addWidget(title, 0, 0, 1, 3)

        self._visit_btn = QPushButton("🔗 访问社区壁纸站")
        self._visit_btn.setCursor(Qt.PointingHandCursor)
        self._visit_btn.setStyleSheet("""
            QPushButton {
                background-color: #6C5CE7;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #5a4bd1; }
        """)
        self._visit_btn.clicked.connect(self._open_community_site)
        header.addWidget(self._visit_btn, 0, 2, Qt.AlignRight | Qt.AlignVCenter)

        layout.addLayout(header)

        # 页签容器
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #E6E6E6;
                border-radius: 6px;
                top: -1px;
            }
            QTabBar::tab {
                padding: 6px 18px;
                color: #666666;
                border: 1px solid #E6E6E6;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                color: #DAAD69;
                background-color: #fdf8ef;
                font-weight: bold;
            }
        """)
        layout.addWidget(self._tabs, 1)

        self._build_local_tab()
        self._build_community_tab()

        # 底部：左侧小字说明 + 右侧关闭按钮
        footer = QLabel("感谢各位对星夜颂歌的支持，社区壁纸点击即可设为桌面壁纸~")
        footer.setStyleSheet("font-size: 11px; color: #999999;")

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet(self._btn_style("#888888"))
        close_row = QHBoxLayout()
        close_row.addWidget(footer)
        close_row.addStretch()
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

        self.setLayout(layout)

    def _build_local_tab(self):
        """「本地壁纸」页：文件夹设置 + 随机切换 + 本地缩略图网格。"""
        page = QWidget()
        v = QVBoxLayout()
        v.setSpacing(10)
        v.setContentsMargins(8, 8, 8, 8)

        # 当前文件夹路径
        folder = config.CONFIG.get("wallpaper_folder", "")
        self._folder_label = QLabel(
            f"📁 当前文件夹: {folder}" if folder else "📁 尚未设置壁纸文件夹"
        )
        self._folder_label.setStyleSheet("font-size: 12px; color: #666666;")
        self._folder_label.setWordWrap(True)
        v.addWidget(self._folder_label)

        # 按钮行
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
        v.addLayout(btn_row)

        # 本地缩略图滚动区域
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._grid_widget = QWidget()
        self._grid_widget.setStyleSheet("background: transparent;")
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setSpacing(10)
        self._grid.setContentsMargins(4, 4, 4, 4)

        self._loading_label = QLabel("当前图片较多，蕾咪正在全速加载中！！")
        self._loading_label.setStyleSheet("font-size: 16px; color: #DAAD69; padding: 60px;")
        self._loading_label.setAlignment(Qt.AlignCenter)
        self._grid.addWidget(self._loading_label, 0, 0, 1, self.COLS)

        self._scroll.setWidget(self._grid_widget)
        v.addWidget(self._scroll, 1)

        page.setLayout(v)
        self._tabs.addTab(page, "📁 本地壁纸")

    def _build_community_tab(self):
        """「社区壁纸」页：状态提示 + 社区缩略图网格 + 加载更多。"""
        page = QWidget()
        v = QVBoxLayout()
        v.setSpacing(10)
        v.setContentsMargins(8, 8, 8, 8)

        # 状态提示（加载中 / 失败 / 暂无更多）
        self._comm_status_label = QLabel("")
        self._comm_status_label.setStyleSheet("font-size: 13px; color: #DAAD69;")
        self._comm_status_label.setAlignment(Qt.AlignCenter)
        self._comm_status_label.setWordWrap(True)
        v.addWidget(self._comm_status_label)

        # 社区缩略图滚动区域
        self._comm_scroll = QScrollArea()
        self._comm_scroll.setWidgetResizable(True)
        self._comm_grid_widget = QWidget()
        self._comm_grid_widget.setStyleSheet("background: transparent;")
        self._comm_grid = QGridLayout(self._comm_grid_widget)
        self._comm_grid.setSpacing(10)
        self._comm_grid.setContentsMargins(4, 4, 4, 4)
        self._comm_scroll.setWidget(self._comm_grid_widget)
        v.addWidget(self._comm_scroll, 1)

        # 加载更多 / 重试
        self._load_more_btn = QPushButton("🔽 加载更多")
        self._load_more_btn.clicked.connect(self._load_more)
        self._load_more_btn.setStyleSheet(self._btn_style("#6C5CE7"))
        self._load_more_btn.setVisible(False)
        more_row = QHBoxLayout()
        more_row.addStretch()
        more_row.addWidget(self._load_more_btn)
        more_row.addStretch()
        v.addLayout(more_row)

        page.setLayout(v)
        self._community_tab_index = self._tabs.addTab(page, "🌐 社区壁纸")

    # ============================================================
    #  本地缩略图加载
    # ============================================================

    def _load_thumbnails(self):
        """清空并重新加载本地缩略图。"""
        for _, btn in self._thumb_buttons:
            btn.deleteLater()
        self._thumb_buttons.clear()
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
        """为本地图片创建一个缩略图按钮。"""
        btn = QPushButton()
        btn.setFixedSize(170, 115)
        btn.setToolTip(os.path.basename(path))

        pixmap = QPixmap(path)
        if pixmap.isNull():
            btn.setText("⚠️")
            btn.setStyleSheet(self._thumb_btn_style(False))
            btn.clicked.connect(lambda checked, p=path: self._on_thumbnail_clicked(p))
            return btn

        scaled = pixmap.scaled(
            self.THUMB_W, self.THUMB_H,
            Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        btn.setIcon(QIcon(scaled))
        btn.setIconSize(scaled.size())

        is_current = os.path.normcase(os.path.abspath(path)) == os.path.normcase(self._current_wallpaper)
        btn.setStyleSheet(self._thumb_btn_style(is_current))

        btn.clicked.connect(lambda checked, p=path: self._on_thumbnail_clicked(p))
        return btn

    # ============================================================
    #  社区壁纸：网络 + 缩略图
    # ============================================================

    def _on_tab_changed(self, index):
        """首次切到社区页时惰性拉取，避免只想要本地壁纸时也发请求。"""
        if index == self._community_tab_index and not self._community_loaded:
            self._load_community(reset=True)

    def _load_community(self, reset=False):
        if self._community_loading:
            return
        self._community_loaded = True
        self._community_loading = True
        if reset:
            self._community_items = []
            self._community_total = None
            self._last_page_full = False
            self._clear_community_grid()
        self._comm_status_label.setText("蕾咪正在加载社区壁纸……")
        self._load_more_btn.setVisible(False)

        url = community_wallpaper.build_images_url(offset=len(self._community_items))
        req = QNetworkRequest(QUrl(url))
        req.setAttribute(QNetworkRequest.User, ("list",))
        self._nam.get(req)

    def _load_more(self):
        self._load_community(reset=False)

    def _open_community_site(self):
        webbrowser.open(community_wallpaper.BASE_URL)

    def _clear_community_grid(self):
        for _, btn in self._comm_thumb_buttons:
            btn.deleteLater()
        self._comm_thumb_buttons.clear()
        while self._comm_grid.count():
            item = self._comm_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _request_thumb(self, item):
        req = QNetworkRequest(QUrl(item["thumb_url"]))
        req.setAttribute(QNetworkRequest.User, ("thumb", item))
        self._nam.get(req)

    def _on_nam_finished(self, reply):
        """统一网络回包入口，按请求上挂的上下文分流。"""
        ctx = reply.request().attribute(QNetworkRequest.User)
        data = bytes(reply.readAll())
        err = reply.error()
        reply.deleteLater()

        if not isinstance(ctx, tuple) or not ctx:
            return
        kind = ctx[0]
        if kind == "list":
            self._on_community_list(data, err)
        elif kind == "thumb":
            self._on_community_thumb(ctx[1], data, err)
        elif kind == "full":
            self._on_community_full(ctx[1], data, err)

    def _on_community_list(self, data, err):
        self._community_loading = False
        if err != QNetworkReply.NoError:
            self._comm_status_label.setText("社区壁纸加载失败，请检查网络后重试。")
            self._load_more_btn.setText("🔁 重试")
            self._load_more_btn.setVisible(True)
            return

        raw = None
        try:
            raw = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raw = None

        items = community_wallpaper.parse_images_response(raw)
        if not items:
            if raw is None:
                self._comm_status_label.setText("社区壁纸加载失败，请稍后再试。")
                self._load_more_btn.setText("🔁 重试")
                self._load_more_btn.setVisible(True)
            else:
                self._comm_status_label.setText("已经没有更多壁纸啦~")
                self._load_more_btn.setVisible(False)
            return

        # 成功拉到一批
        self._last_page_full = len(items) >= community_wallpaper.PAGE_SIZE
        if isinstance(raw, dict):
            try:
                total = int(raw.get("total", 0) or 0)
            except (TypeError, ValueError):
                total = 0
            self._community_total = total if total > 0 else None

        self._community_items.extend(items)
        self._comm_status_label.setText("")
        self._load_more_btn.setText("🔽 加载更多")
        self._update_load_more_visible()

        for item in items:
            self._request_thumb(item)

    def _update_load_more_visible(self):
        n = len(self._community_items)
        if self._community_total is not None:
            has_more = n < self._community_total
        else:
            has_more = self._last_page_full
        self._load_more_btn.setVisible(has_more)

    def _on_community_thumb(self, item, data, err):
        if err != QNetworkReply.NoError:
            return
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        self._make_community_thumbnail(item, pixmap)

    def _make_community_thumbnail(self, item, pixmap):
        btn = QPushButton()
        btn.setFixedSize(170, 115)
        tip = item["title"] or item["display_name"] or f"社区壁纸 #{item['id']}"
        if item["width"] and item["height"]:
            tip += f"\n{item['width']}×{item['height']}"
        btn.setToolTip(tip)

        if pixmap.isNull():
            # webp 图像插件缺失时兜底：仍可点击尝试下载
            btn.setText("⚠️")
        else:
            scaled = pixmap.scaled(
                self.THUMB_W, self.THUMB_H,
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            btn.setIcon(QIcon(scaled))
            btn.setIconSize(scaled.size())
        btn.setStyleSheet(self._thumb_btn_style(self._is_community_current(item)))
        btn.clicked.connect(lambda checked, it=item: self._on_community_clicked(it))

        row, col = divmod(len(self._comm_thumb_buttons), self.COLS)
        self._comm_grid.addWidget(btn, row, col)
        self._comm_thumb_buttons.append((item, btn))

    def _cache_path(self, item):
        cache_dir = os.path.join(utils.user_data_dir(), "wallpaper_cache")
        return os.path.join(cache_dir, f"community_{item['id']}.png")

    def _is_community_current(self, item):
        return os.path.normcase(os.path.abspath(self._cache_path(item))) \
            == os.path.normcase(self._current_wallpaper)

    # ============================================================
    #  事件处理
    # ============================================================

    def _on_thumbnail_clicked(self, path):
        """点击本地缩略图 → 切换壁纸。"""
        if not (wallpaper_utils.IS_WINDOWS or wallpaper_utils.IS_MAC):
            self._warn_not_supported()
            return
        self._apply_wallpaper(path)

    def _on_community_clicked(self, item):
        """点击社区缩略图 → 命中缓存直接设；否则下载大图再设。"""
        if not (wallpaper_utils.IS_WINDOWS or wallpaper_utils.IS_MAC):
            self._warn_not_supported()
            return
        cache_path = self._cache_path(item)
        if os.path.exists(cache_path):
            self._apply_wallpaper(cache_path)
            return
        # 下载大图；期间禁用按钮防重复点击，状态栏提示进度
        for it, btn in self._comm_thumb_buttons:
            if it["id"] == item["id"]:
                btn.setEnabled(False)
                break
        self._comm_status_label.setText(
            f"蕾咪正在下载「{item['title'] or '壁纸'}」……")
        req = QNetworkRequest(QUrl(item["preview_url"]))
        req.setAttribute(QNetworkRequest.User, ("full", item))
        self._nam.get(req)

    def _on_community_full(self, item, data, err):
        # 恢复按钮可用
        for it, btn in self._comm_thumb_buttons:
            if it["id"] == item["id"]:
                btn.setEnabled(True)
                break

        if err != QNetworkReply.NoError:
            self._comm_status_label.setText("下载失败，请稍后再试。")
            return

        image = QImage()
        image.loadFromData(data)
        if image.isNull():
            self._comm_status_label.setText("无法解码该壁纸（格式不支持）。")
            QMessageBox.warning(self, "无法使用", "这张壁纸无法解码，可能是格式不支持。")
            return

        cache_dir = os.path.join(utils.user_data_dir(), "wallpaper_cache")
        try:
            os.makedirs(cache_dir, exist_ok=True)
        except OSError:
            self._comm_status_label.setText("无法创建缓存目录。")
            return

        cache_path = self._cache_path(item)
        if not image.save(cache_path, "PNG"):
            self._comm_status_label.setText("保存壁纸失败。")
            return

        self._comm_status_label.setText("")
        self._apply_wallpaper(cache_path)

    def _apply_wallpaper(self, path):
        """把本地图片设为壁纸 + 刷新高亮 + 触发桌宠表情。"""
        try:
            try:
                wallpaper_utils.set_wallpaper_style_fill()
            except OSError:
                pass
            wallpaper_utils.set_wallpaper(path)
        except Exception as exc:
            self._show_wallpaper_error(exc)
            return
        self._current_wallpaper = os.path.normcase(os.path.abspath(path))
        self._update_highlights()
        self._update_community_highlights()
        parent = self.parent()
        if parent and hasattr(parent, "play_wallpaper_emotion"):
            parent.play_wallpaper_emotion()

    def _show_wallpaper_error(self, exc):
        """设壁纸失败时把原因弹给用户。

        macOS 上最常见的是 Automation 权限没给——那种静默失败用户只会以为
        「点了没反应」，所以这里必须显式弹窗。
        """
        QMessageBox.warning(self, "切换壁纸失败", str(exc) or "切换壁纸失败")

    def _on_random(self):
        """随机选一张本地壁纸并切换。"""
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
        """刷新本地缩略图的边框高亮状态。"""
        for path, btn in self._thumb_buttons:
            is_current = os.path.normcase(os.path.abspath(path)) == os.path.normcase(self._current_wallpaper)
            btn.setStyleSheet(self._thumb_btn_style(is_current))

    def _update_community_highlights(self):
        """刷新社区缩略图的边框高亮状态。"""
        for item, btn in self._comm_thumb_buttons:
            btn.setStyleSheet(self._thumb_btn_style(self._is_community_current(item)))

    def _warn_not_supported(self):
        QMessageBox.information(
            self, "暂不支持",
            "切换壁纸目前只在 Windows 和 macOS 上可用，"
            "当前平台暂未适配。\n其余功能不受影响。")

    # ============================================================
    #  工具
    # ============================================================

    @staticmethod
    def _thumb_btn_style(is_current):
        border_color = "#DAAD69" if is_current else "#cccccc"
        border_width = "2px" if is_current else "1px"
        return f"""
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
        """

    @staticmethod
    def _read_current_wallpaper():
        """读取当前壁纸路径（用于高亮匹配）。跨平台逻辑在 wallpaper_utils。"""
        return wallpaper_utils.get_current_wallpaper()

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
