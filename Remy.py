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
from PyQt5.QtCore import Qt, QSharedMemory

from desktop_pet import RemyDesktopPet

if __name__ == "__main__":
    # 跨屏不同 DPI 时减少窗口几何错乱
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    # ====== 禁止多开：使用共享内存检测 ======
    app = QApplication(sys.argv)
    shared_mem = QSharedMemory("RemyDesktopPet_SingleInstance")

    # **先 attach 再 detach，清掉可能残留的段。**
    #
    # Windows 上共享内存由内核引用计数，最后一个句柄关闭就自动释放，
    # 所以进程怎么死都不会留下东西。
    # **macOS / Linux 不是这样**：进程被强杀（活动监视器结束进程、崩溃、
    # 或者开发时 kill -9）之后，段会留在系统里。
    #
    # 于是下一次启动 attach() 会成功，程序以为「已经有一个在跑」，
    # 弹窗然后退出——**而且此后永远起不来**，重启电脑之前都是这样。
    # 用户看到的现象是「桌宠再也打不开了，一直说已在运行」。
    # 这个 bug 在 macOS 上实测复现过。
    #
    # attach 成功后立刻 detach：如果我们是最后一个引用（说明那个段
    # 是上次崩溃留下的），detach 会把它真正删掉，紧接着 create 就能成功。
    # 要是真有另一个实例活着，它自己还持有那个段，create 仍然会失败——
    # 多开照样挡得住。
    if shared_mem.attach():
        shared_mem.detach()

    if not shared_mem.create(1):
        # 到这一步才是真的有另一个实例在跑
        QMessageBox.warning(
            None,
            "Remy 桌宠",
            "蕾咪已经在运行中啦！\n\n请查看系统托盘中的蕾咪图标"
        )
        sys.exit(0)
    # ========================================

    app.setQuitOnLastWindowClosed(False)

    pet = RemyDesktopPet()
    pet.show()

    sys.exit(app.exec_())
