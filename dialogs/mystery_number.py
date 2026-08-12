# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 显示神秘小数字

悬浮数字管理器：在桌宠头顶显示一个带有颜色的数字，
显示 4 秒后淡出隐藏。每 10 分钟后台随机选取一种颜色/数值，
窗口期内每次点击显示相同数字。
"""

import random
import time

from PyQt5.QtWidgets import QLabel, QGraphicsOpacityEffect
from PyQt5.QtCore import QObject, QTimer, QPropertyAnimation, Qt

import config


class MysteryNumberManager(QObject):
    """在宠物头顶上方显示彩色数字，4 秒后淡出；每 10 分钟更换颜色/数值。"""

    CATEGORIES = {
        "red":    {"color": "#E93F3F"},   # 愤怒次数
        "blue":   {"color": "#3F58BD"},   # 启动次数
        "mint":   {"color": "#5DE6CD"},   # 152 / 16
        "orange": {"color": "#F59E42"},   # 最近 2048 得分
        "violet": {"color": "#B481DD"},   # -2147483648 / -0
        "pink":   {"color": "#F26D9E"},   # "喜欢你"次数
    }

    def __init__(self, pet):
        super().__init__(pet)
        self._pet = pet
        self._selection = None      # (category_key, value_str, color)
        self._last_refresh_time = 0  # 上次刷新时间戳
        self._number_anim = None

        # 悬浮标签：插入布局顶部，占据固定高度但默认透明不可见
        self._number_label = QLabel(self._pet)
        self._number_label.setAlignment(Qt.AlignCenter)
        self._number_label.setFixedHeight(36)
        self._number_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._number_opacity = QGraphicsOpacityEffect(self._number_label)
        self._number_label.setGraphicsEffect(self._number_opacity)
        self._number_opacity.setOpacity(0.0)
        self._pet.layout().insertWidget(0, self._number_label, 0, Qt.AlignHCenter)

        # 10 分钟刷新计时器
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_selection)
        self._refresh_timer.start(10 * 60 * 1000)

        # 4 秒显示计时器（单发）
        self._display_timer = QTimer(self)
        self._display_timer.setSingleShot(True)
        self._display_timer.timeout.connect(self._hide_number)

        # 启动时立刻选定一个，保证首次点击就有数字
        self._refresh_selection()

    # ============================================================
    #  刷新逻辑
    # ============================================================

    def _refresh_selection(self):
        """每 10 分钟随机选 1 个类别并快照数值。窗口期内点击永远显示同一个数。"""
        self._last_refresh_time = time.time()
        key = random.choice(list(self.CATEGORIES.keys()))
        value = self._compute_value(key)
        self._selection = (key, str(value), self.CATEGORIES[key]["color"])

    def _compute_value(self, key):
        """根据类别 key 计算当前数值（快照时机：刷新/首次调用时）"""
        if key == "red":
            return config.STATS.get("angry_count", 0)
        if key == "blue":
            return config.STATS.get("launch_count", 0)
        if key == "mint":
            return random.choice(["152", "16"])
        if key == "orange":
            return config.STATS.get("last_2048_score", 0)
        if key == "violet":
            return random.choice(["-2147483648", "-0"])
        if key == "pink":
            return config.STATS.get("like_count", 0)
        return 0

    # ============================================================
    #  显示 / 隐藏
    # ============================================================

    def show_number(self):
        """菜单点击入口：显示当前选中的数字，重置 4 秒计时。"""
        # 超过 10 分钟则刷新选择（兜底：即使 QTimer 未按时触发也能更新）
        if self._selection is None or time.time() - self._last_refresh_time > 10 * 60:
            self._refresh_selection()
        key, value_str, color = self._selection
        # 计数类数值（红/蓝/橙/粉）实时读取最新值；魔法常量（薄荷绿/紫罗兰）保持快照
        if key in ("red", "blue", "orange", "pink"):
            value_str = str(self._compute_value(key))
        self._stop_animations()
        self._number_label.setText(value_str)
        self._number_label.setStyleSheet(
            f"color: {color}; font-size: 26px; font-weight: bold;"
            "font-family: Microsoft YaHei; background-color: transparent;"
        )
        self._display_timer.start(4000)
        # 淡入
        self._number_anim = QPropertyAnimation(self._number_opacity, b"opacity")
        self._number_anim.setDuration(300)
        self._number_anim.setStartValue(self._number_opacity.opacity())
        self._number_anim.setEndValue(1.0)
        self._number_anim.start()

    def _hide_number(self):
        """4 秒计时到达 → 淡出"""
        self._display_timer.stop()
        anim = QPropertyAnimation(self._number_opacity, b"opacity")
        anim.setDuration(300)
        anim.setStartValue(self._number_opacity.opacity())
        anim.setEndValue(0.0)
        anim.finished.connect(self._on_hidden)
        self._number_anim = anim
        anim.start()

    def _on_hidden(self):
        """淡出完成后清空文字"""
        self._number_label.setText("")

    def _stop_animations(self):
        """中断当前显示（重新点击时调用）"""
        self._display_timer.stop()
        if self._number_anim is not None:
            self._number_anim.stop()
            self._number_anim = None
