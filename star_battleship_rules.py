# -*- coding: utf-8 -*-
"""
星海战棋 - 纯规则模块（不 import Qt，可单测）

把「棋盘、舰体目录、舰队生成、布阵、弱点/特性、命中结算、区域工具」这些纯逻辑
从 UI 里抽出来，胜负判定全部本地确定性执行；UI 层只负责渲染与交互。

规则要点：
- 10x10 棋盘，坐标 A1-J10。
- 双方各 6 类舰体，各有固定形状与固定弱点；弱点随旋转一起转，每艘初始恰 1 个弱点。
  - 「第一格」弱点：直线/方形类舰体，弱点在 cell 列表首格。
  - 「顶点」弱点：指挥舰（干/T）与旗舰（士/十字）在竖直主干的一端。
- 部位分「弱点 / 普通」两种：命中弱点立即击毁；命中普通只累计，打光全部格子也击毁。
- 特性可动态加弱点（弱点+N）或消除弱点（双方护卫舰都可消除自身及所接壤舰体弱点）。
- 舰队：双方 ≥3 艘且必含指挥舰+旗舰；总格数只是上限（AI ≤35、玩家 ≤22），
  舰体类型在各上限内随机分配；AI 额外限制护卫舰+突击舰合计 ≤2。
"""

import random

SIZE = 10

# 部位语义（弱点是每艘船上的一个集合）
WEAK = "weak"
NORMAL = "normal"

# 四向偏移（仅用于「接壤」判定，无优先级）
FOUR_DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1)]

# 六类舰体的统一配色（双方同 key 同色，深色系、色相分明便于区分）
COLORS = {
    "scout": "#1565C0",     # 深蓝
    "frigate": "#2E7D32",   # 深绿
    "assault": "#EF6C00",   # 深橙
    "destroyer": "#6A1B9A", # 深紫
    "command": "#00838F",   # 深青
    "flagship": "#AD1457",  # 深玫红
}


# ============================================================
#  舰体目录
# ============================================================
# 每类：cells 为「规范朝向」下的相对偏移（含锚点，锚点在最小行/列处）；
# weak_index 指向 cells 里的弱点格；rot_k 为允许的旋转次数（0/90/180/270）。
# 弱点随 cells 一起旋转，保证「第一格/顶点」这类方向性弱点在旋转后仍落在正确位置。
SHIP_DEFS = {
    "ai": [
        {"key": "scout", "name": "侦察梭", "trait_name": "孤雀",
         "cells": [(0, 0), (0, 1)], "weak_index": 0, "rot_k": [0, 1], "max_count": 3,
         "trait": "孤雀：场上仅本舰存活时，蕾咪下回合1发炮击变为[激光炮击α]。",
         "trait_short": "唯一存活时，炮击变为[激光α]"},
        {"key": "frigate", "name": "护卫舰", "trait_name": "佑鹤",
         "cells": [(0, 0), (0, 1), (1, 0), (1, 1)], "weak_index": 0, "rot_k": [0], "max_count": 2,
         "trait": "佑鹤：存活时，敌方每回合炮击次数-1。本舰接壤时，消除本舰弱点。",
         "trait_short": "存活时使玩家炮击-1；接壤消除本舰弱点"},
        {"key": "assault", "name": "突击舰", "trait_name": "匿鹰",
         "cells": [(0, 0), (0, 1), (0, 2), (0, 3)], "weak_index": 0, "rot_k": [0, 1], "max_count": 2,
         "trait": "匿鹰：存活时，敌方每回合炮击次数-1。本舰孤立时，消除本舰弱点。",
         "trait_short": "存活时使玩家炮击-1；孤立消除本舰弱点"},
        {"key": "destroyer", "name": "驱逐舰", "trait_name": "颂歌",
         "cells": [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)], "weak_index": 0, "rot_k": [0, 1], "max_count": 1,
         "trait": "颂歌：坠毁时，蕾咪下回合1发炮击变为[激光炮击β]。",
         "trait_short": "坠毁时，下回合1发炮击变[激光β]"},
        {"key": "command", "name": "指挥舰", "trait_name": "星夜",
         # 干字形 9 格：顶横 3 + 中横 3 + 竖 5；弱点在竖笔底端 (4,1)
         "cells": [(0, 0), (0, 1), (0, 2), (1, 1), (2, 0), (2, 1), (2, 2), (3, 1), (4, 1)],
         "weak_index": 8, "rot_k": [0], "max_count": 1,
         "trait": "星夜：存活时，蕾咪每回合炮击次数+1。坠毁时：消除蕾咪所有舰体的弱点。",
         "trait_short": "存活时每回合炮击+1；坠毁消除所有弱点"},
        {"key": "flagship", "name": "旗舰", "trait_name": "流星",
         # 士字形 11 格：顶短横 3 + 底长横 5 + 竖 5；弱点在竖笔底端 (4,2)
         "cells": [(0, 1), (0, 2), (0, 3), (1, 2), (2, 2),
                   (3, 0), (3, 1), (3, 2), (3, 3), (3, 4), (4, 2)],
         "weak_index": 10, "rot_k": [0], "max_count": 1,
         "trait": "流星：存活时，蕾咪每回合炮击次数+1。坠毁时：蕾咪下回合所有炮击变为[齐射γ]。",
         "trait_short": "存活时每回合炮击+1；坠毁全部炮击变[齐射γ]"},
    ],
    "player": [
        {"key": "scout", "name": "侦察梭", "trait_name": "垂眸",
         "cells": [(0, 0)], "weak_index": 0, "rot_k": [0], "max_count": 3,
         "trait": "垂眸：场上仅本舰存活时，你获得1发[齐射γ]和1发[扫描θ]。坠毁时：你获得1发[扫描]。",
         "trait_short": "唯一存活时获得[齐射γ]+[扫描θ]；坠毁获得[扫描]"},
        {"key": "frigate", "name": "护卫舰", "trait_name": "裙摆",
         "cells": [(0, 0), (0, 1)], "weak_index": 0, "rot_k": [0, 1], "max_count": 2,
         "trait": "裙摆：本舰接壤时，消除本舰及所接壤舰体的弱点。坠毁时：你获得1发[扫描θ]。",
         "trait_short": "接壤时消除本舰及邻舰弱点；坠毁获得[扫描θ]"},
        {"key": "assault", "name": "突击舰", "trait_name": "宽恕",
         "cells": [(0, 0), (0, 1), (0, 2)], "weak_index": 0, "rot_k": [0, 1], "max_count": 2,
         "trait": "宽恕：击坠时，你获得一发[齐射]，然后使本舰弱点+1。",
         "trait_short": "击毁敌舰时获得[齐射]，自身弱点+1"},
        {"key": "destroyer", "name": "驱逐舰", "trait_name": "悲悯",
         "cells": [(0, 0), (0, 1), (0, 2), (0, 3)], "weak_index": 0, "rot_k": [0, 1], "max_count": 1,
         "trait": "悲悯：当本舰接壤时，你获得1发[激光炮击α]。当本舰孤立时，你获得1发[激光炮击β]。",
         "trait_short": "接壤获得[激光α]，孤立获得[激光β]"},
        {"key": "command", "name": "指挥舰", "trait_name": "羽翼",
         # T 字形 6 格：顶横 3 + 竖 4；弱点在竖笔底端 (3,1)
         "cells": [(0, 0), (0, 1), (0, 2), (1, 1), (2, 1), (3, 1)],
         "weak_index": 5, "rot_k": [0], "max_count": 1,
         "trait": "羽翼：你初始可使用道具次数+1。存活时：通过弱点击坠敌舰时，你获得1发[扫描θ]。",
         "trait_short": "初始道具次数+1；弱点击坠获得[扫描θ]"},
        {"key": "flagship", "name": "旗舰", "trait_name": "女神",
         # 十字形 6 格：横 3 + 竖 4；弱点在上方短柄顶端 (0,1)
         "cells": [(0, 1), (1, 0), (1, 1), (1, 2), (2, 1), (3, 1)],
         "weak_index": 0, "rot_k": [0], "max_count": 1,
         "trait": "女神：你初始额外获得1发[齐射γ]。击坠时：每回合限一次，你下回合所有炮击升级为齐射。",
         "trait_short": "初始获得[齐射γ]；击坠下回合炮击升级齐射"},
    ],
}


def _rotate(cells, k):
    """把一组相对偏移顺时针旋转 k*90 度并重新归一到左上角。"""
    out = list(cells)
    for _ in range(k % 4):
        out = [(c, -r) for r, c in out]
    min_r = min(r for r, _ in out)
    min_c = min(c for _, c in out)
    return [(r - min_r, c - min_c) for r, c in out]


def _build_ship_types(side):
    table = {}
    for d in SHIP_DEFS[side]:
        rotations = []
        for k in d["rot_k"]:
            cells = _rotate(d["cells"], k)
            weak_cells = {cells[d["weak_index"]]}
            rotations.append({"cells": cells, "weak_cells": weak_cells})
        table[d["key"]] = {
            "key": d["key"],
            "name": d["name"],
            "trait_name": d["trait_name"],
            "color": COLORS[d["key"]],
            "size": len(d["cells"]),
            "max_count": d["max_count"],
            "trait": d["trait"],
            "trait_short": d["trait_short"],
            "cells": d["cells"],
            "weak_cell": d["cells"][d["weak_index"]],
            "weak_index": d["weak_index"],
            "rotations": rotations,
        }
    return table


SHIP_TYPES = {
    "ai": _build_ship_types("ai"),
    "player": _build_ship_types("player"),
}

SHIP_KEYS = ["scout", "frigate", "assault", "destroyer", "command", "flagship"]


# ============================================================
#  舰队生成
# ============================================================

def _valid_fleets(bag, mandatory, max_cells, side):
    """枚举袋内所有「额外舰体」子集：加上 mandatory 后总格数 ≤ max_cells、
    总舰数 ≥3；AI 额外限制 护卫舰+突击舰 ≤2。返回合法额外舰体列表。"""
    n = len(bag)
    valid = []
    for mask in range(1 << n):
        subset = [bag[i] for i in range(n) if (mask >> i) & 1]
        fleet = mandatory + subset
        if len(fleet) < 3:
            continue
        total = sum(SHIP_TYPES[side][k]["size"] for k in fleet)
        if total > max_cells:
            continue
        if side == "ai":
            if sum(1 for k in fleet if k in ("frigate", "assault")) > 2:
                continue
        valid.append(subset)
    return valid


def generate_fleet(side, rng=None):
    """随机生成一方舰队（返回舰体 key 列表）。

    - 双方均 ≥3 艘且必含 指挥舰+旗舰。
    - 总格数只是上限（AI ≤35、玩家 ≤22），不要求填满。
    - 舰体类型在各自上限（max_count）内随机分配；AI 额外限制护卫舰+突击舰 ≤2。
    """
    rng = rng or random
    max_cells = 35 if side == "ai" else 22
    mandatory = ["command", "flagship"]
    bag = (["scout"] * 3 + ["frigate"] * 2
           + ["assault"] * 2 + ["destroyer"] * 1)
    subs = _valid_fleets(bag, mandatory, max_cells, side)
    if not subs:
        raise RuntimeError(f"无法为 {side} 生成合法舰队")
    fleet = mandatory + list(rng.choice(subs))
    rng.shuffle(fleet)
    return fleet


def place_fleet(side, fleet, rng=None):
    """在 10x10 上随机不重叠布阵，返回 (board, ships)。

    board[r][c] 为舰体编号（1-based，0 表示空）。
    ships 每项：type/name/color/cells/weak_cells/hits/alive（按 fleet 原顺序返回）。
    弱点按类型固定位置随旋转映射；入场特性（护卫舰佑鹤/裙摆、突击舰匿鹰）由
    apply_deploy_traits 单独调用。
    """
    rng = rng or random
    # 大船先放，避免后期被小舰堵死导致无落点
    order = sorted(range(len(fleet)),
                   key=lambda i: -SHIP_TYPES[side][fleet[i]]["size"])
    for _ in range(20):
        board = [[0] * SIZE for _ in range(SIZE)]
        ship_map = {}
        ok = True
        for i in order:
            key = fleet[i]
            t = SHIP_TYPES[side][key]
            candidates = []
            for variant in t["rotations"]:
                max_dr = max(dr for dr, _ in variant["cells"])
                max_dc = max(dc for _, dc in variant["cells"])
                for r in range(SIZE - max_dr):
                    for c in range(SIZE - max_dc):
                        cells = [(r + dr, c + dc) for dr, dc in variant["cells"]]
                        if all(board[rr][cc] == 0 for rr, cc in cells):
                            candidates.append((variant, r, c, cells))
            if not candidates:
                ok = False
                break
            variant, r, c, cells = rng.choice(candidates)
            for rr, cc in cells:
                board[rr][cc] = i + 1
            weak_cells = {(r + dr, c + dc) for dr, dc in variant["weak_cells"]}
            ship_map[i] = {
                "type": key,
                "name": t["name"],
                "color": t["color"],
                "trait_name": t["trait_name"],
                "cells": cells,
                "weak_cells": weak_cells,
                "init_weak_cells": set(weak_cells),
                "hits": set(),
                "alive": True,
            }
        if ok:
            return board, [ship_map[i] for i in range(len(fleet))]
    raise RuntimeError(f"无法为 {side} 完成布阵（重试 20 次仍失败）")


# ============================================================
#  接壤 / 特性
# ============================================================

def ship_at(ships, pos):
    """返回覆盖 pos 的存活舰体，无则 None。"""
    for s in ships:
        if s["alive"] and pos in s["cells"]:
            return s
    return None


def has_adjacent_ship(ship, ships):
    """是否与其它存活舰体接壤（贴地图边界不算）。"""
    for r, c in ship["cells"]:
        for dr, dc in FOUR_DIRS:
            other = ship_at(ships, (r + dr, c + dc))
            if other is not None and other is not ship:
                return True
    return False


def touches_boundary(ship):
    return any(r == 0 or r == SIZE - 1 or c == 0 or c == SIZE - 1
               for r, c in ship["cells"])


def eliminate_weak_points(ship):
    """消除一艘舰体的全部弱点；无弱点时返回 False。"""
    if not ship["weak_cells"]:
        return False
    ship["weak_cells"].clear()
    return True


def add_weak_points(ship, n):
    """给舰体追加 n 个弱点格（优先补非弱点格），返回未补完的余量。"""
    for cell in ship["cells"]:
        if n <= 0:
            break
        if cell not in ship["weak_cells"]:
            ship["weak_cells"].add(cell)
            n -= 1
    return n


def _eliminate_adjacent_weak_points(ship, ships):
    """消除 ship 所接壤（上下左右）的所有邻舰弱点，返回消除的舰体数。"""
    seen = set()
    for r, c in ship["cells"]:
        for dr, dc in FOUR_DIRS:
            other = ship_at(ships, (r + dr, c + dc))
            if other is not None and other is not ship and id(other) not in seen:
                seen.add(id(other))
                eliminate_weak_points(other)
    return len(seen)


def apply_deploy_traits(ships, side):
    """入场特性（开局一次），返回事件文本列表。

    AI：护卫舰佑鹤（接壤→消除自身弱点）；突击舰匿鹰（孤立→消除自身弱点）。
    玩家：护卫舰裙摆（接壤→消除自身及所接壤舰体弱点）。
    """
    events = []
    for s in ships:
        if not s["alive"]:
            continue
        if s["type"] == "frigate":
            if has_adjacent_ship(s, ships):
                if side == "ai":
                    if eliminate_weak_points(s):
                        events.append(f"{s['name']}佑鹤：消除自身弱点")
                else:
                    if eliminate_weak_points(s):
                        events.append(f"{s['name']}裙摆：消除自身弱点")
                    n = _eliminate_adjacent_weak_points(s, ships)
                    if n:
                        events.append(f"{s['name']}裙摆：消除{n}艘邻舰的弱点")
        elif s["type"] == "assault" and side == "ai":
            if not has_adjacent_ship(s, ships):
                s["weak_cells"].clear()
                events.append(f"{s['name']}匿鹰：消除自身弱点")
    return events


def last_surviving_type(ships):
    """返回「唯一存活的舰体类型」，无存活或多类存活返回 None。"""
    alive = [s["type"] for s in ships if s["alive"]]
    if not alive:
        return None
    first = alive[0]
    return first if all(t == first for t in alive) else None


def has_alive(ships, key):
    return any(s["type"] == key and s["alive"] for s in ships)


def special_shot_on_destroy(ship):
    """AI 舰体坠毁触发的特殊炮击：驱逐舰→激光β；旗舰→齐射γ（所有炮击）；其余→None。"""
    if ship["type"] == "destroyer":
        return "laser_row"
    if ship["type"] == "flagship":
        return "phase_3x3_all"
    return None


def command_eliminate_on_destroy(ships):
    """AI 指挥舰坠毁：消除己方所有舰体弱点，返回事件文本。"""
    n = 0
    for s in ships:
        if s["alive"] and eliminate_weak_points(s):
            n += 1
    return f"指挥舰坠毁：消除己方{n}艘舰体的弱点" if n else ""


# ============================================================
#  命中结算
# ============================================================

def hit_cell(ship, cell):
    """命中 ship 的一个格子。返回 (destroyed_now, hit_weak)。

    命中弱点 → 立即击毁（其余普通部位一并标记击毁）；命中普通 → 累计，
    打光全部格子也击毁。
    """
    ship["hits"].add(cell)
    if cell in ship["weak_cells"]:
        ship["hits"].update(ship["cells"])
        ship["alive"] = False
        return True, True
    if len(ship["hits"]) == len(ship["cells"]):
        ship["alive"] = False
        return True, False
    return False, False


def is_destroyed(ship):
    return not ship["alive"]


def resolve_hits(ships, shots, cells):
    """对一组格子结算命中（普通/特殊/齐射共用）。

    shots 为攻击方的已炮击集合（会被更新）；
    返回 (events, destroyed_ships, weak_killed)，weak_killed 为本次通过弱点击毁的舰体列表。
    """
    events = []
    destroyed = []
    weak_killed = []
    for p in cells:
        if p in shots:
            continue
        shots.add(p)
        ship = ship_at(ships, p)
        if ship is None:
            events.append(f"{fmt(p)}落空")
            continue
        destroyed_now, hit_weak = hit_cell(ship, p)
        if destroyed_now:
            if ship not in destroyed:
                destroyed.append(ship)
                if hit_weak:
                    weak_killed.append(ship)
            shots.update(ship["cells"])  # 击毁后整舰格子视为已炮击
            events.append(f"击毁{ship['name']}！")
        else:
            events.append(f"命中{ship['name']}！")
    if not events:
        events.append("落空")
    return events, destroyed, weak_killed


# ============================================================
#  坐标 / 区域工具
# ============================================================

def col_name(c):
    return chr(ord("A") + c)


def fmt(pos):
    return f"{col_name(pos[1])}{pos[0] + 1}"


def parse_coord(text):
    """从文本解析一个 10x10 坐标（A1-J10），失败返回 None。"""
    import re
    m = re.search(r"([A-Ja-j])\s*[- ]?\s*(10|[1-9])(?!\d)", text)
    if not m:
        return None
    return (int(m.group(2)) - 1, ord(m.group(1).upper()) - ord("A"))


def area_2x2(center):
    """以目标格为左上角的 2x2 区域（越界时夹回棋盘内）。"""
    r0 = min(center[0], SIZE - 2)
    c0 = min(center[1], SIZE - 2)
    return [(r0, c0), (r0, c0 + 1), (r0 + 1, c0), (r0 + 1, c0 + 1)]


def area_3x3(center):
    """以目标格为中心的 3x3 区域（越界时夹回棋盘内）。"""
    r0 = min(max(center[0] - 1, 0), SIZE - 3)
    c0 = min(max(center[1] - 1, 0), SIZE - 3)
    return [(r, c) for r in range(r0, r0 + 3) for c in range(c0, c0 + 3)]


def column_cells(c):
    return [(r, c) for r in range(SIZE)]


def row_cells(r):
    return [(r, c) for c in range(SIZE)]


def line_6_vertical(anchor):
    """以 anchor 为锚的竖直 6 格直线（越界时夹回棋盘内）。"""
    r, c = anchor
    r0 = min(max(r - 2, 0), SIZE - 6)
    return [(rr, c) for rr in range(r0, r0 + 6)]


def line_6_horizontal(anchor):
    """以 anchor 为锚的水平 6 格直线（越界时夹回棋盘内）。"""
    r, c = anchor
    c0 = min(max(c - 2, 0), SIZE - 6)
    return [(r, cc) for cc in range(c0, c0 + 6)]
