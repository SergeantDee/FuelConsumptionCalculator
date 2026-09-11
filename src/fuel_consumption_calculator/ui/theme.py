from __future__ import annotations


DARK_MARINE_STYLESHEET = """
QWidget {
    background-color: #08131d;
    color: #dce7ee;
    font-family: "Segoe UI";
    font-size: 10pt;
}
QLabel { background: transparent; }
QMainWindow, QDialog { background-color: #08131d; }
#topClockRow {
    background-color: #0b1a25;
    border-bottom: 1px solid #1d3342;
}
#clockCaption { color: #7893a3; font-size: 8pt; font-weight: 700; }
#clockPrimary { color: #f6fafc; font-size: 16pt; font-weight: 700; }
#clockZone { color: #9eb1bd; font-size: 9pt; font-weight: 600; }
#clockSecondary { color: #8aa0ae; font-size: 9pt; }
#clockSeparator { color: #38505f; }
QPushButton#clockAdjustButton {
    background-color: #101f2a;
    border: 1px solid #263f4e;
    color: #c7d5de;
    min-height: 26px;
    padding: 2px 10px;
}
QPushButton#clockAdjustButton:hover { background-color: #172d3a; border-color: #35596b; color: #ffffff; }
#sidebar {
    background-color: #0c1d29;
    border-right: 1px solid #1d3342;
}
#brandTitle { color: #f4f8fb; font-size: 14pt; font-weight: 700; }
#brandVersion { color: #718c9c; font-size: 8.5pt; }
QPushButton#navigationButton {
    background: transparent;
    border: 0;
    border-left: 3px solid transparent;
    border-radius: 6px;
    color: #a4b7c3;
    padding: 9px 11px;
    text-align: left;
}
QPushButton#navigationButton:hover { background-color: #132b38; color: #eef5f8; }
QPushButton#navigationButton:checked {
    background-color: #173441;
    border-left: 3px solid #2e8ca5;
    color: #f4f9fb;
    font-weight: 600;
}
#pageTitle { color: #f5f9fb; font-size: 20pt; font-weight: 700; }
#pageSubtitle { color: #829aa9; font-size: 9.5pt; }
#pageEyebrow { color: #55b7cf; font-size: 8.5pt; font-weight: 700; }
#card {
    background-color: #10232f;
    border: 1px solid #203846;
    border-radius: 7px;
}
#identityCard { background-color: #0e202c; border: 1px solid #1d3342; border-radius: 7px; }
#robCard { background-color: #10232f; border: 1px solid #203846; border-radius: 7px; }
#robCard[fuel="ULSFO"] { border-top: 2px solid #28768a; }
#robCard[fuel="VLSFO"] { border-top: 2px solid #645487; }
#robCard[fuel="MDO"] { border-top: 2px solid #80521f; }
#cardLabel { color: #7f99a8; font-size: 8.5pt; font-weight: 600; }
#cardValue { color: #f5f9fb; font-size: 17pt; font-weight: 700; }
#configuredStatus {
    background-color: #113029;
    border: 1px solid #245445;
    border-radius: 6px;
    color: #84d2b1;
    padding: 7px 10px;
}
#notConfiguredStatus {
    background-color: #302717;
    border: 1px solid #5d4926;
    border-radius: 6px;
    color: #e6c277;
    padding: 7px 10px;
}
QLineEdit {
    background-color: #0c1c27;
    border: 1px solid #294353;
    border-radius: 6px;
    min-height: 28px;
    padding: 4px 8px;
    selection-background-color: #236f84;
}
QLineEdit:hover { border-color: #35576a; }
QLineEdit:focus { border-color: #318ca5; }
QLineEdit[readOnly="true"] {
    background-color: #0f202b;
    border-color: #203846;
    color: #9fb1bc;
}
QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QDateTimeEdit {
    background-color: #0c1c27;
    border: 1px solid #294353;
    border-radius: 6px;
    color: #eef4f7;
    min-height: 28px;
    padding: 3px 8px;
    selection-background-color: #236f84;
    selection-color: #ffffff;
}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QDateEdit:hover, QDateTimeEdit:hover { border-color: #35576a; }
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus, QDateTimeEdit:focus {
    border-color: #318ca5;
}
QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QDateEdit:disabled, QDateTimeEdit:disabled, QLineEdit:disabled {
    background-color: #0d1922;
    color: #647b89;
    border-color: #1d303d;
}
QComboBox QAbstractItemView {
    background-color: #10232f;
    color: #eef4f7;
    border: 1px solid #294353;
    selection-background-color: #1d5264;
    selection-color: #ffffff;
}
QCheckBox {
    color: #d5e0e7;
    min-height: 24px;
    spacing: 8px;
}
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #365465; border-radius: 4px; background-color: #0b1a24; }
QCheckBox::indicator:hover { border-color: #4b778d; }
QCheckBox::indicator:checked { background-color: #287f98; border-color: #3d9ab3; }
QPushButton {
    background-color: #112531;
    border: 1px solid #294353;
    border-radius: 6px;
    color: #e4edf2;
    min-height: 30px;
    padding: 4px 13px;
}
QPushButton:hover { background-color: #18313f; border-color: #3a5d6f; color: #ffffff; }
QPushButton:pressed { background-color: #0d202b; }
QPushButton:focus { border-color: #318ca5; }
QPushButton:disabled {
    background-color: #0c1821;
    color: #607783;
    border-color: #1b2d38;
}
QPushButton#primaryButton {
    background-color: #176b82;
    border: 1px solid #277f96;
    border-radius: 6px;
    color: #ffffff;
    font-weight: 600;
    min-height: 32px;
    padding: 5px 16px;
}
QPushButton#primaryButton:hover { background-color: #1d7f99; border-color: #3997af; }
QPushButton#secondaryButton { background-color: #112531; border-color: #294353; color: #dbe6ec; }
QPushButton#dangerButton {
    background-color: #3b2024;
    border: 1px solid #714047;
    color: #efc2c6;
}
QPushButton#dangerButton:hover { background-color: #50272d; border-color: #8a4a53; }
QLabel#fieldLabel { color: #a7b9c4; font-weight: 600; }
QLabel#sectionTitle {
    color: #eef4f7;
    font-size: 11pt;
    font-weight: 700;
}
QLabel#sectionCardTitle {
    color: #f2f7f9;
    font-size: 13pt;
    font-weight: 700;
}
QLabel#emptyState {
    background-color: #0f202b;
    border: 1px solid #203846;
    border-radius: 7px;
    color: #91a6b2;
    padding: 10px 12px;
}
QLabel#mutedText {
    color: #8da4b1;
}
QToolTip {
    background-color: #17384d;
    color: #f4fbff;
    border: 1px solid #3d7088;
    padding: 5px 7px;
}
QFrame#panel {
    background-color: #0f222e;
    border: 1px solid #203846;
    border-radius: 7px;
}
QGroupBox {
    background-color: #0f222e;
    border: 1px solid #203846;
    border-radius: 7px;
    margin-top: 12px;
    padding-top: 9px;
    font-weight: 600;
}
QGroupBox::title { color: #b9c9d2; subcontrol-origin: margin; left: 10px; padding: 0 4px; }
QFrame#voyageStagePlanned {
    background-color: #0f222e;
    border: 1px solid #203846;
    border-radius: 7px;
}
QFrame#voyageStageCurrent {
    background-color: #14313d;
    border: 1px solid #367c91;
    border-radius: 7px;
}
QFrame#voyageStageCompleted {
    background-color: #0d1d27;
    border: 1px solid #1d3340;
    border-radius: 7px;
}
QLabel#stageBadgeCurrent {
    background-color: #1b6579;
    border-radius: 4px;
    color: #ffffff;
    font-weight: 700;
    padding: 3px 8px;
}
QLabel#stageBadgePlanned {
    background-color: #1b303d;
    border-radius: 4px;
    color: #bdccd5;
    font-weight: 700;
    padding: 3px 8px;
}
QLabel#stageBadgeCompleted {
    background-color: #1b2a34;
    border-radius: 4px;
    color: #879ca8;
    font-weight: 700;
    padding: 3px 8px;
}
QTableView, QTableWidget, QAbstractItemView {
    background-color: #0a1721;
    alternate-background-color: #0e202b;
    color: #e5edf2;
    gridline-color: #1c303c;
    border: 1px solid #203846;
    border-radius: 4px;
    selection-background-color: #1b5365;
    selection-color: #ffffff;
}
QTableView::item:hover, QTableWidget::item:hover {
    background-color: #142c39;
}
QTableView::item, QTableWidget::item {
    padding: 4px 5px;
    color: #e5edf2;
}
QTableView::item:alternate, QTableWidget::item:alternate {
    background-color: #0e202b;
}
QTableView::item:selected, QTableWidget::item:selected {
    background-color: #1b5365;
    color: #ffffff;
}
QTableView::item:disabled, QTableWidget::item:disabled {
    color: #7892a2;
}
QHeaderView::section {
    background-color: #122633;
    color: #cbd8df;
    border: 0;
    border-right: 1px solid #263e4c;
    border-bottom: 1px solid #2a4656;
    padding: 7px 8px;
    font-weight: 600;
}
QHeaderView::section:vertical {
    background-color: #0f202b;
    color: #94a8b4;
}
QTableCornerButton::section {
    background-color: #122633;
    border: 0;
    border-right: 1px solid #263e4c;
    border-bottom: 1px solid #2a4656;
}
QTabWidget::pane {
    border: 1px solid #203846;
    background-color: #0a1721;
    top: -1px;
}
QTabBar::tab {
    background-color: #0e202b;
    color: #92a8b5;
    border: 0;
    border-bottom: 2px solid transparent;
    padding: 7px 13px;
    min-height: 24px;
}
QTabBar::tab:selected {
    background-color: #162e3a;
    border-bottom: 2px solid #318ca5;
    color: #f1f6f8;
    font-weight: 600;
}
QTabBar::tab:hover {
    background-color: #142a36;
    color: #e8f0f4;
}
QScrollArea { border: none; background: transparent; }
QDialogButtonBox { padding-top: 6px; }
QDialogButtonBox QPushButton { min-width: 96px; }
QScrollBar:vertical, QScrollBar:horizontal {
    background-color: #091721;
    border: 0;
    margin: 0;
}
QScrollBar:vertical { width: 10px; }
QScrollBar:horizontal { height: 10px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background-color: #345467;
    border-radius: 4px;
    min-height: 28px;
    min-width: 28px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background-color: #477389;
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
QStatusBar { background-color: #0a1822; color: #6f8998; border-top: 1px solid #182c38; }
#tankWorkspace { background-color: #0b1b25; border: 1px solid #1d3342; border-radius: 7px; }
#tankGroupHeading { background: transparent; font-size: 12pt; font-weight: 700; padding: 6px 2px 5px 2px; border-bottom: 1px solid #203846; }
#tankCard { background-color: #10232f; border: 1px solid #294353; border-radius: 6px; }
#tankCard[fuel="MDO"] { border-top: 2px solid #80521f; }
#tankCard[fuel="ULSFO"] { border-top: 2px solid #28768a; }
#tankCard[fuel="VLSFO"] { border-top: 2px solid #645487; }
#tankCard:hover { background-color: #142c39; border-color: #477083; }
#tankName { color: #eef4f7; font-size: 14px; font-weight: 600; }
#tankRob { color: #f5f9fb; font-size: 23px; font-weight: 650; }
#tankFill { font-size: 17px; font-weight: 700; }
#tankMeta { color: #829aa8; font-size: 10px; }
#tankGaugeMark { color: #a5b7c1; font-size: 9px; }
#planSummaryCard, #phaseValidationCard { background-color: #0f222e; border: 1px solid #203846; border-radius: 7px; }
#consumptionPhaseCard { background-color: #10232f; border: 1px solid #203846; border-radius: 7px; }
#phaseTitle, #planSummaryLabel { color: #91a7b4; font-size: 9pt; font-weight: 700; }
#planSummaryValue { color: #f1f6f8; font-size: 13pt; font-weight: 700; }
#phaseTankName { color: #dce7ed; }
#phaseAllocation { color: #f1f6f8; font-weight: 700; }
#phaseForecastLine { color: #829aa8; }
#phaseBadgeCurrent, #phaseBadgeActive { background-color: #1b6579; color: #ffffff; border-radius: 4px; padding: 3px 8px; font-weight: 700; }
#phaseBadgeCompleted { background-color: #1b2a34; color: #879ca8; border-radius: 4px; padding: 3px 8px; font-weight: 700; }
#phaseBadgeNext, #phaseBadgePlanned { background-color: #1b303d; color: #bdccd5; border-radius: 4px; padding: 3px 8px; font-weight: 700; }
#soundingSurveyDialog { background-color: #08131d; }
#surveyIcon { color: #4ba9bf; font-size: 25px; }
#surveyTitle { color: #f3f8fa; font-size: 22px; font-weight: 700; }
#surveyHeaderCard, #surveySummaryCard { background-color: #0f222e; border: 1px solid #203846; border-radius: 7px; }
#surveyHint { color: #839ba9; font-size: 10px; }
#surveyBasisText { color: #d8e3e9; font-size: 11px; }
#surveyTankName { color: #eef4f7; font-size: 12px; font-weight: 600; padding-left: 6px; }
#surveyCalculated { color: #d8e3e9; font-size: 12px; font-weight: 600; padding-left: 8px; }
#surveySummaryTitle { color: #a7b9c4; font-size: 10px; font-weight: 700; }
#surveyTotalValue { color: #f4f8fa; font-size: 20px; font-weight: 700; }
#surveyCountValue { color: #f4f8fa; font-size: 18px; font-weight: 700; }
QTableWidget#soundingSurveyTable { background-color: #0a1822; border: 1px solid #203846; gridline-color: #1d3342; }
QPushButton#surveyCancelButton { min-height: 36px; min-width: 110px; }
#receivingTanksDialog { background-color: #08131d; }
#receivingTitleIcon { color: #4ba9bf; font-size: 22px; }
#receivingTitle { color: #f3f8fa; font-size: 22px; font-weight: 700; }
#receivingHint, #receivingNote { color: #8da4b1; font-size: 11px; }
#receivingIncomingCard, #receivingSummaryCard { background-color: #0f222e; border: 1px solid #203846; border-radius: 7px; }
QTableWidget#receivingTanksTable { background-color: #0a1822; border: 1px solid #203846; gridline-color: #1d3342; }
#receivingSummaryValue { color: #eef4f7; font-size: 14px; font-weight: 700; }
QPushButton#receivingCancelButton, QPushButton#receivingSaveButton { min-height: 38px; min-width: 130px; }
QPushButton#receivingSaveButton { background-color: #176b82; border-color: #277f96; color: #ffffff; font-weight: 700; }
"""
