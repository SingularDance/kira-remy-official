# -*- coding: utf-8 -*-
"""
星海战棋 - 纯规则模块（不 import Qt，可单测）

把「棋盘、舰体目录、舰队生成、布阵、弱点/特性、命中结算、区域工具」这些纯逻辑
从 UI 里抽出来，胜负判定全部本地确定性执行；UI 层只负责渲染与交互。

规则要点：
- 10x10 棋盘，坐标 A1-J10。
- 双方各 6 类舰体，各有固定形状与固定弱点；弱点随旋转一起转，每艘初始恰 1 个弱点。
  - 「第一格」弱点：直线/方形类舰体，弱点在 cell 列表首格。
  - 「顶点」弱点：指挥舰（干/T）与 AI 旗舰（士）在竖直主干**底端**；玩家旗舰（十字）在上方短柄**顶端**。
- 部位分「弱点 / 普通」两种：命中弱点立即击毁；命中普通只累计，打光全部格子也击毁。
- 特性可动态加弱点（弱点+N）或消除弱点；护卫舰的弱点不可被外部消除。
- 舰队：AI 3~6 艘（必含指挥舰+旗舰）、玩家 6~9 艘（指挥舰、旗舰二选一）；
  总格数只是上限（AI ≤33、玩家 ≤22），舰体类型在各上限内随机分配。
"""

import random

SIZE = 10

# 部位语义（弱点是每艘船上的一个集合）
WEAK = "weak"
NORMAL = "normal"

# 四向偏移（仅用于「接壤」判定，无优先级）
FOUR_DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1)]

# 护卫舰消除邻舰弱点的优先方向
DIR_ORDER_AI = [(-1, 0), (1, 0), (0, -1), (0, 1)]      # 上 → 下 → 左 → 右
DIR_ORDER_PLAYER = [(-1, 0), (1, 0), (0, 1), (0, -1)]  # 上 → 下 → 右 → 左

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
        {"key": "scout", "name": "侦察梭", "trait_name": "孤勇",
         "cells": [(0, 0), (0, 1)], "weak_index": 0, "rot_k": [0, 1], "max_count": 3,
         "trait": "孤勇：场上仅自身存活时，蕾咪下回合1发炮击变为[激光炮击α]。",
         "trait_short": "唯一存活时，炮击变为[激光α]"},
        {"key": "frigate", "name": "护卫舰", "trait_name": "护佑",
         "cells": [(0, 0), (0, 1), (1, 0), (1, 1)], "weak_index": 0, "rot_k": [0], "max_count": 3,
         "trait": "护佑：自身弱点无法被消除，当自身接壤时，使自身弱点+3，并消除所接壤舰体的弱点。",
         "trait_short": "接壤时消除邻舰弱点，自身弱点+3"},
        {"key": "assault", "name": "突击舰", "trait_name": "藏匿",
         "cells": [(0, 0), (0, 1), (0, 2)], "weak_index": 0, "rot_k": [0, 1], "max_count": 3,
         "trait": "藏匿：当自身孤立时，消除自身弱点。",
         "trait_short": "孤立时消除自身弱点"},
        {"key": "destroyer", "name": "驱逐舰", "trait_name": "荣光",
         "cells": [(0, 0), (0, 1), (0, 2), (0, 3)], "weak_index": 0, "rot_k": [0, 1], "max_count": 2,
         "trait": "荣光：坠毁时，蕾咪下回合1发炮击变为[激光炮击β]。",
         "trait_short": "坠毁时，下回合1发炮击变[激光β]"},
        {"key": "command", "name": "指挥舰", "trait_name": "指引",
         # 干字形 9 格：顶横 3 + 中横 3 + 竖 5；弱点在竖笔底端 (4,1)
         "cells": [(0, 0), (0, 1), (0, 2), (1, 1), (2, 0), (2, 1), (2, 2), (3, 1), (4, 1)],
         "weak_index": 8, "rot_k": [0], "max_count": 1,
         "trait": "指引：存活时，蕾咪每回合炮击次数+1。坠毁时：消除己方所有舰体的弱点。",
         "trait_short": "存活时每回合炮击+1；坠毁消除己方弱点"},
        {"key": "flagship", "name": "旗舰", "trait_name": "流星",
         # 士字形 11 格：顶长横 5 + 底短横 3 + 竖 5；弱点在竖笔底端 (4,2)
         "cells": [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4), (1, 2), (2, 2),
                   (3, 1), (3, 2), (3, 3), (4, 2)],
         "weak_index": 10, "rot_k": [0], "max_count": 1,
         "trait": "流星：存活时，蕾咪每回合炮击次数+1。坠毁时：蕾咪下回合所有炮击变为[相位炮击γ]。",
         "trait_short": "存活时每回合炮击+1；坠毁全部炮击变[相位γ]"},
    ],
    "player": [
        {"key": "scout", "name": "侦察梭", "trait_name": "斥候",
         "cells": [(0, 0)], "weak_index": 0, "rot_k": [0], "max_count": 3,
         "trait": "斥候：场上仅自身存活时，我方每回合炮击次数+1。坠毁时：我方获得1发[扫描]。",
         "trait_short": "唯一存活时每回合炮击+1；坠毁获得[扫描]"},
        {"key": "frigate", "name": "护卫舰", "trait_name": "防卫",
         "cells": [(0, 0), (0, 1)], "weak_index": 0, "rot_k": [0, 1], "max_count": 3,
         "trait": "防卫：自身弱点无法被消除，当自身与其他舰体接壤时，使自身弱点+1，并消除所接壤舰体的弱点。坠毁时：我方获得1发[扫描]。",
         "trait_short": "接壤时消除邻舰弱点，自身弱点+1"},
        {"key": "assault", "name": "突击舰", "trait_name": "绝命",
         "cells": [(0, 0), (0, 1), (0, 2)], "weak_index": 0, "rot_k": [0, 1], "max_count": 3,
         "trait": "绝命：击坠时，我方获得一发[齐射]，然后使自身弱点+1。",
         "trait_short": "击毁敌舰时获得[齐射]，自身弱点+1"},
        {"key": "destroyer", "name": "驱逐舰", "trait_name": "强袭",
         "cells": [(0, 0), (0, 1), (0, 2), (0, 3)], "weak_index": 0, "rot_k": [0, 1], "max_count": 2,
         "trait": "强袭：当自身接壤时，我方获得1发[激光炮击α]。当自身孤立时，我方获得1发[激光炮击β]。",
         "trait_short": "接壤获得[激光α]，孤立获得[激光β]"},
        {"key": "command", "name": "指挥舰", "trait_name": "计策",
         # T 字形 6 格：顶横 3 + 竖 4；弱点在竖笔底端 (3,1)
         "cells": [(0, 0), (0, 1), (0, 2), (1, 1), (2, 1), (3, 1)],
         "weak_index": 5, "rot_k": [0], "max_count": 1,
         "trait": "计策：我方初始额外获得1发[相位扫描θ]。我方每回合可使用道具次数+1。",
         "trait_short": "初始获得[相位θ]；每回合道具次数+1"},
        {"key": "flagship", "name": "旗舰", "trait_name": "女神",
         # 十字形 6 格：横 3 + 竖 4；弱点在上方短柄顶端 (0,1)
         "cells": [(0, 1), (1, 0), (1, 1), (1, 2), (2, 1), (3, 1)],
         "weak_index": 0, "rot_k": [0], "max_count": 1,
         "trait": "女神：我方初始额外获得1发[相位炮击γ]。击坠时：每回合限一次，我方可再次进行一次炮击。",
         "trait_short": "初始获得[相位γ]；击毁敌舰可再炮击一次"},
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

def _valid_fleets(bag, ship_count, mandatory, max_cells, side):
    """枚举袋内所有「额外舰体」子集：额外数量 == ship_count - len(mandatory)、
    加上 mandatory 后总格数 ≤ max_cells。返回合法额外舰体列表。"""
    n = len(bag)
    need = ship_count - len(mandatory)
    valid = []
    for mask in range(1 << n):
        if bin(mask).count("1") != need:
            continue
        subset = [bag[i] for i in range(n) if (mask >> i) & 1]
        total = sum(SHIP_TYPES[side][k]["size"] for k in mandatory + subset)
        if total <= max_cells:
            valid.append(subset)
    return valid


def draw_ship_count(rng=None):
    """本局 AI 方舰体总数：从 3~6 中随机抽取。"""
    rng = rng or random
    return rng.randint(3, 6)


def player_ship_count_for(ai_count):
    """对应关系：AI 3/4/5/6 艘 → 玩家 6/7/8/9 艘。"""
    return ai_count + 3


def generate_fleet(side, rng=None, ship_count=None):
    """随机生成一方舰队（返回舰体 key 列表）。

    - 舰体数：AI 3~6（必含 指挥舰+旗舰）；玩家 6~9（指挥舰、旗舰二选一）。
    - 总格数只是上限（AI ≤33、玩家 ≤22），不要求填满。
    - 舰体类型在各自上限（max_count）内随机分配。
    """
    rng = rng or random
    if ship_count is None:
        ship_count = draw_ship_count(rng) if side == "ai" \
            else player_ship_count_for(draw_ship_count(rng))
    max_cells = 33 if side == "ai" else 22
    if side == "ai":
        mandatory = ["command", "flagship"]
    else:
        mandatory = [rng.choice(["command", "flagship"])]
    bag = (["scout"] * 3 + ["frigate"] * 3
           + ["assault"] * 3 + ["destroyer"] * 2)
    subs = _valid_fleets(bag, ship_count, mandatory, max_cells, side)
    if not subs:
        raise RuntimeError(f"无法为 {side} 生成合法舰队（{ship_count} 艘）")
    fleet = mandatory + list(rng.choice(subs))
    rng.shuffle(fleet)
    return fleet


def place_fleet(side, fleet, rng=None):
    """在 10x10 上随机不重叠布阵，返回 (board, ships)。

    board[r][c] 为舰体编号（1-based，0 表示空）。
    ships 每项：type/name/color/cells/weak_cells/hits/alive（按 fleet 原顺序返回）。
    弱点按类型固定位置随旋转映射；入场特性（护卫舰护佑、突击舰藏匿）由
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
    """消除一艘舰体的全部弱点。护卫舰的弱点不可被消除、无弱点时返回 False。"""
    if ship["type"] == "frigate" or not ship["weak_cells"]:
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


def frigate_protect(ship, ships, dir_order, gain):
    """护卫舰护佑：按 dir_order 找一艘可消除弱点的邻舰，消除其弱点并使自身弱点 +gain。

    返回被护佑的邻舰（无则 None）。
    """
    for dr, dc in dir_order:
        for r, c in ship["cells"]:
            other = ship_at(ships, (r + dr, c + dc))
            if other is None or other is ship:
                continue
            if eliminate_weak_points(other):
                add_weak_points(ship, gain)
                return other
    return None


def apply_deploy_traits(ships, side):
    """入场特性（开局一次），返回事件文本列表。

    AI：护卫舰护佑（+3，上→下→左→右）；突击舰藏匿（孤立则消除自身弱点）。
    玩家：护卫舰防卫（+1，上→下→右→左）。
    """
    events = []
    if side == "ai":
        dir_order = DIR_ORDER_AI
        gain = 3
    else:
        dir_order = DIR_ORDER_PLAYER
        gain = 1

    for s in ships:
        if s["type"] == "frigate" and s["alive"]:
            other = frigate_protect(s, ships, dir_order, gain)
            if other is not None:
                events.append(f"{s['name']}护佑了{other['name']}，自身弱点+{gain}")
    if side == "ai":
        for s in ships:
            if s["type"] == "assault" and s["alive"]:
                if not has_adjacent_ship(s, ships):
                    s["weak_cells"].clear()
                    events.append(f"{s['name']}藏匿：消除自身弱点")
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
    """AI 舰体坠毁触发的特殊炮击：驱逐舰→激光β；旗舰→相位γ（所有炮击）；其余→None。"""
    if ship["type"] == "destroyer":
        return "laser_row"
    if ship["type"] == "flagship":
        return "phase_3x3_all"
    return None


def command_eliminate_on_destroy(ships):
    """AI 指挥舰坠毁：消除己方所有舰体弱点（护卫舰除外），返回事件文本。"""
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

    shots 为攻击方的已炮击集合（会被更新）；返回 (events, destroyed_ships)。
    """
    events = []
    destroyed = []
    for p in cells:
        if p in shots:
            continue
        shots.add(p)
        ship = ship_at(ships, p)
        if ship is None:
            events.append(f"{fmt(p)}落空")
            continue
        destroyed_now, _hit_weak = hit_cell(ship, p)
        if destroyed_now:
            if ship not in destroyed:
                destroyed.append(ship)
            shots.update(ship["cells"])  # 击毁后整舰格子视为已炮击
            events.append(f"击毁{ship['name']}！")
        else:
            events.append(f"命中{ship['name']}！")
    if not events:
        events.append("落空")
    return events, destroyed


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


def line_4_vertical(anchor):
    """以 anchor 为锚的竖直 4 格直线（越界时夹回棋盘内）。"""
    r, c = anchor
    r0 = min(max(r - 1, 0), SIZE - 4)
    return [(rr, c) for rr in range(r0, r0 + 4)]


def line_4_horizontal(anchor):
    """以 anchor 为锚的水平 4 格直线（越界时夹回棋盘内）。"""
    r, c = anchor
    c0 = min(max(c - 1, 0), SIZE - 4)
    return [(r, cc) for cc in range(c0, c0 + 4)]
