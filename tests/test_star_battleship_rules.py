# -*- coding: utf-8 -*-
"""星海战棋规则模块单测。"""

import unittest

import star_battleship_rules as R


def _make_ship(cells, weak, type_key="scout"):
    return {"type": type_key, "name": "t", "cells": cells, "weak_cells": set(weak),
            "hits": set(), "alive": True}


class TestCoordHelpers(unittest.TestCase):
    def test_col_name(self):
        self.assertEqual(R.col_name(0), "A")
        self.assertEqual(R.col_name(8), "I")
        self.assertEqual(R.col_name(9), "J")

    def test_fmt(self):
        self.assertEqual(R.fmt((0, 0)), "A1")
        self.assertEqual(R.fmt((8, 8)), "I9")
        self.assertEqual(R.fmt((9, 9)), "J10")

    def test_parse_coord(self):
        self.assertEqual(R.parse_coord("A1"), (0, 0))
        self.assertEqual(R.parse_coord("I9"), (8, 8))
        self.assertEqual(R.parse_coord("b5"), (4, 1))
        self.assertEqual(R.parse_coord("J10"), (9, 9))
        self.assertIsNone(R.parse_coord("K1"))
        self.assertIsNone(R.parse_coord("A0"))


class TestAreas(unittest.TestCase):
    def test_area_2x2_clamp(self):
        cells = R.area_2x2((9, 9))
        self.assertEqual(set(cells), {(8, 8), (8, 9), (9, 8), (9, 9)})

    def test_area_3x3_center(self):
        cells = R.area_3x3((4, 4))
        self.assertEqual(len(cells), 9)
        self.assertIn((4, 4), cells)
        self.assertIn((3, 3), cells)
        self.assertIn((5, 5), cells)

    def test_area_3x3_clamp(self):
        cells = R.area_3x3((0, 0))
        self.assertEqual(set(cells), {(r, c) for r in range(3) for c in range(3)})

    def test_column_row(self):
        self.assertEqual(len(R.column_cells(3)), 10)
        self.assertEqual(len(R.row_cells(3)), 10)

    def test_line_6(self):
        v = R.line_6_vertical((5, 5))
        self.assertEqual(v, [(3, 5), (4, 5), (5, 5), (6, 5), (7, 5), (8, 5)])
        h = R.line_6_horizontal((5, 5))
        self.assertEqual(h, [(5, 3), (5, 4), (5, 5), (5, 6), (5, 7), (5, 8)])
        # 越界时夹回，仍为 6 格
        self.assertEqual(len(R.line_6_vertical((0, 0))), 6)
        self.assertEqual(len(R.line_6_horizontal((0, 0))), 6)
        self.assertEqual(len(R.line_6_vertical((9, 9))), 6)
        self.assertEqual(len(R.line_6_horizontal((9, 9))), 6)


class TestShipShapes(unittest.TestCase):
    def test_ai_command_shape(self):
        t = R.SHIP_TYPES["ai"]["command"]
        self.assertEqual(t["size"], 9)
        self.assertEqual(t["weak_cell"], (4, 1))  # 干字竖笔底端

    def test_ai_flagship_shape(self):
        t = R.SHIP_TYPES["ai"]["flagship"]
        self.assertEqual(t["size"], 11)
        self.assertEqual(t["weak_cell"], (4, 2))  # 士字竖笔底端
        # 士字：顶短横 3（row0 cols1-3）+ 底长横 5（row3 cols0-4）+ 竖 5（col2）
        self.assertEqual(set(t["cells"]), {
            (0, 1), (0, 2), (0, 3), (1, 2), (2, 2),
            (3, 0), (3, 1), (3, 2), (3, 3), (3, 4), (4, 2),
        })

    def test_ai_assault_shape(self):
        self.assertEqual(R.SHIP_TYPES["ai"]["assault"]["size"], 4)

    def test_ai_destroyer_shape(self):
        self.assertEqual(R.SHIP_TYPES["ai"]["destroyer"]["size"], 5)

    def test_max_counts(self):
        expected = {"scout": 3, "frigate": 2, "assault": 2,
                    "destroyer": 1, "command": 1, "flagship": 1}
        for side in ("ai", "player"):
            for key, cnt in expected.items():
                self.assertEqual(R.SHIP_TYPES[side][key]["max_count"], cnt)

    def test_player_command_shape(self):
        t = R.SHIP_TYPES["player"]["command"]
        self.assertEqual(t["size"], 6)
        self.assertEqual(t["weak_cell"], (3, 1))  # T 字竖笔底端

    def test_player_flagship_shape(self):
        t = R.SHIP_TYPES["player"]["flagship"]
        self.assertEqual(t["size"], 6)
        self.assertEqual(t["weak_cell"], (0, 1))  # 十字上方短柄顶端

    def test_line_ships_weak_first(self):
        for side in ("ai", "player"):
            self.assertEqual(R.SHIP_TYPES[side]["scout"]["weak_cell"], (0, 0))
            self.assertEqual(R.SHIP_TYPES[side]["assault"]["weak_cell"], (0, 0))
            self.assertEqual(R.SHIP_TYPES[side]["destroyer"]["weak_cell"], (0, 0))


class TestFleetGeneration(unittest.TestCase):
    def _fleet_stats(self, side):
        fleet = R.generate_fleet(side)
        total = sum(R.SHIP_TYPES[side][k]["size"] for k in fleet)
        counts = {k: fleet.count(k) for k in set(fleet)}
        return fleet, total, counts

    def test_ai_fleet(self):
        for _ in range(60):
            fleet, total, counts = self._fleet_stats("ai")
            self.assertLessEqual(total, 35)  # 总格数只是上限
            self.assertIn("command", fleet)
            self.assertIn("flagship", fleet)
            self.assertGreaterEqual(len(fleet), 3)  # 至少 3 艘
            # 护卫舰+突击舰 合计 ≤2
            self.assertLessEqual(fleet.count("frigate") + fleet.count("assault"), 2)
            for k, c in counts.items():
                self.assertLessEqual(c, R.SHIP_TYPES["ai"][k]["max_count"])

    def test_player_fleet(self):
        for _ in range(60):
            fleet, total, counts = self._fleet_stats("player")
            self.assertLessEqual(total, 22)
            self.assertGreaterEqual(len(fleet), 3)  # 至少 3 艘
            # 指挥舰与旗舰都必带
            self.assertIn("command", fleet)
            self.assertIn("flagship", fleet)
            for k, c in counts.items():
                self.assertLessEqual(c, R.SHIP_TYPES["player"][k]["max_count"])


class TestPlacement(unittest.TestCase):
    def test_place_fleet_no_overlap(self):
        for side in ("ai", "player"):
            fleet = R.generate_fleet(side)
            board, ships = R.place_fleet(side, fleet)
            self.assertEqual(len(ships), len(fleet))
            occupied = set()
            for s in ships:
                self.assertEqual(len(s["cells"]), R.SHIP_TYPES[side][s["type"]]["size"])
                self.assertTrue(s["weak_cells"])
                for cell in s["cells"]:
                    self.assertNotIn(cell, occupied)
                    occupied.add(cell)
            self.assertEqual(len(occupied), sum(R.SHIP_TYPES[side][k]["size"] for k in fleet))

    def test_weak_cells_are_subset_of_cells(self):
        for side in ("ai", "player"):
            fleet = R.generate_fleet(side)
            _, ships = R.place_fleet(side, fleet)
            for s in ships:
                self.assertTrue(s["weak_cells"].issubset(set(s["cells"])))


class TestHitResolution(unittest.TestCase):
    def test_weak_hit_destroys_instantly(self):
        s = _make_ship([(0, 0), (0, 1)], [(0, 0)])
        destroyed, weak = R.hit_cell(s, (0, 0))
        self.assertTrue(destroyed)
        self.assertTrue(weak)
        self.assertTrue(R.is_destroyed(s))
        # 剩余普通部位也标记击毁
        self.assertEqual(s["hits"], {(0, 0), (0, 1)})

    def test_normal_hit_accumulates(self):
        s = _make_ship([(0, 0), (0, 1), (0, 2)], [(0, 0)])
        destroyed, weak = R.hit_cell(s, (0, 1))
        self.assertFalse(destroyed)
        self.assertFalse(weak)
        self.assertFalse(R.is_destroyed(s))

    def test_all_cells_hit_destroys(self):
        # 弱点已被消除的舰体：打光全部格子也击毁
        s = _make_ship([(0, 0), (0, 1)], [])
        R.hit_cell(s, (0, 1))
        self.assertFalse(R.is_destroyed(s))
        R.hit_cell(s, (0, 0))
        self.assertTrue(R.is_destroyed(s))

    def test_resolve_hits_weak(self):
        ships = [_make_ship([(0, 0), (0, 1)], [(0, 0)], "destroyer")]
        shots = set()
        events, destroyed, weak_killed = R.resolve_hits(ships, shots, [(0, 0)])
        self.assertEqual(len(destroyed), 1)
        self.assertEqual(len(weak_killed), 1)  # 通过弱点击毁
        self.assertIn((0, 0), shots)
        self.assertIn((0, 1), shots)  # 整舰格子已炮击


class TestTraits(unittest.TestCase):
    def test_last_surviving_type(self):
        ships = [_make_ship([(0, 0)], [(0, 0)], "scout"),
                 _make_ship([(1, 1)], [(1, 1)], "scout")]
        self.assertEqual(R.last_surviving_type(ships), "scout")
        ships.append(_make_ship([(2, 2)], [(2, 2)], "frigate"))
        self.assertIsNone(R.last_surviving_type(ships))

    def test_has_adjacent_ship(self):
        a = _make_ship([(0, 0)], [(0, 0)], "scout")
        b = _make_ship([(0, 1)], [(0, 1)], "scout")
        self.assertTrue(R.has_adjacent_ship(a, [a, b]))
        c = _make_ship([(5, 5)], [(5, 5)], "scout")
        self.assertFalse(R.has_adjacent_ship(c, [a, b, c]))

    def test_eliminate_weak_frigate(self):
        frigate = _make_ship([(0, 0), (0, 1)], [(0, 0)], "frigate")
        self.assertTrue(R.eliminate_weak_points(frigate))
        self.assertFalse(frigate["weak_cells"])  # 护卫舰弱点现可被消除

    def test_add_weak_points(self):
        s = _make_ship([(0, 0), (0, 1), (0, 2), (0, 3)], [(0, 0)], "frigate")
        R.add_weak_points(s, 3)
        self.assertEqual(len(s["weak_cells"]), 4)

    def test_frigate_adjacent_clear(self):
        # 玩家护卫舰【裙摆】：接壤时消除自身及所接壤舰体的弱点
        frigate = _make_ship([(0, 0), (0, 1)], [(0, 0)], "frigate")
        scout = _make_ship([(0, 2)], [(0, 2)], "scout")
        events = R.apply_deploy_traits([frigate, scout], "player")
        self.assertFalse(frigate["weak_cells"])  # 自身弱点被消除
        self.assertFalse(scout["weak_cells"])    # 邻舰弱点被消除
        self.assertTrue(any("裙摆" in e for e in events))

    def test_assault_conceal(self):
        assault = _make_ship([(0, 0), (0, 1), (0, 2)], [(0, 0)], "assault")
        events = R.apply_deploy_traits([assault], "ai")
        self.assertFalse(assault["weak_cells"])  # 孤立 → 匿鹰消除自身弱点
        self.assertTrue(any("匿鹰" in e for e in events))

    def test_special_shot_on_destroy(self):
        self.assertEqual(R.special_shot_on_destroy(_make_ship([(0, 0)], [(0, 0)], "destroyer")),
                         "laser_row")
        self.assertEqual(R.special_shot_on_destroy(_make_ship([(0, 0)], [(0, 0)], "flagship")),
                         "phase_3x3_all")
        self.assertIsNone(R.special_shot_on_destroy(_make_ship([(0, 0)], [(0, 0)], "scout")))

    def test_player_trait_texts(self):
        # 侦察梭【垂眸】→ 唯一存活时获得齐射γ+扫描θ
        self.assertIn("齐射γ", R.SHIP_TYPES["player"]["scout"]["trait"])
        self.assertIn("扫描θ", R.SHIP_TYPES["player"]["scout"]["trait"])
        # 指挥舰【羽翼】→ 初始可使用道具次数+1
        self.assertIn("初始可使用道具次数+1", R.SHIP_TYPES["player"]["command"]["trait"])
        # AI 侦察梭【孤雀】→ 唯一存活时炮击变激光α
        self.assertIn("激光炮击α", R.SHIP_TYPES["ai"]["scout"]["trait"])
        # 所有舰体均有简略特性（悬浮窗用）
        for side in ("ai", "player"):
            for key in R.SHIP_KEYS:
                self.assertIn("trait_short", R.SHIP_TYPES[side][key])
                self.assertTrue(R.SHIP_TYPES[side][key]["trait_short"])


if __name__ == "__main__":
    unittest.main()
