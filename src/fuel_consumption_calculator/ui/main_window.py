from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from fuel_consumption_calculator.config import APPLICATION_NAME, APPLICATION_VERSION
from fuel_consumption_calculator.services.bunker_service import BunkerService
from fuel_consumption_calculator.services.consumption_service import ConsumptionService
from fuel_consumption_calculator.services.fuel_tank_service import FuelTankService
from fuel_consumption_calculator.services.rob_service import ROBService
from fuel_consumption_calculator.services.schedule_service import ScheduleService
from fuel_consumption_calculator.services.scraper_service import ScraperService
from fuel_consumption_calculator.services.settings_service import SettingsService
from fuel_consumption_calculator.services.vessel_service import VesselService
from fuel_consumption_calculator.services.voyage_service import VoyageService
from fuel_consumption_calculator.ui.pages.bunker_page import BunkerPage
from fuel_consumption_calculator.ui.pages.consumption_page import ConsumptionPage
from fuel_consumption_calculator.ui.pages.dashboard_page import DashboardPage
from fuel_consumption_calculator.ui.pages.fuel_tanks_page import FuelTanksPage
from fuel_consumption_calculator.ui.pages.schedule_page import SchedulePage
from fuel_consumption_calculator.ui.pages.settings_page import SettingsPage
from fuel_consumption_calculator.ui.pages.voyage_page import VoyagePage
from fuel_consumption_calculator.ui.widgets.vessel_clock import (
    MAX_OFFSET_MINUTES,
    MIN_OFFSET_MINUTES,
    clamp_offset_minutes,
    format_gmt_offset,
    vessel_local_time,
)


class MainWindow(QMainWindow):
    PAGE_NAMES = ("Dashboard", "Schedule", "Voyage Planner", "Consumption", "Fuel Oil Tanks", "Bunker Planner", "Settings")

    def __init__(
        self,
        vessel_service: VesselService,
        schedule_service: ScheduleService,
        scraper_service: ScraperService,
        consumption_service: ConsumptionService,
        rob_service: ROBService,
        bunker_service: BunkerService,
        fuel_tank_service: FuelTankService,
        voyage_service: VoyageService,
        settings_service: SettingsService,
    ) -> None:
        super().__init__()
        self.setWindowTitle(f"{APPLICATION_NAME} {APPLICATION_VERSION}")
        self.setMinimumSize(1000, 650)
        self.resize(1180, 760)
        self._settings_service = settings_service
        self._vessel_time_offset_minutes = settings_service.vessel_time_offset_minutes()

        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self._build_clock_row())
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        central_layout.addWidget(root, 1)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 24, 16, 18)
        sidebar_layout.setSpacing(7)
        brand = QLabel("FUEL PLANNER")
        brand.setObjectName("brandTitle")
        sidebar_layout.addWidget(brand)
        version = QLabel(f"Desktop  •  v{APPLICATION_VERSION}")
        version.setObjectName("brandVersion")
        sidebar_layout.addWidget(version)
        sidebar_layout.addSpacing(22)

        self.page_stack = QStackedWidget()
        self.dashboard_page = DashboardPage(vessel_service, schedule_service, consumption_service, voyage_service, rob_service)
        self.schedule_page = SchedulePage(vessel_service, schedule_service, scraper_service, settings_service)
        self.voyage_page = VoyagePage(vessel_service, schedule_service, consumption_service, voyage_service, rob_service, settings_service)
        self.consumption_page = ConsumptionPage(vessel_service, consumption_service, schedule_service, voyage_service)
        self.fuel_tanks_page = FuelTanksPage(vessel_service, fuel_tank_service)
        self.bunker_page = BunkerPage(vessel_service, bunker_service, schedule_service, consumption_service, rob_service, voyage_service)
        self.settings_page = SettingsPage(vessel_service, schedule_service, settings_service, voyage_service, rob_service)
        pages = (
            self.dashboard_page,
            self.schedule_page,
            self.voyage_page,
            self.consumption_page,
            self.fuel_tanks_page,
            self.bunker_page,
            self.settings_page,
        )
        for page in pages:
            self.page_stack.addWidget(page)

        self.navigation_buttons: list[QPushButton] = []
        for index, name in enumerate(self.PAGE_NAMES):
            button = QPushButton(name)
            button.setObjectName("navigationButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, page_index=index: self.select_page(page_index))
            sidebar_layout.addWidget(button)
            self.navigation_buttons.append(button)
        sidebar_layout.addStretch()

        root_layout.addWidget(sidebar)
        root_layout.addWidget(self.page_stack, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Ready")

        self.settings_page.vessel_saved.connect(self._vessel_configuration_changed)
        self.bunker_page.actual_sounding_saved.connect(self._actual_sounding_saved)
        self.consumption_page.changeover_saved.connect(self._fuel_changeover_saved)
        self.settings_page.vessel_time_offset_changed.connect(self._set_vessel_time_offset)
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._refresh_clock)
        self._clock_timer.start(1000)
        self._refresh_clock()
        self.select_page(0)

    def _build_clock_row(self) -> QFrame:
        row = QFrame()
        row.setObjectName("topClockRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(16, 5, 16, 5)
        layout.setSpacing(10)
        local_title = QLabel("VESSEL LOCAL TIME")
        local_title.setObjectName("fieldLabel")
        self.vessel_time_label = QLabel()
        self.vessel_time_label.setObjectName("cardValue")
        self.gmt_offset_label = QLabel()
        self.gmt_offset_label.setObjectName("fieldLabel")
        separator_one = QLabel("|")
        utc_title = QLabel("UTC")
        utc_title.setObjectName("fieldLabel")
        self.utc_time_label = QLabel()
        self.utc_time_label.setObjectName("mutedText")
        separator_two = QLabel("|")
        self.vessel_time_minus_button = QPushButton("-1 HOUR")
        self.vessel_time_plus_button = QPushButton("+1 HOUR")
        for button in (self.vessel_time_minus_button, self.vessel_time_plus_button):
            button.setMinimumHeight(26)
        self.vessel_time_minus_button.clicked.connect(lambda: self._adjust_vessel_time_offset(-60))
        self.vessel_time_plus_button.clicked.connect(lambda: self._adjust_vessel_time_offset(60))
        for widget in (local_title, self.vessel_time_label, self.gmt_offset_label, separator_one, utc_title, self.utc_time_label, separator_two, self.vessel_time_minus_button, self.vessel_time_plus_button):
            layout.addWidget(widget)
        layout.addStretch()
        return row

    def _refresh_clock(self) -> None:
        utc_now = datetime.now(timezone.utc)
        vessel_now = vessel_local_time(utc_now, self._vessel_time_offset_minutes)
        self.vessel_time_label.setText(vessel_now.strftime("%d %b %Y %H:%M:%S"))
        self.gmt_offset_label.setText(format_gmt_offset(self._vessel_time_offset_minutes))
        self.utc_time_label.setText(utc_now.strftime("%d %b %Y %H:%M:%S"))
        self.vessel_time_minus_button.setEnabled(self._vessel_time_offset_minutes > MIN_OFFSET_MINUTES)
        self.vessel_time_plus_button.setEnabled(self._vessel_time_offset_minutes < MAX_OFFSET_MINUTES)

    def _adjust_vessel_time_offset(self, adjustment_minutes: int) -> None:
        self._set_vessel_time_offset(self._vessel_time_offset_minutes + adjustment_minutes)

    def _set_vessel_time_offset(self, minutes: int) -> None:
        self._vessel_time_offset_minutes = clamp_offset_minutes(minutes)
        self._settings_service.save_vessel_time_offset_minutes(self._vessel_time_offset_minutes)
        self._refresh_clock()

    def select_page(self, index: int) -> None:
        if not 0 <= index < self.page_stack.count():
            raise IndexError(f"Page index {index} is outside the navigation range.")
        self.page_stack.setCurrentIndex(index)
        for button_index, button in enumerate(self.navigation_buttons):
            button.setChecked(button_index == index)
        if index == 0:
            self.dashboard_page.refresh()
        elif index == 1:
            self.schedule_page.refresh()
        elif index == 2:
            self.voyage_page.refresh()
        elif index == 3:
            self.consumption_page.refresh()
        elif index == 4:
            self.fuel_tanks_page.refresh()
        elif index == 5:
            self.bunker_page.refresh()
        elif index == 6:
            self.settings_page.refresh()

    def _vessel_configuration_changed(self) -> None:
        self.dashboard_page.refresh()
        self.schedule_page.refresh()
        self.voyage_page.refresh()
        self.consumption_page.refresh()
        self.fuel_tanks_page.refresh()
        self.bunker_page.refresh()
        self.statusBar().showMessage("Vessel configuration saved", 4000)

    def _actual_sounding_saved(self) -> None:
        self.dashboard_page.refresh()
        self.voyage_page.refresh()
        self.bunker_page.refresh()
        self.statusBar().showMessage("Actual Sounding ROB saved", 4000)

    def _fuel_changeover_saved(self) -> None:
        self.voyage_page.refresh()
        self.dashboard_page.refresh()
        self.statusBar().showMessage("Fuel changeover saved; voyage and ROB projections refreshed", 4000)
