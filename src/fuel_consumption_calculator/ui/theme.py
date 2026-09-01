from __future__ import annotations


# Central visual tokens. Fuel identity colours intentionally live in the shared
# fuel-display widget, not in general application surfaces.
COLORS = {
    "app_background": "#0B1015", "shell": "#11181F", "sidebar": "#10171E",
    "surface": "#0E151B", "raised": "#151E26", "input": "#101820",
    "hover": "#21303A", "selected": "#193447", "border": "#293A46",
    "separator": "#22313B", "text": "#F2F5F7", "secondary_text": "#B2BEC7",
    "muted_text": "#768691", "accent": "#2CB6DE", "accent_bright": "#58C5E8",
    "success": "#5B9C8C", "success_text": "#B6DBD1", "warning": "#B88A48",
    "danger": "#A95D63",
}


DARK_MARINE_STYLESHEET = f"""
QWidget {{ background-color: {COLORS['app_background']}; color: {COLORS['text']}; font-family: "Segoe UI"; font-size: 10pt; }}
QMainWindow, QDialog {{ background-color: {COLORS['app_background']}; }}
#topClockRow {{ background-color: {COLORS['shell']}; border-bottom: 1px solid {COLORS['separator']}; }}
#sidebar {{ background-color: {COLORS['sidebar']}; border-right: 1px solid {COLORS['separator']}; }}
#brandTitle {{ color: {COLORS['text']}; font-size: 13pt; font-weight: 700; letter-spacing: 0.5px; }}
#brandVersion {{ color: {COLORS['muted_text']}; font-size: 8pt; }}
QPushButton#navigationButton {{ background: transparent; border: none; border-left: 3px solid transparent; border-radius: 4px; color: {COLORS['secondary_text']}; min-height: 29px; padding: 5px 10px; text-align: left; }}
QPushButton#navigationButton:hover {{ background-color: {COLORS['hover']}; color: {COLORS['text']}; }}
QPushButton#navigationButton:checked {{ background-color: {COLORS['selected']}; border-left-color: {COLORS['accent']}; color: {COLORS['accent_bright']}; font-weight: 600; }}
#pageTitle {{ color: {COLORS['text']}; font-size: 20pt; font-weight: 700; }}
#pageSubtitle {{ color: {COLORS['secondary_text']}; font-size: 11pt; }}
#sectionTitle {{ color: {COLORS['text']}; font-size: 11pt; font-weight: 700; }}
#card, #panel {{ background-color: {COLORS['raised']}; border: 1px solid {COLORS['border']}; border-radius: 6px; }}
#dashboardCard, #fuelRobCard {{ background-color: {COLORS['raised']}; border: 1px solid {COLORS['border']}; border-radius: 7px; }}
#dashboardSectionTitle {{ color: {COLORS['secondary_text']}; font-size: 8pt; font-weight: 700; }}
#dashboardValue {{ color: {COLORS['text']}; font-size: 14pt; font-weight: 700; }}
#dashboardMetric {{ color: {COLORS['text']}; font-size: 17pt; font-weight: 700; }}
#dashboardMeta {{ color: {COLORS['muted_text']}; font-size: 8pt; }}
#dashboardEmptyState {{ background-color: {COLORS['surface']}; border: 1px solid {COLORS['separator']}; border-left: 3px solid {COLORS['accent']}; border-radius: 5px; color: {COLORS['secondary_text']}; padding: 8px 10px; }}
#infoBanner {{ background-color: {COLORS['surface']}; border: 1px solid {COLORS['separator']}; border-left: 3px solid {COLORS['accent']}; border-radius: 5px; color: {COLORS['secondary_text']}; padding: 8px 10px; }}
#dashboardTable {{ background-color: {COLORS['input']}; border: none; }}
#identityPanel {{ background-color: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 6px; }}
#robCard {{ background-color: {COLORS['raised']}; border: 1px solid {COLORS['border']}; border-radius: 6px; }}
#fuelAccent {{ border: none; border-radius: 2px; max-height: 3px; min-height: 3px; }}
#tankCard {{ background-color: {COLORS['raised']}; border: 1px solid {COLORS['border']}; border-radius: 6px; }}
#tankName {{ color: {COLORS['text']}; font-weight: 700; }}
#tankRob {{ color: {COLORS['text']}; font-size: 10pt; font-weight: 700; }}
#tankMeta {{ color: {COLORS['muted_text']}; font-size: 8pt; }}
#cardLabel {{ color: {COLORS['secondary_text']}; font-size: 8pt; font-weight: 700; }}
#cardValue {{ color: {COLORS['text']}; font-size: 16pt; font-weight: 700; }}
#robValue {{ color: {COLORS['text']}; font-size: 19pt; font-weight: 700; }}
#clockPrimary {{ color: {COLORS['text']}; font-size: 12pt; font-weight: 700; }}
#clockSecondary {{ color: {COLORS['secondary_text']}; font-size: 10pt; }}
#clockSeparator {{ color: {COLORS['separator']}; }}
#configuredStatus {{ background-color: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-left: 3px solid {COLORS['success']}; border-radius: 4px; color: {COLORS['success_text']}; padding: 7px 10px; }}
#notConfiguredStatus {{ background-color: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-left: 3px solid {COLORS['warning']}; border-radius: 4px; color: {COLORS['secondary_text']}; padding: 7px 10px; }}
QLineEdit {{ background-color: {COLORS['input']}; border: 1px solid {COLORS['border']}; border-radius: 4px; min-height: 28px; padding: 3px 8px; selection-background-color: {COLORS['selected']}; }}
QLineEdit:focus {{ border-color: {COLORS['accent']}; }}
QLineEdit[readOnly="true"] {{ background-color: {COLORS['surface']}; color: {COLORS['secondary_text']}; }}
QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QDateTimeEdit {{ background-color: {COLORS['input']}; border: 1px solid {COLORS['border']}; border-radius: 4px; color: {COLORS['text']}; min-height: 28px; padding: 3px 8px; selection-background-color: {COLORS['selected']}; selection-color: {COLORS['text']}; }}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus, QDateTimeEdit:focus {{ border-color: {COLORS['accent']}; }}
QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QDateEdit:disabled, QDateTimeEdit:disabled, QLineEdit:disabled {{ background-color: {COLORS['surface']}; color: {COLORS['muted_text']}; border-color: {COLORS['separator']}; }}
QComboBox QAbstractItemView {{ background-color: {COLORS['raised']}; color: {COLORS['text']}; border: 1px solid {COLORS['border']}; selection-background-color: {COLORS['selected']}; }}
QCheckBox {{ color: {COLORS['text']}; min-height: 24px; spacing: 7px; }}
QPushButton {{ background-color: {COLORS['raised']}; border: 1px solid {COLORS['border']}; border-radius: 4px; color: {COLORS['text']}; min-height: 28px; padding: 4px 12px; }}
QPushButton:hover {{ background-color: {COLORS['hover']}; border-color: {COLORS['secondary_text']}; }}
QPushButton:focus {{ border-color: {COLORS['accent']}; }}
QPushButton:disabled {{ background-color: {COLORS['surface']}; color: {COLORS['muted_text']}; border-color: {COLORS['separator']}; }}
QPushButton#primaryButton {{ background-color: {COLORS['accent']}; border: 1px solid {COLORS['accent']}; color: #071218; font-weight: 700; min-height: 32px; padding: 5px 15px; }}
QPushButton#primaryButton:hover {{ background-color: {COLORS['accent_bright']}; border-color: {COLORS['accent_bright']}; }}
QPushButton#dangerButton {{ background-color: #47282D; border: 1px solid {COLORS['danger']}; color: #F0C6C9; }}
QPushButton#dangerButton:hover {{ background-color: #5C3036; }}
QLabel#fieldLabel {{ color: {COLORS['secondary_text']}; font-size: 8pt; font-weight: 700; }}
QLabel#emptyState {{ background-color: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 5px; color: {COLORS['secondary_text']}; padding: 9px 11px; }}
QLabel#mutedText {{ color: {COLORS['muted_text']}; }}
QToolTip {{ background-color: {COLORS['raised']}; color: {COLORS['text']}; border: 1px solid {COLORS['border']}; padding: 5px 7px; }}
QFrame#voyageStagePlanned {{ background-color: {COLORS['raised']}; border: 1px solid {COLORS['border']}; border-radius: 7px; }}
QFrame#voyageStageCurrent {{ background-color: {COLORS['selected']}; border: 1px solid {COLORS['accent']}; border-radius: 7px; }}
QFrame#voyageStageCompleted {{ background-color: {COLORS['surface']}; border: 1px solid {COLORS['separator']}; border-radius: 7px; }}
QLabel#stageBadgeCurrent {{ background-color: {COLORS['accent']}; border-radius: 4px; color: #071218; font-weight: 700; padding: 4px 7px; }}
QLabel#stageBadgePlanned {{ background-color: {COLORS['hover']}; border-radius: 4px; color: {COLORS['secondary_text']}; font-weight: 700; padding: 4px 7px; }}
QLabel#stageBadgeCompleted {{ background-color: {COLORS['separator']}; border-radius: 4px; color: {COLORS['muted_text']}; font-weight: 700; padding: 4px 7px; }}
QTableView, QTableWidget, QAbstractItemView {{ background-color: {COLORS['input']}; alternate-background-color: {COLORS['surface']}; color: {COLORS['text']}; gridline-color: {COLORS['separator']}; border: 1px solid {COLORS['border']}; selection-background-color: {COLORS['selected']}; selection-color: {COLORS['text']}; }}
QTableView::item:hover, QTableWidget::item:hover {{ background-color: {COLORS['hover']}; }}
QTableView::item, QTableWidget::item {{ padding: 4px 6px; color: {COLORS['text']}; }}
QTableView::item:alternate, QTableWidget::item:alternate {{ background-color: {COLORS['surface']}; }}
QTableView::item:selected, QTableWidget::item:selected {{ background-color: {COLORS['selected']}; color: {COLORS['text']}; }}
QTableView::item:disabled, QTableWidget::item:disabled {{ color: {COLORS['muted_text']}; }}
QHeaderView::section {{ background-color: {COLORS['raised']}; color: {COLORS['secondary_text']}; border: 0; border-right: 1px solid {COLORS['border']}; border-bottom: 1px solid {COLORS['border']}; padding: 6px; font-weight: 700; }}
QHeaderView::section:vertical {{ background-color: {COLORS['surface']}; color: {COLORS['muted_text']}; }}
QTableCornerButton::section {{ background-color: {COLORS['raised']}; border: 0; border-right: 1px solid {COLORS['border']}; border-bottom: 1px solid {COLORS['border']}; }}
QTabWidget::pane {{ border: 1px solid {COLORS['border']}; background-color: {COLORS['input']}; top: -1px; }}
QTabBar::tab {{ background-color: {COLORS['surface']}; color: {COLORS['secondary_text']}; border: 1px solid {COLORS['border']}; border-bottom: none; padding: 7px 12px; min-height: 24px; }}
QTabBar::tab:selected {{ background-color: {COLORS['selected']}; color: {COLORS['accent_bright']}; font-weight: 700; }}
QTabBar::tab:hover {{ background-color: {COLORS['hover']}; color: {COLORS['text']}; }}
QScrollArea {{ border: none; background: transparent; }} QDialogButtonBox {{ padding-top: 8px; border-top: 1px solid {COLORS['separator']}; }}
QScrollBar:vertical, QScrollBar:horizontal {{ background-color: {COLORS['input']}; border: 1px solid {COLORS['separator']}; margin: 0; }}
QScrollBar:vertical {{ width: 13px; }} QScrollBar:horizontal {{ height: 13px; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{ background-color: {COLORS['border']}; border-radius: 4px; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{ background-color: {COLORS['secondary_text']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ background: none; border: none; width: 0; height: 0; }} QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QStatusBar {{ background-color: {COLORS['shell']}; color: {COLORS['muted_text']}; border-top: 1px solid {COLORS['separator']}; font-size: 8pt; }}
#v2TopToolbar {{ background-color: #171C22; border-bottom: 1px solid #29343D; }}
#v2Sidebar {{ background-color: #151B21; border-right: 1px solid #29343D; }}
#v2BrandIcon {{ color: #38B6D9; font-size: 22pt; }}
#v2BrandTitle {{ color: #F2F4F6; font-size: 11pt; font-weight: 700; letter-spacing: 0.5px; }}
#v2BrandVersion, #v2CardMeta {{ color: #7F8B95; font-size: 8pt; }}
QPushButton#v2NavigationButton {{ background: transparent; border: none; border-left: 3px solid transparent; border-radius: 4px; color: #B5BEC6; min-height: 31px; padding: 5px 9px; text-align: left; }}
QPushButton#v2NavigationButton:hover {{ background-color: #27323C; color: #F2F4F6; }}
QPushButton#v2NavigationButton:checked {{ background-color: #243847; border-left-color: #38B6D9; color: #38B6D9; font-weight: 600; }}
#v2ToolbarTitle {{ color: #B5BEC6; font-size: 8pt; font-weight: 700; }}
#v2ClockPrimary {{ color: #F2F4F6; font-size: 11pt; font-weight: 700; }}
#v2ClockSecondary {{ color: #B5BEC6; font-size: 9pt; }}
#v2ToolbarSeparator {{ color: #29343D; font-size: 12pt; }}
QPushButton#v2OutlineButton {{ background-color: transparent; border: 1px solid #34414C; border-radius: 4px; color: #B5BEC6; min-height: 27px; padding: 3px 10px; }}
QPushButton#v2OutlineButton:hover {{ background-color: #27323C; border-color: #38B6D9; color: #F2F4F6; }}
#v2PageTitle {{ color: #F2F4F6; font-size: 26px; font-weight: 700; }}
#v2PageSubtitle {{ color: #B5BEC6; font-size: 13px; }}
#v2AppCard {{ background-color: #1B2229; border: 1px solid #34414C; border-radius: 7px; }}
#v2CardHeading {{ color: #B5BEC6; font-size: 9px; font-weight: 700; }}
#v2VesselIcon {{ color: #38B6D9; font-size: 25px; }}
#v2VesselName {{ color: #F2F4F6; font-size: 18px; font-weight: 700; }}
#v2FuelMetric {{ color: #F2F4F6; font-size: 26px; font-weight: 700; }}
#v2MetricValue {{ color: #F2F4F6; font-size: 19px; font-weight: 700; }}
#v2EmptyState {{ background-color: #141A20; border: 1px solid #29343D; border-left: 3px solid #38B6D9; border-radius: 5px; color: #B5BEC6; padding: 8px 10px; }}
#v2ScheduleTable {{ background-color: #151B21; border: 1px solid #34414C; }}
#v2TankGroupHeading, #v2Orientation {{ color: #B5BEC6; font-size: 10px; font-weight: 700; }}
#v2Orientation {{ color: #7F8B95; font-weight: 400; }}
#v2TankCard {{ background-color: #202830; border: 1px solid #34414C; border-radius: 6px; }}
#v2TankCard[selected="true"] {{ background-color: #243847; border: 2px solid #38B6D9; }}
#v2TankName {{ color: #F2F4F6; font-size: 11px; font-weight: 700; }}
#v2TankCaption {{ color: #B5BEC6; font-size: 9px; font-weight: 700; }}
#v2TankValue, #v2InspectorValue {{ color: #F2F4F6; font-size: 18px; font-weight: 700; }}
#v2TankMeta {{ color: #7F8B95; font-size: 10px; }}
QProgressBar#v2TankGauge {{ background-color: #101820; border: 1px solid #293A46; border-radius: 4px; min-height: 12px; max-height: 12px; }}
QProgressBar#v2TankGauge::chunk {{ border-radius: 3px; }}
#v2HistoryTable, #v2SurveyTable {{ background-color: #151B21; border: 1px solid #34414C; }}
#v2SurveyBasis {{ color: #B5BEC6; font-size: 9px; }}
#v2SurveyTotals {{ color: #F2F4F6; font-size: 15px; font-weight: 700; }}
#v2SurveyStatus, #v2SurveyActualOption {{ color: #B5BEC6; }}
#v2InspectorEmptyIcon {{ color: #768691; font-size: 32px; }}
#v2InspectorEmptyTitle {{ color: #F2F5F7; font-size: 14px; font-weight: 600; }}
#v2DialogTitle {{ color: #F2F5F7; font-size: 20px; font-weight: 700; }}
#v2FuelInfoCard {{ background-color: #151E26; border: 1px solid #293A46; border-radius: 6px; }}
"""
