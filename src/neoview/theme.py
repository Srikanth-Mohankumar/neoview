"""NeoView application theme."""

LIGHT_STYLE = """
QMainWindow { background-color: #f4f5f7; }
QMenuBar { background-color: #ffffff; color: #1a1a1a; border-bottom: 1px solid #d7dbe0; padding: 2px; }
QMenuBar::item { padding: 4px 10px; border-radius: 3px; }
QMenuBar::item:selected { background-color: #0a66c2; color: #ffffff; }
QMenu { background-color: #ffffff; color: #1a1a1a; border: 1px solid #d7dbe0; padding: 4px; }
QMenu::item { padding: 6px 24px; }
QMenu::item:selected { background-color: #0a66c2; color: #ffffff; }
QMenu::separator { height: 1px; background: #d7dbe0; margin: 4px 8px; }
QToolBar { background-color: #ffffff; border: none; border-bottom: 1px solid #d7dbe0; spacing: 2px; padding: 4px; }
QToolBar::separator { width: 1px; background: #d7dbe0; margin: 2px 6px; }
QToolButton { background-color: #f4f5f7; color: #1a1a1a; border: 1px solid #cfd6dd; border-radius: 4px; padding: 6px 10px; font-size: 12px; min-width: 50px; }
QToolButton:hover { background-color: #e8ecf1; }
QToolButton:pressed, QToolButton:checked { background-color: #0a66c2; border-color: #0a66c2; color: #ffffff; }
QStatusBar { background-color: #eef1f4; color: #1a1a1a; font-size: 11px; }
QStatusBar QLabel { color: #1a1a1a; padding: 0 8px; }
QGraphicsView { background-color: #e5e7eb; border: none; }
QScrollBar:vertical { background: #f0f2f5; width: 10px; }
QScrollBar::handle:vertical { background: #c7ced6; border-radius: 5px; min-height: 20px; }
QScrollBar::handle:vertical:hover { background: #b8c1cb; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #f0f2f5; height: 10px; }
QScrollBar::handle:horizontal { background: #c7ced6; border-radius: 5px; min-width: 20px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QDialog { background-color: #ffffff; color: #1a1a1a; }
QLabel { color: #1a1a1a; }
QComboBox { background-color: #ffffff; color: #1a1a1a; border: 1px solid #cfd6dd; border-radius: 4px; padding: 6px; }
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView { background-color: #ffffff; color: #1a1a1a; selection-background-color: #0a66c2; selection-color: #ffffff; }
QPushButton { background-color: #0a66c2; color: white; border: none; border-radius: 4px; padding: 8px 16px; font-weight: 500; }
QPushButton:hover { background-color: #0b74dd; }
QPushButton[secondary="true"] { background-color: #ffffff; color: #1a1a1a; border: 1px solid #cfd6dd; }
"""
