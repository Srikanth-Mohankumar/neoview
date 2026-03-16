"""NeoView application theme — professional PDF viewer styling."""

DARK_STYLE = """
* {
    font-family: "Inter", "SF Pro Display", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
    color: #e2e4e9;
    selection-background-color: #4a90d9;
    selection-color: #ffffff;
}

/* ── Main containers ── */
QMainWindow,
QDialog {
    background: #1e1e1e;
}
QWidget {
    background: transparent;
    color: #e2e4e9;
}

/* ── Tab bar ── */
QTabWidget::pane {
    border: none;
    background: #1e1e1e;
}
QTabBar {
    background: #252526;
    border-bottom: 1px solid #333333;
    qproperty-drawBase: 0;
}
QTabBar::tab {
    background: #2d2d2d;
    border: none;
    border-right: 1px solid #333333;
    padding: 7px 18px;
    min-width: 100px;
    max-width: 220px;
    font-size: 12px;
    color: #999999;
}
QTabBar::tab:selected {
    background: #1e1e1e;
    color: #ffffff;
    border-bottom: 2px solid #4a90d9;
}
QTabBar::tab:hover:!selected {
    background: #353535;
    color: #cccccc;
}
QTabBar::close-button {
    image: none;
    subcontrol-position: right;
    padding: 2px;
}

/* ── Menu bar ── */
QMenuBar {
    background: #2d2d2d;
    border-bottom: 1px solid #404040;
    padding: 0;
    spacing: 0;
    font-size: 12px;
    min-height: 30px;
}
QMenuBar::item {
    padding: 6px 12px;
    background: transparent;
    border-radius: 0;
}
QMenuBar::item:selected {
    background: #3d3d3d;
    color: #ffffff;
}
QMenuBar::item:pressed {
    background: #4a90d9;
    color: #ffffff;
}

/* ── Dropdown menus ── */
QMenu {
    background: #2d2d2d;
    border: 1px solid #484848;
    border-radius: 4px;
    padding: 4px 0;
    font-size: 12px;
}
QMenu::item {
    padding: 6px 32px 6px 28px;
    border: none;
    min-width: 160px;
}
QMenu::item:selected {
    background: #4a90d9;
    color: #ffffff;
}
QMenu::item:disabled {
    color: #666666;
}
QMenu::separator {
    height: 1px;
    background: #404040;
    margin: 4px 8px;
}
QMenu::icon {
    padding-left: 8px;
}
QMenu::indicator {
    width: 14px;
    height: 14px;
    padding-left: 8px;
}

/* ── Toolbar ── */
QToolBar {
    background: #2d2d2d;
    border: none;
    border-bottom: 1px solid #404040;
    spacing: 2px;
    padding: 3px 8px;
    min-height: 36px;
}
QToolBar::separator {
    width: 1px;
    background: #404040;
    margin: 4px 6px;
}
QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 4px;
    min-width: 28px;
    min-height: 28px;
    color: #cccccc;
    font-size: 12px;
}
QToolButton:hover {
    background: #3d3d3d;
    border-color: #505050;
}
QToolButton:pressed {
    background: #4a4a4a;
}
QToolButton:checked {
    background: #37547a;
    border-color: #4a90d9;
    color: #ffffff;
}
QToolButton::menu-indicator {
    image: none;
    width: 0;
}

/* ── Status bar ── */
QStatusBar {
    background: #252526;
    border-top: 1px solid #404040;
    min-height: 24px;
    font-size: 11px;
    color: #999999;
}
QStatusBar::item {
    border: none;
}
QStatusBar QLabel {
    padding: 0 6px;
    color: #999999;
    font-size: 11px;
}

/* ── Graphics view (PDF canvas) ── */
QGraphicsView {
    background: #1a1a1a;
    border: none;
}

/* ── Scroll bars ── */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #555555;
    border-radius: 5px;
    min-height: 30px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover {
    background: #777777;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #555555;
    border-radius: 5px;
    min-width: 30px;
    margin: 2px;
}
QScrollBar::handle:horizontal:hover {
    background: #777777;
}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0;
}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical,
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: transparent;
}

/* ── Input fields ── */
QLineEdit,
QComboBox,
QPlainTextEdit,
QTextEdit,
QSpinBox,
QDoubleSpinBox {
    background: #333333;
    border: 1px solid #4a4a4a;
    border-radius: 4px;
    padding: 5px 8px;
    color: #e2e4e9;
    font-size: 12px;
    min-height: 20px;
}
QLineEdit:focus,
QComboBox:focus,
QPlainTextEdit:focus,
QTextEdit:focus,
QSpinBox:focus,
QDoubleSpinBox:focus {
    border-color: #4a90d9;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
    padding-right: 4px;
}
QComboBox::down-arrow {
    width: 8px;
    height: 8px;
}
QComboBox QAbstractItemView {
    background: #2d2d2d;
    border: 1px solid #484848;
    selection-background-color: #4a90d9;
    outline: none;
}

/* ── Buttons ── */
QPushButton {
    background: #3d3d3d;
    border: 1px solid #555555;
    border-radius: 4px;
    padding: 5px 14px;
    color: #e2e4e9;
    font-size: 12px;
    min-height: 20px;
}
QPushButton:hover {
    background: #4a4a4a;
    border-color: #666666;
}
QPushButton:pressed {
    background: #333333;
}
QPushButton[secondary="true"] {
    background: #2d2d2d;
    border: 1px solid #484848;
    color: #bbbbbb;
}
QPushButton[secondary="true"]:hover {
    background: #3a3a3a;
}

/* ── Lists and trees ── */
QListWidget,
QTreeWidget {
    background: #252526;
    border: 1px solid #3d3d3d;
    border-radius: 4px;
    padding: 2px;
    outline: none;
    font-size: 12px;
}
QListWidget::item,
QTreeWidget::item {
    padding: 4px 8px;
    border-radius: 3px;
    border: none;
}
QListWidget::item:selected,
QTreeWidget::item:selected {
    background: #37547a;
    color: #ffffff;
}
QListWidget::item:hover:!selected,
QTreeWidget::item:hover:!selected {
    background: #2f2f2f;
}
QTreeWidget::branch {
    background: transparent;
}
QHeaderView::section {
    background: #2d2d2d;
    border: none;
    border-bottom: 1px solid #404040;
    padding: 4px 8px;
    font-size: 11px;
    color: #999999;
}

/* ── Dock widgets ── */
QDockWidget {
    font-size: 12px;
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}
QDockWidget::title {
    background: #2d2d2d;
    border: none;
    border-bottom: 1px solid #404040;
    padding: 6px 10px;
    text-align: left;
    font-weight: 600;
    font-size: 11px;
    color: #bbbbbb;
}
QDockWidget > QWidget {
    border: none;
    background: #252526;
}

/* ── Checkboxes ── */
QCheckBox {
    spacing: 6px;
    font-size: 12px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #555555;
    border-radius: 3px;
    background: #333333;
}
QCheckBox::indicator:hover {
    border-color: #4a90d9;
}
QCheckBox::indicator:checked {
    background: #4a90d9;
    border-color: #4a90d9;
}

/* ── Sliders ── */
QSlider::groove:horizontal {
    background: #404040;
    height: 4px;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #bbbbbb;
    width: 12px;
    height: 12px;
    margin: -4px 0;
    border-radius: 6px;
}
QSlider::handle:horizontal:hover {
    background: #4a90d9;
}

/* ── Tooltips ── */
QToolTip {
    background: #3d3d3d;
    border: 1px solid #555555;
    color: #e2e4e9;
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 11px;
}

/* ── Separator lines ── */
QFrame[separator="true"] {
    background: #404040;
    max-height: 1px;
    min-height: 1px;
    margin: 4px 0;
}

/* ── Inspector panel ── */
QWidget#InspectorPanel {
    background: #252526;
}
QToolButton#InspectorSectionHeader {
    background: transparent;
    border: none;
    border-bottom: 1px solid transparent;
    font-weight: 600;
    font-size: 11px;
    text-align: left;
    padding: 8px 4px 6px 0;
    color: #bbbbbb;
}
QToolButton#InspectorSectionHeader:hover {
    color: #ffffff;
}
QWidget#InspectorSectionContent {
    background: transparent;
}

/* ── Inspector data labels ── */
QLabel#InfoLabel {
    color: #888888;
    font-size: 11px;
}
QLabel#InfoValue {
    color: #dddddd;
    font-weight: 600;
    font-size: 11px;
}
QLabel#MonoValue {
    color: #e8e8e8;
    font-family: "JetBrains Mono", "Fira Code", "Consolas", "Courier New", "DejaVu Sans Mono", monospace;
    font-size: 13px;
    font-weight: 600;
}

/* ── Status indicators ── */
QLabel#StatusDot {
    min-width: 8px;
    max-width: 8px;
    min-height: 8px;
    max-height: 8px;
    border-radius: 4px;
    background: #4a90d9;
}
QLabel#StatusDot[offline="true"] {
    background: #666666;
}

/* ── Floating badges ── */
QLabel#FloatingMeasureBadge {
    background: rgba(30, 30, 30, 240);
    border: 1px solid rgba(74, 144, 217, 160);
    border-radius: 4px;
    padding: 3px 8px;
    color: #e2e4e9;
    font-family: "JetBrains Mono", "Fira Code", "Consolas", "Courier New", "DejaVu Sans Mono", monospace;
    font-size: 11px;
    font-weight: 600;
}
QLabel#LinkBadge {
    background: rgba(30, 30, 30, 240);
    border: 1px solid rgba(74, 144, 217, 160);
    border-radius: 9px;
}

/* ── Panel toggle buttons ── */
QPushButton#PanelToggleBtn {
    background: transparent;
    border: none;
    border-radius: 3px;
    padding: 4px 8px;
    font-size: 11px;
    color: #999999;
    min-height: 22px;
}
QPushButton#PanelToggleBtn:hover {
    background: #3d3d3d;
    color: #cccccc;
}
QPushButton#PanelToggleBtn:checked {
    background: #37547a;
    color: #ffffff;
}

/* ── Inspector tab widget ── */
QTabWidget#InspectorTabs::pane {
    border: none;
    background: transparent;
}
QTabWidget#InspectorTabs > QTabBar {
    background: #2d2d2d;
    border-bottom: 1px solid #3d3d3d;
}
QTabWidget#InspectorTabs > QTabBar::tab {
    background: #2d2d2d;
    border: none;
    padding: 5px 10px;
    font-size: 11px;
    color: #888888;
    min-width: 0;
    max-width: 9999px;
}
QTabWidget#InspectorTabs > QTabBar::tab:selected {
    background: #252526;
    color: #e2e4e9;
    border-bottom: 2px solid #4a90d9;
}
QTabWidget#InspectorTabs > QTabBar::tab:hover:!selected {
    background: #333333;
    color: #bbbbbb;
}

/* ── Annotation list alternating rows ── */
QListWidget#annotation_list::item:alternate {
    background: #2a2a2a;
}
"""

LIGHT_STYLE = """
* {
    font-family: "Inter", "SF Pro Display", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
    color: #333333;
    selection-background-color: #2680eb;
    selection-color: #ffffff;
}

/* ── Main containers ── */
QMainWindow,
QDialog {
    background: #f5f5f5;
}
QWidget {
    background: transparent;
    color: #333333;
}

/* ── Tab bar ── */
QTabWidget::pane {
    border: none;
    background: #f5f5f5;
}
QTabBar {
    background: #e8e8e8;
    border-bottom: 1px solid #d1d1d1;
    qproperty-drawBase: 0;
}
QTabBar::tab {
    background: #e0e0e0;
    border: none;
    border-right: 1px solid #d1d1d1;
    padding: 7px 18px;
    min-width: 100px;
    max-width: 220px;
    font-size: 12px;
    color: #777777;
}
QTabBar::tab:selected {
    background: #f5f5f5;
    color: #222222;
    border-bottom: 2px solid #2680eb;
}
QTabBar::tab:hover:!selected {
    background: #d8d8d8;
    color: #444444;
}
QTabBar::close-button {
    image: none;
    subcontrol-position: right;
    padding: 2px;
}

/* ── Menu bar ── */
QMenuBar {
    background: #f0f0f0;
    border-bottom: 1px solid #d1d1d1;
    padding: 0;
    spacing: 0;
    font-size: 12px;
    min-height: 30px;
}
QMenuBar::item {
    padding: 6px 12px;
    background: transparent;
    border-radius: 0;
}
QMenuBar::item:selected {
    background: #dce7f5;
    color: #1a5fb4;
}
QMenuBar::item:pressed {
    background: #2680eb;
    color: #ffffff;
}

/* ── Dropdown menus ── */
QMenu {
    background: #ffffff;
    border: 1px solid #d1d1d1;
    border-radius: 4px;
    padding: 4px 0;
    font-size: 12px;
}
QMenu::item {
    padding: 6px 32px 6px 28px;
    border: none;
    min-width: 160px;
}
QMenu::item:selected {
    background: #2680eb;
    color: #ffffff;
}
QMenu::item:disabled {
    color: #aaaaaa;
}
QMenu::separator {
    height: 1px;
    background: #e0e0e0;
    margin: 4px 8px;
}
QMenu::icon {
    padding-left: 8px;
}
QMenu::indicator {
    width: 14px;
    height: 14px;
    padding-left: 8px;
}

/* ── Toolbar ── */
QToolBar {
    background: #f0f0f0;
    border: none;
    border-bottom: 1px solid #d1d1d1;
    spacing: 2px;
    padding: 3px 8px;
    min-height: 36px;
}
QToolBar::separator {
    width: 1px;
    background: #d1d1d1;
    margin: 4px 6px;
}
QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 4px;
    min-width: 28px;
    min-height: 28px;
    color: #555555;
    font-size: 12px;
}
QToolButton:hover {
    background: #e0e0e0;
    border-color: #c8c8c8;
}
QToolButton:pressed {
    background: #d0d0d0;
}
QToolButton:checked {
    background: #dce7f5;
    border-color: #2680eb;
    color: #1a5fb4;
}
QToolButton::menu-indicator {
    image: none;
    width: 0;
}

/* ── Status bar ── */
QStatusBar {
    background: #f0f0f0;
    border-top: 1px solid #d1d1d1;
    min-height: 24px;
    font-size: 11px;
    color: #777777;
}
QStatusBar::item {
    border: none;
}
QStatusBar QLabel {
    padding: 0 6px;
    color: #777777;
    font-size: 11px;
}

/* ── Graphics view (PDF canvas) ── */
QGraphicsView {
    background: #e0e0e0;
    border: none;
}

/* ── Scroll bars ── */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #c0c0c0;
    border-radius: 5px;
    min-height: 30px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover {
    background: #a0a0a0;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #c0c0c0;
    border-radius: 5px;
    min-width: 30px;
    margin: 2px;
}
QScrollBar::handle:horizontal:hover {
    background: #a0a0a0;
}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0;
}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical,
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: transparent;
}

/* ── Input fields ── */
QLineEdit,
QComboBox,
QPlainTextEdit,
QTextEdit,
QSpinBox,
QDoubleSpinBox {
    background: #ffffff;
    border: 1px solid #c8c8c8;
    border-radius: 4px;
    padding: 5px 8px;
    color: #333333;
    font-size: 12px;
    min-height: 20px;
}
QLineEdit:focus,
QComboBox:focus,
QPlainTextEdit:focus,
QTextEdit:focus,
QSpinBox:focus,
QDoubleSpinBox:focus {
    border-color: #2680eb;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
    padding-right: 4px;
}
QComboBox::down-arrow {
    width: 8px;
    height: 8px;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #d1d1d1;
    selection-background-color: #2680eb;
    outline: none;
}

/* ── Buttons ── */
QPushButton {
    background: #e8e8e8;
    border: 1px solid #c8c8c8;
    border-radius: 4px;
    padding: 5px 14px;
    color: #333333;
    font-size: 12px;
    min-height: 20px;
}
QPushButton:hover {
    background: #dcdcdc;
    border-color: #bbbbbb;
}
QPushButton:pressed {
    background: #d0d0d0;
}
QPushButton[secondary="true"] {
    background: #f0f0f0;
    border: 1px solid #d1d1d1;
    color: #555555;
}
QPushButton[secondary="true"]:hover {
    background: #e4e4e4;
}

/* ── Lists and trees ── */
QListWidget,
QTreeWidget {
    background: #ffffff;
    border: 1px solid #d1d1d1;
    border-radius: 4px;
    padding: 2px;
    outline: none;
    font-size: 12px;
}
QListWidget::item,
QTreeWidget::item {
    padding: 4px 8px;
    border-radius: 3px;
    border: none;
}
QListWidget::item:selected,
QTreeWidget::item:selected {
    background: #dce7f5;
    color: #1a5fb4;
}
QListWidget::item:hover:!selected,
QTreeWidget::item:hover:!selected {
    background: #f0f4fa;
}
QTreeWidget::branch {
    background: transparent;
}
QHeaderView::section {
    background: #f0f0f0;
    border: none;
    border-bottom: 1px solid #d1d1d1;
    padding: 4px 8px;
    font-size: 11px;
    color: #777777;
}

/* ── Dock widgets ── */
QDockWidget {
    font-size: 12px;
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}
QDockWidget::title {
    background: #f0f0f0;
    border: none;
    border-bottom: 1px solid #d1d1d1;
    padding: 6px 10px;
    text-align: left;
    font-weight: 600;
    font-size: 11px;
    color: #555555;
}
QDockWidget > QWidget {
    border: none;
    background: #f5f5f5;
}

/* ── Checkboxes ── */
QCheckBox {
    spacing: 6px;
    font-size: 12px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #bbbbbb;
    border-radius: 3px;
    background: #ffffff;
}
QCheckBox::indicator:hover {
    border-color: #2680eb;
}
QCheckBox::indicator:checked {
    background: #2680eb;
    border-color: #2680eb;
}

/* ── Sliders ── */
QSlider::groove:horizontal {
    background: #d1d1d1;
    height: 4px;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #777777;
    width: 12px;
    height: 12px;
    margin: -4px 0;
    border-radius: 6px;
}
QSlider::handle:horizontal:hover {
    background: #2680eb;
}

/* ── Tooltips ── */
QToolTip {
    background: #ffffff;
    border: 1px solid #d1d1d1;
    color: #333333;
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 11px;
}

/* ── Separator lines ── */
QFrame[separator="true"] {
    background: #d1d1d1;
    max-height: 1px;
    min-height: 1px;
    margin: 4px 0;
}

/* ── Inspector panel ── */
QWidget#InspectorPanel {
    background: #f5f5f5;
}
QToolButton#InspectorSectionHeader {
    background: transparent;
    border: none;
    border-bottom: 1px solid transparent;
    font-weight: 600;
    font-size: 11px;
    text-align: left;
    padding: 8px 4px 6px 0;
    color: #555555;
}
QToolButton#InspectorSectionHeader:hover {
    color: #1a5fb4;
}
QWidget#InspectorSectionContent {
    background: transparent;
}

/* ── Inspector data labels ── */
QLabel#InfoLabel {
    color: #888888;
    font-size: 11px;
}
QLabel#InfoValue {
    color: #333333;
    font-weight: 600;
    font-size: 11px;
}
QLabel#MonoValue {
    color: #222222;
    font-family: "JetBrains Mono", "Fira Code", "Consolas", "Courier New", "DejaVu Sans Mono", monospace;
    font-size: 13px;
    font-weight: 600;
}

/* ── Status indicators ── */
QLabel#StatusDot {
    min-width: 8px;
    max-width: 8px;
    min-height: 8px;
    max-height: 8px;
    border-radius: 4px;
    background: #2680eb;
}
QLabel#StatusDot[offline="true"] {
    background: #aaaaaa;
}

/* ── Floating badges ── */
QLabel#FloatingMeasureBadge {
    background: rgba(255, 255, 255, 240);
    border: 1px solid rgba(38, 128, 235, 160);
    border-radius: 4px;
    padding: 3px 8px;
    color: #333333;
    font-family: "JetBrains Mono", "Fira Code", "Consolas", "Courier New", "DejaVu Sans Mono", monospace;
    font-size: 11px;
    font-weight: 600;
}
QLabel#LinkBadge {
    background: rgba(255, 255, 255, 240);
    border: 1px solid rgba(38, 128, 235, 160);
    border-radius: 9px;
}

/* ── Panel toggle buttons ── */
QPushButton#PanelToggleBtn {
    background: transparent;
    border: none;
    border-radius: 3px;
    padding: 4px 8px;
    font-size: 11px;
    color: #777777;
    min-height: 22px;
}
QPushButton#PanelToggleBtn:hover {
    background: #e0e0e0;
    color: #444444;
}
QPushButton#PanelToggleBtn:checked {
    background: #dce7f5;
    color: #1a5fb4;
}

/* ── Inspector tab widget ── */
QTabWidget#InspectorTabs::pane {
    border: none;
    background: transparent;
}
QTabWidget#InspectorTabs > QTabBar {
    background: #ebebeb;
    border-bottom: 1px solid #d1d1d1;
}
QTabWidget#InspectorTabs > QTabBar::tab {
    background: #ebebeb;
    border: none;
    padding: 5px 10px;
    font-size: 11px;
    color: #888888;
    min-width: 0;
    max-width: 9999px;
}
QTabWidget#InspectorTabs > QTabBar::tab:selected {
    background: #f5f5f5;
    color: #222222;
    border-bottom: 2px solid #2680eb;
}
QTabWidget#InspectorTabs > QTabBar::tab:hover:!selected {
    background: #e0e0e0;
    color: #555555;
}

/* ── Annotation list alternating rows ── */
QListWidget::item:alternate {
    background: #fafafa;
}
"""
