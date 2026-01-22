"""NeoView application theme."""

DARK_STYLE = """
QMainWindow { background-color: #1e1e1e; }
QMenuBar { background-color: #2d2d2d; color: #e0e0e0; border-bottom: 1px solid #404040; padding: 2px; }
QMenuBar::item { padding: 4px 10px; border-radius: 3px; }
QMenuBar::item:selected { background-color: #0078d4; }
QMenu { background-color: #2d2d2d; color: #e0e0e0; border: 1px solid #404040; padding: 4px; }
QMenu::item { padding: 6px 24px; }
QMenu::item:selected { background-color: #0078d4; }
QMenu::separator { height: 1px; background: #404040; margin: 4px 8px; }
QToolBar { background-color: #252526; border: none; border-bottom: 1px solid #404040; spacing: 2px; padding: 4px; }
QToolBar::separator { width: 1px; background: #404040; margin: 2px 6px; }
QToolButton { background-color: #3c3c3c; color: #e0e0e0; border: 1px solid #4a4a4a; border-radius: 4px; padding: 6px 10px; font-size: 12px; min-width: 50px; }
QToolButton:hover { background-color: #4a4a4a; }
QToolButton:pressed, QToolButton:checked { background-color: #0078d4; border-color: #0078d4; }
QStatusBar { background-color: #007acc; color: white; font-size: 11px; }
QStatusBar QLabel { color: white; padding: 0 8px; }
QGraphicsView { background-color: #404040; border: none; }
QScrollBar:vertical { background: #2d2d2d; width: 10px; }
QScrollBar::handle:vertical { background: #5a5a5a; border-radius: 5px; min-height: 20px; }
QScrollBar::handle:vertical:hover { background: #6a6a6a; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #2d2d2d; height: 10px; }
QScrollBar::handle:horizontal { background: #5a5a5a; border-radius: 5px; min-width: 20px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QDialog { background-color: #2d2d2d; color: #e0e0e0; }
QLabel { color: #e0e0e0; }
QComboBox { background-color: #3c3c3c; color: #e0e0e0; border: 1px solid #4a4a4a; border-radius: 4px; padding: 6px; }
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView { background-color: #2d2d2d; color: #e0e0e0; selection-background-color: #0078d4; }
QPushButton { background-color: #0078d4; color: white; border: none; border-radius: 4px; padding: 8px 16px; font-weight: 500; }
QPushButton:hover { background-color: #1a88e0; }
QPushButton[secondary="true"] { background-color: #3c3c3c; border: 1px solid #4a4a4a; }
"""
