# -*- coding: utf-8 -*-
"""config.py 里 update 段的迁移测试。

老用户的 config.json 是在更新功能之前写的，里面没有 update 段。
`sanitize_config` 必须补齐它，否则「跳过此版本」和「每天只查一次」
没有地方持久化——功能看起来在跑，实际每次启动都重新提示。

这类迁移逻辑出错不会报异常，只会让功能悄悄失效，所以必须测。
"""

import unittest

import config


class TestUpdateSectionMigration(unittest.TestCase):

    def test_default_config_has_update_section(self):
        update = config.default_config()["update"]
        self.assertTrue(update["enabled"])
        self.assertEqual(update["owner"], "SingularDance")
        self.assertEqual(update["repo"], "kira-remy-official")
        self.assertEqual(update["skip_version"], "")
        self.assertEqual(update["last_check_date"], "")

    def test_legacy_config_gets_update_section(self):
        """老配置（无 update 段）必须被补齐。"""
        legacy = {"nickname": "调查员", "api": {"primary": "deepseek"}}
        result = config.sanitize_config(legacy)
        self.assertIn("update", result)
        self.assertTrue(result["update"]["enabled"])

    def test_existing_user_settings_preserved(self):
        """补齐时不能覆盖用户已经设置过的值。"""
        cfg = {"update": {"enabled": False, "skip_version": "1.1.1"}}
        result = config.sanitize_config(cfg)
        self.assertFalse(result["update"]["enabled"])
        self.assertEqual(result["update"]["skip_version"], "1.1.1")
        # 缺的键仍然补上
        self.assertEqual(result["update"]["owner"], "SingularDance")

    def test_non_dict_update_section_replaced(self):
        """手改配置写坏了也不能让程序崩。"""
        result = config.sanitize_config({"update": "打开"})
        self.assertIsInstance(result["update"], dict)
        self.assertTrue(result["update"]["enabled"])

    def test_non_bool_enabled_corrected(self):
        """enabled 被写成字符串时纠正为布尔，否则 `if not cfg.enabled` 判断会错。"""
        result = config.sanitize_config({"update": {"enabled": "true"}})
        self.assertIs(result["update"]["enabled"], True)

    def test_roundtrip_with_updater_config(self):
        """config.json 的 update 段必须能被 UpdateConfig 直接消费。"""
        import updater
        section = config.sanitize_config({})["update"]
        cfg = updater.UpdateConfig.from_dict(section)
        self.assertEqual(cfg.owner, "SingularDance")
        self.assertEqual(cfg.repo, "kira-remy-official")
        self.assertTrue(cfg.enabled)


if __name__ == "__main__":
    unittest.main()
