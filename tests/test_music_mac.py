# -*- coding: utf-8 -*-
"""macOS 听歌识别的「音频闸门」测试。

`music_mac.now_playing()` 在发任何 osascript 之前先问 CoreAudio
「现在有谁在出声」。这一层是为了修掉一个实打实的误报：

    浏览器那条路判断的是「标签开着」，不是「正在播放」。
    实测过一次——四个标签命中白名单、一个都没在放，
    它照样报了 `longchain-哔哩哔哩_bilibili`。

所以本文件钉的核心是两条相反的性质：
**没声音时必须闭嘴，有声音时必须照常工作。**

用 mock 注入音频进程列表，不需要真的播放音乐，也不需要 mac 之外的环境。
非 macOS 上整个文件跳过——这些代码在 Windows 上根本不会被 import。
"""

import sys
import unittest
from unittest import mock

IS_MAC = sys.platform == "darwin"

if IS_MAC:
    import mac_audio
    import music_mac


def _procs(*entries):
    """构造音频进程列表。entries: (bundle_id, pid)，都视为正在输出。"""
    return [(bundle_id, pid, True) for bundle_id, pid in entries]


@unittest.skipUnless(IS_MAC, "只在 macOS 上有意义")
class TestAudioGate(unittest.TestCase):

    def setUp(self):
        # 把 pgrep 摘掉：本文件测的是闸门，不是「应用在不在运行」
        patcher = mock.patch.object(music_mac, "is_running", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.probed = []

    def _run(self, procs, app_paths=None):
        """在给定的音频状态下跑一次 now_playing()，返回结果。

        procs 为 None 表示「拿不到音频状态」（macOS 14.4 以下）。
        """
        app_paths = app_paths or {}

        def player(app):
            self.probed.append(f"player:{app}")
            return ("某首歌", "某歌手")

        def browser(proc, app):
            self.probed.append(f"browser:{app}")
            return ("某个标签标题", "")

        with mock.patch.object(mac_audio, "audio_processes", return_value=procs), \
             mock.patch.object(mac_audio, "_app_bundle_from_pid",
                               side_effect=lambda pid: app_paths.get(pid, "")), \
             mock.patch.object(music_mac, "_player_track", side_effect=player), \
             mock.patch.object(music_mac, "_browser_tab", side_effect=browser):
            return music_mac.now_playing()

    # ---------- 没声音就闭嘴 ----------

    def test_无人出声时返回空且不发任何探测(self):
        got = self._run([])
        self.assertEqual(got, ("", ""))
        # 不只是结果为空，连 osascript 都不该发出去——
        # 这既是准确性也是性能（常态 6ms 而不是 280ms）
        self.assertEqual(self.probed, [])

    def test_无关应用出声时不冒认(self):
        got = self._run(_procs(("com.tencent.xinWeChat", 333)), {333: "WeChat"})
        self.assertEqual(got, ("", ""))
        self.assertEqual(self.probed, [])

    # ---------- 有声音就照常工作 ----------

    def test_Chrome出声时探测Chrome(self):
        got = self._run(_procs(("com.google.Chrome.helper", 111)),
                        {111: "Google Chrome"})
        self.assertEqual(got, ("某个标签标题", ""))
        self.assertIn("browser:Google Chrome", self.probed)

    def test_仅凭bundle_id也能认出Chrome(self):
        # 浏览器的音频由 helper 进程发出，bundle id 是 com.google.Chrome.helper。
        # 取不到可执行文件路径时，靠剥掉 .helper 后缀也必须认得出来
        got = self._run(_procs(("com.google.Chrome.helper", 111)))
        self.assertEqual(got, ("某个标签标题", ""))

    def test_桌面播放器优先于浏览器(self):
        got = self._run(_procs(("com.spotify.client", 222),
                               ("com.google.Chrome.helper", 111)),
                        {222: "Spotify", 111: "Google Chrome"})
        # Spotify 给的是结构化歌名歌手，浏览器只有脏标题，能拿干净的就不用脏的
        self.assertEqual(got, ("某首歌", "某歌手"))
        self.assertEqual(self.probed[0], "player:Spotify")

    def test_不去问没在出声的来源(self):
        self._run(_procs(("com.google.Chrome.helper", 111)), {111: "Google Chrome"})
        self.assertNotIn("player:Spotify", self.probed)
        self.assertNotIn("player:Music", self.probed)

    # ---------- Safari 的 WebKit 歧义 ----------

    def test_WebKit出声时Safari算候选(self):
        # Safari 的网页音频走系统共享的 com.apple.WebKit.GPU，
        # 其父进程是 launchd，没法反查回 Safari（实测确认），
        # 只能放宽成「有 WebKit 应用在出声则 Safari 算候选」
        got = self._run(_procs(("com.apple.WebKit.GPU", 444)))
        self.assertEqual(got, ("某个标签标题", ""))
        self.assertIn("browser:Safari", self.probed)

    def test_WebKit的歧义不扩散到其他浏览器(self):
        self._run(_procs(("com.apple.WebKit.GPU", 444)))
        self.assertNotIn("browser:Google Chrome", self.probed)
        self.assertNotIn("browser:Microsoft Edge", self.probed)

    # ---------- 降级 ----------

    def test_拿不到音频状态时放行(self):
        # macOS 14.4 以下没有进程级音频属性。
        # 这时必须退回原来的行为（可能误报），而不是彻底哑掉——
        # 「不知道」不等于「没在放」
        got = self._run(None)
        self.assertEqual(got, ("某首歌", "某歌手"))
        self.assertIn("player:Music", self.probed)


@unittest.skipUnless(IS_MAC, "只在 macOS 上有意义")
class TestCleanTitle(unittest.TestCase):
    """网页标题清洗。

    在源头洗而不是在 prompt 里求模型忽略：提示词是两端共用的，
    不该为 mac 特有的脏数据去改它。
    """

    def test_剥掉平台后缀(self):
        c = music_mac.clean_title
        self.assertEqual(c("longchain-哔哩哔哩_bilibili"), "longchain")
        self.assertEqual(c("某某某-bilibili"), "某某某")
        self.assertEqual(c("线条小人看世界 - YouTube"), "线条小人看世界")

    def test_剥掉多层后缀(self):
        # 「千本桜 - 単曲 - 网易云音乐」有两层，一次只剥最外层，所以要循环
        self.assertEqual(music_mac.clean_title("千本桜 - 単曲 - 网易云音乐"), "千本桜")

    def test_丢掉方括号但保留圆括号(self):
        c = music_mac.clean_title
        self.assertEqual(c("【4K修复】千本樱_哔哩哔哩_bilibili"), "千本樱")
        # 圆括号里常有正经信息，feat 是歌手，不能扔
        self.assertEqual(c("Bad Apple!! (feat. nomico) - Official Music Video"),
                         "Bad Apple!! (feat. nomico)")

    def test_后缀锚定在结尾_不从中间挖(self):
        # 不锚定的话「- YouTube」会被从中间挖走，
        # 剩下「Channel dashboard Studio」这种四不像
        self.assertEqual(music_mac.clean_title("Channel dashboard - YouTube Studio"),
                         "Channel dashboard - YouTube Studio")

    def test_不误伤正文(self):
        self.assertEqual(music_mac.clean_title("C++ 从入门到放弃 P37_哔哩哔哩_bilibili"),
                         "C++ 从入门到放弃 P37")

    def test_全是噪音时退回原文(self):
        # B 站首页这种标题洗完会空，退回原文比给个空串好——
        # 空串会被上层当成「没在放」，反而丢失了信息
        self.assertEqual(music_mac.clean_title("哔哩哔哩_bilibili"), "哔哩哔哩")

    def test_空标题(self):
        self.assertEqual(music_mac.clean_title(""), "")
        self.assertEqual(music_mac.clean_title(None), "")


@unittest.skipUnless(IS_MAC, "只在 macOS 上有意义")
class TestMacAudioModule(unittest.TestCase):

    def test_命令行进程也算在出声(self):
        # afplay 这类工具既没有 bundle id 也没有 .app 路径，
        # playing_apps() 的标识集合会是空的，但它确实在出声。
        # anything_playing() 必须看进程列表而不是标识集合，否则会漏判
        with mock.patch.object(mac_audio, "audio_processes",
                               return_value=[("", 999, True)]):
            self.assertTrue(mac_audio.anything_playing())
            self.assertEqual(mac_audio.playing_apps(), set())

    def test_接口不可用时一律放行(self):
        with mock.patch.object(mac_audio, "audio_processes", return_value=None):
            self.assertTrue(mac_audio.anything_playing())
            self.assertTrue(mac_audio.is_playing("Google Chrome",
                                                 ("com.google.Chrome",)))
            self.assertIsNone(mac_audio.playing_apps())


if __name__ == "__main__":
    unittest.main()
