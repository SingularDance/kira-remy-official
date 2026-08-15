# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 版本更新对话框

样式沿用项目其余对话框：白底 + #DAAD69 金边 + 圆角，
取消类按钮用 objectName="cancel" 变灰。

职责边界：本对话框负责「展示 + 下载 + 校验」，并在打包态提供
「一键安装并重启」。覆盖安装由 self_update.py 生成的 .bat 独立进程完成
（见 UPDATE_CHECK.md §7.1）——正在运行的程序无法覆盖自己。
开发态（非打包）无 exe 可替换，退回到「打开所在文件夹」手动安装。
"""

import os
import tempfile
import threading
import webbrowser

from PyQt5.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout,
    QTextBrowser, QPushButton, QProgressBar, QMessageBox
)
from PyQt5.QtCore import Qt, pyqtSignal

import config
import downloader
import self_update
import version


class UpdateDialog(QDialog):
    """展示新版本信息，并可直接下载安装包。

    下载在后台线程进行，通过信号回主线程更新进度——Qt 的控件只能在
    主线程操作，跨线程直接调用会随机崩溃。
    """

    # 下载线程 → 主线程。Qt 会自动把跨线程的信号排队到接收者所在线程。
    progress_changed = pyqtSignal(int, int)      # (已下载字节, 总字节)
    download_finished = pyqtSignal(bool, str)    # (是否成功, 路径或错误信息)

    def __init__(self, release, parent=None):
        super().__init__(parent)
        self.release = release
        self._cancel_requested = False
        self._downloading = False
        self._downloaded_path = ""
        self.install_pending = False   # 用户点了「立即安装并重启」

        self.setWindowTitle("🔄 发现新版本")
        self.setGeometry(300, 300, 460, 400)
        self.setWindowOpacity(0.95)
        self.setStyleSheet("""
            QDialog {
                background-color: rgba(255, 255, 255, 240);
                border-radius: 15px;
                border: 1px solid #DAAD69;
            }
            QLabel { color: #333333; font-family: Microsoft YaHei; }
            QLabel#version {
                font-size: 15px;
                font-weight: bold;
                color: #1a1a1a;
            }
            QLabel#hint { color: #888888; font-size: 12px; }
            QTextBrowser {
                background-color: rgba(245, 245, 245, 230);
                border: 1px solid #333333;
                border-radius: 8px;
                color: #333333;
                font-size: 13px;
                padding: 8px;
            }
            QProgressBar {
                background-color: rgba(245, 245, 245, 230);
                border: 1px solid #333333;
                border-radius: 8px;
                text-align: center;
                color: #333333;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: #DAAD69;
                border-radius: 7px;
            }
            QPushButton {
                background-color: #DAAD69;
                color: #1a1a1a;
                border: none;
                border-radius: 5px;
                padding: 8px 20px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #E0C080; }
            QPushButton:disabled {
                background-color: #dddddd;
                color: #999999;
            }
            QPushButton#cancel { background-color: #aaaaaa; }
            QPushButton#cancel:hover { background-color: #999999; }
        """)

        self.progress_changed.connect(self._on_progress)
        self.download_finished.connect(self._on_download_finished)
        self.init_ui()

    # ============================================================
    #  UI
    # ============================================================

    def init_ui(self):
        layout = QVBoxLayout()

        title = QLabel(f"v{version.VERSION}  →  v{self.release.version}")
        title.setObjectName("version")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        if self.release.size:
            info = QLabel(f"安装包 {self.release.asset_name}"
                          f"（{self.release.size_mb} MB）")
        else:
            # 302 兜底路径拿不到大小，不能显示「0 MB」误导用户
            info = QLabel(f"安装包 {self.release.asset_name}")
        info.setObjectName("hint")
        info.setAlignment(Qt.AlignCenter)
        layout.addWidget(info)

        layout.addWidget(QLabel("更新内容："))
        self.notes_view = QTextBrowser()
        self.notes_view.setOpenExternalLinks(True)
        self.notes_view.setMarkdown(self.release.notes or "（本次没有提供更新说明）")
        layout.addWidget(self.notes_view)

        self.progress_bar = QProgressBar()
        self.progress_bar.hide()          # 未开始下载时不占视觉重量
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setObjectName("hint")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        btn_layout = QHBoxLayout()

        self.update_btn = QPushButton("⬇️ 立即下载")
        self.update_btn.clicked.connect(self.start_download)
        btn_layout.addWidget(self.update_btn)

        self.manual_btn = QPushButton("🌐 打开下载页")
        self.manual_btn.setObjectName("cancel")
        self.manual_btn.clicked.connect(self.open_release_page)
        btn_layout.addWidget(self.manual_btn)

        self.skip_btn = QPushButton("跳过此版本")
        self.skip_btn.setObjectName("cancel")
        self.skip_btn.clicked.connect(self.skip_version)
        btn_layout.addWidget(self.skip_btn)

        self.later_btn = QPushButton("稍后")
        self.later_btn.setObjectName("cancel")
        self.later_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.later_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

    # ============================================================
    #  下载
    # ============================================================

    def start_download(self):
        if self._downloading:
            return
        if not self.release.download_url:
            QMessageBox.warning(self, "提示", "⚠️ 这个版本没有提供下载地址")
            return

        self._downloading = True
        self._cancel_requested = False
        self.update_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.status_label.setText("正在连接…")

        # 「稍后」在下载期间改成取消，避免用户以为关窗就能停
        self.later_btn.setText("取消下载")
        self.later_btn.clicked.disconnect()
        self.later_btn.clicked.connect(self.cancel_download)

        threading.Thread(target=self._download_worker, daemon=True).start()

    def _download_worker(self):
        """后台线程：下载 + 校验。绝不在这里碰任何控件。"""
        dest = os.path.join(tempfile.gettempdir(),
                            self.release.asset_name or "Remy_update.zip")
        result = downloader.download(
            self.release.download_url,
            dest,
            expected_size=self.release.size,
            progress=lambda got, total: self.progress_changed.emit(got, total),
            should_cancel=lambda: self._cancel_requested,
        )
        if not result.ok:
            self.download_finished.emit(False, result.error)
            return

        # 下载完成不等于可用：断掉的 zip 解压会写入半个文件，
        # 而用户此时可能已经关掉了旧程序，等于变砖。
        ok, detail = downloader.verify_zip(result.path)
        if not ok:
            self.download_finished.emit(False, f"校验失败：{detail}")
            return

        self.download_finished.emit(True, result.path)

    def cancel_download(self):
        self._cancel_requested = True
        self.status_label.setText("正在取消…")

    def _on_progress(self, got, total):
        if total:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(got)
            self.status_label.setText(
                f"已下载 {got / 1048576:.1f} / {total / 1048576:.1f} MB")
        else:
            # 总大小未知时用忙碌态，别显示假的百分比
            self.progress_bar.setMaximum(0)
            self.status_label.setText(f"已下载 {got / 1048576:.1f} MB")

    def _on_download_finished(self, ok, detail):
        self._downloading = False
        self._restore_later_button()

        if not ok:
            self.progress_bar.hide()
            self.update_btn.setEnabled(True)
            self.skip_btn.setEnabled(True)
            self.status_label.setText(f"下载失败：{detail}")
            # GitHub 在国内常常连不上，直接给手动下载这条路
            QMessageBox.warning(
                self, "下载失败",
                f"⚠️ {detail}\n\n可以点「打开下载页」手动下载。")
            return

        self._downloaded_path = detail
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(100)
        self.status_label.setText("下载完成，已通过完整性校验")
        self.update_btn.setEnabled(True)
        self.update_btn.clicked.disconnect()

        if self_update.is_frozen():
            # 打包态：一键安装并重启，不再让用户手动解压
            self.update_btn.setText("🔄 立即安装并重启")
            self.update_btn.clicked.connect(self.install_and_restart)
        else:
            # 开发态没有可替换的 exe，退回手动打开文件夹
            self.update_btn.setText("📂 打开所在文件夹")
            self.update_btn.clicked.connect(self.open_download_folder)
            QMessageBox.information(
                self, "下载完成",
                f"✅ 已下载到：\n{detail}\n\n"
                "请退出蕾咪后，把压缩包内容解压覆盖到程序目录。\n"
                "注意保留你自己的 config.json（里面有 API Key）。")

    def _restore_later_button(self):
        self.later_btn.setText("关闭")
        self.later_btn.clicked.disconnect()
        self.later_btn.clicked.connect(self.reject)

    # ============================================================
    #  其他动作
    # ============================================================

    def open_release_page(self):
        url = self.release.page_url or self.release.download_url
        if url:
            webbrowser.open(url)

    def open_download_folder(self):
        if not self._downloaded_path:
            return
        folder = os.path.dirname(self._downloaded_path)
        try:
            # os.startfile 只有 Windows 有；其他平台退回 file:// 交给系统处理
            if hasattr(os, "startfile"):
                os.startfile(folder)
            else:
                webbrowser.open(f"file://{folder}")
        except OSError as exc:
            QMessageBox.warning(self, "提示", f"⚠️ 打不开文件夹：{exc}")

    def install_and_restart(self):
        """一键安装并重启：解压到 staging → 生成 .bat → 启动，然后关闭整个程序。

        .bat 已在后台分离启动并等待旧程序退出；本方法只负责「关掉自己」，
        剩下的替换+重启由 .bat 完成。
        """
        if not self._downloaded_path:
            return
        try:
            self_update.apply_update(self._downloaded_path)
        except Exception as exc:
            QMessageBox.warning(self, "安装失败", f"⚠️ {exc}")
            return
        self.install_pending = True
        self.accept()

    def skip_version(self):
        """记住这个版本，以后不再自动提示。手动检查更新时仍会显示。"""
        config.CONFIG.setdefault("update", {})["skip_version"] = \
            self.release.version
        config.save_config()
        QMessageBox.information(
            self, "已跳过",
            f"✅ 不再提示 v{self.release.version}。\n"
            "想要重新检查，可以从右键菜单点「检查更新」。")
        self.reject()

    def closeEvent(self, event):
        """关窗时确保下载线程会退出，别留个后台线程继续写临时文件。"""
        self._cancel_requested = True
        super().closeEvent(event)
