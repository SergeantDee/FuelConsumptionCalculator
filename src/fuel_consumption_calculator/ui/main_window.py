from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from fuel_consumption_calculator.config import APPLICATION_NAME, APPLICATION_VERSION
from fuel_consumption_calculator.services.bunker_service import BunkerService
from fuel_consumption_calculator.services.consumption_service import ConsumptionService
from fuel_consumption_calculator.services.rob_service import ROBService
from fuel_consumption_calculator.services.schedule_service import ScheduleService
from fuel_consumption_calculator.services.scraper_service import ScraperService
from fuel_consumption_calculator.services.vessel_service import VesselService
from fuel_consumption_calculator.services.voyage_service import VoyageService
from fuel_consumption_calculator.ui.pages.bunker_page import BunkerPage
from fuel_consumption_calculator.ui.pages.consumption_page import ConsumptionPage
from fuel_consumption_calculator.ui.pages.dashboard_page import DashboardPage
from fuel_consumption_calculator.ui.pages.rob_page import RobPage
from fuel_consumption_calculator.ui.pages.schedule_page import SchedulePage
from fuel_consumption_calculator.ui.pages.settings_page import SettingsPage
from fuel_consumption_calculator.ui.pages.voyage_page import VoyagePage


class MainWindow(QMainWindow):
    PAGE_NAMES = ("Dashboard", "Schedule", "Voyage Planner", "Consumption", "ROB Planner", "Bunker Planner", "Settings")

    def __init__(
        self,
        vessel_service: VesselService,
        schedule_service: ScheduleService,
        scraper_service: ScraperService,
        consumption_service: ConsumptionService,
        rob_service: ROBService,
        bunker_service: BunkerService,
        voyage_service: VoyageService,
    ) -> None:
        super().__init__()
        self.setWindowTitle(f"{APPLICATION_NAME} {APPLICATION_VERSION}")
        self.setMinimumSize(1000, 650)
        self.resize(1180, 760)

        central = QWidget()
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

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
        self.dashboard_page = DashboardPage(vessel_service)
        self.schedule_page = SchedulePage(vessel_service, schedule_service, scraper_service)
        self.voyage_page = VoyagePage(vessel_service, schedule_service, consumption_service, voyage_service)
        self.consumption_page = ConsumptionPage(vessel_service, consumption_service, schedule_service)
        self.rob_page = RobPage(vessel_service, rob_service, schedule_service, consumption_service)
        self.bunker_page = BunkerPage(vessel_service, bunker_service, schedule_service, consumption_service, rob_service)
        self.settings_page = SettingsPage(vessel_service)
        pages = (
            self.dashboard_page,
            self.schedule_page,
            self.voyage_page,
            self.consumption_page,
            self.rob_page,
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
        self.select_page(0)

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
            self.rob_page.refresh()
        elif index == 5:
            self.bunker_page.refresh()
        elif index == 6:
            self.settings_page.refresh()

    def _vessel_configuration_changed(self) -> None:
        self.dashboard_page.refresh()
        self.schedule_page.refresh()
        self.voyage_page.refresh()
        self.consumption_page.refresh()
        self.rob_page.refresh()
        self.bunker_page.refresh()
        self.statusBar().showMessage("Vessel configuration saved", 4000)
