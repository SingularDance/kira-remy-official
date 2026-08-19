# -*- coding: utf-8 -*-
"""星海战棋纯规则逻辑的单元测试。

覆盖：坐标解析、舰队生成（=13 格 / 每类上限 / >=4 艘）、布阵（不重叠不越界）、
弱点映射（六类固定位置随旋转）、护卫舰弱点转移与回补、突击舰隔离消除、
命中结算（弱点秒毁 / 普通累计 / 打光才毁）、区域工具（2x2 / 3x3 / 竖排 / 横排）。
"""

import random
import unittest

import battleship_rules as br


class TestCoord(unittest.TestCase):
    def test_col_name(self):
        self.assertEqual(br.col_name(0), "A")
        self.assertEqual(br.col_name(8), "I")

    def test_parse_coord_valid(self):
        self.assertEqual(br.parse_coord("A1"), (0, 0))
        self.assertEqual(br.parse_coord("I9"), (8, 8))
        self.assertEqual(br.parse_coord("B5"), (4, 1))
        self.assertEqual(br.parse_coord("b5"), (4, 1))
        self.assertEqual(br.parse_coord("C-3"), (2, 2))
        self.assertEqual(br.parse_coord("射击 E7"), (6, 4))

    def test_parse_coord_invalid(self):
        self.assertIsNone(br.parse_coord("J1"))     # 超列
        self.assertIsNone(br.parse_coord("A0"))     # 行超下界
        self.assertIsNone(br.parse_coord("A10"))    # 行超上界
        self.assertIsNone(br.parse_coord("xyz"))    # 无坐标

    def test_fmt(self):
        self.assertEqual(br.fmt((0, 0)), "A1")
        self.assertEqual(br.fmt((8, 8)), "I9")


class TestAreas(unittest.TestCase):
    def test_area_2x2(self):
        cells = br.area_2x2((0, 0))
        self.assertEqual(set(cells), {(0, 0), (0, 1), (1, 0), (1, 1)})
        # 越界夹回
        cells = br.area_2x2((8, 8))
        self.assertEqual(set(cells), {(7, 7), (7, 8), (8, 7), (8, 8)})

    def test_area_3x3(self):
        cells = br.area_3x3((4, 4))
        self.assertEqual(len(cells), 9)
        self.assertIn((4, 4), cells)
        # 贴边夹回
        cells = br.area_3x3((0, 0))
        self.assertEqual(set(cells), {(r, c) for r in range(3) for c in range(3)})

    def test_column_row(self):
        self.assertEqual(br.column_cells(0), [(r, 0) for r in range(9)])
        self.assertEqual(br.row_cells(3), [(3, c) for c in range(9)])


class TestFleetGeneration(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(42)

    def test_valid_fleets_exist(self):
        self.assertTrue(br._VALID_FLEETS)

    def test_generate_fleet_constraints(self):
        for _ in range(200):
            fleet = br.generate_fleet(self.rng)
            total = sum(br.SHIP_TYPES[k]["size"] for k in fleet)
            self.assertEqual(total, br.MAX_TOTAL_CELLS)
            self.assertGreaterEqual(len(fleet), br.MIN_SHIPS)
            for key, t in br.SHIP_TYPES.items():
                self.assertLessEqual(fleet.count(key), t["max_count"])


class TestPlacement(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(7)
        self.fleet = br.generate_fleet(self.rng)

    def test_place_no_overlap_no_oob(self):
        board, ships = br.place_fleet(self.fleet, self.rng)
        self.assertEqual(len(ships), len(self.fleet))
        seen = set()
        total = 0
        for ship in ships:
            self.assertEqual(len(ship["cells"]), br.SHIP_TYPES[ship["type"]]["size"])
            self.assertEqual(len(ship["weak_cells"]), 1)
            for r, c in ship["cells"]:
                self.assertTrue(0 <= r < br.SIZE and 0 <= c < br.SIZE)
                self.assertNotIn((r, c), seen)
                seen.add((r, c))
                self.assertNotEqual(board[r][c], 0)
            total += len(ship["cells"])
        self.assertEqual(total, br.MAX_TOTAL_CELLS)
        self.assertEqual(len(seen), br.MAX_TOTAL_CELLS)


class TestWeakMapping(unittest.TestCase):
    """弱点位置固定：验证六类舰体每种旋转变体弱点数量都是 1。"""

    def test_every_rotation_one_weak(self):
        for key, t in br.SHIP_TYPES.items():
            for v in t["rotations"]:
                self.assertEqual(len(v["weak_cells"]), 1)
                wc = next(iter(v["weak_cells"]))
                self.assertIn(wc, v["cells"])

    def test_line_ship_weak_positions(self):
        # 突击舰弱点在中心（三格正中）
        for v in br.SHIP_TYPES["assault"]["rotations"]:
            wc = next(iter(v["weak_cells"]))
            # 无论横竖，中心格都不是端点
            self.assertNotEqual(v["cells"].index(wc), 0)
            self.assertNotEqual(v["cells"].index(wc), len(v["cells"]) - 1)


class TestTraits(unittest.TestCase):
    def _ship(self, key, cells, weak):
        return {"type": key, "name": br.SHIP_TYPES[key]["name"],
                "cells": list(cells), "weak_cells": set(weak),
                "hits": set(), "alive": True, "transfer": None}

    def test_frigate_transfer_and_restore(self):
        frigate = self._ship("frigate", [(0, 0), (0, 1)], {(0, 0)})
        other = self._ship("assault", [(1, 0), (1, 1), (1, 2)], {(1, 1)})
        ships = [frigate, other]
        self.assertTrue(br.frigate_transfer(frigate, ships))
        # 护卫舰两格皆弱点，邻舰弱点被移除
        self.assertEqual(frigate["weak_cells"], {(0, 0), (0, 1)})
        self.assertEqual(other["weak_cells"], set())
        # 坠毁回补
        br.restore_frigate_weak(frigate)
        self.assertEqual(other["weak_cells"], {(1, 1)})

    def test_frigate_no_adjacent_no_transfer(self):
        frigate = self._ship("frigate", [(0, 0), (0, 1)], {(0, 0)})
        other = self._ship("assault", [(5, 5), (5, 6), (5, 7)], {(5, 6)})
        self.assertFalse(br.frigate_transfer(frigate, [frigate, other]))
        self.assertEqual(frigate["weak_cells"], {(0, 0)})

    def test_assault_isolated_removes_weak(self):
        # 不贴边、无邻舰 → 消除弱点
        assault = self._ship("assault", [(4, 4), (4, 5), (4, 6)], {(4, 5)})
        others = [self._ship("scout", [(0, 0)], {(0, 0)})]
        br.apply_deploy_traits([assault] + others)
        self.assertEqual(assault["weak_cells"], set())

    def test_assault_touching_boundary_keeps_weak(self):
        assault = self._ship("assault", [(0, 4), (0, 5), (0, 6)], {(0, 5)})
        br.apply_deploy_traits([assault])
        self.assertEqual(assault["weak_cells"], {(0, 5)})

    def test_has_alive_command(self):
        command = self._ship("command", [(0, 0), (0, 1), (0, 2), (1, 1), (2, 1)], {(2, 1)})
        scout = self._ship("scout", [(5, 5)], {(5, 5)})
        self.assertTrue(br.has_alive_command([command, scout]))
        command["alive"] = False
        self.assertFalse(br.has_alive_command([command, scout]))
        self.assertFalse(br.has_alive_command([scout]))

    def test_scout_alpha(self):
        scouts = [self._ship("scout", [(0, 0)], {(0, 0)}),
                  self._ship("scout", [(8, 8)], {(8, 8)})]
        self.assertTrue(br.scout_alpha_active(scouts))
        scouts.append(self._ship("frigate", [(4, 4), (4, 5)], {(4, 4)}))
        self.assertFalse(br.scout_alpha_active(scouts))

    def test_special_shot_on_destroy(self):
        self.assertEqual(br.special_shot_on_destroy(
            self._ship("destroyer", [(0, 0)], {(0, 0)})), "beta")
        self.assertEqual(br.special_shot_on_destroy(
            self._ship("flagship", [(0, 0)], {(0, 0)})), "volley3")
        self.assertIsNone(br.special_shot_on_destroy(
            self._ship("scout", [(0, 0)], {(0, 0)})))


class TestHitResolution(unittest.TestCase):
    def _ship(self, key, cells, weak):
        return {"type": key, "name": br.SHIP_TYPES[key]["name"],
                "cells": list(cells), "weak_cells": set(weak),
                "hits": set(), "alive": True, "transfer": None}

    def test_weak_hit_instant_destroy(self):
        ship = self._ship("assault", [(0, 0), (0, 1), (0, 2)], {(0, 1)})
        ships = [ship]
        shots = set()
        events, destroyed = br.resolve_hits(ships, shots, [(0, 1)])
        self.assertEqual(destroyed, [ship])
        self.assertFalse(ship["alive"])
        self.assertTrue(any("击毁" in e for e in events))

    def test_normal_hit_accumulates_then_destroy(self):
        ship = self._ship("assault", [(0, 0), (0, 1), (0, 2)], {(0, 1)})
        ships = [ship]
        shots = set()
        # 命中端点（普通），不击毁
        events, destroyed = br.resolve_hits(ships, shots, [(0, 0)])
        self.assertEqual(destroyed, [])
        self.assertTrue(ship["alive"])
        # 打光剩余格子 → 击毁（中间弱点已被端点命中覆盖？不，弱点在中间）
        events, destroyed = br.resolve_hits(ships, shots, [(0, 1), (0, 2)])
        self.assertEqual(destroyed, [ship])
        self.assertFalse(ship["alive"])

    def test_all_cells_destroy_without_weak_hit(self):
        # 突击舰弱点被消除后，打光三格才击毁
        ship = self._ship("assault", [(0, 0), (0, 1), (0, 2)], set())
        ships = [ship]
        shots = set()
        events, destroyed = br.resolve_hits(ships, shots, [(0, 0), (0, 1)])
        self.assertEqual(destroyed, [])
        self.assertTrue(ship["alive"])
        events, destroyed = br.resolve_hits(ships, shots, [(0, 2)])
        self.assertEqual(destroyed, [ship])

    def test_miss(self):
        ships = [self._ship("scout", [(0, 0)], {(0, 0)})]
        shots = set()
        events, destroyed = br.resolve_hits(ships, shots, [(5, 5)])
        self.assertEqual(destroyed, [])
        self.assertTrue(any("落空" in e for e in events))

    def test_skip_already_shot(self):
        ship = self._ship("scout", [(0, 0)], {(0, 0)})
        ships = [ship]
        shots = {(0, 0)}
        # 已在 shots 里，不再结算
        events, _ = br.resolve_hits(ships, shots, [(0, 0)])
        self.assertEqual(events, ["落空"])


class TestInferWeakTargets(unittest.TestCase):
    def _board_cells(self):
        return {(r, c) for r in range(br.SIZE) for c in range(br.SIZE)}

    def _ship_abs(self, key, dr, dc):
        """把某类舰体按规范朝向放到 (dr,dc)，返回 (绝对格子集, 绝对弱点格)。"""
        t = br.SHIP_TYPES[key]
        cells = {(r + dr, c + dc) for r, c in t["cells"]}
        wr, wc = t["weak_cell"]
        return cells, (wr + dr, wc + dc)

    def test_command_fully_revealed(self):
        # 指挥舰完全暴露、周围判空 → 唯一一致放置，弱点正是 T 字底边中心
        cells, weak = self._ship_abs("command", 3, 3)
        blocked = self._board_cells() - cells
        counts = br.infer_weak_targets(["command"], cells, blocked)
        self.assertEqual(counts, {weak: 1})

    def test_destroyer_partial_reveals_weak_at_first_end(self):
        # 驱逐舰只暴露中间一格、其余判空 → 弱点落在首端（左端），不是另一端
        cells, weak = self._ship_abs("destroyer", 0, 0)
        known = {(0, 2)}
        blocked = self._board_cells() - cells
        counts = br.infer_weak_targets(["destroyer"], known, blocked)
        self.assertEqual(counts, {weak: 1})
        self.assertEqual(weak, (0, 0))

    def test_blocked_excludes_wrong_placement(self):
        # 若把舰体实际位置之外的一整列判空，竖直放置会被排除
        cells, weak = self._ship_abs("destroyer", 0, 0)
        known = {(0, 2)}
        blocked = self._board_cells() - cells
        # 竖直放置（沿第 2 列）会覆盖 (1,2)/(2,2)/(3,2)，这些都在 blocked 里 → 被排除
        counts = br.infer_weak_targets(["destroyer"], known, blocked)
        self.assertNotIn((1, 2), counts)
        self.assertEqual(counts, {weak: 1})

    def test_no_known_has_returns_empty(self):
        self.assertEqual(br.infer_weak_targets(["command"], set(), set()), {})


if __name__ == "__main__":
    unittest.main()
