# -*- coding: utf-8 -*-
"""粉色数字「喜欢/爱」表达统计的纯逻辑测试。

`count_affection_hits` 只做字符串匹配，`call_me` / `nickname` 从外部注入，
便于单测。关键词来自「喜欢/爱 + 称呼 + 昵称」；「你」只是默认称呼，不再作为
独立基础词硬编码。
"""

import unittest

from config import count_affection_hits


class TestCountAffectionHits(unittest.TestCase):
    """回复中「喜欢/爱」表达次数的统计。"""

    def test_empty_reply(self):
        self.assertEqual(count_affection_hits("", "你", "调查员"), 0)
        self.assertEqual(count_affection_hits(None, "你", "调查员"), 0)

    def test_default_call_me_you(self):
        # 默认称呼「你」→「喜欢{称呼}」=「喜欢你」
        self.assertEqual(count_affection_hits("喜欢你", "你", "调查员"), 1)
        self.assertEqual(count_affection_hits("爱你", "你", "调查员"), 1)

    def test_nickname(self):
        self.assertEqual(count_affection_hits("喜欢调查员", "你", "调查员"), 1)
        self.assertEqual(count_affection_hits("爱调查员", "你", "调查员"), 1)

    def test_multiple_occurrences(self):
        self.assertEqual(count_affection_hits("喜欢你，真的好喜欢你", "你", "调查员"), 2)

    def test_mixed_like_and_love(self):
        self.assertEqual(count_affection_hits("我喜欢你也爱你", "你", "调查员"), 2)

    def test_custom_call_me_and_nickname(self):
        self.assertEqual(count_affection_hits("喜欢主人", "主人", "Fizz"), 1)
        self.assertEqual(count_affection_hits("爱主人", "主人", "Fizz"), 1)
        self.assertEqual(count_affection_hits("喜欢Fizz", "主人", "Fizz"), 1)
        self.assertEqual(count_affection_hits("爱Fizz", "主人", "Fizz"), 1)

    def test_custom_name_drops_you(self):
        # 称呼改成「主人」后，「喜欢你」不再命中（「你」不再是关键词来源）
        self.assertEqual(count_affection_hits("喜欢你", "主人", "Fizz"), 0)

    def test_empty_names_no_bare_match(self):
        # 称呼和昵称都为空时关键词集合为空，裸「喜欢」「爱」不误匹配
        self.assertEqual(count_affection_hits("我喜欢吃蛋糕", "", ""), 0)
        self.assertEqual(count_affection_hits("喜欢你", "", ""), 0)

    def test_duplicate_names_dedup(self):
        # 称呼与昵称相同时去重，不重复计数
        self.assertEqual(count_affection_hits("喜欢你", "你", "你"), 1)

    def test_overlap_not_double_counted(self):
        # 昵称以「你」开头时，非重叠匹配避免「喜欢你」与「喜欢你主人」重复计成 3
        self.assertEqual(count_affection_hits("喜欢你喜欢你主人", "你", "你主人"), 2)


if __name__ == "__main__":
    unittest.main()
