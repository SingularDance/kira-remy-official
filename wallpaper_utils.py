# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 壁纸切换工具

Windows：ctypes + winreg（SystemParametersInfoW + 注册表填充样式）
macOS：osascript 调 System Events（set picture of every desktop）
其余平台：显式报错，不静默吞掉

本模块不 import Qt：Windows 走 ctypes/winreg，macOS 走 subprocess 调
osascript，两边都能脱离 UI 独立单测。
"""

import ctypes
import os
import subprocess
import sys

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# winreg 与 user32 是 Windows 独占。无条件 import 会让整个程序在非 Windows
# 平台启动失败（dialogs 包会连带导入本模块）。加这个保护只是为了让代码在
# 别的平台上可导入、可测试。
if IS_WINDOWS:
    import ctypes.wintypes
    import winreg

SPI_SETDESKWALLPAPER = 0x0014        # 20
SPIF_UPDATEINIFILE = 0x0001
SPIF_SENDCHANGE = 0x0002

WALLPAPER_EXTS = {".jpg", ".jpeg", ".bmp", ".png", ".gif"}

# macOS 上 osascript 偶尔会卡在权限弹窗或目标进程忙，不设超时 UI 会假死。
# 壁纸是一次性点击（对比音乐监听的高频轮询），超时放宽到 5 秒。
OSASCRIPT_TIMEOUT = 5.0

# macOS Automation 权限被拒时的特征串（与 music_mac.py 的判断口径一致）
_DENIED_MARKERS = ("-1743", "not authoriz", "不允许", "没有权限", "not allowed")


def list_wallpapers(folder):
    """枚举文件夹内所有受支持的壁纸图片，返回绝对路径列表（按文件名排序）。
    文件夹为空 / 不存在 / 无权限时返回 []。"""
    if not folder or not os.path.isdir(folder):
        return []
    try:
        names = [f for f in os.listdir(folder)
                 if os.path.splitext(f)[1].lower() in WALLPAPER_EXTS]
        paths = [os.path.join(folder, n) for n in names
                 if os.path.isfile(os.path.join(folder, n))]
    except OSError:
        return []
    return sorted(paths, key=lambda p: os.path.basename(p).lower())


def set_wallpaper(path):
    """把指定图片设为桌面壁纸（需绝对路径）。

    Windows：SystemParametersInfoW；macOS：osascript 调 System Events。
    失败抛 RuntimeError（macOS 权限被拒时带修复指引）。
    非 Win/Mac 平台抛 RuntimeError。
    """
    if IS_WINDOWS:
        _set_wallpaper_windows(path)
    elif IS_MAC:
        _set_wallpaper_mac(path)
    else:
        raise RuntimeError("切换壁纸仅支持 Windows 与 macOS")


def _set_wallpaper_windows(path):
    """SystemParametersInfoW 设壁纸。失败抛 ctypes.WinError（OSError 子类）。"""
    ctypes.windll.user32.SystemParametersInfoW.argtypes = [
        ctypes.c_uint, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]
    ctypes.windll.user32.SystemParametersInfoW.restype = ctypes.wintypes.BOOL
    ok = ctypes.windll.user32.SystemParametersInfoW(
        SPI_SETDESKWALLPAPER, 0, os.path.abspath(path),
        SPIF_UPDATEINIFILE | SPIF_SENDCHANGE)
    if not ok:
        raise ctypes.WinError()


def _set_wallpaper_mac(path):
    """osascript 调 System Events 设壁纸。

    路径用 `on run argv` 当参数传给脚本，而不是嵌进 AppleScript 字符串里——
    路径里可能带引号、反斜杠，拼字符串会踩转义坑。
    """
    script = (
        "on run argv\n"
        "    set wallpaperPath to POSIX file (item 1 of argv)\n"
        '    tell application "System Events"\n'
        "        set picture of every desktop to wallpaperPath\n"
        "    end tell\n"
        "end run"
    )
    try:
        p = subprocess.run(
            ["osascript", "-e", script, os.path.abspath(path)],
            capture_output=True, text=True, timeout=OSASCRIPT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("设置壁纸超时（osascript 卡住了）")
    except OSError as exc:
        raise RuntimeError(f"无法调用 osascript：{exc}")

    if p.returncode != 0:
        err = (p.stderr or "").strip()
        if any(m in err for m in _DENIED_MARKERS):
            raise RuntimeError(
                "蕾咪没有控制「System Events」的权限。\n"
                "请在系统弹出的授权框里点「允许」；若没看到，打开\n"
                "「系统设置 → 隐私与安全性 → 自动化」，找到「MACPetRemy」，"
                "勾选「System Events」后再点一次。")
        raise RuntimeError(err or "设置壁纸失败")


def set_wallpaper_style_fill():
    """把壁纸样式设为 Fill（Windows 注册表 WallpaperStyle=4, TileWallpaper=0）。

    「填充」是 Windows 的概念；macOS 由系统按图片比例决定缩放，没有对等
    设置，直接返回。非 Windows 平台都不抛错——这个函数是「尽力而为」，
    不该因为平台不支持就阻断设壁纸主流程。
    """
    if not IS_WINDOWS:
        return
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                         r"Control Panel\Desktop", 0, winreg.KEY_SET_VALUE)
    try:
        winreg.SetValueEx(key, "WallpaperStyle", 0, winreg.REG_SZ, "4")
        winreg.SetValueEx(key, "TileWallpaper", 0, winreg.REG_SZ, "0")
    finally:
        winreg.CloseKey(key)


def get_current_wallpaper():
    """读取当前桌面壁纸路径（用于缩略图高亮匹配）。拿不到返回 ""。

    只做高亮辅助，绝不抛——读不到（含 macOS 权限没给）都返回 ""。
    """
    if IS_WINDOWS:
        return _read_current_wallpaper_windows()
    if IS_MAC:
        return _read_current_wallpaper_mac()
    return ""


def _read_current_wallpaper_windows():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Control Panel\Desktop", 0, winreg.KEY_READ)
        value, _ = winreg.QueryValueEx(key, "Wallpaper")
        winreg.CloseKey(key)
        return os.path.normcase(os.path.abspath(value))
    except Exception:
        return ""


def _read_current_wallpaper_mac():
    """问 System Events 当前桌面壁纸，转成 POSIX 路径。"""
    script = (
        'tell application "System Events"\n'
        "    set thePics to picture of every desktop\n"
        "    if (count of thePics) > 0 then\n"
        "        return POSIX path of (item 1 of thePics)\n"
        "    end if\n"
        '    return ""\n'
        "end tell"
    )
    try:
        p = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=OSASCRIPT_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    if p.returncode != 0:
        return ""
    out = (p.stdout or "").strip()
    if not out:
        return ""
    return os.path.normcase(os.path.abspath(out))
