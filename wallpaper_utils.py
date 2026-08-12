# -*- coding: utf-8 -*-
"""
Remy 桌宠 - Windows 壁纸切换工具（ctypes + winreg，仅 Windows 有效）
"""

import ctypes
import ctypes.wintypes
import os
import random
import winreg

SPI_SETDESKWALLPAPER = 0x0014        # 20
SPIF_UPDATEINIFILE = 0x0001
SPIF_SENDCHANGE = 0x0002

WALLPAPER_EXTS = {".jpg", ".jpeg", ".bmp", ".png", ".gif"}


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
    """通过 SystemParametersInfoW 把指定图片设为桌面壁纸（需绝对路径）。
    失败时抛出 ctypes.WinError。"""
    ctypes.windll.user32.SystemParametersInfoW.argtypes = [
        ctypes.c_uint, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]
    ctypes.windll.user32.SystemParametersInfoW.restype = ctypes.wintypes.BOOL
    ok = ctypes.windll.user32.SystemParametersInfoW(
        SPI_SETDESKWALLPAPER, 0, os.path.abspath(path),
        SPIF_UPDATEINIFILE | SPIF_SENDCHANGE)
    if not ok:
        raise ctypes.WinError()


def set_wallpaper_style_fill():
    """把壁纸样式设为 Fill（WallpaperStyle=4, TileWallpaper=0），持久化到注册表。"""
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                         r"Control Panel\Desktop", 0, winreg.KEY_SET_VALUE)
    try:
        winreg.SetValueEx(key, "WallpaperStyle", 0, winreg.REG_SZ, "4")
        winreg.SetValueEx(key, "TileWallpaper", 0, winreg.REG_SZ, "0")
    finally:
        winreg.CloseKey(key)
