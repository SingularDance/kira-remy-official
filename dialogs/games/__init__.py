# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 小游戏包

三个独立小游戏，各自零业务依赖。
"""

from dialogs.games.rps import RPSDialog
from dialogs.games.game_2048 import Game2048Dialog
from dialogs.games.dice import DiceDialog

__all__ = [
    "RPSDialog",
    "Game2048Dialog",
    "DiceDialog",
]
