# -*- coding: utf-8 -*-
"""听歌识曲的纯逻辑测试。

music_monitor.py 顶部的三个纯函数（提示词拼装 + 防抖判定）不依赖 PyQt / winrt，
`now`/`last_react_time` 从外部注入，所以可以直接单测，不需要联网、不需要真在放歌。

钉住两件事：提示词格式稳定（LLM 行为别被悄悄改掉）、防抖与空闲判定边界正确。
"""

import unittest

from music_monitor import (MEDIA_MUSIC, MEDIA_UNKNOWN, MEDIA_VIDEO,
                           MUSIC_REACT_COOLDOWN, MUSIC_STABLE_SECONDS,
                           MusicStabilityTracker, build_music_context,
                           build_music_event_prompt, should_react)


class TestBuildMusicContext(unittest.TestCase):
    """平时聊天时注入的「正在播放」背景。"""

    def test_empty_title_returns_empty(self):
        self.assertEqual(build_music_context("", ""), "")
        self.assertEqual(build_music_context("", "周杰伦"), "")

    def test_title_only_has_no_artist_separator(self):
        s = build_music_context("晴天", "")
        self.assertIn("《晴天》", s)
        self.assertNotIn(" - ", s)

    def test_title_and_artist(self):
        s = build_music_context("晴天", "周杰伦")
        self.assertIn("《晴天》", s)
        self.assertIn(" - 周杰伦", s)
        # 结尾是完整的一句话
        self.assertTrue(s.rstrip().endswith("。）"))

    def test_music_type(self):
        s = build_music_context("晴天", "周杰伦", MEDIA_MUSIC)
        self.assertIn("播放音乐", s)
        self.assertNotIn("视频", s)

    def test_video_type(self):
        s = build_music_context("晴天", "", MEDIA_VIDEO)
        self.assertIn("观看视频", s)
        self.assertNotIn("音乐", s)


class TestBuildMusicEventPrompt(unittest.TestCase):
    """切歌时的隐形提示词。"""

    def test_includes_title_artist_and_constraints(self):
        s = build_music_event_prompt("晴天", "周杰伦")
        self.assertIn("《晴天》", s)
        self.assertIn("周杰伦", s)
        # 角色扮演约束关键词：37 字、emoji
        self.assertIn("37", s)
        self.assertIn("emoji", s)

    def test_music_type(self):
        s = build_music_event_prompt("晴天", "周杰伦", MEDIA_MUSIC)
        self.assertIn("歌名", s)

    def test_video_type(self):
        s = build_music_event_prompt("晴天", "周杰伦", MEDIA_VIDEO)
        self.assertIn("视频标题", s)

    def test_unknown_type(self):
        s = build_music_event_prompt("晴天", "周杰伦", MEDIA_UNKNOWN)
        self.assertIn("标题", s)
        self.assertNotIn("歌", s)
        self.assertNotIn("视频", s)


class TestShouldReact(unittest.TestCase):
    """切歌后是否该主动反应。"""

    def test_cold_start_reacts(self):
        # 首次启动 last_react_time=0，有歌名、不忙 → 反应
        self.assertTrue(should_react("晴天", 1_000_000, 0, False))

    def test_within_cooldown_blocks(self):
        now = 1_000_000
        last = now - (MUSIC_REACT_COOLDOWN - 1)  # 还差 1 秒到冷却结束
        self.assertFalse(should_react("晴天", now, last, False))

    def test_cooldown_boundary_reacts(self):
        now = 1_000_000
        last = now - MUSIC_REACT_COOLDOWN  # 正好满冷却 → 允许
        self.assertTrue(should_react("晴天", now, last, False))

    def test_no_title_blocks(self):
        self.assertFalse(should_react("", 1_000_000, 0, False))

    def test_busy_blocks(self):
        self.assertFalse(should_react("晴天", 1_000_000, 0, True))


class TestMusicStabilityTracker(unittest.TestCase):
    """同一媒体持续播放满 MUSIC_STABLE_SECONDS 才触发一次。"""

    def test_first_appearance_does_not_emit(self):
        t = MusicStabilityTracker()
        self.assertIsNone(t.update("晴天", "周杰伦", 1_000_000))

    def test_before_stable_does_not_emit(self):
        t = MusicStabilityTracker()
        t.update("晴天", "周杰伦", 1_000_000)
        self.assertIsNone(t.update("晴天", "周杰伦", 1_000_000 + MUSIC_STABLE_SECONDS - 1))

    def test_stable_boundary_emits_once(self):
        t = MusicStabilityTracker()
        t.update("晴天", "周杰伦", 1_000_000)
        self.assertEqual(t.update("晴天", "周杰伦", 1_000_000 + MUSIC_STABLE_SECONDS),
                         ("晴天", "周杰伦"))

    def test_no_repeat_after_emit(self):
        t = MusicStabilityTracker()
        t.update("晴天", "周杰伦", 1_000_000)
        t.update("晴天", "周杰伦", 1_000_000 + MUSIC_STABLE_SECONDS)
        self.assertIsNone(t.update("晴天", "周杰伦", 1_000_000 + MUSIC_STABLE_SECONDS + 5))

    def test_switch_resets_timer(self):
        t = MusicStabilityTracker()
        t.update("晴天", "周杰伦", 1_000_000)
        # 29 秒后切歌 → 旧媒体不触发，新计时开始
        self.assertIsNone(t.update("夜曲", "周杰伦", 1_000_000 + MUSIC_STABLE_SECONDS - 1))
        self.assertIsNone(t.update("夜曲", "周杰伦", 1_000_000 + MUSIC_STABLE_SECONDS))
        self.assertEqual(t.update("夜曲", "周杰伦", 1_000_000 + MUSIC_STABLE_SECONDS * 2 - 1),
                         ("夜曲", "周杰伦"))

    def test_stop_resets(self):
        t = MusicStabilityTracker()
        t.update("晴天", "周杰伦", 1_000_000)
        # 停止播放（title 空）→ 重置
        self.assertIsNone(t.update("", "", 1_000_000 + 10))
        # 重新播放同一首 → 需重新计时满 30 秒
        self.assertIsNone(t.update("晴天", "周杰伦", 1_000_000 + 20))
        self.assertEqual(t.update("晴天", "周杰伦", 1_000_000 + 20 + MUSIC_STABLE_SECONDS),
                         ("晴天", "周杰伦"))


if __name__ == "__main__":
    unittest.main()
