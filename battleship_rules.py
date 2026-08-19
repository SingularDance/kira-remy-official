# -*- coding: utf-8 -*-
"""
星海战棋 - 纯规则模块（不 import Qt，可单测）

与 community_wallpaper.py / music_monitor.py 同一套纪律：把「棋盘、舰体目录、
舰队生成、布阵、弱点/特性、命中结算、区域工具」这些纯逻辑从 UI 里抽出来，
胜负判定全部本地确定性执行；UI 层只负责渲染与交互。

规则要点（已与用户对齐）：
- 9x9 棋盘，坐标 A1-I9。
- 六类舰体，各有固定形状与固定弱点；弱点随旋转一起转，每艘恰好 1 个弱点。
- 命中弱点 → 立即击毁；命中普通 → 只累计，打光全部格子也击毁。
- 舰队：双方随机生成——总格数 13、每类上限、舰体总数 >=4。
- 部位只有「弱点 / 普通」两种。
"""

import re

SIZE = 9
MAX_TOTAL_CELLS = 13
MIN_SHIPS = 4

# 部位常量
WEAK = "weak"
NORMAL = "normal"

# 护卫舰转移弱点时，多艘接壤的优先方向：上 → 下 → 右 → 左
DIR_ORDER = [(-1, 0), (1, 0), (0, 1), (0, -1)]

# 四向偏移（无优先级顺序，用于接壤判定）
FOUR_DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1)]


# ============================================================
#  舰体目录
# ============================================================
# 每类的 cells 是「规范朝向」下的相对偏移（含锚点，锚点在左上角最小处）；
# weak_index 指向 cells 里的弱点格；rot_k 是允许的旋转次数（0/90/180/270）。
# 弱点随 cells 一起旋转，保证「第一格/中心/端点/底边中心/顶点」这类方向性
# 弱点在旋转后仍落在正确的位置上。
SHIP_DEFS = [
    {
        "key": "scout",
        "name": "侦察梭",
        "cells": [(0, 0)],
        "weak_index": 0,
        "max_count": 2,
        "rot_k": [0],
        "trait": "存活时：若侦察梭是我方最后存活的一类舰体，只触发一次——本回合炮击变为激光齐射α（攻击一竖排）。",
    },
    {
        "key": "frigate",
        "name": "护卫舰",
        "cells": [(0, 0), (0, 1)],
        "weak_index": 0,
        "max_count": 2,
        "rot_k": [0, 1],
        "trait": "入场时：与邻舰接壤则转移邻舰 1 个弱点至自身（两格皆弱点）；坠毁时弱点回原处。",
    },
    {
        "key": "assault",
        "name": "突击舰",
        "cells": [(0, 0), (0, 1), (0, 2)],
        "weak_index": 1,
        "max_count": 2,
        "rot_k": [0, 1],
        "trait": "入场时：无舰体接壤且不贴地图边界时，消除自身弱点。",
    },
    {
        "key": "destroyer",
        "name": "驱逐舰",
        "cells": [(0, 0), (0, 1), (0, 2), (0, 3)],
        "weak_index": 0,
        "max_count": 1,
        "rot_k": [0, 1],
        "trait": "坠毁时：下回合炮击变为激光齐射β（攻击一横排）。",
    },
    {
        "key": "command",
        "name": "指挥舰",
        # T 型：顶边 3 格 + 向下主干 2 格；弱点在主干底端（T 字底边中心）
        "cells": [(0, 0), (0, 1), (0, 2), (1, 1), (2, 1)],
        "weak_index": 4,
        "max_count": 1,
        "rot_k": [0, 1, 2, 3],
        "trait": "存活时：每击沉敌方 1 艘舰体，我方获得 1 个扫描道具（最多因此获得 2 个）。",
    },
    {
        "key": "flagship",
        "name": "旗舰",
        # 长柄十字：横 3 + 竖 4，共 6 格；弱点在十字顶点（长柄顶端）
        "cells": [(0, 1), (1, 1), (2, 0), (2, 1), (2, 2), (3, 1)],
        "weak_index": 0,
        "max_count": 1,
        "rot_k": [0],
        "trait": "坠毁时：下回合炮击变为齐射3（3×3 区域齐射）。",
    },
]


def _rotate(cells, k):
    """把一组相对偏移顺时针旋转 k*90 度并重新归一到左上角。"""
    out = cells
    for _ in range(k % 4):
        out = [(c, -r) for r, c in out]
    min_r = min(r for r, _ in out)
    min_c = min(c for _, c in out)
    return [(r - min_r, c - min_c) for r, c in out]


def _build_ship_types():
    """把 SHIP_DEFS 展开成运行时要用的 SHIP_TYPES 表（含旋转变体）。"""
    table = {}
    for d in SHIP_DEFS:
        rotations = []
        for k in d["rot_k"]:
            cells = _rotate(d["cells"], k)
            weak_cells = {cells[d["weak_index"]]}
            rotations.append({"cells": cells, "weak_cells": weak_cells})
        table[d["key"]] = {
            "key": d["key"],
            "name": d["name"],
            "size": len(d["cells"]),
            "max_count": d["max_count"],
            "trait": d["trait"],
            "cells": d["cells"],
            "weak_cell": d["cells"][d["weak_index"]],
            "rotations": rotations,
        }
    return table


SHIP_TYPES = _build_ship_types()
SHIP_ORDER = [d["key"] for d in SHIP_DEFS]

# 舰队生成用的「可用舰体袋」：按每类上限展开
_BAG = []
for _d in SHIP_DEFS:
    for _ in range(_d["max_count"]):
        _BAG.append(_d["key"])


def all_valid_fleets():
    """枚举所有合法舰队（总格数 13、舰体数 >=4、每类不超过上限）。"""
    valid = []
    n = len(_BAG)
    for mask in range(1 << n):
        fleet = [_BAG[i] for i in range(n) if (mask >> i) & 1]
        if len(fleet) < MIN_SHIPS:
            continue
        if sum(SHIP_TYPES[k]["size"] for k in fleet) != MAX_TOTAL_CELLS:
            continue
        valid.append(fleet)
    return valid


_VALID_FLEETS = all_valid_fleets()


def generate_fleet(rng=None):
    """随机生成一方的舰队（返回舰体 key 列表，顺序随机）。"""
    rng = rng or __import__("random")
    fleet = list(rng.choice(_VALID_FLEETS))
    rng.shuffle(fleet)
    return fleet


# ============================================================
#  布阵
# ============================================================

def place_fleet(fleet, rng=None):
    """在 9x9 上随机不重叠布阵，返回 (board, ships)。

    board[r][c] 为舰体编号（1-based，0 表示空）。
    ships 每项：type/name/cells/weak_cells/hits/alive/transfer。
    弱点按类型固定位置随旋转映射；入场特性（护卫舰转移、突击舰消除）
    不在这里做，由 apply_deploy_traits 单独调用。
    """
    rng = rng or __import__("random")
    board = [[0] * SIZE for _ in range(SIZE)]
    ships = []
    for i, key in enumerate(fleet):
        t = SHIP_TYPES[key]
        placed = False
        for _ in range(500):
            variant = rng.choice(t["rotations"])
            r = rng.randrange(SIZE)
            c = rng.randrange(SIZE)
            cells = [(r + dr, c + dc) for dr, dc in variant["cells"]]
            if all(0 <= rr < SIZE and 0 <= cc < SIZE and board[rr][cc] == 0
                   for rr, cc in cells):
                for rr, cc in cells:
                    board[rr][cc] = i + 1
                ships.append({
                    "type": key,
                    "name": t["name"],
                    "cells": cells,
                    "weak_cells": {(r + dr, c + dc)
                                   for dr, dc in variant["weak_cells"]},
                    "hits": set(),
                    "alive": True,
                    "transfer": None,
                })
                placed = True
                break
        if not placed:
            raise RuntimeError(f"无法为 {t['name']} 找到落点（81 格几乎不会发生）")
    return board, ships


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
    for r, c in ship["cells"]:
        for dr, dc in FOUR_DIRS:
            other = ship_at(ships, (r + dr, c + dc))
            if other is not None and other is not ship:
                return True
    return False


def touches_boundary(ship):
    return any(r == 0 or r == SIZE - 1 or c == 0 or c == SIZE - 1
               for r, c in ship["cells"])


def frigate_transfer(frigate, ships):
    """护卫舰入场特性：按 上→下→右→左 找邻舰，转移其 1 个弱点到自身。

    成功返回 True，并把来源记录写入 frigate["transfer"] 供坠毁时回补。
    """
    for dr, dc in DIR_ORDER:
        for r, c in frigate["cells"]:
            other = ship_at(ships, (r + dr, c + dc))
            if other is None or other is frigate or not other["weak_cells"]:
                continue
            src_cell = sorted(other["weak_cells"])[0]
            other["weak_cells"].discard(src_cell)
            # 弱点落到护卫舰当前的非弱点格（默认第二格），两格皆成弱点
            for cell in frigate["cells"]:
                if cell not in frigate["weak_cells"]:
                    frigate["weak_cells"].add(cell)
                    frigate["transfer"] = {"source": other, "source_cell": src_cell}
                    return True
    return False


def restore_frigate_weak(frigate):
    """护卫舰坠毁：把转移走的弱点回补到来源舰。"""
    t = frigate.get("transfer")
    if t:
        t["source"]["weak_cells"].add(t["source_cell"])
        frigate["transfer"] = None


def apply_deploy_traits(ships):
    """入场特性（开局一次）：先护卫舰转移弱点，再突击舰消除弱点。"""
    for s in ships:
        if s["type"] == "frigate" and s["alive"]:
            frigate_transfer(s, ships)
    for s in ships:
        if s["type"] == "assault" and s["alive"]:
            if not has_adjacent_ship(s, ships) and not touches_boundary(s):
                s["weak_cells"].clear()


def last_surviving_type(ships):
    """返回「唯一存活舰体类型」，若没有存活或多类存活则返回 None。"""
    alive = [s["type"] for s in ships if s["alive"]]
    if not alive:
        return None
    first = alive[0]
    return first if all(t == first for t in alive) else None


def scout_alpha_active(ships):
    """侦察梭存活特性：若侦察梭是最后存活的一类，则本回合可用激光齐射α。"""
    return last_surviving_type(ships) == "scout"


def has_alive_command(ships):
    """指挥舰存活特性前置：是否存在存活的指挥舰。"""
    return any(s["type"] == "command" and s["alive"] for s in ships)


def special_shot_on_destroy(ship):
    """坠毁特性：驱逐舰→激光齐射β；旗舰→齐射3；其余→None。"""
    if ship["type"] == "destroyer":
        return "beta"
    if ship["type"] == "flagship":
        return "volley3"
    return None


def infer_weak_targets(alive_types, known_has, blocked):
    """从「仍存活的敌方舰型 + 已知有舰/无舰格子」推断候选弱点格。

    alive_types: 仍存活敌舰的 type 列表（如 ["command", "scout"]）。
    known_has:   已知「属于存活舰体」的格子集合（扫描含舰 / 命中未击毁）。
    blocked:     不可能再放存活舰体的格子集合（扫描空 / 落空 / 已坠毁舰体格子）。

    对每种舰型的每个旋转×放置：若放置不落在 blocked 上、且至少一格落在 known_has 上
    （有证据支撑，非凭空猜），则把该放置的弱点格计入候选。返回 {弱点格: 支持放置数}。
    """
    counts = {}
    for key in alive_types:
        for variant in SHIP_TYPES[key]["rotations"]:
            cells = variant["cells"]
            weak = variant["weak_cells"]
            max_dr = SIZE - 1 - max(r for r, _ in cells)
            max_dc = SIZE - 1 - max(c for _, c in cells)
            for dr in range(max_dr + 1):
                for dc in range(max_dc + 1):
                    abs_cells = [(r + dr, c + dc) for r, c in cells]
                    if any(p in blocked for p in abs_cells):
                        continue
                    if not any(p in known_has for p in abs_cells):
                        continue
                    for wr, wc in weak:
                        w = (wr + dr, wc + dc)
                        counts[w] = counts.get(w, 0) + 1
    return counts


# ============================================================
#  命中结算
# ============================================================

def hit_cell(ship, cell):
    """命中 ship 的一个格子。返回 (destroyed_now, hit_weak)。"""
    ship["hits"].add(cell)
    if cell in ship["weak_cells"]:
        return True, True
    if all(c in ship["hits"] for c in ship["cells"]):
        return True, False
    return False, False


def is_destroyed(ship):
    if not ship["alive"]:
        return True
    return any(c in ship["hits"] for c in ship["weak_cells"]) or \
        all(c in ship["hits"] for c in ship["cells"])


def resolve_hits(ships, shots, cells):
    """对一组格子结算命中（普通/特殊/齐射共用）。

    返回 (events, destroyed_ships)：events 为文本列表，destroyed_ships 为本轮
    新击毁的舰体（供坠毁特性、点亮侧栏、爆炸动效使用）。
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
            ship["alive"] = False
            destroyed.append(ship)
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
    """从文本里解析一个 9x9 坐标（A1-I9），失败返回 None。"""
    m = re.search(r"([A-Ia-i])\s*[- ]?\s*([1-9])(?!\d)", text)
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
