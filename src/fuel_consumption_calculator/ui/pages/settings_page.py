from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from fuel_consumption_calculator.domain.voyage import RouteDefinition
from fuel_consumption_calculator.services.schedule_service import ScheduleService
from fuel_consumption_calculator.services.settings_service import SettingsService
from fuel_consumption_calculator.services.vessel_service import VesselService, VesselValidationError
from fuel_consumption_calculator.services.voyage_service import VoyageService
from fuel_consumption_calculator.ui.widgets.page_header import PageHeader
from fuel_consumption_calculator.ui.widgets.vessel_clock import format_gmt_offset


LOGGER = logging.getLogger(__name__)


class SettingsPage(QWidget):
    vessel_saved = Signal()
    vessel_time_offset_changed = Signal(int)

    def __init__(self, vessel_service: VesselService, schedule_service: ScheduleService, settings_service: SettingsService, voyage_service: VoyageService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vessel_service = vessel_service
        self._schedule_service = schedule_service
        self._settings_service = settings_service
        self._voyage_service = voyage_service

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.content = QWidget()
        self.content.setMinimumWidth(900)
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)
        layout.addWidget(PageHeader("Settings", "Configure the active vessel used by this installation."))

        panel = QFrame()
        panel.setObjectName("card")
        panel.setMinimumHeight(150)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(20, 18, 20, 18)
        panel_layout.setSpacing(12)
        section_title = QLabel("Vessel configuration")
        section_title.setObjectName("cardValue")
        panel_layout.addWidget(section_title)

        form = QFormLayout()
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.vessel_name_input = QLineEdit()
        self.vessel_name_input.setPlaceholderText("e.g. MV Ocean Star")
        self.vessel_name_input.setMinimumHeight(32)
        self.imo_input = QLineEdit()
        self.imo_input.setPlaceholderText("7 digits")
        self.imo_input.setMaxLength(7)
        self.imo_input.setMinimumHeight(32)
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
        timezone_panel.setMinimumHeight(300)
        timezone_layout = QVBoxLayout(timezone_panel)
        timezone_layout.setContentsMargins(20, 18, 20, 18)
        timezone_layout.setSpacing(10)
        timezone_title = QLabel("Port timezones")
        timezone_title.setObjectName("cardValue")
        timezone_layout.addWidget(timezone_title)
        timezone_form = QFormLayout()
        timezone_form.setVerticalSpacing(10)
        timezone_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.port_input = QLineEdit()
        self.port_input.setPlaceholderText("e.g. Santos")
        self.port_input.setMinimumHeight(32)
        self.timezone_input = QLineEdit()
        self.timezone_input.setPlaceholderText("e.g. America/Sao_Paulo")
        self.timezone_input.setMinimumHeight(32)
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
        self.timezone_table.setMinimumHeight(190)
        self.timezone_table.verticalHeader().setDefaultSectionSize(28)
        self.timezone_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.timezone_table.horizontalHeader().setStretchLastSection(True)
        self.timezone_table.cellClicked.connect(self._select_timezone_row)
        timezone_layout.addWidget(self.timezone_table)
        layout.addWidget(timezone_panel)

        scraper_panel = QFrame()
        scraper_panel.setObjectName("card")
        scraper_panel.setMinimumHeight(145)
        scraper_layout = QVBoxLayout(scraper_panel)
        scraper_layout.setContentsMargins(20, 18, 20, 18)
        scraper_layout.setSpacing(10)
        scraper_title = QLabel("Scraper")
        scraper_title.setObjectName("cardValue")
        scraper_layout.addWidget(scraper_title)
        scraper_form = QFormLayout()
        scraper_form.setVerticalSpacing(10)
        self.scraper_mode_input = QComboBox()
        self.scraper_mode_input.setMinimumHeight(32)
        self.scraper_mode_input.addItem("Visible Browser", "visible")
        self.scraper_mode_input.addItem("Background / Headless", "headless")
        scraper_form.addRow(self._field_label("Browser Mode"), self.scraper_mode_input)
        self.ui_scale_input = QComboBox()
        self.ui_scale_input.addItems(["80%", "90%", "100%", "110%", "125%"])
        scraper_form.addRow(self._field_label("UI Scale"), self.ui_scale_input)
        self.vessel_time_offset_input = QDoubleSpinBox()
        self.vessel_time_offset_input.setDecimals(0)
        self.vessel_time_offset_input.setRange(-720, 840)
        self.vessel_time_offset_input.setSingleStep(30)
        self.vessel_time_offset_input.setSuffix(" minutes")
        scraper_form.addRow(self._field_label("Vessel Time GMT Offset"), self.vessel_time_offset_input)
        scraper_layout.addLayout(scraper_form)
        scale_note = QLabel("UI Scale is applied the next time the application starts.")
        scale_note.setObjectName("mutedText")
        scraper_layout.addWidget(scale_note)
        self.vessel_time_note = QLabel("Vessel clock display only. Voyage calculations remain UTC.")
        self.vessel_time_note.setObjectName("mutedText")
        scraper_layout.addWidget(self.vessel_time_note)
        scraper_actions = QHBoxLayout()
        self.save_scraper_button = QPushButton("Save scraper settings")
        self.save_scraper_button.clicked.connect(self._save_scraper_settings)
        scraper_actions.addWidget(self.save_scraper_button)
        self.save_ui_scale_button = QPushButton("Save UI scale")
        self.save_ui_scale_button.clicked.connect(self._save_ui_scale)
        scraper_actions.addWidget(self.save_ui_scale_button)
        self.save_vessel_time_button = QPushButton("Save vessel time offset")
        self.save_vessel_time_button.clicked.connect(self._save_vessel_time_offset)
        scraper_actions.addWidget(self.save_vessel_time_button)
        scraper_actions.addStretch()
        scraper_layout.addLayout(scraper_actions)
        layout.addWidget(scraper_panel)
        layout.addStretch()
        self.scroll.setWidget(self.content)
        self.tabs.addTab(self.scroll, "Vessel & System")
        self.routes_tab = self._build_routes_tab()
        self.tabs.addTab(self.routes_tab, "Routes & Distances")
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
        scale = self._settings_service.load().get("ui_scale_percent", 100)
        self.ui_scale_input.setCurrentText(f"{scale}%" if str(scale) in {"80", "90", "100", "110", "125"} else "100%")
        offset = self._settings_service.vessel_time_offset_minutes()
        self.vessel_time_offset_input.setValue(offset)
        self.vessel_time_note.setText(f"Vessel clock display only. {format_gmt_offset(offset)}; voyage calculations remain UTC.")
        self._refresh_timezones()
        self._refresh_routes()

    def _build_routes_tab(self) -> QWidget:
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)

        library_panel = QFrame()
        library_panel.setObjectName("card")
        library_layout = QVBoxLayout(library_panel)
        library_layout.setContentsMargins(20, 18, 20, 18)
        library_layout.setSpacing(10)
        library_layout.addWidget(PageHeader("Routes & Distances", "Manage route-library distances used by voyage calculations."))
        note = QLabel("Rows marked MISSING have no sea distance; downstream speed, consumption, and ROB may be unavailable.")
        note.setObjectName("mutedText")
        note.setWordWrap(True)
        library_layout.addWidget(note)
        self.routes_table = QTableWidget(0, 7)
        self.routes_table.setHorizontalHeaderLabels((
            "Origin",
            "Destination",
            "Departure Pilot Distance NM",
            "Departure Pilot Duration",
            "Sea Distance NM",
            "Arrival Pilot Distance NM",
            "Arrival Pilot Duration",
        ))
        self.routes_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.routes_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.routes_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.routes_table.verticalHeader().setDefaultSectionSize(30)
        self.routes_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.routes_table.horizontalHeader().setStretchLastSection(True)
        self.routes_table.cellClicked.connect(self._select_route_row)
        library_layout.addWidget(self.routes_table, 1)
        layout.addWidget(library_panel, 3)

        editor_panel = QFrame()
        editor_panel.setObjectName("card")
        editor_panel.setMaximumWidth(360)
        editor_layout = QVBoxLayout(editor_panel)
        editor_layout.setContentsMargins(20, 18, 20, 18)
        editor_layout.setSpacing(12)
        title = QLabel("Route editor")
        title.setObjectName("cardValue")
        editor_layout.addWidget(title)
        editor_layout.addWidget(QLabel("Select a route to edit it, or enter a new port pair."))
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.route_origin_input = QLineEdit()
        self.route_destination_input = QLineEdit()
        self.route_inputs = {
            "departure_pilot_distance_nm": _route_spinbox(" NM"),
            "departure_pilotage_hours": _route_spinbox(" h"),
            "sea_distance_nm": _route_spinbox(" NM"),
            "arrival_pilot_distance_nm": _route_spinbox(" NM"),
            "arrival_pilotage_hours": _route_spinbox(" h"),
        }
        form.addRow(self._field_label("Origin"), self.route_origin_input)
        form.addRow(self._field_label("Destination"), self.route_destination_input)
        form.addRow(self._field_label("Departure Pilot Distance"), self.route_inputs["departure_pilot_distance_nm"])
        form.addRow(self._field_label("Departure Pilot Duration"), self.route_inputs["departure_pilotage_hours"])
        form.addRow(self._field_label("Sea Distance"), self.route_inputs["sea_distance_nm"])
        form.addRow(self._field_label("Arrival Pilot Distance"), self.route_inputs["arrival_pilot_distance_nm"])
        form.addRow(self._field_label("Arrival Pilot Duration"), self.route_inputs["arrival_pilotage_hours"])
        editor_layout.addLayout(form)
        self.route_status_label = QLabel("Enter or select a route.")
        self.route_status_label.setObjectName("mutedText")
        self.route_status_label.setWordWrap(True)
        editor_layout.addWidget(self.route_status_label)
        actions = QHBoxLayout()
        clear_button = QPushButton("New Route")
        clear_button.clicked.connect(self._clear_route_editor)
        self.save_route_button = QPushButton("Save Route")
        self.save_route_button.setObjectName("primaryButton")
        self.save_route_button.clicked.connect(self._save_route)
        actions.addWidget(clear_button)
        actions.addWidget(self.save_route_button)
        editor_layout.addLayout(actions)
        editor_layout.addStretch()
        layout.addWidget(editor_panel, 1)
        return tab

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

    def _save_ui_scale(self) -> None:
        settings = self._settings_service.load()
        settings["ui_scale_percent"] = int(self.ui_scale_input.currentText().rstrip("%"))
        self._settings_service.save(settings)
        QMessageBox.information(self, "UI scale saved", "UI Scale will be applied when the application is restarted.")

    def _save_vessel_time_offset(self) -> None:
        offset = int(self.vessel_time_offset_input.value())
        self._settings_service.save_vessel_time_offset_minutes(offset)
        self.vessel_time_note.setText(f"Vessel clock display only. {format_gmt_offset(offset)}; voyage calculations remain UTC.")
        self.vessel_time_offset_changed.emit(offset)

    def _refresh_routes(self) -> None:
        rows = self._voyage_service.list_routes()
        self._route_rows = rows
        self.routes_table.setRowCount(len(rows))
        for row_index, route in enumerate(rows):
            values = (
                route.origin_port,
                route.destination_port,
                _format_route_value(route.departure_pilot_distance_nm),
                _format_route_value(route.departure_pilotage_hours),
                "MISSING" if route.sea_distance_nm <= 0 else _format_route_value(route.sea_distance_nm),
                _format_route_value(route.arrival_pilot_distance_nm),
                _format_route_value(route.arrival_pilotage_hours),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if route.sea_distance_nm <= 0:
                    item.setBackground(QColor("#5a3b20"))
                    item.setForeground(QColor("#f1c778"))
                self.routes_table.setItem(row_index, column, item)

    def _select_route_row(self, row: int, _column: int) -> None:
        if not 0 <= row < len(self._route_rows):
            return
        route = self._route_rows[row]
        self.route_origin_input.setText(route.origin_port)
        self.route_destination_input.setText(route.destination_port)
        for key, input_widget in self.route_inputs.items():
            input_widget.setValue(getattr(route, key))
        self.route_status_label.setText("Sea distance is missing." if route.sea_distance_nm <= 0 else "Route loaded.")

    def _clear_route_editor(self) -> None:
        self.route_origin_input.clear()
        self.route_destination_input.clear()
        for input_widget in self.route_inputs.values():
            input_widget.setValue(0.0)
        self.route_status_label.setText("Enter a new route.")

    def _save_route(self) -> None:
        route = RouteDefinition(
            origin_port=self.route_origin_input.text().strip(),
            destination_port=self.route_destination_input.text().strip(),
            **{key: input_widget.value() for key, input_widget in self.route_inputs.items()},
        )
        try:
            saved = self._voyage_service.save_route(route)
        except Exception as exc:
            QMessageBox.warning(self, "Route not saved", str(exc))
            return
        self._refresh_routes()
        self.route_origin_input.setText(saved.origin_port)
        self.route_destination_input.setText(saved.destination_port)
        self.route_status_label.setText("Route saved." if saved.sea_distance_nm > 0 else "Route saved — sea distance remains MISSING.")


def _route_spinbox(suffix: str) -> QDoubleSpinBox:
    input_widget = QDoubleSpinBox()
    input_widget.setDecimals(2)
    input_widget.setRange(0.0, 999999.99)
    input_widget.setSingleStep(1.0)
    input_widget.setSuffix(suffix)
    return input_widget


def _format_route_value(value: float) -> str:
    return f"{value:.2f}"
