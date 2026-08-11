# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 2048 小游戏（独立模块）

经典 4x4 数字合并游戏，达到 2048 即可获胜（可选择继续）。
完全独立，不依赖 config 等业务模块。
"""

import random

from PyQt5.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout,
    QPushButton, QWidget, QMessageBox, QGridLayout
)
from PyQt5.QtCore import Qt


class Game2048Dialog(QDialog):
    """2048 小游戏 - 4x4 棋盘，达到2048获胜并可继续游玩"""

    # 经典2048颜色方案 (背景色, 文字色)
    TILE_COLORS = {
        0:     ("#cdc1b4", "#cdc1b4"),
        2:     ("#eee4da", "#776e65"),
        4:     ("#ede0c8", "#776e65"),
        8:     ("#f2b179", "#f9f6f2"),
        16:    ("#f59563", "#f9f6f2"),
        32:    ("#f67c5f", "#f9f6f2"),
        64:    ("#f65e3b", "#f9f6f2"),
        128:   ("#edcf72", "#f9f6f2"),
        256:   ("#edcc61", "#f9f6f2"),
        512:   ("#edc850", "#f9f6f2"),
        1024:  ("#edc53f", "#f9f6f2"),
        2048:  ("#edc22e", "#f9f6f2"),
        4096:  ("#3c3a32", "#f9f6f2"),
        8192:  ("#3c3a32", "#f9f6f2"),
        16384: ("#3c3a32", "#f9f6f2"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔢 2048")
        self.setGeometry(300, 200, 420, 550)
        self.setStyleSheet("background-color: #faf8ef; font-family: Microsoft YaHei;")
        self.setMouseTracking(True)
        self._drag_start = None
        self.init_game()
        self.init_ui()

    # ============================================================
    #  游戏状态
    # ============================================================

    def init_game(self):
        """初始化/重置游戏状态"""
        self.board = [[0] * 4 for _ in range(4)]
        self.score = 0
        self.won = False
        self.keep_playing = False
        self.add_random_tile()
        self.add_random_tile()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # ---- 顶部：标题 + 分数 ----
        header = QHBoxLayout()
        title = QLabel("2048")
        title.setStyleSheet("font-size: 36px; font-weight: bold; color: #776e65;")
        header.addWidget(title)
        header.addStretch()

        # 分数卡
        score_card = QWidget()
        score_card.setFixedSize(100, 55)
        score_card.setStyleSheet("background-color: #bbada0; border-radius: 6px;")
        sc_layout = QVBoxLayout(score_card)
        sc_layout.setContentsMargins(0, 2, 0, 2)
        sc_label = QLabel("分数")
        sc_label.setStyleSheet("color: #eee4da; font-size: 12px;")
        sc_label.setAlignment(Qt.AlignCenter)
        self.score_label = QLabel("0")
        self.score_label.setStyleSheet("color: white; font-size: 20px; font-weight: bold;")
        self.score_label.setAlignment(Qt.AlignCenter)
        sc_layout.addWidget(sc_label)
        sc_layout.addWidget(self.score_label)
        header.addWidget(score_card)

        # 最高分卡
        best_card = QWidget()
        best_card.setFixedSize(100, 55)
        best_card.setStyleSheet("background-color: #bbada0; border-radius: 6px;")
        bc_layout = QVBoxLayout(best_card)
        bc_layout.setContentsMargins(0, 2, 0, 2)
        bc_label = QLabel("最高")
        bc_label.setStyleSheet("color: #eee4da; font-size: 12px;")
        bc_label.setAlignment(Qt.AlignCenter)
        self.best_label = QLabel("0")
        self.best_label.setStyleSheet("color: white; font-size: 20px; font-weight: bold;")
        self.best_label.setAlignment(Qt.AlignCenter)
        bc_layout.addWidget(bc_label)
        bc_layout.addWidget(self.best_label)
        header.addWidget(best_card)

        layout.addLayout(header)

        # ---- 提示文字 ----
        hint = QLabel("🖱 在棋盘上滑动鼠标来移动方块，合并到2048！")
        hint.setStyleSheet("color: #776e65; font-size: 12px;")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)

        # ---- 4x4 游戏棋盘 ----
        board_widget = QWidget()
        board_widget.setStyleSheet("background-color: #bbada0; border-radius: 8px;")
        board_widget.setFixedSize(370, 370)
        grid = QGridLayout(board_widget)
        grid.setSpacing(10)
        grid.setContentsMargins(10, 10, 10, 10)

        self.tiles = [[QLabel() for _ in range(4)] for _ in range(4)]
        for i in range(4):
            for j in range(4):
                tile = self.tiles[i][j]
                tile.setAlignment(Qt.AlignCenter)
                tile.setFixedSize(80, 80)
                tile.setStyleSheet("""
                    QLabel {
                        background-color: #cdc1b4;
                        border-radius: 5px;
                        font-size: 28px;
                        font-weight: bold;
                        color: #cdc1b4;
                    }
                """)
                grid.addWidget(tile, i, j)

        layout.addWidget(board_widget, alignment=Qt.AlignCenter)

        # ---- 底部按钮 ----
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)

        new_btn = QPushButton("🔄 新游戏")
        new_btn.clicked.connect(self.new_game)
        new_btn.setStyleSheet("""
            QPushButton {
                background-color: #8f7a66; color: #f9f6f2;
                border: none; border-radius: 5px;
                padding: 10px 25px; font-size: 14px; font-weight: bold;
            }
            QPushButton:hover { background-color: #9f8a76; }
        """)
        btn_layout.addWidget(new_btn)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #bbada0; color: #f9f6f2;
                border: none; border-radius: 5px;
                padding: 10px 25px; font-size: 14px;
            }
            QPushButton:hover { background-color: #cbbdb0; }
        """)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)
        self.update_board()

    # ============================================================
    #  核心游戏逻辑
    # ============================================================

    def add_random_tile(self):
        """在随机空格放置 2（90%）或 4（10%）"""
        empty = [(i, j) for i in range(4) for j in range(4) if self.board[i][j] == 0]
        if empty:
            i, j = random.choice(empty)
            self.board[i][j] = 2 if random.random() < 0.9 else 4

    def _slide_row(self, row):
        """将一行向左滑合并，返回新行"""
        new_row = [x for x in row if x != 0]
        result = []
        i = 0
        while i < len(new_row):
            if i + 1 < len(new_row) and new_row[i] == new_row[i + 1]:
                merged = new_row[i] * 2
                result.append(merged)
                self.score += merged
                i += 2
            else:
                result.append(new_row[i])
                i += 1
        result += [0] * (4 - len(result))
        return result

    def move_left(self):
        moved = False
        for i in range(4):
            new_row = self._slide_row(self.board[i])
            if self.board[i] != new_row:
                moved = True
                self.board[i] = new_row
        return moved

    def move_right(self):
        moved = False
        for i in range(4):
            reversed_row = self.board[i][::-1]
            new_row = self._slide_row(reversed_row)[::-1]
            if self.board[i] != new_row:
                moved = True
                self.board[i] = new_row
        return moved

    def move_up(self):
        moved = False
        for j in range(4):
            col = [self.board[i][j] for i in range(4)]
            new_col = self._slide_row(col)
            if col != new_col:
                moved = True
                for i in range(4):
                    self.board[i][j] = new_col[i]
        return moved

    def move_down(self):
        moved = False
        for j in range(4):
            col = [self.board[i][j] for i in range(4)]
            new_col = self._slide_row(col[::-1])[::-1]
            if col != new_col:
                moved = True
                for i in range(4):
                    self.board[i][j] = new_col[i]
        return moved

    def check_win(self):
        """检查是否首次达到2048"""
        if self.won:
            return False
        for i in range(4):
            for j in range(4):
                if self.board[i][j] >= 2048:
                    return True
        return False

    def check_game_over(self):
        """检查是否无可用移动"""
        for i in range(4):
            for j in range(4):
                if self.board[i][j] == 0:
                    return False
        for i in range(4):
            for j in range(3):
                if self.board[i][j] == self.board[i][j + 1]:
                    return False
        for i in range(3):
            for j in range(4):
                if self.board[i][j] == self.board[i + 1][j]:
                    return False
        return True

    # ============================================================
    #  UI 更新
    # ============================================================

    def update_board(self):
        """刷新棋盘显示和分数"""
        for i in range(4):
            for j in range(4):
                val = self.board[i][j]
                bg, fg = self.TILE_COLORS.get(val, ("#3c3a32", "#f9f6f2"))
                text = str(val) if val != 0 else ""
                font_size = 28
                if val >= 100:
                    font_size = 24
                if val >= 1000:
                    font_size = 20
                if val >= 10000:
                    font_size = 16
                self.tiles[i][j].setText(text)
                self.tiles[i][j].setStyleSheet(
                    f"background-color: {bg}; color: {fg};"
                    f"border-radius: 5px; font-size: {font_size}px; font-weight: bold;"
                )

        self.score_label.setText(str(self.score))
        current_best = int(self.best_label.text())
        if self.score > current_best:
            self.best_label.setText(str(self.score))

    # ============================================================
    #  鼠标拖拽事件
    # ============================================================

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.pos()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_start is not None:
            end = event.pos()
            dx = end.x() - self._drag_start.x()
            dy = end.y() - self._drag_start.y()
            self._drag_start = None

            threshold = 30
            if abs(dx) < threshold and abs(dy) < threshold:
                return

            if abs(dx) > abs(dy):
                self._do_move(self.move_right if dx > 0 else self.move_left)
            else:
                self._do_move(self.move_down if dy > 0 else self.move_up)
        super().mouseReleaseEvent(event)

    def _do_move(self, move_func):
        """执行移动，处理胜负判定"""
        moved = move_func()
        if moved:
            self.add_random_tile()
            self.update_board()

            if self.check_win() and not self.keep_playing:
                self.won = True
                reply = QMessageBox.question(
                    self, "🎉 恭喜！",
                    "你成功达到了 2048！\n\n太厉害了！是否继续挑战更高的分数？",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
                )
                if reply == QMessageBox.Yes:
                    self.keep_playing = True
                else:
                    self.accept()
                    return

            if self.check_game_over():
                QMessageBox.information(
                    self, "游戏结束",
                    f"没有可用的移动了！\n\n最终分数: {self.score}"
                )

    def new_game(self):
        self.init_game()
        self.update_board()
