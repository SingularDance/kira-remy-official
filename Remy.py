# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 主入口

模块化结构：
  Remy.py          — 入口（本文件）
  config.py        — 配置管理 & 全局状态
  utils.py         — 纯工具函数
  dialogs.py       — 所有子窗口/对话框类
  desktop_pet.py   — RemyDesktopPet 主窗口

API Key 请写在项目根目录的 config.json 里。
可先复制 config.example.json 为 config.json，再填入密钥。
也可以启动后在弹窗 / 右键菜单「API 设置」里填写。
"""

import sys

from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import QSharedMemory

from desktop_pet import RemyDesktopPet

if __name__ == "__main__":
    # ====== 禁止多开：使用共享内存检测 ======
    app = QApplication(sys.argv)
    shared_mem = QSharedMemory("RemyDesktopPet_SingleInstance")
    if shared_mem.attach():
        # 已有实例在运行
        QMessageBox.warning(
            None,
            "Remy 桌宠",
            "蕾咪已经在运行中啦！\n\n请查看系统托盘中的蕾咪图标"
        )
        sys.exit(0)
    # 创建共享内存，标记当前实例
    shared_mem.create(1)
    # ========================================

    app.setQuitOnLastWindowClosed(False)

    pet = RemyDesktopPet()
    pet.show()

    sys.exit(app.exec_())
