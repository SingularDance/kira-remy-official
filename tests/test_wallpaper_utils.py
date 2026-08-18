# -*- coding: utf-8 -*-
"""wallpaper_utils 的 macOS 分支测试。

macOS 设壁纸走 osascript，Windows 走 ctypes。本文件用 mock 把 subprocess
摘掉，让 mac 分支在 Windows 开发机上也能跑——测的是「命令怎么拼、失败怎么
报」，不真的去设壁纸，也不需要 mac 环境。
"""

import os
import subprocess
import unittest
from contextlib import contextmanager
from unittest import mock

import wallpaper_utils


def _ok(stdout="", stderr=""):
    return mock.Mock(returncode=0, stdout=stdout, stderr=stderr)


def _fail(stderr="", returncode=1):
    return mock.Mock(returncode=returncode, stdout="", stderr=stderr)


@contextmanager
def _as_mac():
    """临时把模块伪装成 macOS（IS_WINDOWS=False, IS_MAC=True）。"""
    with mock.patch.object(wallpaper_utils, "IS_WINDOWS", False), \
         mock.patch.object(wallpaper_utils, "IS_MAC", True):
        yield


class TestSetWallpaperMac(unittest.TestCase):

    def test_通过osascript调用SystemEvents设壁纸(self):
        with _as_mac(), \
             mock.patch("wallpaper_utils.subprocess.run", return_value=_ok()) as run:
            wallpaper_utils.set_wallpaper("/tmp/a b.png")

        args = run.call_args[0][0]
        self.assertEqual(args[0], "osascript")
        self.assertEqual(args[1], "-e")
        self.assertIn("System Events", args[2])
        # 路径作为 argv 参数传给脚本，而不是嵌进 AppleScript 字符串里
        self.assertEqual(args[3], os.path.abspath("/tmp/a b.png"))

    def test_路径含引号反斜杠不因转义出错(self):
        tricky = '/tmp/"quote"\\back.png'
        with _as_mac(), \
             mock.patch("wallpaper_utils.subprocess.run", return_value=_ok()) as run:
            wallpaper_utils.set_wallpaper(tricky)
        self.assertEqual(run.call_args[0][0][3], os.path.abspath(tricky))

    def test_权限被拒时抛带指引的错(self):
        denied = _fail(stderr="-1743: Not authorized to send Apple events.")
        with _as_mac(), \
             mock.patch("wallpaper_utils.subprocess.run", return_value=denied):
            with self.assertRaises(RuntimeError) as cm:
                wallpaper_utils.set_wallpaper("/tmp/x.png")
        self.assertIn("自动化", str(cm.exception))

    def test_其它失败抛原始错误(self):
        with _as_mac(), \
             mock.patch("wallpaper_utils.subprocess.run",
                        return_value=_fail(stderr="boom")):
            with self.assertRaises(RuntimeError) as cm:
                wallpaper_utils.set_wallpaper("/tmp/x.png")
        self.assertIn("boom", str(cm.exception))

    def test_osascript超时抛错(self):
        with _as_mac(), \
             mock.patch("wallpaper_utils.subprocess.run",
                        side_effect=subprocess.TimeoutExpired("osascript", 5)):
            with self.assertRaises(RuntimeError):
                wallpaper_utils.set_wallpaper("/tmp/x.png")


class TestUnsupportedPlatform(unittest.TestCase):

    def test_非Win非Mac抛错(self):
        with mock.patch.object(wallpaper_utils, "IS_WINDOWS", False), \
             mock.patch.object(wallpaper_utils, "IS_MAC", False):
            with self.assertRaises(RuntimeError):
                wallpaper_utils.set_wallpaper("/tmp/x.png")

    def test_样式设置在非Windows上是空操作(self):
        # 曾因 set_wallpaper_style_fill 在非 Windows 抛 RuntimeError，
        # 导致 mac 上「更换文件夹」也会被它中断。现在必须是空操作。
        with mock.patch.object(wallpaper_utils, "IS_WINDOWS", False):
            wallpaper_utils.set_wallpaper_style_fill()  # 不抛即可


class TestGetCurrentWallpaper(unittest.TestCase):

    def test_mac读取当前壁纸路径(self):
        with _as_mac(), \
             mock.patch("wallpaper_utils.subprocess.run",
                        return_value=_ok(stdout="/Users/foo/bg.jpg\n")):
            got = wallpaper_utils.get_current_wallpaper()
        self.assertEqual(got, os.path.normcase(os.path.abspath("/Users/foo/bg.jpg")))

    def test_mac读不到时返回空串(self):
        with _as_mac(), \
             mock.patch("wallpaper_utils.subprocess.run",
                        return_value=_fail(stderr="-1743")):
            self.assertEqual(wallpaper_utils.get_current_wallpaper(), "")

    def test_非Win非Mac返回空串(self):
        with mock.patch.object(wallpaper_utils, "IS_WINDOWS", False), \
             mock.patch.object(wallpaper_utils, "IS_MAC", False):
            self.assertEqual(wallpaper_utils.get_current_wallpaper(), "")


if __name__ == "__main__":
    unittest.main()
