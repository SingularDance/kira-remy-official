# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 星海战棋小游戏（确定性 AI）

10x10 棋盘：AI 方舰体总格 33、每回合最多 3 次炮击；玩家方 22 格、每回合 1 次炮击。
舰体分「弱点部位 / 普通部位」：命中弱点立即击毁，命中普通累计损失，打光全格也击毁。
双方各 6 类舰体（形状/弱点/特性不同），带图鉴、道具、特殊炮击、先手抽取动画、
播报窗口与历史记录。所有规则在 star_battleship_rules 纯逻辑模块中，本文件只负责
UI 与交互。AI 为确定性启发式（无 LLM），配合「固定 3 秒结束回合」。
"""

import math
import random
import time

from PyQt5.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QWidget, QFrame, QScrollArea, QMessageBox, QListWidget,
    QListWidgetItem, QGraphicsOpacityEffect,
)
from PyQt5.QtCore import Qt, QTimer, QPointF, QRectF, QPropertyAnimation
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QPolygonF, QCursor, QPixmap, QPainterPath

import star_battleship_rules as R
from utils import resource_path

SIZE = R.SIZE
CELL = 30

# 炮击 / 道具两大类
SHOT_MODES = {None, "laser_alpha", "laser_beta", "phase_gamma"}
ITEM_MODES = {"scan", "phase_theta", "volley"}

ITEM_LABELS = {
    "scan": "🔍 扫描",
    "volley": "💥 齐射",
    "laser_alpha": "📏 激光α",
    "laser_beta": "📐 激光β",
    "phase_gamma": "🌀 相位γ",
    "phase_theta": "🔭 相位θ",
}

SEA_COLOR = "#A8D8E8"
MISS_COLOR = "#E8F4F8"          # 浅蓝（与海战棋的「落空」同色）
SUNK_COLOR = "#C0392B"          # 红叉
LATEST_SHOT_COLOR = "#FFC107"   # 蕾咪最新炮击描边高亮
SHOT_ANIM_COLOR = "#FF6D00"     # 炮击动效（内缩/放大/闪烁）边框色
SCAN_ANIM_COLOR = "#00ACC1"     # 扫描动效（画圆/闪烁）边框色

_FLASH_RED = True               # 击沉舰体边框闪烁相位（红 / 暗红交替）
FLASH_RED = "#E53935"           # 闪烁·红
FLASH_RED_DARK = "#8B1A1A"      # 闪烁·暗红


def _hexagon_points(rect):
    cx = rect.center().x()
    cy = rect.center().y()
    radius = min(rect.width(), rect.height()) / 2 - 3
    pts = []
    for i in range(6):
        ang = math.radians(60 * i - 30)
        pts.append(QPointF(cx + radius * math.cos(ang), cy + radius * math.sin(ang)))
    return QPolygonF(pts)


def _draw_cross(painter, rect):
    """命中/击毁红叉：先画白色描边再画红叉，确保在任意舰体颜色上都可见。"""
    painter.setPen(QPen(QColor("#FFFFFF"), 5))
    painter.drawLine(rect.topLeft(), rect.bottomRight())
    painter.drawLine(rect.topRight(), rect.bottomLeft())
    painter.setPen(QPen(QColor(SUNK_COLOR), 3))
    painter.drawLine(rect.topLeft(), rect.bottomRight())
    painter.drawLine(rect.topRight(), rect.bottomLeft())


def _draw_hexagon(painter, rect, solid=True):
    """弱点六边形：实心（白底深描边）或空心（仅白描边）。"""
    poly = _hexagon_points(rect)
    if solid:
        painter.setBrush(QBrush(QColor(255, 255, 255, 210)))
        painter.setPen(QPen(QColor("#333333"), 1.5))
    else:
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor("#FFFFFF"), 2))
    painter.drawPolygon(poly)


class BoardCell(QWidget):
    """自绘格子：背景色 + 弱点六边形 + 击毁红叉 + 悬停预览。"""

    def __init__(self, row, col, click_cb=None, hover_cb=None):
        super().__init__()
        self.row = row
        self.col = col
        self.click_cb = click_cb
        self.hover_cb = hover_cb
        self.setFixedSize(CELL, CELL)
        self.setMouseTracking(True)
        self._state = "sea"
        self._color = None
        self._weak_marker = None
        self.preview = False
        self._latest_shot = False
        self._flash = False
        self._shot_anim_scale = None   # 炮击动效：边框缩放（None=无动效）
        self._shot_anim_visible = True
        self._scan_anim = None         # 扫描动效：(phase, param, cx, cy, radius)

    def set_state(self, state, color=None, weak_marker=None, flash=False):
        self._state = state
        self._color = color
        self._weak_marker = weak_marker
        self._flash = flash
        self.update()

    def set_preview(self, flag):
        if self.preview != flag:
            self.preview = flag
            self.update()

    def set_latest_shot(self, flag):
        if self._latest_shot != flag:
            self._latest_shot = flag
            self.update()

    def set_shot_anim(self, scale, visible=True):
        self._shot_anim_scale = scale
        self._shot_anim_visible = visible
        self.update()

    def set_scan_anim(self, phase, param, cx, cy, radius):
        self._scan_anim = None if phase is None else (phase, param, cx, cy, radius)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        state = self._state

        # 1. 背景：海域 / 落空(浅蓝) / 扫描提示 / 舰体颜色（命中与击毁也显示舰体颜色）
        if state == "miss":
            painter.setBrush(QColor(MISS_COLOR))
        elif state == "scan_ship":
            painter.setBrush(QColor("#E8B4D8"))
        elif state == "scan_empty":
            painter.setBrush(QColor("#D8C9E8"))
        elif state in ("ship", "reveal", "hit", "sunk"):
            painter.setBrush(QColor(self._color or SEA_COLOR))
        else:  # sea
            painter.setBrush(QColor(SEA_COLOR))
        painter.setPen(QPen(QColor("#8FC3D8"), 1))
        painter.drawRect(rect)

        # 2. 弱点标记：存活/揭示舰体用实心；被击沉舰体用实心（有弱点）或空心（无弱点）
        if self._weak_marker == "solid":
            _draw_hexagon(painter, rect, solid=True)
        elif self._weak_marker == "hollow":
            _draw_hexagon(painter, rect, solid=False)

        # 3. 命中 / 击毁红叉（白描边 + 红叉，叠在舰体颜色上）
        if state in ("hit", "sunk"):
            _draw_cross(painter, rect)

        # 4. 落空 / 扫描标记
        if state == "miss":
            painter.setPen(QPen(QColor("#7AA5B8"), 2))
            painter.drawEllipse(rect.center(), 5, 5)
        elif state == "scan_ship":
            painter.setPen(QPen(QColor("#A03070"), 1))
            painter.drawText(rect, Qt.AlignCenter, "⚑")
        elif state == "scan_empty":
            painter.setPen(QPen(QColor("#8A7AA5"), 1))
            painter.drawText(rect, Qt.AlignCenter, "·")

        # 5. 悬停预览
        if self.preview:
            painter.fillRect(rect, QColor(255, 200, 0, 80))
            painter.setPen(QPen(QColor("#DAAD69"), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)

        # 6. 蕾咪最新炮击描边（置顶高亮，仅描边不填充，避免盖住红叉）
        if self._latest_shot:
            painter.setPen(QPen(QColor(LATEST_SHOT_COLOR), 3))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)

        # 7. 击沉舰体边框闪烁（红 / 暗红交替，持续 2 秒）
        if state == "sunk" and self._flash:
            color = FLASH_RED if _FLASH_RED else FLASH_RED_DARK
            painter.setPen(QPen(QColor(color), 3))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)

        # 8. 炮击动效：内缩边框（0.5s 缩到内部 → 0.01s 放大回满 → 闪烁两下）
        if self._shot_anim_scale is not None and self._shot_anim_visible:
            s = self._shot_anim_scale
            dx = int((1 - s) * rect.width() / 2)
            dy = int((1 - s) * rect.height() / 2)
            inner = rect.adjusted(dx, dy, -dx, -dy)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(SHOT_ANIM_COLOR), 3))
            painter.drawRect(inner)

        # 9. 扫描动效：从正方形上顶点顺时针画圆（0.5s）→ 消失（0.01s）→ 边框闪两下
        if self._scan_anim is not None:
            phase, param, cx, cy, radius = self._scan_anim
            if phase == "circle":
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor(SCAN_ANIM_COLOR), 2))
                brect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
                painter.drawArc(brect, 90 * 16, int(-param * 360 * 16))
            elif phase == "flash" and param:
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor(SCAN_ANIM_COLOR), 3))
                painter.drawRect(rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.click_cb:
            self.click_cb(self.row, self.col)

    def enterEvent(self, event):
        if self.hover_cb:
            self.hover_cb(self.row, self.col)
        super().enterEvent(event)


class BoardFrame(QFrame):
    """棋盘外框：鼠标移出时清空悬停预览，并承载回合描边高亮。"""

    def __init__(self, leave_cb=None, parent=None):
        super().__init__(parent)
        self.leave_cb = leave_cb

    def leaveEvent(self, event):
        if self.leave_cb:
            self.leave_cb()
        super().leaveEvent(event)


class ShipShapeWidget(QWidget):
    """绘制一艘舰体的规范形状（含弱点六边形），用于名册与图鉴。"""

    def __init__(self, side, key, cell=13, parent=None):
        super().__init__(parent)
        self.t = R.SHIP_TYPES[side][key]
        cells = self.t["cells"]
        max_r = max(r for r, _ in cells)
        max_c = max(c for _, c in cells)
        self._cell = cell
        self.setFixedSize((max_c + 1) * cell, (max_r + 1) * cell)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        weak = self.t["weak_cell"]
        for r, c in self.t["cells"]:
            rect = QRectF(c * self._cell, r * self._cell,
                          self._cell - 2, self._cell - 2)
            painter.setBrush(QColor(self.t["color"]))
            painter.setPen(QPen(QColor("#333333"), 1))
            painter.drawRect(rect)
            if (r, c) == weak:
                painter.setBrush(QBrush(QColor(255, 255, 255, 200)))
                painter.setPen(QPen(QColor("#333333"), 1.5))
                painter.drawPolygon(_hexagon_points(rect))


class ShipCodexDialog(QDialog):
    """图鉴：展示双方 12 类舰体的名字、形状、弱点与特性。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📖 星海战棋 · 舰体图鉴")
        self.setGeometry(150, 80, 720, 640)
        self.setStyleSheet("background-color: #ffffff; color: #333333; font-family: Microsoft YaHei;")

        layout = QVBoxLayout(self)
        title = QLabel("📖 舰体图鉴")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #DAAD69;")
        layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)

        for side, side_name in (("ai", "蕾咪舰队"), ("player", "我方舰队")):
            header = QLabel(f"—— {side_name} ——")
            header.setStyleSheet("font-size: 14px; font-weight: bold; color: #2E6C8E;")
            content_layout.addWidget(header)
            for key in R.SHIP_KEYS:
                t = R.SHIP_TYPES[side][key]
                row = QHBoxLayout()
                row.addWidget(ShipShapeWidget(side, key))
                info = QLabel(f"{t['name']}　【{t['trait_name']}】")
                info.setStyleSheet("font-size: 13px; font-weight: bold;")
                desc = QLabel(t["trait"])
                desc.setWordWrap(True)
                desc.setStyleSheet("color: #666666; font-size: 12px;")
                text_col = QVBoxLayout()
                text_col.addWidget(info)
                text_col.addWidget(desc)
                row.addLayout(text_col, 1)
                row.addStretch()
                content_layout.addLayout(row)
        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet(
            "QPushButton { background-color: #333333; color: white; border: none;"
            " border-radius: 6px; padding: 8px 24px; font-size: 13px; }"
            "QPushButton:hover { background-color: #555555; }")
        layout.addWidget(close_btn, alignment=Qt.AlignCenter)


class StarBattleshipDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🛸 星海战棋")
        self.setGeometry(60, 30, 1220, 880)
        self.setStyleSheet("background-color: #ffffff; color: #333333; font-family: Microsoft YaHei;")
        self.init_game()
        self.init_ui()

        # 击沉舰体边框闪烁定时器（首次击沉时启动，2 秒后自动停止）
        self._sunk_flash_timer = QTimer(self)
        self._sunk_flash_timer.timeout.connect(self._sunk_flash_tick)
        self._sunk_flash_timer.setInterval(200)

        # 炮击动效定时器（有炮击时启动，动效结束后自动停止）
        self._shot_anim_timer = QTimer(self)
        self._shot_anim_timer.timeout.connect(self._shot_anim_tick)
        self._shot_anim_timer.setInterval(30)

        # 扫描动效定时器（有扫描时启动，动效结束后自动停止）
        self._scan_anim_timer = QTimer(self)
        self._scan_anim_timer.timeout.connect(self._scan_anim_tick)
        self._scan_anim_timer.setInterval(30)

        # 舰体特性悬浮窗（悬停显示，移出淡出隐藏）
        self._init_ship_tooltip()

    def _init_ship_tooltip(self):
        self.ship_tip = QLabel(self)
        self.ship_tip.setStyleSheet(
            "background-color: rgba(40, 40, 40, 235); color: #FFFFFF;"
            " border: 1px solid #DAAD69; border-radius: 6px; padding: 6px 10px;"
            " font-size: 12px;")
        self.ship_tip.setWordWrap(False)
        self.ship_tip_effect = QGraphicsOpacityEffect(self.ship_tip)
        self.ship_tip.setGraphicsEffect(self.ship_tip_effect)
        self.ship_tip_effect.setOpacity(0.0)
        self.ship_tip.hide()
        self._tip_anim = QPropertyAnimation(self.ship_tip_effect, b"opacity", self)
        self._tip_anim.setDuration(260)
        self._tip_anim.finished.connect(self._on_tip_fade_finished)

    # ============================================================
    #  状态
    # ============================================================

    def init_game(self):
        self.phase = "placement"          # placement → coinflip → battle → over
        self.current = "player"
        self.waiting = False
        self.round = 1
        self.action_mode = None
        self.side_first = "player"

        self.player_shots = set()         # 玩家在 AI 棋盘上的炮击格
        self.ai_shots = set()             # AI 在玩家棋盘上的炮击格
        self.ai_latest_shot = set()       # 蕾咪本回合的所有炮击格（玩家棋盘描边高亮）
        self.player_scanned = {}          # 玩家对 AI 棋盘的扫描结果 pos->bool

        self.player_items = {}

        self._shots_remaining = 0
        self._items_remaining = 0
        self._extra_shot_used = False
        self._pending_ai_specials = []

        self._coin_timer = None
        self._coin_ticks = 0

        # 本局双方舰体数：AI 3~6 随机抽取，玩家按对应关系 6~9
        self.ai_ship_count = R.draw_ship_count()
        self.player_ship_count = R.player_ship_count_for(self.ai_ship_count)

        self._sunk_ships = {}             # 已击沉舰体 id -> 击沉时刻（用于边框闪烁）
        self._shot_effects = []           # 炮击动效：{board, cells, start}
        self._scan_effects = []           # 扫描动效：{cells, r0, c0, k, start}

        self._deploy_ai()
        self._deploy_player()

    def _deploy_ai(self):
        self.ai_fleet = R.generate_fleet("ai", ship_count=self.ai_ship_count)
        self.ai_board, self.ai_ships = R.place_fleet("ai", self.ai_fleet)
        R.apply_deploy_traits(self.ai_ships, "ai")

    def _deploy_player(self):
        self.player_fleet = R.generate_fleet("player", ship_count=self.player_ship_count)
        self.player_board, self.player_ships = R.place_fleet("player", self.player_fleet)
        R.apply_deploy_traits(self.player_ships, "player")
        self._init_player_items()

    def _init_player_items(self):
        self.player_items = {"scan": 2, "volley": 2, "laser_alpha": 0,
                             "laser_beta": 0, "phase_gamma": 0, "phase_theta": 0}
        for s in self.player_ships:
            if s["type"] == "destroyer":
                if R.has_adjacent_ship(s, self.player_ships):
                    self.player_items["laser_alpha"] += 1
                else:
                    self.player_items["laser_beta"] += 1
        if R.has_alive(self.player_ships, "command"):
            self.player_items["phase_theta"] += 1
        if R.has_alive(self.player_ships, "flagship"):
            self.player_items["phase_gamma"] += 1

    # ============================================================
    #  UI
    # ============================================================

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(14, 14, 14, 14)

        # 顶部：标题 + 回合指示
        top = QHBoxLayout()
        title = QLabel("🛸 星海战棋")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #DAAD69;")
        self.turn_label = QLabel("布阵阶段")
        self.turn_label.setAlignment(Qt.AlignCenter)
        self.turn_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #2E6C8E;")
        top.addWidget(title)
        top.addStretch()
        top.addWidget(self.turn_label)
        layout.addLayout(top)

        # 双方舰体数 / 每回合炮击次数（动态）
        self.info_label = QLabel("")
        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setStyleSheet("font-size: 12px; color: #555555;")
        layout.addWidget(self.info_label)

        # 播报窗口（中间上方）
        self.broadcast_label = QLabel("")
        self.broadcast_label.setAlignment(Qt.AlignCenter)
        self.broadcast_label.setWordWrap(True)
        self.broadcast_label.setMinimumHeight(40)
        self.broadcast_label.setStyleSheet(
            "background-color: #FFF6E8; color: #8A6D3B; border: 1px solid #DAAD69;"
            " border-radius: 8px; padding: 8px 12px; font-size: 14px; font-weight: bold;")
        layout.addWidget(self.broadcast_label)

        # 中央提示（思考中 / 布阵指引 / 先手动画）
        self.center_label = QLabel("布阵阶段：点击「重新随机」调整舰队，满意后点「开战」")
        self.center_label.setAlignment(Qt.AlignCenter)
        self.center_label.setStyleSheet("font-size: 13px; color: #666666;")
        layout.addWidget(self.center_label)

        # 棋盘区：AI名册 | AI棋盘 | 玩家棋盘 | 玩家名册
        boards = QHBoxLayout()
        boards.setSpacing(12)
        boards.addStretch()
        boards.addWidget(self._build_remy_passive())
        self.ai_roster_frame, self.ai_roster_labels = self._build_roster("蕾咪舰队")
        boards.addWidget(self.ai_roster_frame)

        self.ai_cells, self.ai_board_frame = self._build_board(
            "🌊 蕾咪的海域", self._on_ai_cell_click, self._on_ai_cell_hover, self._on_board_leave)
        boards.addWidget(self.ai_board_frame)

        self.player_cells, self.player_board_frame = self._build_board(
            "⚓ 你的海域", None, self._on_player_cell_hover, self._on_board_leave)
        boards.addWidget(self.player_board_frame)

        self.player_roster_frame, self.player_roster_labels = self._build_roster("我的舰队")
        boards.addWidget(self.player_roster_frame)
        boards.addStretch()
        layout.addLayout(boards)

        # 道具按钮（左侧：本回合剩余炮击 / 道具次数）
        item_layout = QHBoxLayout()
        item_layout.setSpacing(8)
        self.action_counter_label = QLabel("")
        self.action_counter_label.setAlignment(Qt.AlignCenter)
        self.action_counter_label.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #2E6C8E;"
            " background-color: #EEF6FB; border: 1px solid #BBD6E8;"
            " border-radius: 6px; padding: 6px 10px;")
        item_layout.addWidget(self.action_counter_label)
        item_layout.addStretch()
        self.item_buttons = {}
        for key, label in ITEM_LABELS.items():
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setEnabled(False)
            btn.setStyleSheet(self._item_btn_qss())
            btn.clicked.connect(lambda checked, k=key: self._set_mode(k))
            self.item_buttons[key] = btn
            item_layout.addWidget(btn)
        item_layout.addStretch()
        layout.addLayout(item_layout)

        # 操作按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()
        self.end_btn = QPushButton("⏭ 结束回合")
        self.end_btn.clicked.connect(self._end_player_turn)
        self.reroll_btn = QPushButton("🎲 重新随机")
        self.reroll_btn.clicked.connect(self._reroll_player)
        self.start_btn = QPushButton("⚔️ 开战！")
        self.start_btn.clicked.connect(self._start_coinflip)
        self.new_btn = QPushButton("🔄 新游戏")
        self.new_btn.clicked.connect(self._new_game)
        self.codex_btn = QPushButton("📖 图鉴")
        self.codex_btn.clicked.connect(self._open_codex)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        for btn in (self.end_btn, self.reroll_btn, self.start_btn,
                    self.new_btn, self.codex_btn, close_btn):
            btn.setStyleSheet(self._action_btn_qss())
            btn_layout.addWidget(btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # 历史记录（左下）
        self.history_list = QListWidget()
        self.history_list.setMaximumHeight(150)
        self.history_list.setStyleSheet(
            "QListWidget { border: 1px solid #DDD; border-radius: 6px; font-size: 12px; }")
        layout.addWidget(self.history_list)

        self.setLayout(layout)
        self.end_btn.setEnabled(False)
        self._render_player_board()
        self._render_ai_board()
        self._render_rosters()
        self._sync_item_buttons()

    @staticmethod
    def _item_btn_qss():
        return """
            QPushButton {
                background-color: #2E6C8E; color: white; border: none;
                border-radius: 6px; padding: 7px 12px; font-size: 12px;
            }
            QPushButton:hover { background-color: #3E7C9E; }
            QPushButton:checked { background-color: #DAAD69; }
            QPushButton:disabled { background-color: #999999; }
        """

    @staticmethod
    def _action_btn_qss():
        return """
            QPushButton {
                background-color: #333333; color: white; border: none;
                border-radius: 6px; padding: 8px 16px; font-size: 13px;
            }
            QPushButton:hover { background-color: #555555; }
            QPushButton:disabled { background-color: #999999; }
        """

    def _build_board(self, caption, click_cb, hover_cb, leave_cb):
        frame = BoardFrame(leave_cb)
        frame.setStyleSheet("QFrame { border: 3px solid transparent; border-radius: 8px; }")
        v = QVBoxLayout(frame)
        v.setContentsMargins(6, 6, 6, 6)
        label = QLabel(caption)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size: 13px; font-weight: bold; color: #2E6C8E;")
        v.addWidget(label)

        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setSpacing(2)
        grid.setContentsMargins(2, 2, 2, 2)
        for c in range(SIZE):
            hdr = QLabel(R.col_name(c))
            hdr.setAlignment(Qt.AlignCenter)
            hdr.setFixedSize(CELL, 16)
            hdr.setStyleSheet("color: #2E6C8E; font-weight: bold; font-size: 10px;")
            grid.addWidget(hdr, 0, c + 1)
        cells = []
        for r in range(SIZE):
            hdr = QLabel(str(r + 1))
            hdr.setAlignment(Qt.AlignCenter)
            hdr.setFixedSize(16, CELL)
            hdr.setStyleSheet("color: #2E6C8E; font-weight: bold; font-size: 10px;")
            grid.addWidget(hdr, r + 1, 0)
            row_cells = []
            for c in range(SIZE):
                cell = BoardCell(r, c, click_cb, hover_cb)
                grid.addWidget(cell, r + 1, c + 1)
                row_cells.append(cell)
            cells.append(row_cells)
        v.addWidget(grid_widget, alignment=Qt.AlignCenter)
        return cells, frame

    def _build_roster(self, title):
        # 名册不再加外框：仅一个标题 + 若干舰名标签，避免与舰体数产生歧义
        frame = QWidget()
        frame.setFixedWidth(120)
        v = QVBoxLayout(frame)
        v.setContentsMargins(6, 8, 6, 8)
        v.setSpacing(2)
        t = QLabel(title)
        t.setAlignment(Qt.AlignCenter)
        t.setStyleSheet("font-size: 12px; font-weight: bold; color: #2E6C8E;")
        v.addWidget(t)
        return frame, []

    def _build_remy_passive(self):
        """蕾咪圆形头像 + 【沉稳】被动说明（弹窗左侧）。"""
        widget = QWidget()
        widget.setFixedWidth(120)
        v = QVBoxLayout(widget)
        v.setContentsMargins(6, 8, 6, 8)
        v.setSpacing(6)
        v.addStretch()

        avatar = QLabel()
        avatar.setFixedSize(96, 96)
        avatar.setPixmap(self._circular_pixmap("Remy_Shut.png", 96))
        avatar.setAlignment(Qt.AlignCenter)
        v.addWidget(avatar, alignment=Qt.AlignCenter)

        desc = QLabel("【沉稳】\n每回合额外\n齐射一次（2×2）")
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet("font-size: 11px; font-weight: bold; color: #2E6C8E;")
        v.addWidget(desc, alignment=Qt.AlignCenter)
        v.addStretch()
        return widget

    @staticmethod
    def _circular_pixmap(path, size):
        """把图片裁成 size×size 的圆形 QPixmap（居中裁剪 + 椭圆裁剪）。"""
        pm = QPixmap(resource_path(path))
        if pm.isNull():
            pm = QPixmap(size, size)
            pm.fill(QColor("#DAAD69"))
        pm = pm.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = (pm.width() - size) // 2
        y = (pm.height() - size) // 2
        pm = pm.copy(x, y, size, size)
        out = QPixmap(size, size)
        out.fill(Qt.transparent)
        painter = QPainter(out)
        painter.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addEllipse(0, 0, size, size)
        painter.setClipPath(clip)
        painter.drawPixmap(0, 0, pm)
        painter.end()
        return out

    # ============================================================
    #  渲染
    # ============================================================

    def _render_player_board(self):
        for r in range(SIZE):
            for c in range(SIZE):
                cell = self.player_cells[r][c]
                pos = (r, c)
                ship = self._find_ship(self.player_ships, pos)
                if ship is None:
                    cell.set_state("miss" if pos in self.ai_shots else "sea")
                elif not ship["alive"]:
                    cell.set_state("sunk", ship["color"], self._sunk_weak_marker(ship, pos),
                                   flash=id(ship) in self._sunk_ships)
                elif pos in ship["hits"]:
                    cell.set_state("hit", ship["color"])
                else:
                    cell.set_state("ship", ship["color"],
                                   "solid" if pos in ship["weak_cells"] else None)
                cell.set_latest_shot(pos in self.ai_latest_shot)

    def _render_ai_board(self):
        reveal = self.phase == "over"
        for r in range(SIZE):
            for c in range(SIZE):
                cell = self.ai_cells[r][c]
                pos = (r, c)
                ship = self._find_ship(self.ai_ships, pos)
                if pos in self.player_shots:
                    if ship is None:
                        cell.set_state("miss")
                    elif not ship["alive"]:
                        cell.set_state("sunk", ship["color"], self._sunk_weak_marker(ship, pos),
                                   flash=id(ship) in self._sunk_ships)
                    else:
                        cell.set_state("hit", ship["color"])
                elif reveal and ship is not None:
                    cell.set_state("reveal", ship["color"],
                                   "solid" if pos in ship["weak_cells"] else None)
                elif pos in self.player_scanned:
                    cell.set_state("scan_ship" if self.player_scanned[pos] else "scan_empty")
                else:
                    cell.set_state("sea")

    def _render_rosters(self):
        self._refresh_roster(self.ai_ships, self.ai_roster_labels, self.ai_roster_frame)
        self._refresh_roster(self.player_ships, self.player_roster_labels,
                             self.player_roster_frame)
        self._update_info_label()

    def _update_info_label(self):
        ai_alive = sum(1 for s in self.ai_ships if s["alive"])
        pl_alive = sum(1 for s in self.player_ships if s["alive"])
        ai_shots = 1 + (1 if R.has_alive(self.ai_ships, "command") else 0) \
                     + (1 if R.has_alive(self.ai_ships, "flagship") else 0)
        pl_shots = self._shots_per_turn() \
                   + (1 if R.has_alive(self.player_ships, "flagship") else 0)
        self.info_label.setText(
            f"🛸 蕾咪舰队 {ai_alive}/{self.ai_ship_count} 艘 · 每回合 💥×{ai_shots}＋【沉稳】齐射"
            f"　　⚓ 我方舰队 {pl_alive}/{self.player_ship_count} 艘 · 每回合 💥×{pl_shots}")

    def _refresh_roster(self, ships, labels, frame):
        # 名册容器：标题之后的竖直布局
        v = frame.layout()
        # 移除旧的舰体标签（保留标题）
        for lab in labels:
            v.removeWidget(lab)
            lab.deleteLater()
        labels.clear()
        for ship in ships:
            text = ship["name"] + ("  ✕" if not ship["alive"] else "")
            lab = QLabel(text)
            lab.setAlignment(Qt.AlignCenter)
            color = "#C0392B" if not ship["alive"] else ship["color"]
            lab.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: bold;")
            labels.append(lab)
            v.addWidget(lab)

    def _note_sunk(self, ship):
        """记录一艘舰体被击沉的时刻，并启动边框闪烁定时器。"""
        self._sunk_ships[id(ship)] = time.monotonic()
        if not self._sunk_flash_timer.isActive():
            self._sunk_flash_timer.start()

    def _sunk_flash_tick(self):
        """击沉舰体边框闪烁：翻转红/暗红相位，2 秒后自动移除闪烁。"""
        global _FLASH_RED
        _FLASH_RED = not _FLASH_RED
        now = time.monotonic()
        for sid in list(self._sunk_ships):
            if now - self._sunk_ships[sid] >= 2.0:
                del self._sunk_ships[sid]
        self._render_player_board()
        self._render_ai_board()
        if not self._sunk_ships:
            self._sunk_flash_timer.stop()

    # ============================================================
    #  炮击动效
    # ============================================================

    def _record_shot_effect(self, board, cells):
        """记录一次炮击的动效（board: 'player' 或 'ai'，表示落在哪块棋盘）。"""
        self._shot_effects.append({
            "board": board,
            "cells": set(cells),
            "start": time.monotonic(),
        })
        if not self._shot_anim_timer.isActive():
            self._shot_anim_timer.start()

    @staticmethod
    def _shot_anim_state(t):
        """由经过时间 t 计算动效状态，返回 (scale, visible)；结束返回 None。

        阶段：0~0.5s 边框从满缩到 0.3；0.5~0.51s 快速放大回满；之后闪烁两下。
        """
        shrink = 0.5
        expand = 0.01
        blink_on = 0.12
        blink_off = 0.12
        if t < shrink:
            return 1.0 - 0.7 * (t / shrink), True
        if t < shrink + expand:
            return 0.3 + 0.7 * ((t - shrink) / expand), True
        bt = t - (shrink + expand)
        cycle = blink_on + blink_off
        if bt < 2 * cycle:
            return 1.0, (bt % cycle) < blink_on
        return None

    def _shot_anim_tick(self):
        """驱动炮击动效：更新每格的缩放/可见性，动效结束后清理并停表。"""
        now = time.monotonic()
        remaining = []
        for eff in self._shot_effects:
            t = now - eff["start"]
            grid = self.player_cells if eff["board"] == "player" else self.ai_cells
            state = self._shot_anim_state(t)
            if state is None:
                for r, c in eff["cells"]:
                    grid[r][c].set_shot_anim(None)
            else:
                scale, visible = state
                for r, c in eff["cells"]:
                    grid[r][c].set_shot_anim(scale, visible)
                remaining.append(eff)
        self._shot_effects = remaining
        if not self._shot_effects:
            self._shot_anim_timer.stop()

    def _record_scan_effect(self, cells):
        """记录一次扫描的动效（扫描作用于蕾咪棋盘，即 ai_cells）。"""
        cells = list(cells)
        if not cells:
            return
        r0 = min(r for r, _ in cells)
        c0 = min(c for _, c in cells)
        k = len({r for r, _ in cells})
        self._scan_effects.append({
            "cells": set(cells),
            "r0": r0,
            "c0": c0,
            "k": k,
            "start": time.monotonic(),
        })
        if not self._scan_anim_timer.isActive():
            self._scan_anim_timer.start()

    @staticmethod
    def _scan_anim_state(t):
        """由经过时间 t 计算扫描动效状态，返回 (phase, param)；结束返回 None。

        阶段：0~0.5s 从正方形上顶点顺时针画圆；0.5~0.51s 圆消失；之后边框闪两下。
        """
        sweep = 0.5
        vanish = 0.01
        flash_on = 0.12
        flash_off = 0.12
        if t < sweep:
            return ("circle", t / sweep)
        if t < sweep + vanish:
            return ("vanish", None)
        bt = t - (sweep + vanish)
        cycle = flash_on + flash_off
        if bt < 2 * cycle:
            return ("flash", (bt % cycle) < flash_on)
        return None

    def _scan_anim_tick(self):
        """驱动扫描动效：更新每格画圆/闪烁状态，动效结束后清理并停表。"""
        now = time.monotonic()
        remaining = []
        for eff in self._scan_effects:
            t = now - eff["start"]
            state = self._scan_anim_state(t)
            r0, c0, k = eff["r0"], eff["c0"], eff["k"]
            if state is None:
                for r, c in eff["cells"]:
                    self.ai_cells[r][c].set_scan_anim(None, None, 0, 0, 0)
            else:
                phase, param = state
                for r, c in eff["cells"]:
                    cx = (c0 + k / 2 - c) * CELL
                    cy = (r0 + k / 2 - r) * CELL
                    radius = (k / 2) * CELL
                    self.ai_cells[r][c].set_scan_anim(phase, param, cx, cy, radius)
                remaining.append(eff)
        self._scan_effects = remaining
        if not self._scan_effects:
            self._scan_anim_timer.stop()

    # ============================================================
    #  道具与模式
    # ============================================================

    def _set_mode(self, key):
        if self.phase != "battle" or self.current != "player" or self.waiting:
            self._sync_item_buttons()
            return
        if not self._can_use_action(key):
            self._sync_item_buttons()
            return
        if self.action_mode == key:
            self.action_mode = None
        else:
            self.action_mode = key
        for k, btn in self.item_buttons.items():
            btn.setChecked(k == self.action_mode)
        self._clear_preview()

    def _can_use_action(self, mode):
        if self.phase != "battle" or self.current != "player" or self.waiting:
            return False
        if mode is None:
            return self._shots_remaining > 0
        if mode in SHOT_MODES:
            return (self._shots_remaining > 0) and self.player_items.get(mode, 0) > 0
        return (self._items_remaining > 0) and self.player_items.get(mode, 0) > 0

    def _sync_item_buttons(self):
        can = (self.phase == "battle" and self.current == "player" and not self.waiting)
        for key, btn in self.item_buttons.items():
            count = self.player_items.get(key, 0)
            if key in SHOT_MODES:
                usable = can and self._shots_remaining > 0 and count > 0
            else:
                usable = can and self._items_remaining > 0 and count > 0
            btn.setText(f"{ITEM_LABELS[key]} ×{count}")
            btn.setEnabled(usable)
            btn.setChecked(False)
        self.action_mode = None
        # 结束回合：本回合炮击次数用尽后才亮起
        self.end_btn.setEnabled(can and self._shots_remaining <= 0)
        self._update_action_counter()

    def _update_action_counter(self):
        if self.phase == "battle" and self.current == "player" and not self.waiting:
            text = f"💥 炮击 ×{self._shots_remaining}　道具 ×{self._items_remaining}"
        else:
            text = "💥 炮击 ×—　道具 ×—"
        self.action_counter_label.setText(text)

    # ============================================================
    #  舰体特性悬浮窗
    # ============================================================

    def _update_ship_tip(self, board, r, c):
        ships = self.ai_ships if board == "ai" else self.player_ships
        ship = self._find_ship(ships, (r, c))
        if board == "ai" and ship is not None:
            # AI 舰体未揭示前不显示特性（命中/击沉/结算揭示时才显示）
            visible = (r, c) in self.player_shots or self.phase == "over"
            if not visible:
                ship = None
        if ship is None:
            self._hide_ship_tip()
        else:
            self._show_ship_tip(ship, board)

    def _show_ship_tip(self, ship, board):
        t = R.SHIP_TYPES[board][ship["type"]]
        text = f"{t['name']}【{t['trait_name']}】\n{t['trait_short']}"
        self._tip_anim.stop()
        self.ship_tip.setText(text)
        self.ship_tip.adjustSize()
        pos = self.mapFromGlobal(QCursor.pos())
        self.ship_tip.move(pos.x() + 16, pos.y() + 18)
        self.ship_tip_effect.setOpacity(1.0)
        self.ship_tip.show()
        self.ship_tip.raise_()

    def _hide_ship_tip(self):
        if not self.ship_tip.isVisible():
            return
        self._tip_anim.stop()
        self._tip_anim.setStartValue(self.ship_tip_effect.opacity())
        self._tip_anim.setEndValue(0.0)
        self._tip_anim.start()

    def _on_tip_fade_finished(self):
        if self.ship_tip_effect.opacity() <= 0.0:
            self.ship_tip.hide()

    # ============================================================
    #  悬停预览
    # ============================================================

    def _action_cells(self, mode, anchor):
        r, c = anchor
        if mode in ("scan", "volley"):
            return R.area_2x2(anchor)
        if mode == "laser_alpha":
            return R.line_4_vertical(anchor)
        if mode == "laser_beta":
            return R.line_4_horizontal(anchor)
        if mode in ("phase_gamma", "phase_theta"):
            return R.area_3x3(anchor)
        return [anchor]

    def _on_ai_cell_hover(self, r, c):
        self._update_ship_tip("ai", r, c)
        if self.phase != "battle" or self.current != "player" or self.waiting:
            return
        mode = self.action_mode
        if mode is None or not self._can_use_action(mode):
            return
        self._apply_preview(self._action_cells(mode, (r, c)))

    def _on_player_cell_hover(self, r, c):
        self._update_ship_tip("player", r, c)

    def _on_board_leave(self):
        self._clear_preview()
        self._hide_ship_tip()

    def _apply_preview(self, cells):
        cells_set = set(cells)
        for r in range(SIZE):
            for c in range(SIZE):
                self.ai_cells[r][c].set_preview((r, c) in cells_set)

    def _clear_preview(self):
        for r in range(SIZE):
            for c in range(SIZE):
                self.ai_cells[r][c].set_preview(False)

    # ============================================================
    #  玩家回合
    # ============================================================

    def _on_ai_cell_click(self, r, c):
        if self.phase != "battle" or self.current != "player" or self.waiting:
            return
        mode = self.action_mode
        if not self._can_use_action(mode):
            return
        if mode is None:
            if (r, c) in self.player_shots:
                return
            self._shots_remaining -= 1
            self._player_attack([(r, c)], f"炮击{R.fmt((r, c))}")
        elif mode in ("scan", "phase_theta"):
            self._items_remaining -= 1
            self.player_items[mode] -= 1
            self._do_scan(mode, (r, c))
        else:
            # volley（道具）或激光α/β、相位γ（特殊炮击）
            if mode == "volley":
                self._items_remaining -= 1
            else:
                self._shots_remaining -= 1
            self.player_items[mode] -= 1
            cells = self._action_cells(mode, (r, c))
            self._player_attack(cells, f"{ITEM_LABELS[mode]}{R.fmt((r, c))}一带")
        self._after_player_action()

    def _do_scan(self, mode, anchor):
        """扫描 / 相位扫描θ：标记区域内的舰影（不攻击）。"""
        cells = self._action_cells(mode, anchor)
        self._record_scan_effect(cells)
        found = []
        for p in cells:
            if p not in self.player_scanned and p not in self.player_shots:
                has = self._find_ship(self.ai_ships, p) is not None
                self.player_scanned[p] = has
                if has:
                    found.append(R.fmt(p))
        self._broadcast(f"我方{ITEM_LABELS[mode]}{R.fmt(anchor)}一带"
                        + (f"：发现舰影于{'、'.join(found)}" if found else "：没有发现"))

    def _player_attack(self, cells, label):
        self._record_shot_effect("ai", cells)
        events, destroyed = R.resolve_hits(self.ai_ships, self.player_shots, cells)
        self._broadcast(f"我方{label}：{'；'.join(events)}")
        if destroyed:
            self._on_player_destroyed_ai(destroyed)

    def _on_player_destroyed_ai(self, destroyed):
        for ship in destroyed:
            self._note_sunk(ship)
            self._broadcast(f"我方击毁{ship['name']}！")
            special = R.special_shot_on_destroy(ship)
            if special == "laser_row":
                self._pending_ai_specials.append("laser_row")
                self._broadcast(f"蕾咪的{ship['name']}触发【{ship['trait_name']}】，下回合1发炮击变为[激光炮击β]！")
            elif special == "phase_3x3_all":
                self._pending_ai_specials.append("phase_3x3_all")
                self._broadcast(f"蕾咪的{ship['name']}触发【{ship['trait_name']}】，下回合所有炮击变为[相位炮击γ]！")
            if ship["type"] == "command":
                msg = R.command_eliminate_on_destroy(self.ai_ships)
                if msg:
                    self._broadcast(f"蕾咪{msg}")

            # 玩家突击舰【绝命】：每击毁一艘 → 获得1发齐射 + 各突击舰弱点+1
            alive_assaults = [s for s in self.player_ships
                              if s["type"] == "assault" and s["alive"]]
            if alive_assaults:
                self.player_items["volley"] += 1
                for a in alive_assaults:
                    if len(a["weak_cells"]) < 3:
                        R.add_weak_points(a, 1)
                self._broadcast("我方突击舰触发【绝命】，我方获得1发[齐射]！")

        # 旗舰【女神】：一回合内击毁敌舰可再炮击一次（每回合限一次）
        if R.has_alive(self.player_ships, "flagship") and not self._extra_shot_used:
            self._extra_shot_used = True
            self._shots_remaining += 1
            self._broadcast("我方旗舰触发【女神】，可再次进行一次炮击！")

    def _after_player_action(self):
        self._render_ai_board()
        self._render_player_board()
        self._render_rosters()
        self._clear_preview()
        if all(R.is_destroyed(s) for s in self.ai_ships):
            self._game_over(player_won=True)
            return
        self._sync_item_buttons()

    def _end_player_turn(self):
        if self.phase != "battle" or self.current != "player" or self.waiting:
            return
        self._clear_preview()
        self._start_ai_turn()

    # ============================================================
    #  AI 回合
    # ============================================================

    def _start_ai_turn(self):
        self.current = "ai"
        self.waiting = True
        self.action_mode = None
        self.ai_latest_shot = set()   # 清空上一回合的高亮，本回合逐发累积
        self._clear_preview()
        self._sync_item_buttons()
        self._update_turn_ui()
        self.center_label.setText("蕾咪舰长思考中……")
        self.center_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #C0392B;")
        QTimer.singleShot(3000, self._ai_do_turn)

    def _ai_do_turn(self):
        if self.phase != "battle":
            return
        n = 1 + (1 if R.has_alive(self.ai_ships, "command") else 0) \
              + (1 if R.has_alive(self.ai_ships, "flagship") else 0)
        for kind in self._ai_shot_plan(n):
            target = self._ai_pick_cell()
            if target is None:
                break
            self._ai_fire(kind, target)
            if all(R.is_destroyed(s) for s in self.player_ships):
                self._game_over(player_won=False)
                return
        # 全局被动【沉稳】：每回合额外齐射一次（2×2）
        volley_target = self._ai_pick_cell()
        if volley_target is not None:
            self._ai_fire("volley", volley_target)
        if all(R.is_destroyed(s) for s in self.player_ships):
            self._game_over(player_won=False)
            return
        self.round += 1
        self._log(f"——— 第 {self.round} 回合 ———")
        self._start_player_turn()

    def _ai_shot_plan(self, n):
        pending = self._pending_ai_specials
        self._pending_ai_specials = []
        if "phase_3x3_all" in pending:
            return ["phase_3x3"] * n
        shots = []
        for _ in range(pending.count("laser_row")):
            shots.append("laser_row")
        if R.last_surviving_type(self.ai_ships) == "scout":
            scount = sum(1 for s in self.ai_ships if s["type"] == "scout" and s["alive"])
            for _ in range(scount):
                shots.append("laser_col")
        while len(shots) < n:
            shots.append("normal")
        return shots[:n]

    def _ai_fire(self, kind, target):
        r, c = target
        if kind == "laser_col":
            cells = R.line_4_vertical(target)
            desc = f"激光炮击α（{R.col_name(c)}列4格一带）"
        elif kind == "laser_row":
            cells = R.line_4_horizontal(target)
            desc = f"激光炮击β（{r + 1}行4格一带）"
        elif kind == "phase_3x3":
            cells = R.area_3x3(target)
            desc = f"相位炮击γ（{R.fmt(target)}一带）"
        elif kind == "volley":
            cells = R.area_2x2(target)
            desc = f"【沉稳】齐射（{R.fmt(target)}一带）"
        else:
            cells = [target]
            desc = f"炮击{R.fmt(target)}"
        self.ai_latest_shot.update(cells)
        self._record_shot_effect("player", cells)
        events, destroyed = R.resolve_hits(self.player_ships, self.ai_shots, cells)
        for ship in destroyed:
            self._on_player_ship_destroyed(ship)
        self._broadcast(f"蕾咪{desc}：{'；'.join(events)}")
        self._render_player_board()
        self._render_rosters()

    def _on_player_ship_destroyed(self, ship):
        self._note_sunk(ship)
        self._broadcast(f"我方{ship['name']}被击毁！")
        if ship["type"] == "scout":
            self.player_items["scan"] += 1
            self._broadcast(f"我方{ship['name']}触发【{ship['trait_name']}】，获得1发[扫描]！")
        elif ship["type"] == "frigate":
            self.player_items["scan"] += 1
            self._broadcast(f"我方{ship['name']}触发【{ship['trait_name']}】，获得1发[扫描]！")

    def _ai_pick_cell(self):
        for s in self.player_ships:
            if s["alive"] and s["hits"]:
                for cell in s["cells"]:
                    if cell not in self.ai_shots:
                        return cell
        unknowns = [(r, c) for r in range(SIZE) for c in range(SIZE)
                    if (r, c) not in self.ai_shots]
        return random.choice(unknowns) if unknowns else None

    # ============================================================
    #  回合流转
    # ============================================================

    def _shots_per_turn(self):
        """本回合我方炮击次数：基础 1 + 侦察梭【斥候】（唯一存活时 +1）。"""
        return 1 + (1 if R.last_surviving_type(self.player_ships) == "scout" else 0)

    def _items_per_turn(self):
        """本回合我方道具次数：基础 1 + 指挥舰【计策】（+1）。"""
        return 1 + (1 if R.has_alive(self.player_ships, "command") else 0)

    def _start_player_turn(self):
        self.current = "player"
        self.waiting = False
        self._shots_remaining = self._shots_per_turn()
        self._items_remaining = self._items_per_turn()
        self._extra_shot_used = False
        self.action_mode = None
        self._clear_preview()
        self._update_turn_ui()
        self.center_label.setText("你的回合：选择道具或直接点击「蕾咪的海域」开炮，结束后点「结束回合」")
        self.center_label.setStyleSheet("font-size: 13px; color: #666666;")
        self._render_player_board()
        self._render_ai_board()
        self._render_rosters()
        self._sync_item_buttons()

    def _update_turn_ui(self):
        if self.current == "player":
            self.turn_label.setText(f"第 {self.round} 回合 · 你的回合")
            self._set_board_highlight("player")
        else:
            self.turn_label.setText(f"第 {self.round} 回合 · 蕾咪的回合")
            self._set_board_highlight("ai")

    def _set_board_highlight(self, who):
        blue = "3px solid #4FC3F7"
        red = "3px solid #E74C3C"
        none = "3px solid transparent"
        ai_style = blue if who == "player" else none
        pl_style = red if who == "ai" else none
        self.ai_board_frame.setStyleSheet(f"QFrame {{ border: {ai_style}; border-radius: 8px; }}")
        self.player_board_frame.setStyleSheet(f"QFrame {{ border: {pl_style}; border-radius: 8px; }}")

    # ============================================================
    #  先手抽取动画 / 流程
    # ============================================================

    def _start_coinflip(self):
        if self.phase != "placement":
            return
        self.phase = "coinflip"
        self.reroll_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.side_first = random.choice(["player", "ai"])
        self._coin_ticks = 0
        self.center_label.setStyleSheet("font-size: 26px; font-weight: bold; color: #2E6C8E;")
        self._coin_timer = QTimer(self)
        self._coin_timer.timeout.connect(self._coin_tick)
        self._coin_timer.start(70)

    def _coin_tick(self):
        self._coin_ticks += 1
        if self._coin_ticks >= 18:
            self._coin_timer.stop()
            self._finish_coinflip()
            return
        side = "player" if self._coin_ticks % 2 == 0 else "ai"
        self.center_label.setText("⚓ 你" if side == "player" else "🛸 蕾咪")

    def _finish_coinflip(self):
        self.current = self.side_first
        self.center_label.setText("⚓ 你先手！" if self.side_first == "player" else "🛸 蕾咪先手！")
        self._log("先手抽取：" + ("⚓ 我方先手" if self.side_first == "player" else "🛸 蕾咪先手"))
        QTimer.singleShot(1300, self._begin_battle)

    def _begin_battle(self):
        self.phase = "battle"
        self.round = 1
        self._render_ai_board()
        self._render_player_board()
        self._render_rosters()
        self._log(f"——— 第 {self.round} 回合 ———")
        if self.current == "player":
            self._start_player_turn()
        else:
            self._start_ai_turn()

    def _reroll_player(self):
        if self.phase != "placement":
            return
        self._deploy_player()
        self._render_player_board()
        self._render_rosters()

    def _new_game(self):
        if self._coin_timer is not None:
            self._coin_timer.stop()
        self.init_game()
        self._sunk_flash_timer.stop()
        self._shot_anim_timer.stop()
        self._scan_anim_timer.stop()
        self._hide_ship_tip()
        # 清掉上一局可能残留的炮击/扫描动效
        for r in range(SIZE):
            for c in range(SIZE):
                self.player_cells[r][c].set_shot_anim(None)
                self.ai_cells[r][c].set_shot_anim(None)
                self.ai_cells[r][c].set_scan_anim(None, None, 0, 0, 0)
        self.reroll_btn.setEnabled(True)
        self.start_btn.setEnabled(True)
        self.end_btn.setEnabled(False)
        self.turn_label.setText("布阵阶段")
        self.center_label.setText("布阵阶段：点击「重新随机」调整舰队，满意后点「开战」")
        self.center_label.setStyleSheet("font-size: 13px; color: #666666;")
        self.broadcast_label.setText("")
        self._set_board_highlight(None)
        self.history_list.clear()
        self._render_player_board()
        self._render_ai_board()
        self._render_rosters()
        self._sync_item_buttons()

    def _open_codex(self):
        ShipCodexDialog(self).exec_()

    # ============================================================
    #  播报 / 历史 / 结算
    # ============================================================

    def _broadcast(self, text):
        self.broadcast_label.setText(text)
        self._log(text)

    def _log(self, text):
        item = QListWidgetItem(text)
        self.history_list.addItem(item)
        self.history_list.scrollToBottom()

    def _game_over(self, player_won):
        self.phase = "over"
        self.waiting = False
        self.action_mode = None
        self._clear_preview()
        self._render_ai_board()
        self._render_player_board()
        self._render_rosters()
        self._sync_item_buttons()
        self.turn_label.setText("对局结束")
        self._set_board_highlight(None)
        if player_won:
            self.center_label.setText("🎉 你击沉了蕾咪的全部舰队！")
            self._broadcast("🎉 我方胜利！")
            QMessageBox.information(self, "🎉 胜利", "你击沉了蕾咪的全部舰队！\n\n蕾咪：才、才不是让你的！")
        else:
            self.center_label.setText("💥 你的舰队被蕾咪全歼了…")
            self._broadcast("💥 我方败北！")
            QMessageBox.information(self, "💥 败北", "你的舰队被蕾咪全歼了…\n\n蕾咪：哼哼，这就是实力差距～")

    # ============================================================
    #  工具
    # ============================================================

    @staticmethod
    def _find_ship(ships, pos):
        for s in ships:
            if pos in s["cells"]:
                return s
        return None

    @staticmethod
    def _sunk_weak_marker(ship, pos):
        """被击沉舰体该格的弱点标记：有弱点→实心；无弱点→在原弱点位置标空心。"""
        if ship["weak_cells"]:
            return "solid" if pos in ship["weak_cells"] else None
        return "hollow" if pos in ship.get("init_weak_cells", set()) else None
