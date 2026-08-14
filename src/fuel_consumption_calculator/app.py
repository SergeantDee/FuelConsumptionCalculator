from __future__ import annotations

import logging
import sys
from types import TracebackType

from PySide6.QtWidgets import QApplication, QMessageBox

from fuel_consumption_calculator.config import APPLICATION_NAME, APPLICATION_VERSION
from fuel_consumption_calculator.infrastructure.logging_config import configure_logging
from fuel_consumption_calculator.paths import AppPaths
from fuel_consumption_calculator.repositories.consumption_repository import ConsumptionRepository
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.schedule_repository import ScheduleRepository
from fuel_consumption_calculator.repositories.vessel_repository import VesselRepository
from fuel_consumption_calculator.services.consumption_service import ConsumptionService
from fuel_consumption_calculator.services.schedule_service import ScheduleService
from fuel_consumption_calculator.services.scraper_service import ScraperService
from fuel_consumption_calculator.services.vessel_service import VesselService
from fuel_consumption_calculator.ui.main_window import MainWindow
from fuel_consumption_calculator.ui.theme import DARK_MARINE_STYLESHEET


LOGGER = logging.getLogger(__name__)


def build_main_window(paths: AppPaths) -> MainWindow:
    database = Database(paths.database_file)
    database.initialize()
    vessel_service = VesselService(VesselRepository(database))
    schedule_service = ScheduleService(ScheduleRepository(database))
    consumption_service = ConsumptionService(ConsumptionRepository(database))
    scraper_service = ScraperService()
    return MainWindow(vessel_service, schedule_service, scraper_service, consumption_service)


def install_global_exception_handler() -> None:
    def handle_exception(
        exception_type: type[BaseException],
        exception_value: BaseException,
        traceback: TracebackType | None,
    ) -> None:
        if issubclass(exception_type, KeyboardInterrupt):
            sys.__excepthook__(exception_type, exception_value, traceback)
            return
        LOGGER.critical(
            "Unhandled application error",
            exc_info=(exception_type, exception_value, traceback),
        )
        QMessageBox.critical(
            None,
            "Unexpected error",
            "An unexpected error occurred. Details were written to the application log.",
        )

    sys.excepthook = handle_exception


def run(paths: AppPaths | None = None) -> int:
    resolved_paths = paths or AppPaths.default()
    resolved_paths.ensure_runtime_directories()
    logger = configure_logging(resolved_paths.log_file)
    logger.info("Application startup: %s %s", APPLICATION_NAME, APPLICATION_VERSION)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APPLICATION_NAME)
    app.setApplicationVersion(APPLICATION_VERSION)
    app.setStyleSheet(DARK_MARINE_STYLESHEET)
    install_global_exception_handler()

    try:
        window = build_main_window(resolved_paths)
    except Exception:
        logger.exception("Critical startup failure")
        QMessageBox.critical(
            None,
            "Application could not start",
            "The application could not initialize. Check the application log for details.",
        )
        return 1

    app.aboutToQuit.connect(lambda: logger.info("Application shutdown"))
    window.show()
    return app.exec()
