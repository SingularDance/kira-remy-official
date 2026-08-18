# -*- coding: utf-8 -*-
"""社区壁纸站接口的纯逻辑测试。

community_wallpaper.py 不 import Qt，URL 拼接与响应解析都能直接单测，
不需要联网。重点钉住：URL query 拼接稳定、以及坏响应（字段缺失、类型错、
相对/绝对路径）解析时不抛且正确降级。
"""

import unittest

from community_wallpaper import (API_IMAGES_PATH, BASE_URL, PAGE_SIZE,
                                 build_images_url, parse_images_response)


class TestBuildImagesUrl(unittest.TestCase):
    def test_defaults(self):
        url = build_images_url()
        self.assertIn(BASE_URL + API_IMAGES_PATH, url)
        self.assertIn("offset=0", url)
        self.assertIn("limit=%d" % PAGE_SIZE, url)
        self.assertIn("sort=composite", url)

    def test_custom_params(self):
        url = build_images_url(offset=40, limit=20, sort="newest")
        self.assertIn("offset=40", url)
        self.assertIn("limit=20", url)
        self.assertIn("sort=newest", url)


class TestParseImagesResponse(unittest.TestCase):
    def test_non_dict_returns_empty(self):
        self.assertEqual(parse_images_response(None), [])
        self.assertEqual(parse_images_response([]), [])
        self.assertEqual(parse_images_response("x"), [])
        self.assertEqual(parse_images_response(123), [])

    def test_items_not_list(self):
        self.assertEqual(parse_images_response({"items": "x"}), [])
        self.assertEqual(parse_images_response({"items": None}), [])
        self.assertEqual(parse_images_response({}), [])

    def test_valid_items_normalized(self):
        raw = {
            "items": [
                {"id": 1, "title": "壁纸", "display_name": "用户#42",
                 "width": 1920, "height": 1080,
                 "thumb_url": "/uploads/a_t.webp",
                 "preview_url": "/uploads/a_p.webp"},
                {"id": 2, "title": "", "display_name": "",
                 "width": "800", "height": "600",
                 "thumb_url": "/uploads/b_t.webp",
                 "preview_url": "/uploads/b_p.webp"},
            ],
            "total": 2,
        }
        items = parse_images_response(raw)
        self.assertEqual(len(items), 2)

        self.assertEqual(items[0]["id"], 1)
        self.assertEqual(items[0]["thumb_url"], BASE_URL + "/uploads/a_t.webp")
        self.assertEqual(items[0]["preview_url"], BASE_URL + "/uploads/a_p.webp")
        self.assertEqual(items[0]["width"], 1920)

        # 字符串数字 width 也要能转成 int
        self.assertEqual(items[1]["width"], 800)

    def test_absolute_url_preserved(self):
        raw = {"items": [{"id": 1, "thumb_url": "https://x/y.webp",
                          "preview_url": "https://x/z.webp"}]}
        items = parse_images_response(raw)
        self.assertEqual(items[0]["thumb_url"], "https://x/y.webp")
        self.assertEqual(items[0]["preview_url"], "https://x/z.webp")

    def test_relative_without_leading_slash(self):
        raw = {"items": [{"id": 1, "thumb_url": "uploads/a.webp",
                          "preview_url": "uploads/b.webp"}]}
        items = parse_images_response(raw)
        self.assertEqual(items[0]["thumb_url"], BASE_URL + "/uploads/a.webp")

    def test_missing_required_fields_skipped(self):
        raw = {"items": [
            {"id": 1},                                        # 缺 thumb/preview
            {"thumb_url": "/a.webp", "preview_url": "/b.webp"},          # 缺 id
            {"id": "abc", "thumb_url": "/a.webp", "preview_url": "/b.webp"},  # id 非法
            {"id": 0, "thumb_url": "/a.webp", "preview_url": "/b.webp"},    # id 为 0
        ]}
        self.assertEqual(parse_images_response(raw), [])

    def test_bad_item_skipped_good_kept(self):
        raw = {"items": [
            {"id": "bad", "thumb_url": "/x.webp", "preview_url": "/y.webp"},
            {"id": 5, "thumb_url": "/ok_t.webp", "preview_url": "/ok_p.webp"},
        ]}
        items = parse_images_response(raw)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], 5)


if __name__ == "__main__":
    unittest.main()
