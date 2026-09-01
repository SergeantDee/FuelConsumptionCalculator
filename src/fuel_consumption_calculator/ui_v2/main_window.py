from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import QSize, QTimer, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from fuel_consumption_calculator.config import APPLICATION_NAME, APPLICATION_VERSION
from fuel_consumption_calculator.services.bunker_service import BunkerService
from fuel_consumption_calculator.services.consumption_service import ConsumptionService
from fuel_consumption_calculator.services.fuel_tank_service import FuelTankService
from fuel_consumption_calculator.services.rob_service import ROBService
from fuel_consumption_calculator.services.schedule_service import ScheduleService
from fuel_consumption_calculator.services.scraper_service import ScraperService
from fuel_consumption_calculator.services.settings_service import SettingsService
from fuel_consumption_calculator.services.tank_forecast_service import TankForecastService
from fuel_consumption_calculator.services.vessel_service import VesselService
from fuel_consumption_calculator.services.voyage_service import VoyageService
from fuel_consumption_calculator.ui.pages.bunker_page import BunkerPage
from fuel_consumption_calculator.ui.pages.consumption_page import ConsumptionPage
from fuel_consumption_calculator.ui.pages.schedule_page import SchedulePage
from fuel_consumption_calculator.ui.pages.settings_page import SettingsPage
from fuel_consumption_calculator.ui.pages.voyage_page import VoyagePage
from fuel_consumption_calculator.ui.widgets.navigation_icons import navigation_icon
from fuel_consumption_calculator.ui.widgets.vessel_clock import MAX_OFFSET_MINUTES, MIN_OFFSET_MINUTES, clamp_offset_minutes, format_gmt_offset, vessel_local_time
from fuel_consumption_calculator.ui_v2.pages.dashboard_page import DashboardV2
from fuel_consumption_calculator.ui_v2.pages.fuel_tanks_page import FuelOilTanksPageV2


class MainWindowV2(QMainWindow):
    """Independent V2 shell with legacy page widgets as temporary fallbacks."""
    PAGE_NAMES = ("Dashboard", "Schedule", "Voyage Planner", "Consumption", "Fuel Oil Tanks", "Bunker Planner", "Settings")
    PAGE_ICONS = ("dashboard", "schedule", "voyage", "consumption", "tanks", "bunker", "settings")

    def __init__(self, vessel_service: VesselService, schedule_service: ScheduleService, scraper_service: ScraperService, consumption_service: ConsumptionService, rob_service: ROBService, bunker_service: BunkerService, fuel_tank_service: FuelTankService, voyage_service: VoyageService, settings_service: SettingsService, tank_forecast_service: TankForecastService | None = None) -> None:
        super().__init__()
        self.setWindowTitle(f"{APPLICATION_NAME} {APPLICATION_VERSION}"); self.setMinimumSize(1000, 650); self.resize(1180, 760)
        self._settings_service = settings_service; self._vessel_time_offset_minutes = settings_service.vessel_time_offset_minutes()
        central = QWidget(); outer = QVBoxLayout(central); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0); outer.addWidget(self._build_top_toolbar())
        body = QWidget(); body_layout = QHBoxLayout(body); body_layout.setContentsMargins(0, 0, 0, 0); body_layout.setSpacing(0); body_layout.addWidget(self._build_sidebar())
        self.page_stack = QStackedWidget(); body_layout.addWidget(self.page_stack, 1); outer.addWidget(body, 1); self.setCentralWidget(central); self.statusBar().showMessage("Ready")
        self.dashboard_page = DashboardV2(vessel_service, schedule_service, consumption_service, voyage_service, rob_service)
        self.schedule_page = SchedulePage(vessel_service, schedule_service, scraper_service, settings_service)
        self.voyage_page = VoyagePage(vessel_service, schedule_service, consumption_service, voyage_service, rob_service, settings_service)
        self.consumption_page = ConsumptionPage(vessel_service, consumption_service, schedule_service, voyage_service)
        self.fuel_tanks_page = FuelOilTanksPageV2(vessel_service, fuel_tank_service, tank_forecast_service, voyage_service)
        self.bunker_page = BunkerPage(vessel_service, bunker_service, schedule_service, consumption_service, rob_service, voyage_service)
        self.settings_page = SettingsPage(vessel_service, schedule_service, settings_service, voyage_service, rob_service)
        for page in (self.dashboard_page, self.schedule_page, self.voyage_page, self.consumption_page, self.fuel_tanks_page, self.bunker_page, self.settings_page): self.page_stack.addWidget(page)
        self.settings_page.vessel_saved.connect(self._vessel_configuration_changed); self.dashboard_page.open_voyage_requested.connect(lambda: self.select_page(2)); self.bunker_page.actual_sounding_saved.connect(self._actual_sounding_saved); self.consumption_page.changeover_saved.connect(self._fuel_changeover_saved); self.settings_page.vessel_time_offset_changed.connect(self._set_vessel_time_offset)
        self._clock_timer = QTimer(self); self._clock_timer.timeout.connect(self._refresh_clock); self._clock_timer.start(1000); self._refresh_clock(); self.select_page(0)

    def _build_top_toolbar(self) -> QFrame:
        row = QFrame(); row.setObjectName("v2TopToolbar"); row.setFixedHeight(54); layout = QHBoxLayout(row); layout.setContentsMargins(20, 8, 20, 8); layout.setSpacing(9)
        title = QLabel("Vessel Local Time"); title.setObjectName("v2ToolbarTitle"); layout.addWidget(title)
        self.vessel_time_label = QLabel(); self.vessel_time_label.setObjectName("v2ClockPrimary"); layout.addWidget(self.vessel_time_label)
        self.gmt_offset_label = QLabel(); self.gmt_offset_label.setObjectName("v2ClockSecondary"); layout.addWidget(self.gmt_offset_label); layout.addWidget(self._separator())
        utc = QLabel("UTC"); utc.setObjectName("v2ToolbarTitle"); layout.addWidget(utc)
        self.utc_time_label = QLabel(); self.utc_time_label.setObjectName("v2ClockSecondary"); layout.addWidget(self.utc_time_label); layout.addWidget(self._separator())
        self.vessel_time_minus_button = QPushButton("-1 HOUR"); self.vessel_time_plus_button = QPushButton("+1 HOUR")
        for button in (self.vessel_time_minus_button, self.vessel_time_plus_button): button.setObjectName("v2OutlineButton"); button.setCursor(Qt.CursorShape.PointingHandCursor); layout.addWidget(button)
        self.vessel_time_minus_button.clicked.connect(lambda: self._adjust_vessel_time_offset(-60)); self.vessel_time_plus_button.clicked.connect(lambda: self._adjust_vessel_time_offset(60)); layout.addStretch()
        return row

    @staticmethod
    def _separator() -> QLabel:
        label = QLabel("|"); label.setObjectName("v2ToolbarSeparator"); return label

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame(); sidebar.setObjectName("v2Sidebar"); sidebar.setFixedWidth(190); layout = QVBoxLayout(sidebar); layout.setContentsMargins(12, 18, 12, 14); layout.setSpacing(4)
        identity = QHBoxLayout(); identity.setSpacing(8); icon = QLabel("◈"); icon.setObjectName("v2BrandIcon"); identity.addWidget(icon); text = QVBoxLayout(); text.setSpacing(0)
        brand = QLabel("FUEL PLANNER"); brand.setObjectName("v2BrandTitle"); version = QLabel(APPLICATION_VERSION); version.setObjectName("v2BrandVersion"); text.addWidget(brand); text.addWidget(version); identity.addLayout(text); identity.addStretch(); layout.addLayout(identity); layout.addSpacing(18)
        self.navigation_buttons: list[QPushButton] = []
        for index, name in enumerate(self.PAGE_NAMES):
            button = QPushButton(name); button.setObjectName("v2NavigationButton"); button.setCheckable(True); button.setIcon(navigation_icon(self.PAGE_ICONS[index], "#B5BEC6")); button.setIconSize(QSize(18, 18)); button.setCursor(Qt.CursorShape.PointingHandCursor); button.clicked.connect(lambda checked=False, page_index=index: self.select_page(page_index)); layout.addWidget(button); self.navigation_buttons.append(button)
        layout.addStretch(); return sidebar

    def _refresh_clock(self) -> None:
        utc_now = datetime.now(timezone.utc); vessel_now = vessel_local_time(utc_now, self._vessel_time_offset_minutes); self.vessel_time_label.setText(vessel_now.strftime("%d %b %Y %H:%M:%S")); self.gmt_offset_label.setText(format_gmt_offset(self._vessel_time_offset_minutes)); self.utc_time_label.setText(utc_now.strftime("%d %b %Y %H:%M:%S")); self.vessel_time_minus_button.setEnabled(self._vessel_time_offset_minutes > MIN_OFFSET_MINUTES); self.vessel_time_plus_button.setEnabled(self._vessel_time_offset_minutes < MAX_OFFSET_MINUTES)

    def _adjust_vessel_time_offset(self, adjustment_minutes: int) -> None: self._set_vessel_time_offset(self._vessel_time_offset_minutes + adjustment_minutes)
    def _set_vessel_time_offset(self, minutes: int) -> None: self._vessel_time_offset_minutes = clamp_offset_minutes(minutes); self._settings_service.save_vessel_time_offset_minutes(self._vessel_time_offset_minutes); self._refresh_clock()

    def select_page(self, index: int) -> None:
        if not 0 <= index < self.page_stack.count(): raise IndexError(f"Page index {index} is outside the navigation range.")
        self.page_stack.setCurrentIndex(index)
        for button_index, button in enumerate(self.navigation_buttons): button.setChecked(button_index == index); button.setIcon(navigation_icon(self.PAGE_ICONS[button_index], "#38B6D9" if button_index == index else "#B5BEC6"))
        page = self.page_stack.currentWidget()
        if hasattr(page, "refresh"): page.refresh()

    def _vessel_configuration_changed(self) -> None:
        for page in (self.dashboard_page, self.schedule_page, self.voyage_page, self.consumption_page, self.fuel_tanks_page, self.bunker_page): page.refresh()
        self.statusBar().showMessage("Vessel configuration saved", 4000)
    def _actual_sounding_saved(self) -> None:
        for page in (self.dashboard_page, self.voyage_page, self.bunker_page): page.refresh()
        self.statusBar().showMessage("Actual Sounding ROB saved", 4000)
    def _fuel_changeover_saved(self) -> None:
        self.voyage_page.refresh(); self.dashboard_page.refresh(); self.statusBar().showMessage("Fuel changeover saved; voyage and ROB projections refreshed", 4000)
