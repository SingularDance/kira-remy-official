# -*- coding: utf-8 -*-
"""自动安装（self_update）的测试。

只测纯逻辑层：解压到 staging、剔除受保护文件、生成 .bat 的内容、
以及打包态/开发态的路径判定。**不真正跑 .bat、不联网、不替换文件**——
那些只能在 Windows 打包态手动验证。
"""

import os
import tempfile
import unittest
import zipfile
from unittest import mock

import self_update
from downloader import PROTECTED_FILES


def make_zip(path, entries):
    """entries: {内部路径: bytes}。用 ZipInfo 以便写出顶层目录结构。"""
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(zipfile.ZipInfo(name), data)


class TempDirCase(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def path(self, name):
        return os.path.join(self.dir, name)


class TestPrepareUpdate(TempDirCase):

    def setUp(self):
        super().setUp()
        self.zip_path = self.path("pkg.zip")
        self.staging = self.path("staging")

    def test_extracts_and_strips_top_level(self):
        make_zip(self.zip_path, {
            "Remy_v1.2.0/Remy.py": b"code",
            "Remy_v1.2.0/dialogs/note.py": b"code",
        })
        out = self_update.prepare_update(self.zip_path, staging=self.staging)
        self.assertEqual(out, self.staging)
        self.assertTrue(os.path.exists(os.path.join(self.staging, "Remy.py")))
        self.assertTrue(os.path.exists(
            os.path.join(self.staging, "dialogs", "note.py")))
        # 顶层目录被剥掉，不能解出嵌套目录
        self.assertFalse(os.path.exists(
            os.path.join(self.staging, "Remy_v1.2.0")))

    def test_strips_protected_files(self):
        """staging 是全新目录，safe_extract 不会跳过受保护文件，
        必须由 _strip_protected 再清一遍，否则 .bat 会冲掉用户数据。"""
        make_zip(self.zip_path, {
            "Remy_v1.2.0/Remy.py": b"code",
            **{f"Remy_v1.2.0/{n}": b"new" for n in PROTECTED_FILES},
        })
        self_update.prepare_update(self.zip_path, staging=self.staging)
        self.assertTrue(os.path.exists(os.path.join(self.staging, "Remy.py")))
        for name in PROTECTED_FILES:
            self.assertFalse(
                os.path.exists(os.path.join(self.staging, name)),
                f"{name} 不该被带进安装目录")

    def test_broken_zip_raises(self):
        with open(self.zip_path, "wb") as f:
            f.write(b"not a zip")
        with self.assertRaises(RuntimeError):
            self_update.prepare_update(self.zip_path, staging=self.staging)


class TestWriteApplyScript(TempDirCase):

    def test_script_contains_paths_and_commands(self):
        staging = self.path("staging")
        zip_path = self.path("pkg.zip")
        install = r"C:\Program Files\Remy"
        exe = r"C:\Program Files\Remy\星夜颂歌-蕾咪！.exe"
        script = self_update.write_apply_script(
            staging, zip_path, install=install, exe=exe)
        self.assertTrue(os.path.exists(script))
        with open(script, encoding=self_update._BAT_ENCODING) as f:
            content = f.read()
        # 四个路径都要注入，且带双引号
        for token in (install, exe, staging, zip_path):
            self.assertIn(token, content)
        self.assertIn(f'"{install}"', content)
        # 关键命令与工作目录保护都在
        self.assertIn("robocopy", content)
        self.assertIn('start "" /D', content)
        self.assertIn("rmdir /s /q", content)
        # onefile 自更新 relaunch 必须重置环境，否则新版会复用旧 _MEI 报 DLL 加载失败
        self.assertIn("PYINSTALLER_RESET_ENVIRONMENT=1", content)

    def test_missing_exe_raises(self):
        """开发态没有 exe，直接调用应当报错而非生成坏脚本。"""
        with mock.patch.object(self_update, "exe_path", return_value=""):
            with self.assertRaises(RuntimeError):
                self_update.write_apply_script(
                    self.path("staging"), self.path("pkg.zip"))


class TestPaths(unittest.TestCase):

    def test_is_frozen_defaults_false(self):
        self.assertFalse(self_update.is_frozen())

    def test_frozen_detection(self):
        with mock.patch.object(self_update.sys, "frozen", True, create=True):
            self.assertTrue(self_update.is_frozen())

    def test_install_dir_frozen(self):
        with mock.patch.object(self_update, "is_frozen", return_value=True), \
             mock.patch.object(self_update.sys, "executable",
                               r"C:\App\星夜颂歌-蕾咪！.exe"):
            self.assertEqual(self_update.install_dir(), r"C:\App")

    def test_exe_path_frozen_and_dev(self):
        with mock.patch.object(self_update, "is_frozen", return_value=True), \
             mock.patch.object(self_update.sys, "executable", r"C:\App\a.exe"):
            self.assertEqual(self_update.exe_path(), r"C:\App\a.exe")
        with mock.patch.object(self_update, "is_frozen", return_value=False):
            self.assertEqual(self_update.exe_path(), "")


if __name__ == "__main__":
    unittest.main()
