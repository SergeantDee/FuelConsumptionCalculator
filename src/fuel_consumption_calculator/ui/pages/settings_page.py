from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from fuel_consumption_calculator.services.schedule_service import ScheduleService
from fuel_consumption_calculator.services.settings_service import SettingsService
from fuel_consumption_calculator.services.vessel_service import VesselService, VesselValidationError
from fuel_consumption_calculator.ui.widgets.page_header import PageHeader


LOGGER = logging.getLogger(__name__)


class SettingsPage(QWidget):
    vessel_saved = Signal()

    def __init__(self, vessel_service: VesselService, schedule_service: ScheduleService, settings_service: SettingsService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vessel_service = vessel_service
        self._schedule_service = schedule_service
        self._settings_service = settings_service

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)
        layout.addWidget(PageHeader("Settings", "Configure the active vessel used by this installation."))

        panel = QFrame()
        panel.setObjectName("card")
        panel.setMaximumWidth(650)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(22, 20, 22, 20)
        panel_layout.setSpacing(16)
        section_title = QLabel("Vessel configuration")
        section_title.setObjectName("cardValue")
        panel_layout.addWidget(section_title)

        form = QFormLayout()
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(14)
        self.vessel_name_input = QLineEdit()
        self.vessel_name_input.setPlaceholderText("e.g. MV Ocean Star")
        self.imo_input = QLineEdit()
        self.imo_input.setPlaceholderText("7 digits")
        self.imo_input.setMaxLength(7)
        form.addRow(self._field_label("Vessel name"), self.vessel_name_input)
        form.addRow(self._field_label("IMO number"), self.imo_input)
        panel_layout.addLayout(form)

        actions = QHBoxLayout()
        actions.addStretch()
        self.save_button = QPushButton("Save vessel")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save_vessel)
        actions.addWidget(self.save_button)
        panel_layout.addLayout(actions)
        layout.addWidget(panel)

        timezone_panel = QFrame()
        timezone_panel.setObjectName("card")
        timezone_layout = QVBoxLayout(timezone_panel)
        timezone_layout.setContentsMargins(22, 20, 22, 20)
        timezone_layout.setSpacing(12)
        timezone_title = QLabel("Port timezones")
        timezone_title.setObjectName("cardValue")
        timezone_layout.addWidget(timezone_title)
        timezone_form = QFormLayout()
        self.port_input = QLineEdit()
        self.port_input.setPlaceholderText("e.g. Santos")
        self.timezone_input = QLineEdit()
        self.timezone_input.setPlaceholderText("e.g. America/Sao_Paulo")
        timezone_form.addRow(self._field_label("Port"), self.port_input)
        timezone_form.addRow(self._field_label("Timezone ID"), self.timezone_input)
        timezone_layout.addLayout(timezone_form)
        tz_actions = QHBoxLayout()
        self.save_timezone_button = QPushButton("Save timezone")
        self.save_timezone_button.clicked.connect(self._save_timezone)
        tz_actions.addWidget(self.save_timezone_button)
        tz_actions.addStretch()
        timezone_layout.addLayout(tz_actions)
        self.timezone_table = QTableWidget(0, 2)
        self.timezone_table.setHorizontalHeaderLabels(["Port", "Timezone ID"])
        self.timezone_table.horizontalHeader().setStretchLastSection(True)
        self.timezone_table.cellClicked.connect(self._select_timezone_row)
        timezone_layout.addWidget(self.timezone_table)
        layout.addWidget(timezone_panel)

        scraper_panel = QFrame()
        scraper_panel.setObjectName("card")
        scraper_layout = QVBoxLayout(scraper_panel)
        scraper_layout.setContentsMargins(22, 20, 22, 20)
        scraper_title = QLabel("Scraper")
        scraper_title.setObjectName("cardValue")
        scraper_layout.addWidget(scraper_title)
        scraper_form = QFormLayout()
        self.scraper_mode_input = QComboBox()
        self.scraper_mode_input.addItem("Visible Browser", "visible")
        self.scraper_mode_input.addItem("Background / Headless", "headless")
        scraper_form.addRow(self._field_label("Browser Mode"), self.scraper_mode_input)
        scraper_layout.addLayout(scraper_form)
        scraper_actions = QHBoxLayout()
        self.save_scraper_button = QPushButton("Save scraper settings")
        self.save_scraper_button.clicked.connect(self._save_scraper_settings)
        scraper_actions.addWidget(self.save_scraper_button)
        scraper_actions.addStretch()
        scraper_layout.addLayout(scraper_actions)
        layout.addWidget(scraper_panel)
        layout.addStretch()
        self.refresh()

    @staticmethod
    def _field_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def refresh(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        self.vessel_name_input.setText(vessel.name if vessel else "")
        self.imo_input.setText(vessel.imo if vessel else "")
        mode = self._settings_service.scraper_browser_mode()
        self.scraper_mode_input.setCurrentIndex(1 if mode == "headless" else 0)
        self._refresh_timezones()

    def _save_vessel(self) -> None:
        try:
            self._vessel_service.configure_active_vessel(
                self.vessel_name_input.text(),
                self.imo_input.text(),
            )
        except VesselValidationError as exc:
            QMessageBox.warning(self, "Check vessel details", str(exc))
            return
        except Exception:
            LOGGER.exception("Unexpected error while saving vessel configuration")
            QMessageBox.critical(self, "Vessel not saved", "The vessel configuration could not be saved. Check the application log for details.")
            return
        self.vessel_saved.emit()
        QMessageBox.information(self, "Vessel saved", "The active vessel configuration has been saved.")

    def _refresh_timezones(self) -> None:
        rows = self._schedule_service.list_port_timezones()
        self.timezone_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            self.timezone_table.setItem(row_index, 0, QTableWidgetItem(row.port))
            self.timezone_table.setItem(row_index, 1, QTableWidgetItem(row.timezone_id))

    def _select_timezone_row(self, row: int, column: int) -> None:
        port_item = self.timezone_table.item(row, 0)
        timezone_item = self.timezone_table.item(row, 1)
        if port_item and timezone_item:
            self.port_input.setText(port_item.text())
            self.timezone_input.setText(timezone_item.text())

    def _save_timezone(self) -> None:
        try:
            self._schedule_service.save_port_timezone(self.port_input.text(), self.timezone_input.text())
        except Exception as exc:
            QMessageBox.warning(self, "Timezone not saved", str(exc))
            return
        self._refresh_timezones()
        QMessageBox.information(self, "Timezone saved", "Port timezone mapping saved. Matching schedule events were re-resolved.")

    def _save_scraper_settings(self) -> None:
        self._settings_service.save_scraper_browser_mode(self.scraper_mode_input.currentData())
        QMessageBox.information(self, "Scraper settings saved", "Scraper browser mode has been saved.")
