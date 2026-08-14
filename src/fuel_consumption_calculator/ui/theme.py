from __future__ import annotations


DARK_MARINE_STYLESHEET = """
QWidget {
    background-color: #0b1622;
    color: #dce8f2;
    font-family: "Segoe UI";
    font-size: 10pt;
}
QMainWindow { background-color: #0b1622; }
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
    padding: 8px;
    selection-background-color: #0d718d;
}
QLineEdit:focus { border-color: #2ba2c3; }
QPushButton#primaryButton {
    background-color: #0d718d;
    border: none;
    border-radius: 5px;
    color: #ffffff;
    font-weight: 600;
    padding: 9px 18px;
}
QPushButton#primaryButton:hover { background-color: #1188a8; }
QLabel#fieldLabel { color: #a8c1cf; font-weight: 600; }
QStatusBar { background-color: #0d1d29; color: #7798aa; }
"""
