# -*- coding: utf-8 -*-
"""下载与解压的测试。

重点在危险路径：下载中断、大小不符、zip 被截断、压缩包里有路径穿越条目、
以及绝不能覆盖 config.json（里面是用户的 API Key）。

这些场景真机很难复现——安装包 47MB，要专门制造断网；而一旦出问题
用户的安装目录就毁了。所以必须在这里造。
"""

import os
import tempfile
import unittest
import zipfile

from downloader import (PROTECTED_FILES, _decode_name, download,
                        download_dir, safe_extract, verify_zip)


class FakeResponse:
    """假的流式响应。chunks 里放 bytes；放 Exception 则在该处抛出。"""

    def __init__(self, chunks=(), status_code=200, headers=None):
        self._chunks = list(chunks)
        self.status_code = status_code
        self.headers = headers or {}

    def iter_content(self, chunk_size=None):
        for c in self._chunks:
            if isinstance(c, Exception):
                raise c
            yield c


def getter(response):
    if isinstance(response, Exception):
        def _get(url, **kw):
            raise response
    else:
        def _get(url, **kw):
            return response
    return _get


class TempDirCase(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def path(self, name):
        return os.path.join(self.dir, name)


# ============================================================
# 下载
# ============================================================

class TestDownload(TempDirCase):

    def test_success_writes_file_and_reports_bytes(self):
        dest = self.path("pkg.zip")
        res = download("http://x/pkg.zip", dest,
                       get=getter(FakeResponse([b"abc", b"de"])))
        self.assertTrue(res.ok, res.error)
        self.assertEqual(res.downloaded, 5)
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), b"abcde")

    def test_no_part_file_left_behind(self):
        dest = self.path("pkg.zip")
        download("http://x", dest, get=getter(FakeResponse([b"abc"])))
        self.assertFalse(os.path.exists(dest + ".part"))

    def test_size_mismatch_rejected_and_dest_absent(self):
        """核心保护：大小不符说明下载不完整，绝不能留下 dest。"""
        dest = self.path("pkg.zip")
        res = download("http://x", dest, expected_size=999,
                       get=getter(FakeResponse([b"abc"])))
        self.assertFalse(res.ok)
        self.assertIn("大小不符", res.error)
        self.assertFalse(os.path.exists(dest))
        self.assertFalse(os.path.exists(dest + ".part"))

    def test_size_match_accepted(self):
        dest = self.path("pkg.zip")
        res = download("http://x", dest, expected_size=3,
                       get=getter(FakeResponse([b"abc"])))
        self.assertTrue(res.ok, res.error)

    def test_unknown_size_skips_check(self):
        """302 兜底路径拿不到大小，此时不能因为无法核对就拒绝下载。"""
        dest = self.path("pkg.zip")
        res = download("http://x", dest, expected_size=0,
                       get=getter(FakeResponse([b"abc"])))
        self.assertTrue(res.ok, res.error)

    def test_http_error(self):
        res = download("http://x", self.path("p.zip"),
                       get=getter(FakeResponse(status_code=404)))
        self.assertFalse(res.ok)
        self.assertIn("404", res.error)

    def test_connection_exception_is_returned_not_raised(self):
        res = download("http://x", self.path("p.zip"),
                       get=getter(OSError("connection reset")))
        self.assertFalse(res.ok)
        self.assertIn("连接失败", res.error)

    def test_mid_stream_exception_cleans_up(self):
        """下到一半断网：不留 dest，也不留 .part。"""
        dest = self.path("pkg.zip")
        res = download("http://x", dest, get=getter(
            FakeResponse([b"abc", OSError("断流")])))
        self.assertFalse(res.ok)
        self.assertFalse(os.path.exists(dest))
        self.assertFalse(os.path.exists(dest + ".part"))

    def test_cancel_stops_and_cleans_up(self):
        dest = self.path("pkg.zip")
        res = download("http://x", dest, should_cancel=lambda: True,
                       get=getter(FakeResponse([b"abc", b"de"])))
        self.assertFalse(res.ok)
        self.assertTrue(res.cancelled)
        self.assertFalse(os.path.exists(dest))

    def test_progress_callback_receives_totals(self):
        seen = []
        download("http://x", self.path("p.zip"), expected_size=5,
                 progress=lambda got, total: seen.append((got, total)),
                 get=getter(FakeResponse([b"abc", b"de"])))
        self.assertEqual(seen, [(3, 5), (5, 5)])

    def test_progress_uses_content_length_when_size_unknown(self):
        seen = []
        download("http://x", self.path("p.zip"),
                 progress=lambda got, total: seen.append(total),
                 get=getter(FakeResponse([b"abc"],
                                         headers={"Content-Length": "3"})))
        self.assertEqual(seen, [3])

    def test_progress_callback_exception_does_not_fail_download(self):
        """进度回调是 UI 代码，它出问题不该让下载失败。"""
        def boom(got, total):
            raise RuntimeError("UI 挂了")
        res = download("http://x", self.path("p.zip"), progress=boom,
                       get=getter(FakeResponse([b"abc"])))
        self.assertTrue(res.ok, res.error)

    def test_empty_keepalive_chunks_ignored(self):
        res = download("http://x", self.path("p.zip"),
                       get=getter(FakeResponse([b"", b"abc", b""])))
        self.assertEqual(res.downloaded, 3)


# ============================================================
# 下载目录
# ============================================================

class TestDownloadDir(unittest.TestCase):

    def test_darwin_uses_downloads_folder(self):
        """macOS 用「下载」目录，而不是随机字符的临时目录。"""
        self.assertEqual(download_dir("darwin"),
                         os.path.expanduser("~/Downloads"))

    def test_other_platforms_use_tempdir(self):
        self.assertEqual(download_dir("win32"), tempfile.gettempdir())


# ============================================================
# 校验
# ============================================================

def make_zip(path, entries):
    """entries: {内部路径: bytes}。用 ZipInfo 以便写出不安全的条目名。"""
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(zipfile.ZipInfo(name), data)


class TestVerifyZip(TempDirCase):

    def test_good_zip(self):
        p = self.path("ok.zip")
        make_zip(p, {"a.txt": b"hello"})
        self.assertEqual(verify_zip(p), (True, "完整"))

    def test_missing_file(self):
        ok, why = verify_zip(self.path("nope.zip"))
        self.assertFalse(ok)
        self.assertIn("不存在", why)

    def test_not_a_zip(self):
        p = self.path("fake.zip")
        with open(p, "wb") as f:
            f.write("这其实是 HTML 错误页".encode("utf-8"))
        ok, why = verify_zip(p)
        self.assertFalse(ok)
        self.assertIn("不是合法的 zip", why)

    def test_truncated_zip_rejected(self):
        """最关键的一条：下载中断最常见的表现就是文件被截断。

        解压半个 zip 会写入半个文件，把安装目录搞坏。
        """
        p = self.path("cut.zip")
        make_zip(p, {"a.txt": b"x" * 5000})
        size = os.path.getsize(p)
        with open(p, "r+b") as f:      # 砍掉尾部
            f.truncate(size // 2)
        ok, _ = verify_zip(p)
        self.assertFalse(ok)

    def test_empty_zip_rejected(self):
        p = self.path("empty.zip")
        with zipfile.ZipFile(p, "w"):
            pass
        ok, why = verify_zip(p)
        self.assertFalse(ok)
        self.assertIn("空", why)


# ============================================================
# 解压
# ============================================================

class TestSafeExtract(TempDirCase):

    def setUp(self):
        super().setUp()
        self.zip_path = self.path("pkg.zip")
        self.target = self.path("app")
        os.makedirs(self.target, exist_ok=True)

    def test_extracts_flat_archive(self):
        make_zip(self.zip_path, {"Remy.py": b"code", "utils.py": b"code"})
        res = safe_extract(self.zip_path, self.target)
        self.assertTrue(res.ok, res.error)
        self.assertEqual(res.extracted, 2)
        self.assertTrue(os.path.exists(os.path.join(self.target, "Remy.py")))

    def test_strips_common_top_level_dir(self):
        """发布包通常有一层 Remy_v1.1.1/，不剥掉就会解出嵌套目录，
        更新等于没生效。"""
        make_zip(self.zip_path, {
            "Remy_v1.1.1/Remy.py": b"code",
            "Remy_v1.1.1/dialogs/note.py": b"code",
        })
        res = safe_extract(self.zip_path, self.target)
        self.assertTrue(os.path.exists(os.path.join(self.target, "Remy.py")))
        self.assertTrue(os.path.exists(
            os.path.join(self.target, "dialogs", "note.py")))

    def test_keeps_top_level_when_disabled(self):
        make_zip(self.zip_path, {"Remy_v1.1.1/Remy.py": b"code"})
        safe_extract(self.zip_path, self.target, strip_top_level=False)
        self.assertTrue(os.path.exists(
            os.path.join(self.target, "Remy_v1.1.1", "Remy.py")))

    def test_does_not_strip_when_multiple_top_levels(self):
        make_zip(self.zip_path, {"a/x.py": b"1", "b/y.py": b"2"})
        safe_extract(self.zip_path, self.target)
        self.assertTrue(os.path.exists(os.path.join(self.target, "a", "x.py")))

    def test_protected_file_not_overwritten(self):
        """最重要的一条：config.json 里是用户的 API Key。"""
        cfg = os.path.join(self.target, "config.json")
        with open(cfg, "w", encoding="utf-8") as f:
            f.write('{"api": {"primary_key": "用户的真实密钥"}}')
        make_zip(self.zip_path, {"config.json": b"{}", "Remy.py": b"code"})

        res = safe_extract(self.zip_path, self.target)
        self.assertIn("config.json", res.skipped)
        with open(cfg, encoding="utf-8") as f:
            self.assertIn("用户的真实密钥", f.read())

    def test_protected_file_written_on_fresh_install(self):
        """全新安装时目标不存在，应该拿到包里的默认配置。"""
        make_zip(self.zip_path, {"config.json": b"{}"})
        res = safe_extract(self.zip_path, self.target)
        self.assertEqual(res.skipped, [])
        self.assertTrue(os.path.exists(os.path.join(self.target, "config.json")))

    def test_all_protected_names_covered(self):
        """受保护清单里每个文件都真的会被跳过。"""
        for name in PROTECTED_FILES:
            with open(os.path.join(self.target, name), "w") as f:
                f.write("用户数据")
        make_zip(self.zip_path, {n: b"new" for n in PROTECTED_FILES})
        res = safe_extract(self.zip_path, self.target)
        self.assertEqual(sorted(res.skipped), sorted(PROTECTED_FILES))

    def test_rejects_path_traversal(self):
        """zip slip：条目名带 .. 时会写到目标目录之外。

        安装包是从网络下的，必须当作不可信输入。
        """
        make_zip(self.zip_path, {
            "../evil.txt": b"pwned",
            "ok.py": b"code",
        })
        res = safe_extract(self.zip_path, self.target)
        self.assertIn("../evil.txt", res.rejected)
        self.assertFalse(os.path.exists(
            os.path.join(os.path.dirname(self.target), "evil.txt")))
        self.assertTrue(os.path.exists(os.path.join(self.target, "ok.py")))

    def test_rejects_absolute_path(self):
        make_zip(self.zip_path, {"/etc/passwd": b"pwned"})
        res = safe_extract(self.zip_path, self.target)
        self.assertIn("/etc/passwd", res.rejected)

    def test_rejects_windows_drive_path(self):
        make_zip(self.zip_path, {"C:/Windows/x.dll": b"pwned"})
        res = safe_extract(self.zip_path, self.target)
        self.assertIn("C:/Windows/x.dll", res.rejected)

    def test_rejects_nested_traversal(self):
        make_zip(self.zip_path, {"a/../../evil.txt": b"pwned"})
        res = safe_extract(self.zip_path, self.target)
        self.assertEqual(res.rejected, ["a/../../evil.txt"])

    def test_refuses_broken_archive(self):
        """解压前必须先校验——这是防止「更新变砖」的最后一道闸。"""
        p = self.path("bad.zip")
        with open(p, "wb") as f:
            f.write(b"not a zip")
        res = safe_extract(p, self.target)
        self.assertFalse(res.ok)
        self.assertIn("不是合法的 zip", res.error)

    def test_unicode_filename_roundtrip(self):
        """make_release.py 用 zipfile 写出的中文名（带 UTF-8 标志），
        解压后应原样落盘，不会变成乱码 exe。

        这是「打包脚本产出」与「safe_extract 消费」之间的端到端保证。
        """
        exe = "星夜颂歌-蕾咪！.exe"
        make_zip(self.zip_path, {f"Remy_v1.2.0/{exe}": b"MZ"})
        res = safe_extract(self.zip_path, self.target)
        self.assertTrue(res.ok, res.error)
        self.assertTrue(os.path.exists(os.path.join(self.target, exe)))
        self.assertFalse(os.listdir(self.target)[0].startswith("╨"))


# ============================================================
# 文件名编码（GBK 无 UTF-8 标志的 zip）
# ============================================================

class TestDecodeName(unittest.TestCase):
    """中文 Windows 上打包工具常用 GBK 存中文名且不设 UTF-8 标志，
    zipfile 会把 GBK 字节按 CP437 解成乱码。_decode_name 负责还原。

    Python 的 zipfile 公开 API 写不出「GBK 无标志」的中文名，所以直接
    对纯函数断言，用「GBK 字节 → CP437 解码」的乱码串模拟 zipfile 的结果。
    """

    CN = "星夜颂歌-蕾咪！.exe"

    def _info(self, filename, flag_bits=0):
        info = zipfile.ZipInfo(filename)
        info.flag_bits = flag_bits
        return info

    def test_gbk_mojibake_decoded_back(self):
        """无标志 + GBK→CP437 乱码名，应解回正确中文。"""
        mojibake = self.CN.encode("gbk").decode("cp437")
        self.assertNotEqual(mojibake, self.CN)      # 确认造出的确实是乱码
        self.assertEqual(_decode_name(self._info(mojibake, 0)), self.CN)

    def test_utf8_flag_untouched(self):
        """已设 UTF-8 标志时 zipfile 已解对，不应二次解码。"""
        self.assertEqual(
            _decode_name(self._info(self.CN, 0x800)), self.CN)

    def test_ascii_untouched(self):
        self.assertEqual(
            _decode_name(self._info("Remy.py", 0)), "Remy.py")

    def test_non_gbk_bytes_fall_back(self):
        """既非 GBK 也非 Big5 的字节序列，退回原样而非抛异常。"""
        name = b"caf\xe9".decode("cp437")   # 'café'，GBK 解不成完整序列
        self.assertEqual(_decode_name(self._info(name, 0)), name)

    def test_unmappable_to_cp437_untouched(self):
        """文件名里若含 CP437 表示不了的字符，直接原样返回。"""
        self.assertEqual(_decode_name(self._info(self.CN, 0)), self.CN)


if __name__ == "__main__":
    unittest.main()
