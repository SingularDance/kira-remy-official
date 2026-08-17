# -*- coding: utf-8 -*-
"""更新检查的测试。数据源为 GitHub Releases。

网络和时间都是注入的，所以以下场景全部可直接测，不需要联网也不需要等一天：
GitHub API 限流、响应是 HTML、跨天节流、`1.10` vs `1.9`、release 没挂附件。

真实响应形状取自实测（2026-08-13 抓的 kira-remy-official 最新 release）：
tag_name=v1.1.1，资产 Remy_v1.1.1.zip，48821272 字节。
"""

import unittest
from datetime import datetime
from unittest import mock

from updater import (ASSET_TEMPLATE, MAC_ASSET_TEMPLATE, UPDATE_PHRASES, Release,
                     UpdateConfig, UpdateStatus, _pick_asset, asset_template,
                     bubble_phrase, check_for_update, fetch_latest_release,
                     fetch_via_api, fetch_via_redirect, is_newer,
                     normalize_version, parse_api_release, parse_version,
                     today_str, tray_message)

DAY1 = datetime(2026, 8, 13, 15, 0, 0).timestamp()
DAY2 = DAY1 + 86400

CFG = UpdateConfig(owner="SingularDance", repo="kira-remy-official")

# 按实测响应裁剪，只保留本模块会读的字段
API_PAYLOAD = {
    "tag_name": "v1.1.1",
    "name": "Remy v1.1.1",
    "body": "## What's Changed\n* Refactor thinking bubble UI",
    "html_url": "https://github.com/SingularDance/kira-remy-official/releases/tag/v1.1.1",
    "assets": [{
        "name": "Remy_v1.1.1.zip",
        "size": 48821272,
        "browser_download_url": ("https://github.com/SingularDance/"
                                 "kira-remy-official/releases/download/"
                                 "v1.1.1/Remy_v1.1.1.zip"),
    }],
}


class FakeResponse:
    """假的 requests 响应。"""

    def __init__(self, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._json is None:
            raise ValueError("不是合法 JSON")
        return self._json


def getter(*responses):
    """按调用顺序返回预设响应；传入 Exception 实例则抛出它。"""
    queue = list(responses)

    def _get(url, **kw):
        item = queue.pop(0) if queue else responses[-1]
        if isinstance(item, Exception):
            raise item
        return item
    return _get


class TestVersionParsing(unittest.TestCase):

    def test_parse_plain_and_prefixed(self):
        self.assertEqual(parse_version("1.2.3"), (1, 2, 3))
        self.assertEqual(parse_version("v1.2.3"), (1, 2, 3))

    def test_parse_unparsable(self):
        self.assertEqual(parse_version("latest"), ())
        self.assertEqual(parse_version(""), ())
        self.assertEqual(parse_version(None), ())

    def test_normalize_strips_only_leading_v(self):
        self.assertEqual(normalize_version("v1.1.1"), "1.1.1")
        self.assertEqual(normalize_version("V1.1.1"), "1.1.1")
        self.assertEqual(normalize_version("1.1.1"), "1.1.1")
        # 中间的 v 不该被动（比如带渠道名的 tag）
        self.assertEqual(normalize_version("v1.1.1-preview"), "1.1.1-preview")

    def test_is_newer_double_digit_segment(self):
        """经典 bug：字符串比较下 "1.10.0" < "1.9.0" 会是 True。"""
        self.assertTrue(is_newer("1.10.0", "1.9.0"))
        self.assertFalse(is_newer("1.9.0", "1.10.0"))

    def test_is_newer_equal_and_padding(self):
        self.assertFalse(is_newer("1.1.1", "1.1.1"))
        self.assertFalse(is_newer("1.2", "1.2.0"))
        self.assertTrue(is_newer("1.2.1", "1.2"))

    def test_is_newer_conservative_on_garbage(self):
        """解析不出来时保守处理：不提示，不误报。"""
        self.assertFalse(is_newer("latest", "1.0.0"))
        self.assertFalse(is_newer("1.0.1", "unknown"))


class TestParseApiRelease(unittest.TestCase):

    def test_valid_payload(self):
        r = parse_api_release(API_PAYLOAD, CFG)
        self.assertEqual(r.version, "1.1.1")
        self.assertEqual(r.tag, "v1.1.1")
        self.assertEqual(r.asset_name, "Remy_v1.1.1.zip")
        self.assertEqual(r.size, 48821272)
        self.assertEqual(r.size_mb, 46.6)
        self.assertIn("thinking bubble", r.notes)
        self.assertEqual(r.source, "api")

    def test_rate_limit_response_rejected(self):
        """限流时 GitHub 只返回 message，没有 tag_name。"""
        self.assertIsNone(parse_api_release(
            {"message": "API rate limit exceeded"}, CFG))

    def test_non_dict_rejected(self):
        self.assertIsNone(parse_api_release("<html>", CFG))
        self.assertIsNone(parse_api_release([1, 2], CFG))
        self.assertIsNone(parse_api_release(None, CFG))

    def test_unparsable_tag_rejected(self):
        self.assertIsNone(parse_api_release({"tag_name": "nightly"}, CFG))

    def test_prefers_asset_matching_template(self):
        """release 里常常还挂着源码包，不能取「第一个」。"""
        payload = dict(API_PAYLOAD, assets=[
            {"name": "source.zip", "size": 1,
             "browser_download_url": "https://example.com/source.zip"},
            API_PAYLOAD["assets"][0],
        ])
        r = parse_api_release(payload, CFG)
        self.assertEqual(r.asset_name, "Remy_v1.1.1.zip")

    def test_ignores_non_zip_assets(self):
        payload = dict(API_PAYLOAD, assets=[
            {"name": "checksums.txt", "size": 1,
             "browser_download_url": "https://example.com/checksums.txt"},
        ])
        r = parse_api_release(payload, CFG)
        # 没有可用 zip → 退回命名模板
        self.assertEqual(r.asset_name, ASSET_TEMPLATE.format(tag="v1.1.1"))
        self.assertIn("/releases/download/v1.1.1/", r.download_url)

    def test_falls_back_to_template_when_no_assets(self):
        """release 没挂附件时用命名模板拼接，size 归零表示未知。"""
        r = parse_api_release(dict(API_PAYLOAD, assets=[]), CFG)
        self.assertEqual(r.download_url,
                         "https://github.com/SingularDance/kira-remy-official"
                         "/releases/download/v1.1.1/Remy_v1.1.1.zip")
        self.assertEqual(r.size, 0)

    def test_rejects_non_https_download_url(self):
        """下载地址来自远端，不能盲信。"""
        payload = dict(API_PAYLOAD, assets=[
            {"name": "Remy_v1.1.1.zip", "size": 10,
             "browser_download_url": "http://evil.example.com/x.zip"},
        ])
        r = parse_api_release(payload, CFG)
        self.assertTrue(r.download_url.startswith("https://github.com/"))

    def test_bad_size_field_does_not_crash(self):
        payload = dict(API_PAYLOAD, assets=[
            dict(API_PAYLOAD["assets"][0], size="很大"),
        ])
        self.assertEqual(parse_api_release(payload, CFG).size, 0)


class TestPlatformAsset(unittest.TestCase):
    """按平台选资产：macOS 用 _Mac 后缀，且绝不下错成 Windows 包。"""

    def test_asset_template_default_is_windows(self):
        self.assertEqual(asset_template(), ASSET_TEMPLATE)

    def test_asset_template_darwin(self):
        self.assertEqual(asset_template("darwin"), MAC_ASSET_TEMPLATE)
        self.assertEqual(asset_template("win32"), ASSET_TEMPLATE)

    def test_parse_api_release_picks_mac_asset(self):
        """release 同时挂了 Win/Mac 两个包，mac 上应精确挑中 _Mac。"""
        payload = dict(API_PAYLOAD, assets=[
            {"name": "Remy_v1.1.1.zip", "size": 1,
             "browser_download_url": "https://example.com/Remy_v1.1.1.zip"},
            {"name": "Remy_v1.1.1_Mac.zip", "size": 2,
             "browser_download_url": "https://example.com/Remy_v1.1.1_Mac.zip"},
        ])
        with mock.patch("updater.asset_template",
                        return_value=MAC_ASSET_TEMPLATE):
            r = parse_api_release(payload, CFG)
        self.assertEqual(r.asset_name, "Remy_v1.1.1_Mac.zip")

    def test_mac_pick_exact(self):
        assets = [
            {"name": "Remy_v1.1.1.zip", "size": 1,
             "browser_download_url": "https://example.com/Remy_v1.1.1.zip"},
            {"name": "Remy_v1.1.1_Mac.zip", "size": 2,
             "browser_download_url": "https://example.com/Remy_v1.1.1_Mac.zip"},
        ]
        with mock.patch("updater.asset_template",
                        return_value=MAC_ASSET_TEMPLATE):
            picked = _pick_asset(assets, "v1.1.1")
        self.assertIsNotNone(picked)
        self.assertEqual(picked["name"], "Remy_v1.1.1_Mac.zip")

    def test_mac_does_not_fall_back_to_windows_zip(self):
        """release 只有 Windows 包时，mac 上必须返回 None，绝不退回下错包。"""
        assets = [{"name": "Remy_v1.1.1.zip", "size": 1,
                   "browser_download_url": "https://example.com/Remy_v1.1.1.zip"}]
        with mock.patch("updater.asset_template",
                        return_value=MAC_ASSET_TEMPLATE):
            self.assertIsNone(_pick_asset(assets, "v1.1.1"))


class TestFetchViaApi(unittest.TestCase):

    def test_success(self):
        raw = fetch_via_api(CFG, get=getter(FakeResponse(json_data=API_PAYLOAD)))
        self.assertEqual(raw["tag_name"], "v1.1.1")

    def test_rate_limited_returns_none(self):
        self.assertIsNone(fetch_via_api(CFG, get=getter(FakeResponse(403))))

    def test_server_error_returns_none(self):
        self.assertIsNone(fetch_via_api(CFG, get=getter(FakeResponse(500))))

    def test_html_response_returns_none(self):
        self.assertIsNone(fetch_via_api(
            CFG, get=getter(FakeResponse(text="<html>"))))

    def test_network_exception_returns_none(self):
        """GitHub 在国内连不上是常态，必须静默降级。"""
        self.assertIsNone(fetch_via_api(
            CFG, get=getter(OSError("connection reset"))))


class TestFetchViaRedirect(unittest.TestCase):

    LOCATION = ("https://github.com/SingularDance/kira-remy-official"
                "/releases/tag/v1.1.1")

    def test_parses_tag_from_location(self):
        r = fetch_via_redirect(CFG, get=getter(
            FakeResponse(302, headers={"Location": self.LOCATION})))
        self.assertEqual(r.version, "1.1.1")
        self.assertEqual(r.tag, "v1.1.1")
        self.assertEqual(r.source, "redirect")

    def test_redirect_path_has_no_size_or_notes(self):
        """这条路拿不到大小和 changelog，下载时无法核对字节数。"""
        r = fetch_via_redirect(CFG, get=getter(
            FakeResponse(302, headers={"Location": self.LOCATION})))
        self.assertEqual(r.size, 0)
        self.assertEqual(r.notes, "")

    def test_missing_location_returns_none(self):
        self.assertIsNone(fetch_via_redirect(CFG, get=getter(FakeResponse(200))))

    def test_location_without_tag_returns_none(self):
        self.assertIsNone(fetch_via_redirect(CFG, get=getter(
            FakeResponse(302, headers={"Location": "https://github.com/login"}))))

    def test_network_exception_returns_none(self):
        self.assertIsNone(fetch_via_redirect(CFG, get=getter(OSError("boom"))))


class TestFetchLatestRelease(unittest.TestCase):

    LOCATION = ("https://github.com/SingularDance/kira-remy-official"
                "/releases/tag/v1.2.0")

    def test_uses_api_when_available(self):
        r = fetch_latest_release(CFG, get=getter(
            FakeResponse(json_data=API_PAYLOAD)))
        self.assertEqual(r.source, "api")

    def test_falls_back_to_redirect_on_rate_limit(self):
        """API 限流 → 走 302 兜底，功能不中断。"""
        r = fetch_latest_release(CFG, get=getter(
            FakeResponse(403),
            FakeResponse(302, headers={"Location": self.LOCATION})))
        self.assertEqual(r.source, "redirect")
        self.assertEqual(r.version, "1.2.0")

    def test_returns_none_when_both_paths_fail(self):
        self.assertIsNone(fetch_latest_release(CFG, get=getter(
            FakeResponse(403), FakeResponse(500))))


def fetcher(release):
    """构造假的 release 获取函数。None 表示获取失败。"""
    return lambda cfg: release


LATEST = Release(version="1.1.1", tag="v1.1.1", size=48821272,
                 download_url="https://github.com/x/y/releases/download/v1.1.1/z.zip")


class TestCheckForUpdate(unittest.TestCase):

    def test_update_available(self):
        res = check_for_update("1.1.0", CFG, DAY1, fetch=fetcher(LATEST))
        self.assertIs(res.status, UpdateStatus.UPDATE_AVAILABLE)
        self.assertTrue(res.should_notify)

    def test_up_to_date(self):
        res = check_for_update("1.1.1", CFG, DAY1, fetch=fetcher(LATEST))
        self.assertIs(res.status, UpdateStatus.UP_TO_DATE)

    def test_local_newer_than_remote(self):
        """开发机上跑着未发布版本时，不该提示「更新」。"""
        res = check_for_update("2.0.0", CFG, DAY1, fetch=fetcher(LATEST))
        self.assertIs(res.status, UpdateStatus.UP_TO_DATE)

    def test_disabled(self):
        cfg = UpdateConfig(enabled=False)
        res = check_for_update("1.0.0", cfg, DAY1, fetch=fetcher(LATEST))
        self.assertIs(res.status, UpdateStatus.DISABLED)
        self.assertFalse(res.attempted_network)

    def test_throttled_same_day(self):
        cfg = UpdateConfig(last_check_date=today_str(DAY1))
        res = check_for_update("1.0.0", cfg, DAY1, fetch=fetcher(LATEST))
        self.assertIs(res.status, UpdateStatus.THROTTLED)
        self.assertFalse(res.attempted_network)

    def test_checks_again_next_day(self):
        cfg = UpdateConfig(last_check_date=today_str(DAY1))
        res = check_for_update("1.0.0", cfg, DAY2, fetch=fetcher(LATEST))
        self.assertIs(res.status, UpdateStatus.UPDATE_AVAILABLE)

    def test_skip_version(self):
        cfg = UpdateConfig(skip_version="1.1.1")
        res = check_for_update("1.0.0", cfg, DAY1, fetch=fetcher(LATEST))
        self.assertIs(res.status, UpdateStatus.SKIPPED)

    def test_skip_only_that_version(self):
        cfg = UpdateConfig(skip_version="1.0.5")
        res = check_for_update("1.0.0", cfg, DAY1, fetch=fetcher(LATEST))
        self.assertIs(res.status, UpdateStatus.UPDATE_AVAILABLE)

    def test_force_ignores_everything(self):
        """右键菜单手动触发：用户主动点了，就该给他看结果。"""
        cfg = UpdateConfig(enabled=False, skip_version="1.1.1",
                           last_check_date=today_str(DAY1))
        res = check_for_update("1.0.0", cfg, DAY1,
                               fetch=fetcher(LATEST), force=True)
        self.assertIs(res.status, UpdateStatus.UPDATE_AVAILABLE)

    def test_fetch_failure_is_silent_error(self):
        res = check_for_update("1.0.0", CFG, DAY1, fetch=fetcher(None))
        self.assertIs(res.status, UpdateStatus.ERROR)
        self.assertFalse(res.should_notify)


class TestUpdateConfig(unittest.TestCase):

    def test_from_dict_ignores_unknown_keys(self):
        cfg = UpdateConfig.from_dict({"enabled": False, "未来字段": 1})
        self.assertFalse(cfg.enabled)

    def test_from_dict_handles_none(self):
        self.assertTrue(UpdateConfig.from_dict(None).enabled)

    def test_roundtrip(self):
        cfg = UpdateConfig(skip_version="1.1.1", last_check_date="2026-08-13")
        self.assertEqual(UpdateConfig.from_dict(cfg.to_dict()), cfg)

    def test_owner_repo_overridable(self):
        """便于测试环境指向自己的 fork 验证端到端。"""
        cfg = UpdateConfig(owner="me", repo="myrepo")
        self.assertIn("me/myrepo", cfg.url("https://x/{owner}/{repo}"))


class TestMessages(unittest.TestCase):

    def test_tray_message_includes_version_and_size(self):
        title, body = tray_message(LATEST)
        self.assertIn("1.1.1", body)
        self.assertIn("46.6 MB", body)
        self.assertIn("蕾咪", title)

    def test_tray_message_omits_size_when_unknown(self):
        """302 兜底路径拿不到大小，不能显示「0 MB」。"""
        _, body = tray_message(Release(version="1.1.1"))
        self.assertNotIn("MB", body)

    def test_bubble_phrase_within_length_limit(self):
        """SYSTEM_PROMPT 要求 37 字以内，气泡也会被截断。"""
        for phrase in UPDATE_PHRASES:
            self.assertLessEqual(len(phrase), 37, f"台词过长：{phrase}")

    def test_bubble_phrase_deterministic_with_seed(self):
        import random
        self.assertIn(bubble_phrase(random.Random(0)), UPDATE_PHRASES)


class TestBubbleEmotionAlignment(unittest.TestCase):
    """气泡台词的表情是设计好的。

    更新气泡经过 show_typed_message，但表情不再靠 detect_emotion 推断——
    台词刻意不带任何情绪关键词，由调用方用 override_avatar 固定成
    Remy_Expect（期待）。这里钉住两点：台词只有一条、且不带情绪词，
    否则 detect_emotion 会抢在 override_avatar 之前把表情改掉。

    detect_emotion 的位置随宿主结构变化：重构前在 Rei.py，重构后在 utils.py。
    """

    def setUp(self):
        self.detect = None
        for module in ("utils", "Rei"):
            try:
                self.detect = getattr(__import__(module), "detect_emotion")
                break
            except (ImportError, AttributeError):
                continue
        if self.detect is None:
            self.skipTest("找不到 detect_emotion")

    def test_phrase_emotions(self):
        # 台词只有一条，且不带情绪关键词：表情由 override_avatar 固定成
        # Remy_Expect，而不是走 detect_emotion 推断。
        self.assertEqual(len(UPDATE_PHRASES), 1)
        phrase = UPDATE_PHRASES[0]
        self.assertNotIn("笨蛋", phrase)
        self.assertIsNone(self.detect(phrase),
                          f"台词「{phrase}」不该触发任何情绪推断")


if __name__ == "__main__":
    unittest.main()
