# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 海战棋小游戏（LLM 驱动）

6x6 迷你局：双方各 3 艘船（战列舰3 / 巡洋舰2 / 炮艇2），
命中任意一格即整舰沉没（碰到就死）；双方各有雷达/齐射道具各一发
（雷达扫描 2x2 探明舰影，齐射炮击 2x2，各两发），典型对局 6-8 回合。
胜负判定全部本地确定性执行；LLM 负责解说吐槽与蕾咪的战术决策，
失败时回退本地 AI 与内置台词，游戏永不卡死。
结算时揭示蕾咪的完整布阵。

每局对局维护独立的对话上下文（随对话框销毁，不污染主聊天历史），
人设提示词运行时引用 config.get_system_prompt()，与主聊天保持一致。
对局结束后生成战报，推送到主聊天窗口并写入对话历史。
"""

import random
import re
import threading

import requests
from PyQt5.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout,
    QPushButton, QWidget, QGridLayout, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal

import config
from thinking import apply_thinking_request

SIZE = 6
SHIPS = [("战列舰", 3), ("巡洋舰", 2), ("炮艇", 2)]

BATTLE_RULES = """
---
你正在和调查员玩海战棋（6x6，坐标A1-F6，如B5）。
规则：双方各有3艘船；船被命中任意一格就整舰沉没（碰到就死）。
道具（每种各两发，每回合限用一个，简报会告诉你剩余次数）：
- 雷达：扫描以目标格为左上角的2x2区域，探明哪些格子有船，不造成伤害，不影响当回合炮击
- 齐射：炮击以目标格为左上角的2x2区域，代替当回合的单发炮击
根据战况简报，严格按以下四行格式输出，不要输出任何其他内容：
【反应】一句话傲娇回应调查员刚才的行动
【道具】雷达/齐射/无（选雷达或齐射时附上目标坐标，选无则不填）
【开炮】你的炮击坐标，必须选标记为.或F的格（若道具选了齐射则与齐射同坐标）
【狠话】一句话开炮狠话"""

LOCAL_HIT_REACTIONS = [
    "呜…居然打中了蕾咪的船！你、你给我等着！",
    "哼，运气好而已！下次就没这么走运了！",
    "竟、竟然命中了…蕾咪才没有慌呢！",
]
LOCAL_MISS_REACTIONS = [
    "噗…打偏了哦？调查员的眼神不太行呢～",
    "哼，就这种水平还想打中蕾咪？",
    "落空啦！蕾咪的舰队可不是那么好找的！",
]
LOCAL_SUNK_REACTIONS = [
    "我、我的{name}…！你完蛋了！蕾咪要认真了！",
    "呜哇！{name}被击沉了…这仇一定要报！",
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
    "用两三句话向调查员复盘这场比赛，保持你的个性，"
    "这是发到主聊天窗口的战报，直接输出文本，不要任何格式标记。"
)


def col_name(c):
    return chr(ord("A") + c)


def parse_coord(text):
    m = re.search(r"([A-Fa-f])\s*[- ]?\s*([1-6])", text)
    if not m:
        return None
    return (int(m.group(2)) - 1, ord(m.group(1).upper()) - ord("A"))


def parse_llm_reply(reply):
    result = {"reaction": "", "coord": None, "taunt": "",
              "item_type": "无", "item_coord": None}
    m = re.search(r"【反应】\s*(.+?)(?=【|$)", reply, re.S)
    if m:
        result["reaction"] = m.group(1).strip().splitlines()[0].strip()
    m = re.search(r"【道具】\s*(.+?)(?=【|$)", reply, re.S)
    if m:
        item_text = m.group(1).strip()
        if "雷达" in item_text:
            result["item_type"] = "雷达"
        elif "齐射" in item_text:
            result["item_type"] = "齐射"
        result["item_coord"] = parse_coord(item_text)
    m = re.search(r"【开炮】\s*(.+?)(?=【|$)", reply, re.S)
    if m:
        result["coord"] = parse_coord(m.group(1))
    if result["coord"] is None:
        result["coord"] = parse_coord(reply)
    m = re.search(r"【狠话】\s*(.+?)(?=【|$)", reply, re.S)
    if m:
        result["taunt"] = m.group(1).strip().splitlines()[0].strip()
    return result


def area_cells(center):
    r0 = min(center[0], SIZE - 2)
    c0 = min(center[1], SIZE - 2)
    return [(r0, c0), (r0, c0 + 1), (r0 + 1, c0), (r0 + 1, c0 + 1)]


def place_ships_random():
    board = [[0] * SIZE for _ in range(SIZE)]
    ships = []
    for name, length in SHIPS:
        placed = False
        while not placed:
            horizontal = random.random() < 0.5
            r = random.randrange(SIZE)
            c = random.randrange(SIZE)
            cells = [(r, c + i) for i in range(length)] if horizontal \
                else [(r + i, c) for i in range(length)]
            if all(0 <= x < SIZE and 0 <= y < SIZE and board[x][y] == 0 for x, y in cells):
                for x, y in cells:
                    board[x][y] = 1
                ships.append({"name": name, "cells": cells, "hits": set()})
                placed = True
    return board, ships


class CellButton(QPushButton):
    TERMINAL_STATES = ("miss", "sunk", "disabled", "reveal")

    def __init__(self, row, col, click_handler=None):
        super().__init__()
        self.row = row
        self.col = col
        self.setFixedSize(40, 40)
        if click_handler:
            self.clicked.connect(lambda checked: click_handler(self.row, self.col))
        self.set_state("sea")

    def set_state(self, state):
        styles = {
            "sea":        ("#A8D8E8", "#A8D8E8", ""),
            "ship":       ("#4A6B8A", "#4A6B8A", ""),
            "miss":       ("#E8F4F8", "#7AA5B8", "○"),
            "sunk":       ("#C0392B", "#FFFFFF", "✕"),
            "scan_empty": ("#D8C9E8", "#8A7AA5", "·"),
            "scan_ship":  ("#E8B4D8", "#A03070", "⚑"),
            "reveal":     ("#4A6B8A", "#FFFFFF", "⚓"),
            "disabled":   ("#A8D8E8", "#A8D8E8", ""),
        }
        bg, fg, text = styles[state]
        self.setText(text)
        self.setStyleSheet(
            f"QPushButton {{ background-color: {bg}; color: {fg};"
            f" border: 1px solid #8FC3D8; border-radius: 4px;"
            f" font-size: 16px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: #C4E4F0; }}"
        )
        if state in self.TERMINAL_STATES:
            self.setEnabled(False)


class BattleshipDialog(QDialog):
    llm_ready = pyqtSignal(str, int)
    llm_failed = pyqtSignal(int)
    summary_ready = pyqtSignal(str, int)
    summary_failed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🚢 海战棋")
        self.setGeometry(200, 100, 720, 560)
        self.setStyleSheet("background-color: #ffffff; color: #333333; font-family: Microsoft YaHei;")
        self.llm_ready.connect(self._on_llm_ready)
        self.llm_failed.connect(self._on_llm_failed)
        self.summary_ready.connect(self._on_summary_ready)
        self.summary_failed.connect(self._on_summary_failed)
        self._token = 0
        self._retried = False
        self._system_prompt = config.get_system_prompt() + BATTLE_RULES
        self._summary_delivered = True
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self.init_game()
        self.init_ui()

    def init_game(self):
        self.phase = "placement"
        self.player_board, self.player_ships = place_ships_random()
        self.remy_board, self.remy_ships = place_ships_random()
        self.player_shots = set()
        self.remy_shots = set()
        self.player_scanned = {}
        self.remy_scanned = {}
        self.player_radar = 2
        self.player_barrage = 2
        self.remy_radar = 2
        self.remy_barrage = 2
        self.last_player_events = []
        self.last_remy_events = []
        self._radar_note = ""
        self.waiting = False
        self.rounds = 0
        self.game_history = []
        self._pending_briefing = ""
        self.action_mode = None

    # ============================================================
    #  UI
    # ============================================================

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel("🚢 海战棋")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #DAAD69;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self.bubble = QLabel("蕾咪：哼，先摆好你的舰队吧。蕾咪才不会手下留情哦。")
        self.bubble.setWordWrap(True)
        self.bubble.setAlignment(Qt.AlignCenter)
        self.bubble.setStyleSheet(
            "background-color: #FFF6E8; color: #8A6D3B; border: 1px solid #DAAD69;"
            " border-radius: 8px; padding: 8px 12px; font-size: 13px;"
        )
        self.bubble.setMinimumHeight(48)
        layout.addWidget(self.bubble)

        boards_layout = QHBoxLayout()
        boards_layout.setSpacing(24)
        boards_layout.addStretch()
        self.remy_cells, remy_panel = self._build_board("🌊 蕾咪的海域（点击开炮）", self.on_cell_click)
        boards_layout.addWidget(remy_panel)
        self.player_cells, player_panel = self._build_board("⚓ 你的海域", None)
        boards_layout.addWidget(player_panel)
        boards_layout.addStretch()
        layout.addLayout(boards_layout)

        self.status_label = QLabel("布阵阶段：点击「重新随机」调整舰队，满意后点「开战」")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #666666; font-size: 12px;")
        layout.addWidget(self.status_label)

        item_layout = QHBoxLayout()
        item_layout.setSpacing(12)
        item_layout.addStretch()
        self.radar_btn = QPushButton("🔍 雷达 ×2")
        self.barrage_btn = QPushButton("💥 齐射 ×2")
        for btn in (self.radar_btn, self.barrage_btn):
            btn.setCheckable(True)
            btn.setEnabled(False)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #2E6C8E; color: white; border: none;
                    border-radius: 6px; padding: 8px 18px; font-size: 13px;
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
        btn_layout.setSpacing(12)
        btn_layout.addStretch()
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
        for btn in (self.reroll_btn, self.start_btn, new_btn, close_btn):
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #333333; color: white; border: none;
                    border-radius: 6px; padding: 8px 18px; font-size: 13px;
                }
                QPushButton:hover { background-color: #555555; }
                QPushButton:disabled { background-color: #999999; }
            """)
        layout.addLayout(btn_layout)
        self.setLayout(layout)
        self._render_player_board()

    def _build_board(self, caption, click_handler):
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        label = QLabel(caption)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size: 14px; font-weight: bold; color: #2E6C8E;")
        v.addWidget(label)

        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setSpacing(2)
        grid.setContentsMargins(2, 2, 2, 2)

        for c in range(SIZE):
            hdr = QLabel(col_name(c))
            hdr.setAlignment(Qt.AlignCenter)
            hdr.setFixedSize(40, 18)
            hdr.setStyleSheet("color: #2E6C8E; font-weight: bold; font-size: 11px;")
            grid.addWidget(hdr, 0, c + 1)
        cells = []
        for r in range(SIZE):
            hdr = QLabel(str(r + 1))
            hdr.setAlignment(Qt.AlignCenter)
            hdr.setFixedSize(18, 40)
            hdr.setStyleSheet("color: #2E6C8E; font-weight: bold; font-size: 11px;")
            grid.addWidget(hdr, r + 1, 0)
            row_cells = []
            for c in range(SIZE):
                cell = CellButton(r, c, click_handler)
                grid.addWidget(cell, r + 1, c + 1)
                row_cells.append(cell)
            cells.append(row_cells)
        v.addWidget(grid_widget, alignment=Qt.AlignCenter)
        return cells, panel

    def _set_mode(self, mode):
        if self.phase != "battle" or self.waiting:
            self._sync_item_buttons()
            return
        charges_ok = (mode == "radar" and self.player_radar > 0) or \
                     (mode == "barrage" and self.player_barrage > 0)
        if not charges_ok:
            self._sync_item_buttons()
            return
        if self.action_mode == mode:
            self.action_mode = None
            self.radar_btn.setChecked(False)
            self.barrage_btn.setChecked(False)
            self.status_label.setText("交战中：点击左侧「蕾咪的海域」开炮！")
            return
        self.action_mode = mode
        self.radar_btn.setChecked(mode == "radar")
        self.barrage_btn.setChecked(mode == "barrage")
        if mode == "radar":
            self.status_label.setText("🔍 雷达模式：点击蕾咪海域的一格，扫描以其为左上角的 2x2 区域（不消耗炮击）")
        else:
            self.status_label.setText("💥 齐射模式：点击蕾咪海域的一格，炮击以其为左上角的 2x2 区域！")

    def _sync_item_buttons(self):
        self.radar_btn.setText(f"🔍 雷达 ×{self.player_radar}")
        self.barrage_btn.setText(f"💥 齐射 ×{self.player_barrage}")
        can_use = self.phase == "battle" and not self.waiting
        self.radar_btn.setEnabled(can_use and self.player_radar > 0)
        self.barrage_btn.setEnabled(can_use and self.player_barrage > 0)
        self.radar_btn.setChecked(False)
        self.barrage_btn.setChecked(False)
        self.action_mode = None

    # ============================================================
    #  渲染
    # ============================================================

    def _render_player_board(self):
        for r in range(SIZE):
            for c in range(SIZE):
                cell = self.player_cells[r][c]
                pos = (r, c)
                if pos in self.remy_shots:
                    cell.set_state("sunk" if self.player_board[r][c] == 1 else "miss")
                else:
                    cell.set_state("ship" if self.player_board[r][c] == 1 else "disabled")

    def _render_remy_cell(self, r, c):
        cell = self.remy_cells[r][c]
        pos = (r, c)
        if pos in self.player_shots:
            cell.set_state("sunk" if self.remy_board[r][c] == 1 else "miss")
            return
        if pos in self.player_scanned:
            cell.set_state("scan_ship" if self.remy_board[r][c] == 1 else "scan_empty")
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
                if pos in self.player_shots:
                    cell.set_state("sunk" if self.remy_board[r][c] == 1 else "miss")
                elif self.remy_board[r][c] == 1:
                    cell.set_state("reveal")
                else:
                    cell.set_state("sea")
                    cell.setEnabled(False)

    @staticmethod
    def _ship_at(ships, pos):
        for ship in ships:
            if pos in ship["cells"]:
                return ship
        return None

    @staticmethod
    def _is_sunk(ship):
        return len(ship["hits"]) == len(ship["cells"])

    @staticmethod
    def _fmt(pos):
        return f"{col_name(pos[1])}{pos[0] + 1}"

    # ============================================================
    #  流程
    # ============================================================

    def reroll_ships(self):
        if self.phase != "placement":
            return
        self.player_board, self.player_ships = place_ships_random()
        self._render_player_board()

    def start_battle(self):
        if self.phase != "placement":
            return
        self.phase = "battle"
        self.reroll_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.status_label.setText("交战中：点击左侧「蕾咪的海域」开炮！")
        self.bubble.setText("蕾咪：舰队已就位！来吧，让你先手。哼，别客气哦～")
        self._render_all_remy()
        self._sync_item_buttons()

    def new_game(self):
        self._token += 1
        self._watchdog.stop()
        self._retried = False
        self.init_game()
        self.reroll_btn.setEnabled(True)
        self.start_btn.setEnabled(True)
        self.status_label.setText("布阵阶段：点击「重新随机」调整舰队，满意后点「开战」")
        self.bubble.setText("蕾咪：再来一局？哼，这次蕾咪可不会输了！")
        self._render_player_board()
        self._render_all_remy()
        self._sync_item_buttons()

    def on_cell_click(self, r, c):
        if self.phase != "battle" or self.waiting:
            return
        if self.action_mode == "radar":
            self._player_radar((r, c))
            return
        if self.action_mode == "barrage":
            self.player_barrage -= 1
            events = self._fire_at(self.remy_board, self.remy_ships,
                                   self.player_shots, area_cells((r, c)))
            events[0] = f"齐射（中心{self._fmt((r, c))}）：" + events[0]
            self.last_player_events = events
        else:
            if (r, c) in self.player_shots:
                return
            events = self._fire_at(self.remy_board, self.remy_ships,
                                   self.player_shots, [(r, c)])
            self.last_player_events = events
        if self._radar_note:
            self.last_player_events.insert(0, self._radar_note)
            self._radar_note = ""
        self.rounds += 1
        self._sync_item_buttons()
        self._render_all_remy()
        if all(self._is_sunk(s) for s in self.remy_ships):
            self._game_over(player_won=True)
            return
        self.waiting = True
        self._render_all_remy()
        self._sync_item_buttons()
        self.status_label.setText("蕾咪思考中…")
        self._request_remy_turn()

    def _player_radar(self, center):
        self.player_radar -= 1
        found = 0
        for p in area_cells(center):
            has_ship = self.remy_board[p[0]][p[1]] == 1
            if p not in self.player_scanned and p not in self.player_shots:
                self.player_scanned[p] = has_ship
            if has_ship:
                found += 1
        self._radar_note = f"用雷达扫描了你 {self._fmt(center)} 一带"
        self.status_label.setText(
            f"🔍 雷达扫描完成：该区域{'发现 ' + str(found) + ' 格舰影（⚑）！' if found else '没有发现舰影。'}继续开炮！"
        )
        self._render_all_remy()
        self._sync_item_buttons()

    def _fire_at(self, board, ships, shots, cells):
        """碰到就死：命中任意一格即整舰沉没，返回事件文本列表。"""
        events = []
        for p in cells:
            if p in shots:
                continue
            shots.add(p)
            if board[p[0]][p[1]] == 1:
                ship = self._ship_at(ships, p)
                if not self._is_sunk(ship):
                    ship["hits"].update(ship["cells"])
                    shots.update(ship["cells"])
                    events.append(f"击沉{ship['name']}！")
            else:
                events.append(f"{self._fmt(p)}落空")
        if not events:
            events.append("落空")
        return events

    # ============================================================
    #  LLM 回合
    # ============================================================

    def _build_briefing(self, retry_note=None):
        lines = ["你对调查员海域的探测图（.未知 ~扫描为空 F扫描发现船 o落空 X击沉）："]
        lines.append("  " + " ".join(col_name(c) for c in range(SIZE)))
        for r in range(SIZE):
            row = []
            for c in range(SIZE):
                pos = (r, c)
                if pos in self.remy_shots:
                    row.append("X" if self.player_board[r][c] == 1 else "o")
                elif pos in self.remy_scanned:
                    row.append("F" if self.remy_scanned[pos] else "~")
                else:
                    row.append(".")
            lines.append(f"{r + 1} " + " ".join(row))

        if self.last_player_events:
            lines.append(f"本回合调查员的行动：{'；'.join(self.last_player_events)}")
        if self.last_remy_events:
            lines.append(f"你上一回合的行动结果：{'；'.join(self.last_remy_events)}")
        lines.append(f"你的道具剩余：雷达x{self.remy_radar} 齐射x{self.remy_barrage}")
        player_alive = sum(1 for s in self.player_ships if not self._is_sunk(s))
        remy_alive = sum(1 for s in self.remy_ships if not self._is_sunk(s))
        lines.append(f"对方剩余船只：{player_alive}艘；你的剩余船只：{remy_alive}艘。")
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
        """回合请求的终极保险：30 秒仍卡在等待就强制本地接管。"""
        if self.waiting and self.phase == "battle" and self._token == token:
            print("[Remy Debug] [海战棋] 看门狗超时，强制本地战术接管")
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
                        "max_tokens": 160,
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
                        print("[Remy Debug] [海战棋] 正文为空：思考模式未关闭，token 预算被思维链耗尽")
                        continue
                print(f"[Remy Debug] [海战棋] API error: {response.status_code} {response.text[:300]}")
            except Exception as e:
                print(f"[Remy Debug] [海战棋] API exception: {type(e).__name__}: {e}")
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
                    retry_note="注意：你上次给出的坐标无效或已炮击过，请重新选择标记为.或F的格子。"
                )
            else:
                self._retried = False
                self._remy_fire(self._local_action(), local_fallback=True)
            return
        self._retried = False
        self._remy_fire(action)

    def _valid_action(self, action):
        if action["item_type"] == "齐射" and self.remy_barrage > 0:
            return action["item_coord"] is not None
        coord = action["coord"]
        return coord is not None and coord not in self.remy_shots

    def _on_llm_failed(self, token):
        if token != self._token or self.phase != "battle":
            return
        self._remy_fire(self._local_action(), local_fallback=True)

    def _local_action(self):
        action = {"reaction": "", "taunt": "", "coord": None,
                  "item_type": "无", "item_coord": None}
        known = [p for p, has in self.remy_scanned.items()
                 if has and p not in self.remy_shots]
        if self.remy_barrage > 0 and (known or self.rounds >= 3):
            center = random.choice(known) if known else (
                random.randrange(SIZE), random.randrange(SIZE))
            action["item_type"] = "齐射"
            action["item_coord"] = center
            action["coord"] = center
            return action
        if self.remy_radar > 0 and self.rounds >= 2:
            best, best_gain = None, -1
            for _ in range(12):
                center = (random.randrange(SIZE), random.randrange(SIZE))
                gain = sum(1 for p in area_cells(center) if p not in self.remy_scanned)
                if gain > best_gain:
                    best, best_gain = center, gain
            action["item_type"] = "雷达"
            action["item_coord"] = best
        if known:
            action["coord"] = random.choice(known)
        else:
            unknowns = [(r, c) for r in range(SIZE) for c in range(SIZE)
                        if (r, c) not in self.remy_shots]
            action["coord"] = random.choice(unknowns) if unknowns else None
        return action

    def _remy_fire(self, action, local_fallback=False):
        reaction = action.get("reaction") or self._local_reaction()
        taunt = action.get("taunt") or random.choice(LOCAL_TAUNTS)
        self.bubble.setText(f"蕾咪：{reaction}")

        events = []
        item_type = action.get("item_type", "无")
        item_coord = action.get("item_coord")
        if item_type == "雷达" and self.remy_radar > 0 and item_coord is not None:
            self.remy_radar -= 1
            found = []
            for p in area_cells(item_coord):
                if p not in self.remy_scanned:
                    has_ship = self.player_board[p[0]][p[1]] == 1
                    self.remy_scanned[p] = has_ship
                    if has_ship:
                        found.append(self._fmt(p))
            events.append(
                f"雷达扫描{self._fmt(item_coord)}一带"
                + (f"：发现舰影于{'、'.join(found)}" if found else "：没有发现")
            )
            item_note = f"蕾咪用雷达扫描了 {self._fmt(item_coord)} 一带！"
        else:
            item_note = ""

        if item_type == "齐射" and self.remy_barrage > 0 and item_coord is not None:
            self.remy_barrage -= 1
            fire_events = self._fire_at(self.player_board, self.player_ships,
                                        self.remy_shots, area_cells(item_coord))
            events.append(f"齐射（中心{self._fmt(item_coord)}）：{'；'.join(fire_events)}")
            shot_text = f"{taunt} → 蕾咪齐射 {self._fmt(item_coord)} 一带：{'；'.join(fire_events)}"
        else:
            coord = action.get("coord")
            if coord is None:
                self.waiting = False
                self._render_all_remy()
                self._sync_item_buttons()
                return
            fire_events = self._fire_at(self.player_board, self.player_ships,
                                        self.remy_shots, [coord])
            events.append(f"炮击{self._fmt(coord)}：{'；'.join(fire_events)}")
            shot_text = f"{taunt} → 蕾咪炮击 {self._fmt(coord)}：{'；'.join(fire_events)}"

        self.last_remy_events = events
        self._render_player_board()
        if item_note:
            shot_text = item_note + " " + shot_text
        if local_fallback:
            shot_text += "（本地战术模式）"
        self.status_label.setText(shot_text)

        if all(self._is_sunk(s) for s in self.player_ships):
            self._game_over(player_won=False)
            return
        self.waiting = False
        self._render_all_remy()
        self._sync_item_buttons()

    def _local_reaction(self):
        for event in self.last_player_events:
            if "击沉" in event:
                for ship in self.remy_ships:
                    if ship["name"] in event:
                        return random.choice(LOCAL_SUNK_REACTIONS).format(name=ship["name"])
                return random.choice(LOCAL_SUNK_REACTIONS).format(name="船")
        for event in self.last_player_events:
            if "落空" in event:
                return random.choice(LOCAL_MISS_REACTIONS)
        if any("雷达" in e for e in self.last_player_events):
            return "哼，随便你扫，蕾咪的舰队藏得可深了！"
        return random.choice(LOCAL_MISS_REACTIONS)

    # ============================================================
    #  结算与战报
    # ============================================================

    def _game_over(self, player_won):
        self.phase = "over"
        self.waiting = False
        self._token += 1
        self._reveal_remy_board()
        self._render_player_board()
        self._sync_item_buttons()
        self._request_summary(player_won)
        if player_won:
            self.status_label.setText("🎉 你击沉了蕾咪的全部舰队！")
            self.bubble.setText(f"蕾咪：{LOCAL_WIN_LINE}")
            QMessageBox.information(self, "🎉 胜利", "你击沉了蕾咪的全部舰队！\n\n蕾咪：才、才不是让你的！")
        else:
            self.status_label.setText("💥 蕾咪击沉了你的全部舰队！")
            self.bubble.setText(f"蕾咪：{LOCAL_LOSE_LINE}")
            QMessageBox.information(self, "💥 败北", "你的舰队被蕾咪全歼了…\n\n蕾咪：哼哼，这就是实力差距～")

    def _request_summary(self, player_won):
        """对局结束：基于对局上下文生成战报，推送到主聊天窗口。"""
        self._token += 1
        token = self._token
        self._summary_delivered = False
        self._summary_player_won = player_won
        result_text = (
            "调查员击沉了你的全部舰队，你输了" if player_won
            else "你击沉了调查员的全部舰队，你赢了"
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
                print(f"[Remy Debug] [海战棋] 战报生成异常: {type(e).__name__}: {e}")
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
                f"呜…刚才那局海战棋打了{self.rounds}回合，蕾咪的舰队全军覆没……"
                "才、才不是实力不如你！下次蕾咪一定会赢回来的，等着瞧！"
            )
        else:
            text = (
                f"哼哼，刚才那局海战棋，蕾咪{self.rounds}回合就把你的舰队全歼啦！"
                "这就是阿斯忒瑞亚号舰长的实力～想复仇的话随时奉陪哦！"
            )
        self._deliver_summary(text)

    def _deliver_summary(self, text):
        """战报双投递：主窗口气泡播报 + 写入主聊天历史（让蕾咪之后还记得这局）。"""
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
