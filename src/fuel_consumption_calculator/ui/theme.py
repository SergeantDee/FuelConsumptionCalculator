from __future__ import annotations


DARK_MARINE_STYLESHEET = """
QWidget {
    background-color: #0b1622;
    color: #dce8f2;
    font-family: "Segoe UI";
    font-size: 10pt;
}
QMainWindow { background-color: #0b1622; }
QDialog { background-color: #0b1622; }
#topClockRow {
    background-color: #0d1d29;
    border-bottom: 1px solid #23475d;
}
#sidebar {
    background-color: #102535;
    border-right: 1px solid #1f4156;
}
#brandTitle { color: #f4fbff; font-size: 15pt; font-weight: 700; }
#brandVersion { color: #7fa6bc; font-size: 9pt; }
QPushButton#navigationButton {
    background: transparent;
    border: none;
    border-radius: 5px;
    color: #a9c1d0;
    padding: 11px 14px;
    text-align: left;
}
QPushButton#navigationButton:hover { background-color: #17384d; color: #ffffff; }
QPushButton#navigationButton:checked {
    background-color: #0d637b;
    color: #ffffff;
    font-weight: 600;
}
#pageTitle { color: #ffffff; font-size: 22pt; font-weight: 700; }
#pageSubtitle { color: #86a7b9; font-size: 10pt; }
#card {
    background-color: #122838;
    border: 1px solid #23475d;
    border-radius: 8px;
}
#cardLabel { color: #87aabd; font-size: 9pt; font-weight: 600; }
#cardValue { color: #f5fbff; font-size: 18pt; font-weight: 700; }
#configuredStatus {
    background-color: #12382f;
    border: 1px solid #246c5a;
    border-radius: 6px;
    color: #86e3bd;
    padding: 9px 12px;
}
#notConfiguredStatus {
    background-color: #3b2d1b;
    border: 1px solid #735529;
    border-radius: 6px;
    color: #f1c778;
    padding: 9px 12px;
}
QLineEdit {
    background-color: #0c1d29;
    border: 1px solid #31556b;
    border-radius: 5px;
    min-height: 30px;
    padding: 4px 8px;
    selection-background-color: #0d718d;
}
QLineEdit:focus { border-color: #2ba2c3; }
QLineEdit[readOnly="true"] {
    background-color: #102535;
    border-color: #23475d;
    color: #a8c1cf;
}
QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QDateTimeEdit {
    background-color: #0c1d29;
    border: 1px solid #31556b;
    border-radius: 5px;
    color: #f4fbff;
    min-height: 30px;
    padding: 3px 8px;
    selection-background-color: #0d718d;
    selection-color: #ffffff;
}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus, QDateTimeEdit:focus {
    border-color: #2ba2c3;
}
QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QDateEdit:disabled, QDateTimeEdit:disabled, QLineEdit:disabled {
    background-color: #10202b;
    color: #7892a2;
    border-color: #263f50;
}
QComboBox QAbstractItemView {
    background-color: #102535;
    color: #f4fbff;
    border: 1px solid #31556b;
    selection-background-color: #0d718d;
    selection-color: #ffffff;
}
QCheckBox {
    color: #dce8f2;
    min-height: 26px;
    spacing: 8px;
}
QPushButton {
    background-color: #102535;
    border: 1px solid #31556b;
    border-radius: 5px;
    color: #f4fbff;
    min-height: 32px;
    padding: 5px 14px;
}
QPushButton:hover { background-color: #17384d; border-color: #3d7088; }
QPushButton:focus { border-color: #2ba2c3; }
QPushButton:disabled {
    background-color: #101b25;
    color: #6f8796;
    border-color: #253845;
}
QPushButton#primaryButton {
    background-color: #0d718d;
    border: none;
    border-radius: 5px;
    color: #ffffff;
    font-weight: 600;
    min-height: 34px;
    padding: 6px 18px;
}
QPushButton#primaryButton:hover { background-color: #1188a8; }
QPushButton#dangerButton {
    background-color: #4b2024;
    border: 1px solid #8f454c;
    color: #ffd7da;
}
QPushButton#dangerButton:hover { background-color: #672b31; }
QLabel#fieldLabel { color: #a8c1cf; font-weight: 600; }
QLabel#sectionTitle {
    color: #f4fbff;
    font-size: 11pt;
    font-weight: 700;
}
QLabel#mutedText {
    color: #8caabd;
}
QToolTip {
    background-color: #17384d;
    color: #f4fbff;
    border: 1px solid #3d7088;
    padding: 5px 7px;
}
QFrame#panel {
    background-color: #102535;
    border: 1px solid #23475d;
    border-radius: 8px;
}
QFrame#voyageStagePlanned {
    background-color: #102535;
    border: 1px solid #23475d;
    border-radius: 10px;
}
QFrame#voyageStageCurrent {
    background-color: #0f3140;
    border: 2px solid #1aa0b8;
    border-radius: 10px;
}
QFrame#voyageStageCompleted {
    background-color: #0e2230;
    border: 1px solid #274354;
    border-radius: 10px;
}
QLabel#stageBadgeCurrent {
    background-color: #0d718d;
    border-radius: 5px;
    color: #ffffff;
    font-weight: 700;
    padding: 5px 9px;
}
QLabel#stageBadgePlanned {
    background-color: #17384d;
    border-radius: 5px;
    color: #c9dce8;
    font-weight: 700;
    padding: 5px 9px;
}
QLabel#stageBadgeCompleted {
    background-color: #233845;
    border-radius: 5px;
    color: #8caabd;
    font-weight: 700;
    padding: 5px 9px;
}
QTableView, QTableWidget, QAbstractItemView {
    background-color: #0b1824;
    alternate-background-color: #102535;
    color: #eef7ff;
    gridline-color: #263f50;
    border: 1px solid #31556b;
    selection-background-color: #0d718d;
    selection-color: #ffffff;
}
QTableView::item:hover, QTableWidget::item:hover {
    background-color: #143246;
}
QTableView::item, QTableWidget::item {
    padding: 5px 6px;
    color: #eef7ff;
}
QTableView::item:alternate, QTableWidget::item:alternate {
    background-color: #102535;
}
QTableView::item:selected, QTableWidget::item:selected {
    background-color: #0d718d;
    color: #ffffff;
}
QTableView::item:disabled, QTableWidget::item:disabled {
    color: #7892a2;
}
QHeaderView::section {
    background-color: #132d3f;
    color: #dce8f2;
    border: 0;
    border-right: 1px solid #31556b;
    border-bottom: 1px solid #31556b;
    padding: 8px 7px;
    font-weight: 600;
}
QHeaderView::section:vertical {
    background-color: #102535;
    color: #a8c1cf;
}
QTableCornerButton::section {
    background-color: #132d3f;
    border: 0;
    border-right: 1px solid #31556b;
    border-bottom: 1px solid #31556b;
}
QTabWidget::pane {
    border: 1px solid #31556b;
    background-color: #0b1824;
    top: -1px;
}
QTabBar::tab {
    background-color: #102535;
    color: #9eb8c8;
    border: 1px solid #31556b;
    border-bottom: none;
    padding: 8px 14px;
    min-height: 26px;
}
QTabBar::tab:selected {
    background-color: #0d637b;
    color: #ffffff;
    font-weight: 600;
}
QTabBar::tab:hover {
    background-color: #17384d;
    color: #ffffff;
}
QScrollArea { border: none; background: transparent; }
QDialogButtonBox { padding-top: 6px; }
QScrollBar:vertical, QScrollBar:horizontal {
    background-color: #0b1824;
    border: 1px solid #263f50;
    margin: 0;
}
QScrollBar:vertical { width: 15px; }
QScrollBar:horizontal { height: 15px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background-color: #31556b;
    border-radius: 5px;
    min-height: 28px;
    min-width: 28px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background-color: #3d7088;
}
QScrollBar::add-line, QScrollBar::sub-line {
    background: none;
    border: none;
    width: 0;
    height: 0;
}
QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
}
QStatusBar { background-color: #0d1d29; color: #7798aa; }
"""
