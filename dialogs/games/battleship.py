# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 星海战棋小游戏（LLM 驱动）

9x9 星域对局：双方各一支由星际舰体组成的舰队（随机生成，总 13 格、每类上限、
舰体数 >=4）。六类舰体各有固定形状与固定弱点；命中弱点立即击毁，命中普通只累计，
打光该舰全部格子也击毁。玩家有扫描/齐射道具各 3 发（2x2 范围）；蕾咪（AI）无道具，
每局改为从「追击/扫射/爆发」中随机获得一个全局增益。并有特殊炮击
（激光齐射α竖排 / 激光齐射β横排 / 齐射3 3x3）由舰体特性触发。

胜负判定全部本地确定性执行（规则在顶层 battleship_rules.py，可单测）；
LLM 负责解说吐槽与蕾咪的战术决策，失败时回退本地 AI 与内置台词，游戏永不卡死。
结算时揭示蕾咪的完整布阵，并把战报推送到主聊天窗口。

每局维护独立的对话上下文（随对话框销毁，不污染主聊天历史），人设提示词运行时
引用 config.get_system_prompt()。
"""

import math
import random
import re
import threading

import requests
from PyQt5.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout,
    QPushButton, QWidget, QGridLayout, QMessageBox, QGraphicsColorizeEffect,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QPropertyAnimation, QRectF, QPointF
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QPolygonF, QFont, QPainterPath, QLinearGradient

import config
import battleship_rules as rules
from thinking import apply_thinking_request

SIZE = rules.SIZE

BATTLE_RULES = """
---
你正在和调查员玩星海战棋（9x9 星域，坐标 A1-I9，如 B5）。
每方有一支星际舰队；击毁对方全部舰体即获胜。

【舰体】六类，各有固定形状与固定弱点（命中弱点即整舰击毁；命中普通格只累计损伤，打光该舰全部格子也击毁）：
- 侦察梭（1格）：弱点在自身那一格。特性：若侦察梭是我方最后存活的一类舰体，只触发一次——本回合炮击变为激光齐射α（攻击一竖排）。
- 护卫舰（2格直线）：弱点在第一格。特性：入场接壤时转移邻舰 1 个弱点到自身。
- 突击舰（3格直线）：弱点在中心格。特性：入场无接壤且不贴边时消除自身弱点。
- 驱逐舰（4格直线）：弱点在一端。特性：坠毁时下回合炮击变为激光齐射β（攻击一横排）。
- 指挥舰（5格T型）：弱点在T字底边中心。特性：存活时每击沉敌方 1 艘舰体，我方获得 1 个扫描道具（最多因此获得 2 个）。
- 旗舰（6格长柄十字，横3竖4）：弱点在十字顶点。特性：坠毁时下回合炮击变为齐射3（3x3区域）。

【道具】你（蕾咪）本局没有扫描/齐射道具；对手（调查员）有扫描/齐射各 3 发（2x2 范围）。每回合必须炮击一次。
【特殊炮击】激光齐射α（一竖排）、激光齐射β（一横排）、齐射3（3x3）。特殊炮击代替当回合普通炮击。

你没有道具可用，专注炮击与特殊炮击即可。

简报会告诉你双方剩余舰体、你本回合可用的特殊炮击。严格按以下四行格式输出，不要输出任何其他内容：
【反应】一句话傲娇回应调查员刚才的行动
【道具】无
【开炮】你的炮击坐标，或特殊炮击（如：激光齐射α 竖排 B / 激光齐射β 横排 3 / 齐射3 C4）
【狠话】一句话开炮狠话"""

LOCAL_HIT_REACTIONS = [
    "呜…居然打中了蕾咪的星舰！你、你给我等着！",
    "哼，运气好而已！下次就没这么走运了！",
    "竟、竟然命中了…蕾咪才没有慌呢！",
]
LOCAL_MISS_REACTIONS = [
    "噗…打偏了哦？调查员的准头不太行呢～",
    "哼，就这种水平还想打中蕾咪的舰队？",
    "落空啦！蕾咪的星舰可没那么好找！",
]
LOCAL_SUNK_REACTIONS = [
    "我、我的{name}…！你完蛋了！蕾咪要认真了！",
    "呜哇！{name}被击毁了…这仇一定要报！",
]
LOCAL_TAUNTS = [
    "吃蕾咪一炮！",
    "哼哼，蕾咪的直觉可是很准的！",
    "这一炮，可不会落空哦！",
    "让你见识一下舰长的实力！",
]
LOCAL_WIN_LINE = "呜…蕾咪输了…才、才不是让着你的！下次一定赢回来！"
LOCAL_LOSE_LINE = "看到了吗！这就是阿斯忒瑞亚号舰长的实力！哼哼～"

SUMMARY_PROMPT = (
    "对局结束：{result}，共进行了{rounds}个回合。\n"
    "用两三句话向调查员复盘这场星海战棋，保持你的个性，"
    "这是发到主聊天窗口的战报，直接输出文本，不要任何格式标记。"
)

# 特殊炮击的中文名（UI / 简报 / 狠话复用）
SPECIAL_NAMES = {
    "alpha": "激光齐射α（竖排）",
    "beta": "激光齐射β（横排）",
    "volley3": "齐射3（3x3）",
}

# 蕾咪 PvE 全局增益：每局开始前从 3 个中随机挑 1 个（互斥，不叠加）
BUFFS = ["追击", "扫射", "爆发"]
BUFF_DESC = {
    "追击": "命中我方舰体时，当回合追加一次 2×2 范围炮击（每回合至多一次）。",
    "扫射": "每 4 回合自动发动一次横排/竖排激光（瞄准已知舰体），发动前一回合在目标行/列显示红色预警线。",
    "爆发": "开局前 3 回合的炮击强化为 3×3 齐射。",
}
# 侧栏徽章用的短说明（窄栏放不下完整 BUFF_DESC）
BUFF_SHORT = {
    "追击": "命中后追加 2×2",
    "扫射": "每 4 回合激光",
    "爆发": "前 3 回合齐射3",
}

# 图鉴里对每类舰体弱点位置的文字说明
WEAK_DESC = {
    "scout": "自身那一格",
    "frigate": "第一格",
    "assault": "中心格",
    "destroyer": "一个端点",
    "command": "T 字底边中心",
    "flagship": "十字顶点",
}

# 每类舰体的专属颜色（让六类舰体一眼可辨，避免与弱点橙色 #F5A623 撞色）
SHIP_COLORS = {
    "scout": "#43A047",      # 侦察梭 绿
    "frigate": "#4A6FA5",    # 护卫舰 蓝
    "assault": "#D94A4A",    # 突击舰 红
    "destroyer": "#8E6BC0",  # 驱逐舰 紫
    "command": "#0FA3B1",    # 指挥舰 青
    "flagship": "#C05A8A",   # 旗舰 玫红
}


def ship_color(key):
    return SHIP_COLORS.get(key, "#4A6FA5")


# 特性生效时的播报文案（键为舰体类型或存活特性标记）
DEPLOY_TEXT = {
    "frigate": "护卫舰特性【入场】生效：转移邻舰 1 个弱点至自身",
    "assault": "突击舰特性【入场】生效：消除自身弱点",
}
SURVIVAL_TEXT = {
    "scout_alpha": "侦察梭特性【存活】生效（只触发一次）：本回合炮击变为激光齐射α（竖排）",
}


# ============================================================
#  舰体剪影绘制（连体剪影 + 六边形弱点）
# ============================================================

def _draw_hexagon(p, cx, cy, radius, color):
    pts = []
    for k in range(6):
        a = math.pi / 6 + k * math.pi / 3
        pts.append(QPointF(cx + radius * math.cos(a), cy + radius * math.sin(a)))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawPolygon(QPolygonF(pts))


def _cell_silhouette(x, y, cell, up, down, left, right):
    """返回一个格子的连体剪影路径（绝对坐标 (x,y)、边长 cell）。

    与同舰相邻的边铺满到格边（不内缩），自由边内缩 cell*0.22；角仅在
    「相邻两边不全连通」时圆角。这样相邻格子共享边、填充后自然连成一整艘舰。
    """
    r = cell * 0.26
    L = x if left else x + r
    R = x + cell if right else x + cell - r
    T = y if up else y + r
    B = y + cell if down else y + cell - r
    tl = not (up and left)
    tr = not (up and right)
    br = not (down and right)
    bl = not (down and left)

    path = QPainterPath()
    path.moveTo(L + (r if tl else 0.0), T)
    if tr:
        path.lineTo(R - r, T)
        path.arcTo(R - 2 * r, T, 2 * r, 2 * r, 90.0, -90.0)
    else:
        path.lineTo(R, T)
    if br:
        path.lineTo(R, B - r)
        path.arcTo(R - 2 * r, B - 2 * r, 2 * r, 2 * r, 0.0, -90.0)
    else:
        path.lineTo(R, B)
    if bl:
        path.lineTo(L + r, B)
        path.arcTo(L, B - 2 * r, 2 * r, 2 * r, 270.0, -90.0)
    else:
        path.lineTo(L, B)
    if tl:
        path.lineTo(L, T + r)
        path.arcTo(L, T, 2 * r, 2 * r, 180.0, -90.0)
    else:
        path.lineTo(L, T)
    path.closeSubpath()
    return path


def _draw_ship_fill(p, path, color, rect):
    """给舰体剪影填渐变 + 深色描边，做出立体感（rect 决定渐变方向）。"""
    base = QColor(color)
    grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    grad.setColorAt(0.0, base.lighter(120))
    grad.setColorAt(0.55, base)
    grad.setColorAt(1.0, base.darker(125))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(grad))
    p.drawPath(path)
    p.setPen(QPen(base.darker(160), 1.3))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)


def paint_ship_shape(p, cells, weak_cells, ox, oy, cell, color, weak_color):
    """在 painter 上从 (ox,oy) 起、按 cell 大小绘制连体剪影 + 弱点六边形。"""
    cs = set(cells)
    weak = set(weak_cells)
    path = QPainterPath()
    for (r, c) in cells:
        x = ox + c * cell
        y = oy + r * cell
        sub = _cell_silhouette(
            x, y, cell,
            up=(r - 1, c) in cs, down=(r + 1, c) in cs,
            left=(r, c - 1) in cs, right=(r, c + 1) in cs,
        )
        path = path.united(sub)
    _draw_ship_fill(p, path, color, path.boundingRect())
    for (r, c) in weak:
        x = ox + c * cell
        y = oy + r * cell
        _draw_hexagon(p, x + cell * 0.72, y + cell * 0.28, cell * 0.22, weak_color)


class ShipShapeWidget(QWidget):
    """单个舰体的剪影小部件（图鉴 / 侧边栏复用）。"""

    def __init__(self, cells, weak_cells, color="#4A6FA5", weak_color="#F5A623",
                 cell_size=20, parent=None):
        super().__init__(parent)
        self.cells = list(cells)
        self.weak_cells = set(weak_cells)
        self.color = color
        self.weak_color = weak_color
        self.cell_size = cell_size
        rows = max(r for r, _ in cells) + 1 if cells else 1
        cols = max(c for _, c in cells) + 1 if cells else 1
        self.setFixedSize(cols * cell_size + 6, rows * cell_size + 6)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        paint_ship_shape(p, self.cells, self.weak_cells, 3, 3,
                         self.cell_size, self.color, self.weak_color)
        p.end()


def ship_canonical(key):
    t = rules.SHIP_TYPES[key]
    return t["cells"], {t["weak_cell"]}


# ============================================================
#  单元格按钮（自定义绘制）
# ============================================================

class CellButton(QPushButton):
    CELL = 32

    BG = {
        "sea": "#DCEBF5", "ship": "#2E3A59", "empty": "#F2F6F9",
        "miss": "#EAF0F4", "sunk": "#C0392B", "scan_empty": "#E6DDF2",
        "scan_ship": "#F2C4D8", "reveal": "#2E3A59", "disabled": "#DCEBF5",
    }
    FG = {
        "sea": "#DCEBF5", "ship": "#FFFFFF", "empty": "#F2F6F9",
        "miss": "#7AA5B8", "sunk": "#FFFFFF", "scan_empty": "#8A7AA5",
        "scan_ship": "#A03070", "reveal": "#FFFFFF", "disabled": "#DCEBF5",
    }
    TEXT = {
        "sea": "", "ship": "", "empty": "", "miss": "○", "sunk": "✕",
        "scan_empty": "·", "scan_ship": "⚑", "reveal": "", "disabled": "",
    }

    def __init__(self, row, col, click_handler=None, hover_handler=None):
        super().__init__()
        self.row = row
        self.col = col
        self.setFixedSize(self.CELL, self.CELL)
        self.setCursor(Qt.PointingHandCursor)
        self.base = "sea"
        self.weak = False
        self.up = self.down = self.left = self.right = False
        self.ship_color = "#4A6FA5"
        self.destroyed = False
        self.preview = False
        self.highlight = False
        self.warning = False
        if click_handler:
            self.clicked.connect(
                lambda checked, r=row, c=col: click_handler(r, c))
        self._hover_handler = hover_handler
        self._apply()

    def set_state(self, state):
        self.base = state
        self.weak = False
        self.destroyed = False
        self.up = self.down = self.left = self.right = False
        self.highlight = False
        self.warning = False
        self._apply()

    def set_ship(self, weak=False, up=False, down=False, left=False, right=False,
                 color="#4A6FA5", destroyed=False):
        self.base = "ship"
        self.weak = weak
        self.up = up
        self.down = down
        self.left = left
        self.right = right
        self.ship_color = color
        self.destroyed = destroyed
        self.highlight = False
        self.warning = False
        self._apply()

    def _apply(self):
        if self.base in ("miss", "sunk", "reveal", "disabled") or self.destroyed:
            self.setEnabled(False)
        else:
            self.setEnabled(True)
        self.update()

    def set_preview(self, on):
        if self.preview != on:
            self.preview = on
            self.update()

    def set_highlight(self, on):
        if self.highlight != on:
            self.highlight = on
            self.update()

    def set_warning(self, on):
        if self.warning != on:
            self.warning = on
            self.update()

    def enterEvent(self, event):
        if self._hover_handler:
            self._hover_handler(self.row, self.col)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._hover_handler:
            self._hover_handler(None, None)
        super().leaveEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()
        p.fillRect(self.rect(), QColor(self.BG[self.base]))
        p.setPen(QPen(QColor("#B8CCD9"), 1))
        p.drawRect(QRectF(0.5, 0.5, w - 1, h - 1))

        if self.base == "ship":
            path = _cell_silhouette(0, 0, w, self.up, self.down, self.left, self.right)
            if self.destroyed:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(self.ship_color).darker(118))
                p.drawPath(path)
                pen = QPen(QColor("#C0392B"), max(2, int(w * 0.12)))
                pen.setCapStyle(Qt.RoundCap)
                p.setPen(pen)
                m = w * 0.24
                p.drawLine(QPointF(m, m), QPointF(w - m, h - m))
                p.drawLine(QPointF(w - m, m), QPointF(m, h - m))
            else:
                _draw_ship_fill(p, path, self.ship_color, QRectF(0, 0, w, h))
        if self.weak:
            _draw_hexagon(p, w * 0.74, h * 0.26, w * 0.17, "#F5A623")

        text = self.TEXT[self.base]
        if text:
            p.setPen(QColor(self.FG[self.base]))
            f = QFont("Microsoft YaHei", 12)
            f.setBold(True)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter, text)

        if self.preview:
            p.fillRect(self.rect(), QColor(255, 200, 40, 90))
        if self.warning:
            p.fillRect(self.rect(), QColor(231, 76, 60, 70))
            pen = QPen(QColor("#E74C3C"), 2)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(1.5, 1.5, w - 3, h - 3))
        if self.highlight:
            pen = QPen(QColor("#FFC300"), 2)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(1.5, 1.5, w - 3, h - 3))
        p.end()


# ============================================================
#  回复解析
# ============================================================

def parse_coord(text):
    return rules.parse_coord(text)


def parse_llm_reply(reply):
    result = {"reaction": "", "coord": None, "taunt": "",
              "item_type": "无", "item_coord": None,
              "special": None, "special_coord": None}
    m = re.search(r"【反应】\s*(.+?)(?=【|$)", reply, re.S)
    if m:
        result["reaction"] = m.group(1).strip().splitlines()[0].strip()
    m = re.search(r"【道具】\s*(.+?)(?=【|$)", reply, re.S)
    if m:
        item_text = m.group(1).strip()
        if "扫描" in item_text:
            result["item_type"] = "扫描"
        elif "齐射" in item_text:
            result["item_type"] = "齐射"
        result["item_coord"] = parse_coord(item_text)
    m = re.search(r"【开炮】\s*(.+?)(?=【|$)", reply, re.S)
    if m:
        fire_text = m.group(1).strip()
        if "齐射3" in fire_text or "齐射三" in fire_text:
            result["special"] = "volley3"
            result["special_coord"] = parse_coord(fire_text)
        elif "α" in fire_text or "阿尔法" in fire_text or "竖排" in fire_text:
            result["special"] = "alpha"
            result["special_coord"] = parse_coord(fire_text)
        elif "β" in fire_text or "贝塔" in fire_text or "横排" in fire_text:
            result["special"] = "beta"
            result["special_coord"] = parse_coord(fire_text)
        else:
            result["coord"] = parse_coord(fire_text)
    if result["coord"] is None and result["special"] is None:
        result["coord"] = parse_coord(reply)
    m = re.search(r"【狠话】\s*(.+?)(?=【|$)", reply, re.S)
    if m:
        result["taunt"] = m.group(1).strip().splitlines()[0].strip()
    return result


def _special_area(mode, r, c):
    if mode == "alpha":
        return rules.column_cells(c)
    if mode == "beta":
        return rules.row_cells(r)
    if mode == "volley3":
        return rules.area_3x3((r, c))
    if mode in ("radar", "barrage"):
        return rules.area_2x2((r, c))
    return [(r, c)]


# ============================================================
#  主对话框
# ============================================================

class BattleshipDialog(QDialog):
    llm_ready = pyqtSignal(str, int)
    llm_failed = pyqtSignal(int)
    summary_ready = pyqtSignal(str, int)
    summary_failed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🛸 星海战棋")
        self.setGeometry(200, 80, 1200, 760)
        self.setStyleSheet("background-color: #ffffff; color: #333333; font-family: Microsoft YaHei;")
        self.llm_ready.connect(self._on_llm_ready)
        self.llm_failed.connect(self._on_llm_failed)
        self.summary_ready.connect(self._on_summary_ready)
        self.summary_failed.connect(self._on_summary_failed)
        self._token = 0
        self._retried = False
        self._system_prompt = config.get_system_prompt() + BATTLE_RULES
        self._summary_delivered = True
        self._anims = []
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self.init_game()
        self.init_ui()

    # ============================================================
    #  游戏状态
    # ============================================================

    def _new_fleet(self):
        rng = random.Random()
        fleet = rules.generate_fleet(rng)
        board, ships = rules.place_fleet(fleet, rng)
        rules.apply_deploy_traits(ships)
        return board, ships

    def init_game(self):
        self.phase = "placement"
        self.player_board, self.player_ships = self._new_fleet()
        self.remy_board, self.remy_ships = self._new_fleet()
        self.player_shots = set()
        self.remy_shots = set()
        self.player_scanned = {}
        self.remy_scanned = {}
        self._last_remy_fire_cells = set()
        self.player_radar = 3
        self.player_barrage = 3
        self.remy_radar = 0
        self.remy_barrage = 0
        self.last_player_events = []
        self.last_remy_events = []
        self.waiting = False
        self.rounds = 0
        self.game_history = []
        self._pending_briefing = ""
        self.action_mode = None
        self.player_special = []
        self.remy_special = []
        self._preview_cells = set()
        self.item_used_this_turn = False
        self.announcements = []
        self.player_scout_alpha_used = False
        self.remy_scout_alpha_used = False
        self.player_command_scans = 0
        self.remy_command_scans = 0
        # 全局增益（每局随机 1 个）
        self.buff = random.choice(BUFFS)
        self._pursuit_used = False
        self._laser_warning = None
        self._update_buff_badge()

    # ============================================================
    #  UI 构建
    # ============================================================

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(14, 14, 14, 14)

        title = QLabel("🛸 星海战棋")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #3E5A8A;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self.bubble = QLabel("蕾咪：哼，先部署好你的星舰吧。蕾咪才不会手下留情哦。")
        self.bubble.setWordWrap(True)
        self.bubble.setAlignment(Qt.AlignCenter)
        self.bubble.setStyleSheet(
            "background-color: #EFF4FB; color: #3E5A8A; border: 1px solid #3E5A8A;"
            " border-radius: 8px; padding: 8px 12px; font-size: 13px;"
        )
        self.bubble.setMinimumHeight(44)
        layout.addWidget(self.bubble)

        boards_layout = QHBoxLayout()
        boards_layout.setSpacing(12)
        boards_layout.addStretch()

        # 左：蕾咪舰队（初始全黑）
        remy_panel = self._build_side_panel("蕾咪的星舰")
        self.buff_label = QLabel()
        self.buff_label.setAlignment(Qt.AlignCenter)
        self.buff_label.setWordWrap(True)
        self.buff_label.setTextFormat(Qt.RichText)
        self.buff_label.setStyleSheet(
            "background-color: #FFF3E0; border: 1px solid #E8A87C;"
            " border-radius: 6px; padding: 6px 4px;"
        )
        remy_panel.layout().insertWidget(1, self.buff_label)
        self._update_buff_badge()
        boards_layout.addWidget(remy_panel)
        # 中左：蕾咪星域（点击开炮）
        self.remy_cells, remy_board_panel = self._build_board("🌌 蕾咪的星域（点击开火）", self.on_cell_click)
        boards_layout.addWidget(remy_board_panel)
        # 中右：我的星域
        self.player_cells, player_board_panel = self._build_board("🛰 你的星域", None)
        boards_layout.addWidget(player_board_panel)
        # 右：我方舰队
        player_panel = self._build_side_panel("你的星舰")
        boards_layout.addWidget(player_panel)

        boards_layout.addStretch()
        layout.addLayout(boards_layout)

        self.status_label = QLabel("部署阶段：点击「重新随机」调整舰队，满意后点「开战」")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #666666; font-size: 12px;")
        layout.addWidget(self.status_label)

        self.announce_label = QLabel("")
        self.announce_label.setAlignment(Qt.AlignCenter)
        self.announce_label.setWordWrap(True)
        self.announce_label.setStyleSheet(
            "background-color: #FFF6E0; color: #B07A2B; border: 1px solid #E8C88A;"
            " border-radius: 6px; padding: 6px 10px; font-size: 12px;"
        )
        self.announce_label.setMinimumHeight(30)
        layout.addWidget(self.announce_label)

        item_layout = QHBoxLayout()
        item_layout.setSpacing(10)
        item_layout.addStretch()
        self.radar_btn = QPushButton("📡 扫描 ×3")
        self.barrage_btn = QPushButton("💥 齐射 ×3")
        for btn in (self.radar_btn, self.barrage_btn):
            btn.setCheckable(True)
            btn.setEnabled(False)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #2E6C8E; color: white; border: none;
                    border-radius: 6px; padding: 6px 14px; font-size: 12px;
                }
                QPushButton:hover { background-color: #3E7C9E; }
                QPushButton:checked { background-color: #DAAD69; }
                QPushButton:disabled { background-color: #999999; }
            """)
            item_layout.addWidget(btn)
        self.radar_btn.clicked.connect(lambda: self._set_mode("radar"))
        self.barrage_btn.clicked.connect(lambda: self._set_mode("barrage"))
        item_layout.addStretch()
        layout.addLayout(item_layout)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()
        self.codex_btn = QPushButton("📖 图鉴")
        self.codex_btn.clicked.connect(self.show_codex)
        btn_layout.addWidget(self.codex_btn)
        self.reroll_btn = QPushButton("🎲 重新随机")
        self.reroll_btn.clicked.connect(self.reroll_ships)
        btn_layout.addWidget(self.reroll_btn)
        self.start_btn = QPushButton("⚔️ 开战！")
        self.start_btn.clicked.connect(self.start_battle)
        btn_layout.addWidget(self.start_btn)
        new_btn = QPushButton("🔄 新游戏")
        new_btn.clicked.connect(self.new_game)
        btn_layout.addWidget(new_btn)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        btn_layout.addStretch()
        for btn in (self.codex_btn, self.reroll_btn, self.start_btn, new_btn, close_btn):
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #333333; color: white; border: none;
                    border-radius: 6px; padding: 6px 14px; font-size: 12px;
                }
                QPushButton:hover { background-color: #555555; }
                QPushButton:disabled { background-color: #999999; }
            """)
        layout.addLayout(btn_layout)
        self.setLayout(layout)
        self._render_player_board()
        self._render_all_remy()
        self._refresh_side_panels()

    def _build_board(self, caption, click_handler):
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        label = QLabel(caption)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size: 13px; font-weight: bold; color: #3E5A8A;")
        v.addWidget(label)

        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setSpacing(2)
        grid.setContentsMargins(2, 2, 2, 2)

        for c in range(SIZE):
            hdr = QLabel(rules.col_name(c))
            hdr.setAlignment(Qt.AlignCenter)
            hdr.setFixedSize(CellButton.CELL, 16)
            hdr.setStyleSheet("color: #3E5A8A; font-weight: bold; font-size: 10px;")
            grid.addWidget(hdr, 0, c + 1)
        cells = []
        for r in range(SIZE):
            hdr = QLabel(str(r + 1))
            hdr.setAlignment(Qt.AlignCenter)
            hdr.setFixedSize(16, CellButton.CELL)
            hdr.setStyleSheet("color: #3E5A8A; font-weight: bold; font-size: 10px;")
            grid.addWidget(hdr, r + 1, 0)
            row_cells = []
            for c in range(SIZE):
                cell = CellButton(r, c, click_handler,
                                  hover_handler=self._on_cell_hover)
                grid.addWidget(cell, r + 1, c + 1)
                row_cells.append(cell)
            cells.append(row_cells)
        v.addWidget(grid_widget, alignment=Qt.AlignCenter)
        return cells, panel

    def _build_side_panel(self, caption):
        panel = QWidget()
        panel.setFixedWidth(132)
        v = QVBoxLayout(panel)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(6)
        label = QLabel(caption)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size: 12px; font-weight: bold; color: #3E5A8A;")
        v.addWidget(label)
        self._side_ship_containers = getattr(self, "_side_ship_containers", {})
        self._side_ship_containers[caption] = QVBoxLayout()
        self._side_ship_containers[caption].setSpacing(6)
        v.addLayout(self._side_ship_containers[caption])
        v.addStretch()
        return panel

    # ============================================================
    #  模式 / 道具 / 特殊炮击
    # ============================================================

    def _set_mode(self, mode):
        if self.phase != "battle" or self.waiting:
            self._sync_controls()
            return
        if mode in ("radar", "barrage"):
            available = self.player_radar > 0 if mode == "radar" else self.player_barrage > 0
            if self.item_used_this_turn or not available:
                self._sync_controls()
                return
        if self.action_mode == mode:
            self.action_mode = None
            self._sync_controls()
            return
        self.action_mode = mode
        self._sync_controls()
        hint = {
            "radar": "📡 扫描模式：点击蕾咪星域一格，扫描以其为左上角的 2x2 区域（不消耗炮击）",
            "barrage": "💥 齐射模式：点击蕾咪星域一格，炮击以其为左上角的 2x2 区域！",
        }
        self.status_label.setText(hint[mode])

    def _sync_controls(self):
        self.radar_btn.setText(f"📡 扫描 ×{self.player_radar}")
        self.barrage_btn.setText(f"💥 齐射 ×{self.player_barrage}")
        can = self.phase == "battle" and not self.waiting
        can_item = can and not self.item_used_this_turn
        self.radar_btn.setEnabled(can_item and self.player_radar > 0)
        self.barrage_btn.setEnabled(can_item and self.player_barrage > 0)
        self.radar_btn.setChecked(self.action_mode == "radar")
        self.barrage_btn.setChecked(self.action_mode == "barrage")
        if self.action_mode not in ("radar", "barrage"):
            self.action_mode = None

    # ============================================================
    #  播报
    # ============================================================

    def _reset_announcements(self):
        self.announcements = []
        self.announce_label.setText("")

    def _announce(self, text):
        if not text:
            return
        self.announcements.append(text)
        self.announce_label.setText("\n".join(self.announcements[-3:]))

    def _update_buff_badge(self):
        """刷新左侧「蕾咪全局增益」徽章（init_game / init_ui 都会调用）。"""
        label = getattr(self, "buff_label", None)
        if label is None:
            return
        label.setText(
            f"<div style='font-size:11px;color:#8A6D3B;'>⚡ 蕾咪全局增益</div>"
            f"<div style='font-size:15px;font-weight:bold;color:#C05A2B;'>【{self.buff}】</div>"
            f"<div style='font-size:11px;color:#6B6B6B;'>{BUFF_SHORT[self.buff]}</div>"
        )

    def _announce_deploy_traits(self):
        """开局播报我方舰体的入场特性（护卫舰转移弱点 / 突击舰消除弱点）。"""
        for s in self.player_ships:
            if s["type"] == "frigate" and s.get("transfer"):
                self._announce("🚢 " + DEPLOY_TEXT["frigate"])
            elif s["type"] == "assault" and not s["weak_cells"]:
                self._announce("🚢 " + DEPLOY_TEXT["assault"])

    # ============================================================
    #  渲染
    # ============================================================

    def _player_ship_at(self, pos):
        for s in self.player_ships:
            if pos in s["cells"]:
                return s
        return None

    def _remy_ship_at(self, pos):
        for s in self.remy_ships:
            if pos in s["cells"]:
                return s
        return None

    def _player_dead_cell(self, pos):
        """pos 是否属于我方已坠毁舰体（不可再被敌方选为目标）。"""
        s = self._player_ship_at(pos)
        return s is not None and not s["alive"]

    def _remy_dead_cell(self, pos):
        """pos 是否属于蕾咪已坠毁舰体（不可再被玩家选为目标）。"""
        s = self._remy_ship_at(pos)
        return s is not None and not s["alive"]

    def _set_cell_ship(self, cell, ship, pos, destroyed=False):
        cs = set(ship["cells"])
        r, c = pos
        cell.set_ship(
            weak=(pos in ship["weak_cells"]),
            up=((r - 1, c) in cs), down=((r + 1, c) in cs),
            left=((r, c - 1) in cs), right=((r, c + 1) in cs),
            color=ship_color(ship["type"]),
            destroyed=destroyed,
        )

    def _render_player_board(self):
        for r in range(SIZE):
            for c in range(SIZE):
                cell = self.player_cells[r][c]
                pos = (r, c)
                ship = self._player_ship_at(pos)
                if ship is not None and not ship["alive"]:
                    self._set_cell_ship(cell, ship, pos, destroyed=True)
                elif pos in self.remy_shots:
                    cell.set_state("sunk" if ship is not None else "miss")
                elif ship is not None:
                    self._set_cell_ship(cell, ship, pos, destroyed=False)
                else:
                    cell.set_state("empty")
                cell.set_highlight(pos in self._last_remy_fire_cells)
                warn = self._laser_warning
                cell.set_warning(
                    warn is not None
                    and (r == warn[1] if warn[0] == "row" else c == warn[1]))

    def _render_remy_cell(self, r, c):
        cell = self.remy_cells[r][c]
        pos = (r, c)
        ship = self._remy_ship_at(pos)
        if ship is not None and not ship["alive"]:
            self._set_cell_ship(cell, ship, pos, destroyed=True)
            return
        if pos in self.player_shots:
            cell.set_state("sunk" if self.remy_board[r][c] != 0 else "miss")
            return
        if pos in self.player_scanned:
            cell.set_state("scan_ship" if self.player_scanned[pos] else "scan_empty")
        else:
            cell.set_state("sea")
        cell.setEnabled(self.phase == "battle" and not self.waiting)

    def _render_all_remy(self):
        for r in range(SIZE):
            for c in range(SIZE):
                self._render_remy_cell(r, c)

    def _reveal_remy_board(self):
        for r in range(SIZE):
            for c in range(SIZE):
                pos = (r, c)
                cell = self.remy_cells[r][c]
                ship = self._remy_ship_at(pos)
                if ship is not None:
                    self._set_cell_ship(cell, ship, pos, destroyed=not ship["alive"])
                elif pos in self.player_shots:
                    cell.set_state("miss")
                else:
                    cell.set_state("sea")
                    cell.setEnabled(False)

    def _refresh_side_panels(self):
        """左：蕾咪舰队（初始全黑，击毁点亮）；右：我方舰队（始终点亮）。"""
        for caption, layout in getattr(self, "_side_ship_containers", {}).items():
            while layout.count():
                item = layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()

        remy_layout = self._side_ship_containers.get("蕾咪的星舰")
        player_layout = self._side_ship_containers.get("你的星舰")
        if remy_layout is not None:
            for s in self.remy_ships:
                remy_layout.addWidget(self._side_entry(s, revealed=True))
        if player_layout is not None:
            for s in self.player_ships:
                player_layout.addWidget(self._side_entry(s, revealed=True))

    def _side_entry(self, ship, revealed):
        entry = QWidget()
        v = QVBoxLayout(entry)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        sunk = not ship["alive"]
        if revealed:
            cells, weak = ship_canonical(ship["type"])
            color = "#9AA5B1" if sunk else ship_color(ship["type"])
            weak_color = "#B9B0A0" if sunk else "#F5A623"
            shape = ShipShapeWidget(cells, weak, cell_size=16,
                                    color=color, weak_color=weak_color)
        else:
            shape = QLabel("▮▮")
            shape.setAlignment(Qt.AlignCenter)
            shape.setFixedSize(52, 24)
            shape.setStyleSheet(
                "background-color: #1A1A1A; color: #1A1A1A;"
                "border-radius: 4px; font-size: 12px;")
        name = QLabel(ship["name"] if revealed else "？？？")
        name.setAlignment(Qt.AlignCenter)
        name.setStyleSheet(
            "font-size: 10px; color: #3E5A8A;" if revealed else
            "font-size: 10px; color: #999999;")
        v.addWidget(shape, alignment=Qt.AlignCenter)
        if sunk:
            cross = QLabel("✕")
            cross.setAlignment(Qt.AlignCenter)
            cross.setStyleSheet("color: #C0392B; font-size: 14px; font-weight: bold;")
            v.addWidget(cross)
        v.addWidget(name)
        return entry

    # ============================================================
    #  流程
    # ============================================================

    def reroll_ships(self):
        if self.phase != "placement":
            return
        self.player_board, self.player_ships = self._new_fleet()
        self._render_player_board()
        self._refresh_side_panels()

    def start_battle(self):
        if self.phase != "placement":
            return
        self.phase = "battle"
        self.reroll_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.status_label.setText("交战中：点击左侧「蕾咪的星域」开火！")
        self.bubble.setText("蕾咪：星舰已就位！来吧，让你先手。哼，别客气哦～")
        self.last_player_events = []
        self.item_used_this_turn = False
        self._reset_announcements()
        self._announce_deploy_traits()
        self._announce(f"⚡ 本局蕾咪获得全局增益【{self.buff}】：{BUFF_DESC[self.buff]}")
        self._compute_player_special()
        self._render_all_remy()
        self._sync_controls()

    def new_game(self):
        self._token += 1
        self._watchdog.stop()
        self._retried = False
        self.init_game()
        self._reset_announcements()
        self.reroll_btn.setEnabled(True)
        self.start_btn.setEnabled(True)
        self.status_label.setText("部署阶段：点击「重新随机」调整舰队，满意后点「开战」")
        self.bubble.setText("蕾咪：再来一局？哼，这次蕾咪可不会输了！")
        self._render_player_board()
        self._render_all_remy()
        self._refresh_side_panels()
        self._sync_controls()

    def on_cell_click(self, r, c):
        if self.phase != "battle" or self.waiting:
            return
        mode = self.action_mode
        if mode in ("radar", "barrage") and self._remy_dead_cell((r, c)):
            return  # 范围道具的锚点不能落在已坠毁舰体上
        if mode == "radar":
            self._player_radar((r, c))
            return
        if mode == "barrage":
            self._player_barrage((r, c))
            return
        # 炮击：若特性已触发，自动升级为特殊炮击（激光 α/β、齐射3）
        special = self._active_player_special()
        if special:
            self._clear_preview()
            events = self._player_fire(_special_area(special, r, c), center=(r, c),
                                       note=SPECIAL_NAMES[special])
            self.player_special.remove(special)
            self._finish_player_turn(events)
            return
        # 普通炮击
        if (r, c) in self.player_shots:
            return
        if self._remy_dead_cell((r, c)):
            return  # 已坠毁舰体的格子不可攻击
        events = self._player_fire([(r, c)], center=(r, c), note=None)
        self._finish_player_turn(events)

    def _player_radar(self, center):
        if self.item_used_this_turn or self.player_radar <= 0:
            return
        self.item_used_this_turn = True
        self.player_radar -= 1
        found = 0
        for p in rules.area_2x2(center):
            has_ship = self.remy_board[p[0]][p[1]] != 0
            if p not in self.player_scanned and p not in self.player_shots:
                self.player_scanned[p] = has_ship
            if has_ship:
                found += 1
        self.last_player_events.append(f"用扫描探查了 {rules.fmt(center)} 一带")
        self.status_label.setText(
            f"📡 扫描完成：该区域{'发现 ' + str(found) + ' 格星舰信号（⚑）！' if found else '没有发现星舰信号。'}继续开火！"
        )
        self.action_mode = None
        self._render_all_remy()
        self._sync_controls()

    def _player_barrage(self, center):
        """齐射道具（2x2，额外伤害，不结束回合——每回合必须再炮击一次）。"""
        if self.item_used_this_turn or self.player_barrage <= 0:
            return
        self.item_used_this_turn = True
        self.player_barrage -= 1
        self._clear_preview()
        events, destroyed = rules.resolve_hits(self.remy_ships, self.player_shots,
                                               rules.area_2x2(center))
        for ship in destroyed:
            self._on_remy_ship_destroyed(ship)
            self._flash_remy_ship(ship)
        note = f"齐射（中心{rules.fmt(center)}）：{'；'.join(events)}"
        self.last_player_events.append(note)
        self.action_mode = None
        self._render_all_remy()
        self._refresh_side_panels()
        self._sync_controls()
        if all(not s["alive"] for s in self.remy_ships):
            self._game_over(player_won=True)
            return
        self.status_label.setText(f"💥 {note} 继续开火！")

    def _player_fire(self, area, center, note):
        events, destroyed = rules.resolve_hits(self.remy_ships, self.player_shots, area)
        for ship in destroyed:
            self._on_remy_ship_destroyed(ship)
            self._flash_remy_ship(ship)
        prefix = f"{note}（中心{rules.fmt(center)}）：" if note else ""
        return [prefix + events[0]] + events[1:]

    def _finish_player_turn(self, events):
        self.last_player_events.extend(events)
        self.rounds += 1
        # 扫射 buff：激光发动前一回合（第 3/7/11…回合）在目标行/列亮红色预警线
        if self.buff == "扫射" and self.rounds % 4 == 3:
            self._laser_warning = self._laser_target()
            idx = self._laser_warning[1]
            line = (f"第 {idx + 1} 行" if self._laser_warning[0] == "row"
                    else f"第 {rules.col_name(idx)} 列")
            self._announce(f"⚠️ 蕾咪的扫射预警：{line} 出现红色预警线！")
            self._render_player_board()
        self._render_all_remy()
        self._refresh_side_panels()
        self._sync_controls()
        if all(not s["alive"] for s in self.remy_ships):
            self._game_over(player_won=True)
            return
        self.waiting = True
        self._clear_preview()
        self._sync_controls()
        self.status_label.setText("蕾咪思考中…")
        self._compute_remy_special()
        self._request_remy_turn()

    def _on_remy_ship_destroyed(self, ship):
        if ship["type"] == "frigate":
            rules.restore_frigate_weak(ship)
        special = rules.special_shot_on_destroy(ship)
        if special:
            self.remy_special.append(special)
        self._announce(f"💥 你击毁了{ship['name']}！")
        if special:
            self._announce(
                f"⚡ {ship['name']}特性【坠毁】生效：蕾咪下回合炮击变为{SPECIAL_NAMES[special]}"
            )
        # 指挥舰存活特性：每击沉敌方 1 艘 → 我方获得 1 个扫描（最多 2 个）
        if rules.has_alive_command(self.player_ships) and self.player_command_scans < 2:
            self.player_command_scans += 1
            self.player_radar += 1
            self._announce(
                f"⚡ 指挥舰特性【存活】生效：获得 1 个扫描道具（{self.player_command_scans}/2）"
            )

    # ============================================================
    #  LLM 回合
    # ============================================================

    def _enemy_dead_count(self, ships):
        return sum(1 for s in ships if not s["alive"])

    def _active_player_special(self):
        """当前要打的特殊炮击（栈顶，后发先至：侦察梭α 先于坠毁特性），无则 None。"""
        if not self.player_special:
            return None
        return self.player_special[-1]

    def _compute_player_special(self):
        if rules.scout_alpha_active(self.player_ships) and not self.player_scout_alpha_used:
            self.player_scout_alpha_used = True
            self.player_special.append("alpha")
            self._announce("⚡ " + SURVIVAL_TEXT["scout_alpha"])
        if self.player_special:
            self.status_label.setText(
                f"⚡ 你的下一次炮击已升级为 {SPECIAL_NAMES[self._active_player_special()]}，"
                f"点击「蕾咪的星域」开火！")

    def _compute_remy_special(self):
        if rules.scout_alpha_active(self.remy_ships) and not self.remy_scout_alpha_used:
            self.remy_scout_alpha_used = True
            self.remy_special.append("alpha")
            self._announce("⚡ 蕾咪的侦察梭特性【存活】生效：蕾咪本回合炮击变为激光齐射α（竖排）")

    def _build_briefing(self, retry_note=None):
        lines = ["你对调查员星域的探测图（.未知 ~扫描为空 F扫描发现星舰 o落空 X击毁）："]
        lines.append("  " + " ".join(rules.col_name(c) for c in range(SIZE)))
        for r in range(SIZE):
            row = []
            for c in range(SIZE):
                pos = (r, c)
                if pos in self.remy_shots:
                    row.append("X" if self.player_board[r][c] != 0 else "o")
                elif pos in self.remy_scanned:
                    row.append("F" if self.remy_scanned[pos] else "~")
                else:
                    row.append(".")
            lines.append(f"{r + 1} " + " ".join(row))

        if self.last_player_events:
            lines.append(f"本回合调查员的行动：{'；'.join(self.last_player_events)}")
        if self.last_remy_events:
            lines.append(f"你上一回合的行动结果：{'；'.join(self.last_remy_events)}")
        remy_alive = [s["name"] for s in self.remy_ships if s["alive"]]
        lines.append(f"你的剩余舰体：{'、'.join(remy_alive) or '无'}。")
        enemy_alive = [s["name"] for s in self.player_ships if s["alive"]]
        lines.append(f"对方剩余舰体：{'、'.join(enemy_alive) or '无'}（共 {len(enemy_alive)} 艘）。")
        lines.append("请优先推理敌方舰体形状与弱点位置，攻击弱点。")
        if self.remy_special:
            names = "、".join(SPECIAL_NAMES[k] for k in sorted(self.remy_special))
            lines.append(f"你本回合可用的特殊炮击：{names}。")
        if retry_note:
            lines.append(retry_note)
        return "\n".join(lines)

    def _request_remy_turn(self, retry_note=None):
        self._token += 1
        token = self._token
        briefing = self._build_briefing(retry_note)
        self._pending_briefing = briefing
        messages = (
            [{"role": "system", "content": self._system_prompt}]
            + list(self.game_history)
            + [{"role": "user", "content": briefing}]
        )
        threading.Thread(
            target=self._llm_worker,
            args=(messages, token),
            daemon=True,
        ).start()
        self._watchdog.stop()
        try:
            self._watchdog.timeout.disconnect()
        except TypeError:
            pass
        self._watchdog.timeout.connect(lambda t=token: self._on_watchdog(t))
        self._watchdog.start(30000)

    def _on_watchdog(self, token):
        if self.waiting and self.phase == "battle" and self._token == token:
            print("[Remy Debug] [星海战棋] 看门狗超时，强制本地战术接管")
            self._token += 1
            self._remy_fire(self._local_action(), local_fallback=True)

    def _llm_worker(self, messages, token):
        api_cfg = config.CONFIG.get("api", {})
        for attempt in range(2):
            if attempt == 0:
                provider_id = api_cfg.get("primary", "")
                api_key = api_cfg.get("primary_key", "")
            else:
                provider_id = api_cfg.get("backup", "")
                api_key = api_cfg.get("backup_key", "")
                if not api_key:
                    break
            if not api_key:
                continue
            provider = config.API_PROVIDERS.get(provider_id)
            if not provider:
                continue
            try:
                payload = apply_thinking_request(
                    provider,
                    {
                        "model": provider["model"],
                        "messages": messages,
                        "temperature": 0.9,
                        "max_tokens": 200,
                    },
                    enabled=False,
                )
                response = requests.post(
                    provider["url"],
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=12,
                )
                if response.status_code == 200:
                    message = response.json()["choices"][0]["message"]
                    reply = message.get("content") or ""
                    if reply.strip():
                        self.llm_ready.emit(reply, token)
                        return
                    if message.get("reasoning_content"):
                        print("[Remy Debug] [星海战棋] 正文为空：思考模式未关闭，token 预算被思维链耗尽")
                        continue
                print(f"[Remy Debug] [星海战棋] API error: {response.status_code} {response.text[:300]}")
            except Exception as e:
                print(f"[Remy Debug] [星海战棋] API exception: {type(e).__name__}: {e}")
        self.llm_failed.emit(token)

    def _on_llm_ready(self, reply, token):
        if token != self._token or self.phase != "battle":
            return
        self.game_history.append({"role": "user", "content": self._pending_briefing})
        self.game_history.append({"role": "assistant", "content": reply})
        action = parse_llm_reply(reply)
        if not self._valid_action(action):
            if not self._retried:
                self._retried = True
                self._request_remy_turn(
                    retry_note="注意：你上次给出的坐标无效或已炮击过，请重新选择标记为.或F的格。"
                )
            else:
                self._retried = False
                self._remy_fire(self._local_action(), local_fallback=True)
            return
        self._retried = False
        self._remy_fire(action)

    def _valid_action(self, action):
        if action["item_type"] == "齐射" and self.remy_barrage > 0:
            if action["item_coord"] is None:
                return False
        if action["special"] is not None:
            return (action["special"] in self.remy_special
                    and action["special_coord"] is not None
                    and not self._player_dead_cell(action["special_coord"]))
        coord = action["coord"]
        return coord is not None and coord not in self.remy_shots \
            and not self._player_dead_cell(coord)

    def _on_llm_failed(self, token):
        if token != self._token or self.phase != "battle":
            return
        self._remy_fire(self._local_action(), local_fallback=True)

    def _special_anchor(self):
        """为特殊炮击选一个不落死格的锚点（优先已命中/已扫描含舰的格子）。"""
        hits = []
        for p in self.remy_shots:
            s = self._player_ship_at(p)
            if s is not None and s["alive"]:
                hits.append(p)
        scanned = [p for p, has in self.remy_scanned.items()
                   if has and not self._player_dead_cell(p)]
        preferred = hits or scanned
        if preferred:
            return random.choice(preferred)
        valid = [(r, c) for r in range(SIZE) for c in range(SIZE)
                 if (r, c) not in self.remy_shots
                 and not self._player_dead_cell((r, c))]
        return random.choice(valid) if valid else None

    def _pursuit_anchor(self, fired_area):
        """追击锚点：fired_area 中命中且舰仍存活的格子，无则 None。"""
        hits = [p for p in fired_area
                if (s := self._player_ship_at(p)) is not None and s["alive"]]
        return random.choice(hits) if hits else None

    def _laser_target(self):
        """扫射目标：统计各行/列的「命中且舰存活」格数，选命中最多的一行或一列。"""
        row_score = [0] * SIZE
        col_score = [0] * SIZE
        for p in self.remy_shots:
            s = self._player_ship_at(p)
            if s is not None and s["alive"]:
                row_score[p[0]] += 1
                col_score[p[1]] += 1
        best_row = max(range(SIZE), key=lambda i: row_score[i])
        best_col = max(range(SIZE), key=lambda i: col_score[i])
        if row_score[best_row] >= col_score[best_col]:
            if row_score[best_row] == 0:
                best_row = random.randrange(SIZE)
            return ("row", best_row)
        if col_score[best_col] == 0:
            best_col = random.randrange(SIZE)
        return ("col", best_col)

    def _adjacent_hunt_target(self):
        """追打：若某艘敌舰已被命中但未坠毁，优先打其命中格旁的未射击格。"""
        wounded = []
        for p in self.remy_shots:
            s = self._player_ship_at(p)
            if s is not None and s["alive"]:
                wounded.append(p)
        if not wounded:
            return None
        candidates = set()
        for r, c in wounded:
            for dr, dc in rules.FOUR_DIRS:
                q = (r + dr, c + dc)
                if (0 <= q[0] < SIZE and 0 <= q[1] < SIZE
                        and q not in self.remy_shots
                        and not self._player_dead_cell(q)):
                    candidates.add(q)
        return random.choice(list(candidates)) if candidates else None

    def _best_weak_target(self):
        """返回当前最该打的弱点格，无可靠候选则 None。"""
        alive_types = sorted({s["type"] for s in self.player_ships if s["alive"]})
        if not alive_types:
            return None
        dead_cells = {c for s in self.player_ships if not s["alive"] for c in s["cells"]}
        known_has = {p for p, has in self.remy_scanned.items() if has}
        known_has |= {p for p in self.remy_shots
                      if self.player_board[p[0]][p[1]] != 0 and p not in dead_cells}
        blocked = {p for p, has in self.remy_scanned.items() if not has}
        blocked |= {p for p in self.remy_shots if self.player_board[p[0]][p[1]] == 0}
        blocked |= dead_cells
        counts = rules.infer_weak_targets(alive_types, known_has, blocked)
        if not counts:
            return None
        candidates = {w: c for w, c in counts.items() if w not in self.remy_shots}
        if not candidates:
            return None
        # 优先支持数高；平手优先落在「已知含舰」内（更稳）
        return max(candidates, key=lambda w: (candidates[w], w in known_has))

    def _local_item_decision(self):
        """本地 AI 的道具决策：蕾咪已取消扫描/齐射道具，恒返回「无」。"""
        return "无", None
        known = [p for p, has in self.remy_scanned.items()
                 if has and p not in self.remy_shots and not self._player_dead_cell(p)]
        if self.remy_barrage > 0 and known:
            # 齐射只打已暴露视野的舰体：选 2x2 覆盖已暴露格最多的锚点
            known_set = set(known)
            center = max(known, key=lambda p: sum(
                1 for q in rules.area_2x2(p) if q in known_set))
            return "齐射", center
        if self.remy_radar > 0:
            best, best_gain = None, -1
            for _ in range(12):
                center = (random.randrange(SIZE), random.randrange(SIZE))
                if self._player_dead_cell(center):
                    continue  # 范围道具锚点不落在死格
                cells = rules.area_2x2(center)
                gain = sum(1 for p in cells
                           if p not in self.remy_scanned and not self._player_dead_cell(p))
                # 偏向能揭示更多舰体形状的扫描——邻接已知含舰格的新格额外加分
                known_set = set(known)
                adj = 0
                for p in cells:
                    if p in self.remy_scanned or self._player_dead_cell(p):
                        continue
                    adj += sum(1 for dr, dc in rules.FOUR_DIRS
                               if (p[0] + dr, p[1] + dc) in known_set)
                gain = gain * 4 + adj
                if gain > best_gain:
                    best, best_gain = center, gain
            if best is not None:
                return "扫描", best
        return "无", None

    def _local_action(self):
        action = {"reaction": "", "taunt": "", "coord": None,
                  "item_type": "无", "item_coord": None,
                  "special": None, "special_coord": None}
        known = [p for p, has in self.remy_scanned.items()
                 if has and p not in self.remy_shots and not self._player_dead_cell(p)]
        # 道具：每回合尽量用一个（不因特殊炮击而跳过）
        action["item_type"], action["item_coord"] = self._local_item_decision()
        # 特殊炮击（升级后的炮击，强制优先打出）：锚点避开死格
        if self.remy_special:
            special = self.remy_special[-1]
            anchor = self._special_anchor()
            if anchor is not None:
                action["special"] = special
                action["special_coord"] = anchor
                return action
        adj = self._adjacent_hunt_target()
        if adj is not None:
            action["coord"] = adj
        else:
            weak = self._best_weak_target()
            if weak is not None:
                action["coord"] = weak
            elif known:
                action["coord"] = random.choice(known)
            else:
                unknowns = [(r, c) for r in range(SIZE) for c in range(SIZE)
                            if (r, c) not in self.remy_shots
                            and not self._player_dead_cell((r, c))]
                action["coord"] = random.choice(unknowns) if unknowns else None
        return action

    def _remy_fire(self, action, local_fallback=False):
        reaction = action.get("reaction") or self._local_reaction()
        taunt = action.get("taunt") or random.choice(LOCAL_TAUNTS)
        self.bubble.setText(f"蕾咪：{reaction}")

        events = []
        item_note = ""
        self._pursuit_used = False  # 追击每回合至多一次
        fired_area = None

        # 扫射 buff：每 4 回合自动横排/竖排激光，取代当回合普通炮击（优先级最高）
        if self.buff == "扫射" and self.rounds % 4 == 0:
            target = self._laser_warning or self._laser_target()
            idx = target[1]
            fired_area = (rules.row_cells(idx) if target[0] == "row"
                          else rules.column_cells(idx))
            line = (f"第 {idx + 1} 行" if target[0] == "row"
                    else f"第 {rules.col_name(idx)} 列")
            fire_events = self._remy_resolve(fired_area, center=fired_area[0], note="扫射")
            events.append(f"扫射（{line}）：{'；'.join(fire_events)}")
            self._laser_warning = None
            shot_text = f"{taunt} → 蕾咪发动扫射：{'；'.join(fire_events)}"
        else:
            item_type = action.get("item_type", "无")
            item_coord = action.get("item_coord")
            # 蕾咪已取消道具（remy_radar/remy_barrage 恒为 0），此分支仅保留兼容
            if item_type == "扫描" and self.remy_radar > 0 and item_coord is not None:
                self.remy_radar -= 1
                found = []
                for p in rules.area_2x2(item_coord):
                    if p not in self.remy_scanned:
                        has_ship = self.player_board[p[0]][p[1]] != 0
                        self.remy_scanned[p] = has_ship
                        if has_ship:
                            found.append(rules.fmt(p))
                events.append(
                    f"扫描{rules.fmt(item_coord)}一带"
                    + (f"：发现星舰于{'、'.join(found)}" if found else "：没有发现")
                )
                item_note = f"蕾咪用扫描探查了 {rules.fmt(item_coord)} 一带！"
            if item_type == "齐射" and self.remy_barrage > 0 and item_coord is not None:
                self.remy_barrage -= 1
                fire_events = self._remy_resolve(rules.area_2x2(item_coord),
                                                 center=item_coord, note="齐射")
                events.append(f"齐射（中心{rules.fmt(item_coord)}）：{'；'.join(fire_events)}")

            special = action.get("special")
            special_coord = action.get("special_coord")
            # 特殊炮击已升级为强制：只要还有可用特殊，就优先打出（LLM 忽略时本地补上）
            if special not in self.remy_special:
                special = self.remy_special[-1] if self.remy_special else None
                special_coord = self._special_anchor() if special else None
            if special is not None and special_coord is not None and special in self.remy_special:
                self.remy_special.remove(special)
                fired_area = _special_area(special, *special_coord)
                fire_events = self._remy_resolve(fired_area, center=special_coord,
                                                 note=SPECIAL_NAMES[special])
                events.append(f"{SPECIAL_NAMES[special]}（{rules.fmt(special_coord)}）："
                              f"{'；'.join(fire_events)}")
                shot_text = f"{taunt} → 蕾咪发动 {SPECIAL_NAMES[special]}：{'；'.join(fire_events)}"
            else:
                coord = action.get("coord")
                if coord is None:
                    self.waiting = False
                    self._render_all_remy()
                    self._sync_controls()
                    return
                # 爆发 buff：前 3 回合普通炮击强化为 3×3 齐射
                if self.buff == "爆发" and self.rounds <= 3:
                    fired_area = rules.area_3x3(coord)
                    fire_events = self._remy_resolve(fired_area, center=coord, note="爆发")
                    events.append(f"爆发3×3（中心{rules.fmt(coord)}）：{'；'.join(fire_events)}")
                    shot_text = f"{taunt} → 蕾咪爆发齐射 {rules.fmt(coord)}：{'；'.join(fire_events)}"
                else:
                    fired_area = [coord]
                    fire_events = self._remy_resolve(fired_area, center=coord, note=None)
                    events.append(f"炮击{rules.fmt(coord)}：{'；'.join(fire_events)}")
                    shot_text = f"{taunt} → 蕾咪炮击 {rules.fmt(coord)}：{'；'.join(fire_events)}"

            # 追击 buff：命中存活舰体时，当回合追加一次 2×2（每回合至多一次）
            if self.buff == "追击" and not self._pursuit_used and fired_area:
                anchor = self._pursuit_anchor(fired_area)
                if anchor is not None:
                    self._pursuit_used = True
                    pursuit_events = self._remy_resolve(rules.area_2x2(anchor),
                                                         center=anchor, note="追击")
                    events.append(f"追击（中心{rules.fmt(anchor)}）："
                                  f"{'；'.join(pursuit_events)}")
                    shot_text += f" → 追击 {'；'.join(pursuit_events)}"

        self.last_remy_events = events
        self._render_player_board()
        self._refresh_side_panels()
        if item_note:
            shot_text = item_note + " " + shot_text
        if local_fallback:
            shot_text += "（本地战术模式）"
        self.status_label.setText(shot_text)

        if all(not s["alive"] for s in self.player_ships):
            self._game_over(player_won=False)
            return
        self.waiting = False
        self.last_player_events = []
        self.item_used_this_turn = False
        self._reset_announcements()
        self._compute_player_special()
        self._render_all_remy()
        self._refresh_side_panels()
        self._sync_controls()

    def _remy_resolve(self, area, center, note):
        self._last_remy_fire_cells = set(area)
        events, destroyed = rules.resolve_hits(self.player_ships, self.remy_shots, area)
        for ship in destroyed:
            if ship["type"] == "frigate":
                rules.restore_frigate_weak(ship)
            special = rules.special_shot_on_destroy(ship)
            if special:
                self.player_special.append(special)
            self._flash_player_ship(ship)
            self._announce(f"💥 你的{ship['name']}被击毁了！")
            if special:
                self._announce(
                    f"⚡ {ship['name']}特性【坠毁】生效：你下回合炮击变为{SPECIAL_NAMES[special]}"
                )
        return events

    def _local_reaction(self):
        for event in self.last_player_events:
            if "击毁" in event:
                for ship in self.remy_ships:
                    if ship["name"] in event:
                        return random.choice(LOCAL_SUNK_REACTIONS).format(name=ship["name"])
                return random.choice(LOCAL_SUNK_REACTIONS).format(name="星舰")
        for event in self.last_player_events:
            if "落空" in event:
                return random.choice(LOCAL_MISS_REACTIONS)
        if any("扫描" in e for e in self.last_player_events):
            return "哼，随便你扫，蕾咪的星舰藏得可深了！"
        return random.choice(LOCAL_MISS_REACTIONS)

    # ============================================================
    #  爆炸特效 / 悬停预览
    # ============================================================

    def _flash_player_ship(self, ship):
        """击毁的舰体爆闪一次（红色，短暂明暗）。"""
        buttons = [self.player_cells[r][c] for r, c in ship["cells"]]
        self._flash_buttons(buttons)

    def _flash_remy_ship(self, ship):
        buttons = [self.remy_cells[r][c] for r, c in ship["cells"]]
        self._flash_buttons(buttons)

    def _flash_buttons(self, buttons):
        for btn in buttons:
            effect = QGraphicsColorizeEffect(btn)
            effect.setColor(QColor("#FF7A00"))
            effect.setStrength(0.0)
            btn.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b"strength", btn)
            anim.setDuration(420)
            anim.setStartValue(0.0)
            anim.setKeyValueAt(0.5, 1.0)
            anim.setEndValue(0.0)
            anim.finished.connect(lambda b=btn: b.setGraphicsEffect(None))
            anim.start()
            self._anims.append(anim)

    def _on_cell_hover(self, r, c):
        self._clear_preview()
        if self.phase != "battle" or self.waiting:
            return
        if r is None:
            return
        mode = self.action_mode or self._active_player_special()
        if mode is None:
            return
        area = _special_area(mode, r, c)
        self._preview_cells = set(area)
        for rr, cc in area:
            self.remy_cells[rr][cc].set_preview(True)

    def _clear_preview(self):
        for rr, cc in self._preview_cells:
            self.remy_cells[rr][cc].set_preview(False)
        self._preview_cells = set()

    # ============================================================
    #  图鉴
    # ============================================================

    def show_codex(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("📖 星海舰体图鉴")
        dialog.setStyleSheet("background-color: #ffffff; color: #333333; font-family: Microsoft YaHei;")
        v = QVBoxLayout(dialog)
        title = QLabel("📖 星海舰体图鉴")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #3E5A8A;")
        v.addWidget(title)
        for key in rules.SHIP_ORDER:
            t = rules.SHIP_TYPES[key]
            cells, weak = ship_canonical(key)
            row = QHBoxLayout()
            shape = ShipShapeWidget(cells, weak, cell_size=22,
                                    color=ship_color(key))
            row.addWidget(shape)
            info = QLabel(
                f"<b>{t['name']}</b>（{t['size']} 格，最多 ×{t['max_count']}）<br>"
                f"<span style='color:#B07A2B;'>弱点：{WEAK_DESC[key]}</span><br>"
                f"<span style='color:#666666;'>{t['trait']}</span>"
            )
            info.setWordWrap(True)
            info.setTextFormat(Qt.RichText)
            row.addWidget(info, 1)
            v.addLayout(row)
        close = QPushButton("关闭")
        close.clicked.connect(dialog.accept)
        v.addWidget(close)
        dialog.exec_()

    # ============================================================
    #  结算与战报
    # ============================================================

    def _game_over(self, player_won):
        self.phase = "over"
        self.waiting = False
        self._token += 1
        self._clear_preview()
        self._reveal_remy_board()
        self._render_player_board()
        self._refresh_side_panels()
        self._sync_controls()
        self._request_summary(player_won)
        if player_won:
            self.status_label.setText("🎉 你击毁了蕾咪的全部星舰！")
            self.bubble.setText(f"蕾咪：{LOCAL_WIN_LINE}")
            QMessageBox.information(self, "🎉 胜利", "你击毁了蕾咪的全部星舰！\n\n蕾咪：才、才不是让你的！")
        else:
            self.status_label.setText("💥 蕾咪击毁了你的全部星舰！")
            self.bubble.setText(f"蕾咪：{LOCAL_LOSE_LINE}")
            QMessageBox.information(self, "💥 败北", "你的星舰被蕾咪全歼了…\n\n蕾咪：哼哼，这就是实力差距～")

    def _request_summary(self, player_won):
        self._token += 1
        token = self._token
        self._summary_delivered = False
        self._summary_player_won = player_won
        result_text = (
            "调查员击毁了你的全部星舰，你输了" if player_won
            else "你击毁了调查员的全部星舰，你赢了"
        )
        prompt = SUMMARY_PROMPT.format(result=result_text, rounds=self.rounds)
        messages = (
            [{"role": "system", "content": self._system_prompt}]
            + list(self.game_history)
            + [{"role": "user", "content": prompt}]
        )
        threading.Thread(
            target=self._summary_worker,
            args=(messages, token),
            daemon=True,
        ).start()

    def _summary_worker(self, messages, token):
        api_cfg = config.CONFIG.get("api", {})
        for attempt in range(2):
            if attempt == 0:
                provider_id = api_cfg.get("primary", "")
                api_key = api_cfg.get("primary_key", "")
            else:
                provider_id = api_cfg.get("backup", "")
                api_key = api_cfg.get("backup_key", "")
                if not api_key:
                    break
            if not api_key:
                continue
            provider = config.API_PROVIDERS.get(provider_id)
            if not provider:
                continue
            try:
                payload = apply_thinking_request(
                    provider,
                    {
                        "model": provider["model"],
                        "messages": messages,
                        "temperature": 0.9,
                        "max_tokens": 100,
                    },
                    enabled=False,
                )
                response = requests.post(
                    provider["url"],
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=20,
                )
                if response.status_code == 200:
                    reply = response.json()["choices"][0]["message"].get("content") or ""
                    if reply.strip():
                        self.summary_ready.emit(reply, token)
                        return
            except Exception as e:
                print(f"[Remy Debug] [星海战棋] 战报生成异常: {type(e).__name__}: {e}")
        self.summary_failed.emit(token)

    def _on_summary_ready(self, reply, token):
        if token != self._token or self._summary_delivered:
            return
        text = " ".join(reply.split())
        self._deliver_summary(text)

    def _on_summary_failed(self, token):
        if token != self._token or self._summary_delivered:
            return
        if self._summary_player_won:
            text = (
                f"呜…刚才那局星海战棋打了{self.rounds}回合，蕾咪的星舰全军覆没……"
                "才、才不是实力不如你！下次蕾咪一定会赢回来的，等着瞧！"
            )
        else:
            text = (
                f"哼哼，刚才那局星海战棋，蕾咪{self.rounds}回合就把你的星舰全歼啦！"
                "这就是阿斯忒瑞亚号舰长的实力～想复仇的话随时奉陪哦！"
            )
        self._deliver_summary(text)

    def _deliver_summary(self, text):
        if self._summary_delivered:
            return
        self._summary_delivered = True
        config.CONVERSATION_HISTORY.append({
            "time": config.get_timestamp(),
            "role": "Remy",
            "content": text,
        })
        config.save_conversation()
        pet = self.parent()
        if pet is not None and hasattr(pet, "show_typed_message"):
            pet.show_typed_message(text)
