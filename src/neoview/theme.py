"""NeoView application theme."""

DARK_STYLE = """
* {
    font-family: "JetBrains Mono", "Fira Code", "Consolas", monospace;
    color: #e8e8ed;
    selection-background-color: #5b8df6;
    selection-color: #ffffff;
}
QMainWindow,
QDialog,
QWidget {
    background: #0d0d0f;
    color: #e8e8ed;
}
QMenuBar {
    background: #111116;
    border-bottom: 1px solid #23242b;
    padding: 4px 8px;
}
QMenuBar::item {
    padding: 5px 10px;
    border-radius: 6px;
}
QMenuBar::item:selected {
    background: #1b2438;
    color: #ffffff;
}
QMenu {
    background: #111116;
    border: 1px solid #242733;
    padding: 6px;
}
QMenu::item {
    padding: 6px 28px 6px 12px;
    border-radius: 6px;
}
QMenu::item:selected {
    background: #20345f;
}
QMenu::separator {
    height: 1px;
    background: #252733;
    margin: 6px 6px;
}
QToolBar {
    background: #101015;
    border: none;
    border-bottom: 1px solid #23242b;
    spacing: 6px;
    padding: 6px 10px;
}
QToolBar::separator {
    width: 1px;
    background: #272a35;
    margin: 3px 10px;
}
QToolButton {
    background: #161822;
    border: 1px solid #272b39;
    border-radius: 7px;
    padding: 6px;
    min-width: 28px;
    min-height: 28px;
}
QToolButton:hover {
    background: #1d2230;
    border-color: #384059;
}
QToolButton:pressed,
QToolButton:checked {
    background: #2a3f71;
    border-color: #5b8df6;
    color: #ffffff;
}
QToolButton::menu-indicator {
    image: none;
    width: 0;
}
QStatusBar {
    background: #0f1014;
    border-top: 1px solid #23242b;
    min-height: 28px;
}
QStatusBar QLabel {
    padding: 0 8px;
    color: #cfd3de;
}
QGraphicsView {
    background: #141417;
    border: none;
}
QScrollBar:vertical {
    background: #0e1015;
    width: 12px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #2a2f40;
    border-radius: 6px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover {
    background: #3b4257;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: #0e1015;
    height: 12px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #2a2f40;
    border-radius: 6px;
    min-width: 28px;
}
QScrollBar::handle:horizontal:hover {
    background: #3b4257;
}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0;
}
QLineEdit,
QComboBox,
QPlainTextEdit,
QTextEdit,
QSpinBox {
    background: #151720;
    border: 1px solid #2a2d3a;
    border-radius: 6px;
    padding: 6px 8px;
    color: #e8e8ed;
}
QLineEdit:focus,
QComboBox:focus,
QPlainTextEdit:focus,
QTextEdit:focus {
    border-color: #5b8df6;
}
QComboBox::drop-down {
    border: none;
    width: 18px;
}
QComboBox QAbstractItemView {
    background: #111218;
    border: 1px solid #2b3040;
}
QPushButton {
    background: #1a2235;
    border: 1px solid #2c3e66;
    border-radius: 7px;
    padding: 6px 12px;
    color: #e9eeff;
}
QPushButton:hover {
    background: #223055;
    border-color: #456bb5;
}
QPushButton:pressed {
    background: #182644;
}
QPushButton[secondary="true"] {
    background: #171920;
    border: 1px solid #303342;
    color: #d8dce8;
}
QListWidget,
QTreeWidget {
    background: #111218;
    border: 1px solid #262a36;
    border-radius: 8px;
    padding: 4px;
}
QListWidget::item,
QTreeWidget::item {
    padding: 4px 6px;
    border-radius: 4px;
}
QListWidget::item:selected,
QTreeWidget::item:selected {
    background: #2a3e71;
}
QDockWidget::title {
    background: #101116;
    border: 1px solid #252935;
    border-bottom: none;
    padding: 8px;
    text-align: left;
}
QDockWidget > QWidget {
    border: 1px solid #252935;
    border-top: none;
}
QCheckBox {
    spacing: 7px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #3a4258;
    border-radius: 3px;
    background: #131620;
}
QCheckBox::indicator:checked {
    background: #5b8df6;
    border-color: #5b8df6;
}
QToolTip {
    background: #1a1d27;
    border: 1px solid #3a4668;
    color: #f1f4ff;
    padding: 4px 8px;
}
QFrame[separator="true"] {
    background: #272a35;
    max-height: 1px;
    min-height: 1px;
}
QWidget#InspectorPanel {
    background: #101116;
}
QToolButton#InspectorSectionHeader {
    background: transparent;
    border: none;
    font-weight: 600;
    text-align: left;
    padding: 8px 4px 6px 2px;
}
QToolButton#InspectorSectionHeader:hover {
    color: #ffffff;
}
QWidget#InspectorSectionContent {
    background: transparent;
}
QLabel#InfoLabel {
    color: #b9bfce;
}
QLabel#InfoValue {
    color: #f3f5fb;
    font-weight: 600;
}
QLabel#MonoValue {
    color: #f4f7ff;
    font-size: 14px;
    font-weight: 700;
}
QLabel#StatusDot {
    min-width: 10px;
    max-width: 10px;
    min-height: 10px;
    max-height: 10px;
    border-radius: 5px;
    background: #5b8df6;
}
QLabel#StatusDot[offline="true"] {
    background: #4f5566;
}
QLabel#FloatingMeasureBadge {
    background: rgba(8, 10, 16, 230);
    border: 1px solid rgba(91, 141, 246, 180);
    border-radius: 7px;
    padding: 4px 7px;
    color: #e9f0ff;
    font-size: 12px;
    font-weight: 700;
}
"""

# Backward compatibility for older imports.
LIGHT_STYLE = DARK_STYLE
