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

    def test_line_4(self):
        v = R.line_4_vertical((5, 5))
        self.assertEqual(v, [(4, 5), (5, 5), (6, 5), (7, 5)])
        h = R.line_4_horizontal((5, 5))
        self.assertEqual(h, [(5, 4), (5, 5), (5, 6), (5, 7)])
        # 越界时夹回，仍为 4 格
        self.assertEqual(len(R.line_4_vertical((0, 0))), 4)
        self.assertEqual(len(R.line_4_horizontal((0, 0))), 4)
        self.assertEqual(len(R.line_4_vertical((9, 9))), 4)
        self.assertEqual(len(R.line_4_horizontal((9, 9))), 4)


class TestShipShapes(unittest.TestCase):
    def test_ai_command_shape(self):
        t = R.SHIP_TYPES["ai"]["command"]
        self.assertEqual(t["size"], 9)
        self.assertEqual(t["weak_cell"], (4, 1))  # 干字竖笔底端

    def test_ai_flagship_shape(self):
        t = R.SHIP_TYPES["ai"]["flagship"]
        self.assertEqual(t["size"], 11)
        self.assertEqual(t["weak_cell"], (4, 2))  # 士字竖笔底端

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
    def _fleet_stats(self, side, ship_count=None):
        fleet = R.generate_fleet(side, ship_count=ship_count)
        total = sum(R.SHIP_TYPES[side][k]["size"] for k in fleet)
        counts = {k: fleet.count(k) for k in set(fleet)}
        return fleet, total, counts

    def test_ai_fleet(self):
        for _ in range(60):
            fleet, total, counts = self._fleet_stats("ai")
            self.assertLessEqual(total, 33)  # 总格数只是上限
            self.assertIn("command", fleet)
            self.assertIn("flagship", fleet)
            self.assertIn(len(fleet), (3, 4, 5, 6))
            for k, c in counts.items():
                self.assertLessEqual(c, R.SHIP_TYPES["ai"][k]["max_count"])

    def test_player_fleet(self):
        for _ in range(60):
            fleet, total, counts = self._fleet_stats("player")
            self.assertLessEqual(total, 22)
            self.assertIn(len(fleet), (6, 7, 8, 9))
            # 指挥舰与旗舰二选一
            self.assertEqual(("command" in fleet) ^ ("flagship" in fleet), True)
            for k, c in counts.items():
                self.assertLessEqual(c, R.SHIP_TYPES["player"][k]["max_count"])

    def test_ship_count_correspondence(self):
        for ai_count in (3, 4, 5, 6):
            self.assertEqual(R.player_ship_count_for(ai_count), ai_count + 3)

    def test_explicit_ship_count(self):
        for _ in range(20):
            for ai_count in (3, 4, 5, 6):
                fleet = R.generate_fleet("ai", ship_count=ai_count)
                self.assertEqual(len(fleet), ai_count)
                player_count = R.player_ship_count_for(ai_count)
                pfleet = R.generate_fleet("player", ship_count=player_count)
                self.assertEqual(len(pfleet), player_count)


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
        events, destroyed = R.resolve_hits(ships, shots, [(0, 0)])
        self.assertEqual(len(destroyed), 1)
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

    def test_eliminate_weak_frigate_protected(self):
        frigate = _make_ship([(0, 0), (0, 1)], [(0, 0)], "frigate")
        self.assertFalse(R.eliminate_weak_points(frigate))
        self.assertTrue(frigate["weak_cells"])  # 护卫舰弱点未被消除

    def test_add_weak_points(self):
        s = _make_ship([(0, 0), (0, 1), (0, 2), (0, 3)], [(0, 0)], "frigate")
        R.add_weak_points(s, 3)
        self.assertEqual(len(s["weak_cells"]), 4)

    def test_frigate_protect(self):
        frigate = _make_ship([(0, 0), (0, 1), (1, 0), (1, 1)], [(0, 0)], "frigate")
        scout = _make_ship([(2, 0)], [(2, 0)], "scout")
        other = R.frigate_protect(frigate, [frigate, scout], R.DIR_ORDER_AI, 3)
        self.assertEqual(other, scout)
        self.assertFalse(scout["weak_cells"])  # 侦察梭弱点被消除
        self.assertEqual(len(frigate["weak_cells"]), 4)  # 自身弱点 +3

    def test_assault_conceal(self):
        assault = _make_ship([(0, 0), (0, 1), (0, 2)], [(0, 0)], "assault")
        self.assertFalse(R.has_adjacent_ship(assault, [assault]))
        assault["weak_cells"].clear()  # 模拟藏匿生效
        self.assertFalse(assault["weak_cells"])

    def test_special_shot_on_destroy(self):
        self.assertEqual(R.special_shot_on_destroy(_make_ship([(0, 0)], [(0, 0)], "destroyer")),
                         "laser_row")
        self.assertEqual(R.special_shot_on_destroy(_make_ship([(0, 0)], [(0, 0)], "flagship")),
                         "phase_3x3_all")
        self.assertIsNone(R.special_shot_on_destroy(_make_ship([(0, 0)], [(0, 0)], "scout")))

    def test_player_trait_texts(self):
        # 侦察梭【斥候】→ 唯一存活时每回合炮击+1
        self.assertIn("每回合炮击次数+1", R.SHIP_TYPES["player"]["scout"]["trait"])
        # 指挥舰【计策】→ 每回合道具次数+1
        self.assertIn("每回合可使用道具次数+1", R.SHIP_TYPES["player"]["command"]["trait"])
        # 所有舰体均有简略特性（悬浮窗用）
        for side in ("ai", "player"):
            for key in R.SHIP_KEYS:
                self.assertIn("trait_short", R.SHIP_TYPES[side][key])
                self.assertTrue(R.SHIP_TYPES[side][key]["trait_short"])


if __name__ == "__main__":
    unittest.main()
