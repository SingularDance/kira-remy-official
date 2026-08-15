# -*- coding: utf-8 -*-
"""自动安装：把已下载并校验通过的安装包替换进安装目录，并重启程序。

为什么需要这个模块：Windows 上运行中的 exe 文件被锁定，程序无法覆盖自己。
所以「覆盖安装」只能交给一个独立的进程来做——这里用一个临时生成的 .bat 脚本：

1. 等旧程序退出、释放 exe 文件锁；
2. 用 robocopy 把新文件覆盖进安装目录（自带锁文件重试）；
3. 清理临时文件与下载包；
4. 以安装目录为工作目录重启新版（config.json 等数据都按工作目录读写，
   不设 /D 会跑到临时目录去新建配置）；
5. 自删。

设计约束（与 updater.py / downloader.py 同一套纪律）：

- **纯逻辑，无 Qt**。本模块只准备文件、生成脚本、启动脚本，不碰任何控件，
  所以能单测到「解压到哪、保护哪些文件、脚本里写了什么」这一层。
- **只在打包态生效**。开发时 `sys.frozen` 为假，`apply_update` 直接抛错，
  由调用方（更新对话框）回退到「打开所在文件夹」的手动行为。
- **安全复用 downloader.safe_extract**：zip slip 防御、剥顶层目录、
  以及「绝不覆盖用户数据」——受保护文件（config.json 含 API Key、chat_log、
  notes、stats、shortcuts、music_history）在 staging 里先剔除，再让脚本覆盖，
  这样脚本本身保持「无脑复制」的简单。
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile

import downloader

logger = logging.getLogger(__name__)

# staging 目录名：解压到这里，再由 .bat 复制进安装目录。
# 放在临时目录而非安装目录内，避免「把目录复制进它自己」的歧义。
_STAGING_NAME = "remy_update_pending"

# .bat 脚本名。固定名，重复更新时直接覆盖，不会堆积。
_SCRIPT_NAME = "remy_update.bat"

# .bat 写入编码。必须与 pack.bat 一致用 GBK：中文 Windows 的 cmd 用 OEM 代码页
# 936 解析 .bat，GBK 是其原生编码，中文路径不会被读乱。之前用 UTF-8 + chcp 65001，
# 在含中文目录名（如「桌面\某文件夹\」）时会被 cmd 读乱，导致更新覆盖到错误路径。
_BAT_ENCODING = "gbk"

# 覆盖安装脚本模板。占位符用 str.format 注入，路径一律双引号包裹。
# 编码用 GBK（见 _BAT_ENCODING），与 pack.bat 一致，靠中文 Windows 的 OEM
# 代码页 936 原生解析中文路径——不再用 chcp 65001（那套在中文目录名上会读乱）。
_BAT_TEMPLATE = """@echo off
rem 等旧程序退出并释放 exe 文件锁
timeout /t 3 /nobreak >nul
rem 覆盖安装（staging 里已剔除受保护的用户数据）
robocopy "{staging}" "{install_dir}" /E /IS /IT /NFL /NDL /NJH /NJS /R:3 /W:2 >nul
rem 清理临时文件与下载包
rmdir /s /q "{staging}"
del /f /q "{zip_path}"
rem 关键：让新版 onefile 忽略继承的 _PYI_APPLICATION_HOME_DIR，重新解压到全新 _MEI。
rem 否则新版会沿用旧进程已被删除的 _MEI 临时目录，报「Failed to load Python DLL」。
set PYINSTALLER_RESET_ENVIRONMENT=1
rem 以安装目录为工作目录重启新版（config.json 等数据都在那）
start "" /D "{install_dir}" "{exe_path}"
rem 自删本脚本（(goto) 跳过当前行使 cmd 释放句柄）
(goto) 2>nul & del "%~f0"
"""


def is_frozen() -> bool:
    """是否 PyInstaller 打包态。开发态不该走自动安装。"""
    return bool(getattr(sys, "frozen", False))


def install_dir() -> str:
    """安装目录：打包后是 exe 所在目录；开发态是脚本目录。"""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def exe_path() -> str:
    """当前程序的 exe 绝对路径。开发态返回空串（没有可替换的 exe）。"""
    return sys.executable if is_frozen() else ""


def staging_dir() -> str:
    return os.path.join(tempfile.gettempdir(), _STAGING_NAME)


def prepare_update(zip_path: str, staging: str = "") -> str:
    """把 zip 解压到 staging，剔除受保护文件后返回 staging 路径。

    失败抛 RuntimeError（由调用方弹窗提示），不返回错误对象——
    这里没有「部分成功要报告」的场景，要么能装要么不能。
    """
    staging = staging or staging_dir()
    # 清掉上次残留，避免新旧文件混在一起
    shutil.rmtree(staging, ignore_errors=True)

    result = downloader.safe_extract(zip_path, staging)
    if not result.ok:
        raise RuntimeError(result.error)

    _strip_protected(staging)
    return staging


def _strip_protected(staging: str) -> None:
    """把 staging 里的受保护文件删掉，确保 .bat 覆盖时不会冲掉用户数据。

    safe_extract 在「目标已存在」时才跳过受保护文件；staging 是全新目录，
    不会触发跳过，所以这里要手动再清一遍。
    """
    for name in downloader.PROTECTED_FILES:
        path = os.path.join(staging, name)
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.exists(path):
                os.remove(path)
        except OSError as exc:
            logger.warning("清理 staging 受保护文件失败：%s", exc)


def write_apply_script(staging: str, zip_path: str,
                       install: str = "", exe: str = "") -> str:
    """生成覆盖安装的 .bat，返回脚本路径。install/exe 留空时自动探测。"""
    target = install or install_dir()
    target_exe = exe or exe_path()
    if not target_exe:
        raise RuntimeError("无法确定程序 exe 路径，无法自动安装")

    content = _BAT_TEMPLATE.format(
        staging=staging,
        install_dir=target,
        zip_path=zip_path,
        exe_path=target_exe,
    )
    script = os.path.join(tempfile.gettempdir(), _SCRIPT_NAME)
    with open(script, "w", encoding=_BAT_ENCODING) as f:
        f.write(content)
    return script


def launch_apply_script(script: str) -> None:
    """分离启动 .bat：不等待、随旧程序退出后继续跑完。

    组合 DETACHED_PROCESS（父进程退出后仍存活）+ CREATE_NO_WINDOW（不闪窗）。
    这些 flag 仅 Windows 有，用 getattr 兜底保证跨平台 import 不炸。
    """
    flags = 0
    for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
        flags |= getattr(subprocess, name, 0)
    subprocess.Popen(["cmd", "/c", script],
                     creationflags=flags, close_fds=True)


def apply_update(zip_path: str) -> None:
    """一键安装：解压到 staging → 生成 .bat → 启动。仅打包态可用。"""
    if not is_frozen():
        raise RuntimeError("仅打包版支持自动安装")
    staging = prepare_update(zip_path)
    script = write_apply_script(staging, zip_path)
    launch_apply_script(script)
