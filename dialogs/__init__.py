# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 对话框包

每个子窗口/对话框独立为一个模块，方便协同开发。
"""

from dialogs.history import HistoryDialog
from dialogs.help_dialog import HelpDialog
from dialogs.settings import SettingsDialog
from dialogs.master_profile import MasterProfileDialog
from dialogs.note import NoteDialog
from dialogs.games.rps import RPSDialog
from dialogs.games.game_2048 import Game2048Dialog
from dialogs.games.dice import DiceDialog
from dialogs.games.battleship import BattleshipDialog
from dialogs.api_settings import APISettingsDialog, APISetupWizard
from dialogs.mystery_number import MysteryNumberManager
from dialogs.wallpaper_picker import WallpaperPickerDialog
from dialogs.update_dialog import UpdateDialog
from dialogs.about_dialog import AboutDialog

__all__ = [
    "HistoryDialog",
    "HelpDialog",
    "SettingsDialog",
    "MasterProfileDialog",
    "NoteDialog",
    "RPSDialog",
    "Game2048Dialog",
    "DiceDialog",
    "BattleshipDialog",
    "APISettingsDialog",
    "APISetupWizard",
    "MysteryNumberManager",
    "WallpaperPickerDialog",
    "UpdateDialog",
    "AboutDialog",
]
