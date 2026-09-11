from __future__ import annotations

import logging
from datetime import datetime, timezone

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from fuel_consumption_calculator.calculations.performance_engine import DEFAULT_ME_SFOC_POINTS
from fuel_consumption_calculator.domain.consumption import FUEL_TYPES
from fuel_consumption_calculator.domain.voyage import GeneratorSfocPoint, MainEngineSfocPoint, MachineryFuelState, VesselEnergyConfig
from fuel_consumption_calculator.services.planning_readiness_service import (
    AGGREGATE_ROB_AVAILABLE,
    INITIAL_FUEL_STATE_CONFIGURED,
    PERFORMANCE_CONFIGURED,
    SCHEDULE_AVAILABLE,
    TANK_CONFIGURATION_AVAILABLE,
    TANK_PHYSICAL_ROB_AVAILABLE,
    VESSEL_CONFIGURED,
    VOYAGE_PROJECTION_AVAILABLE,
)
from fuel_consumption_calculator.ui.pages.fuel_tanks_page import VesselTankSetDialog
from fuel_consumption_calculator.ui.widgets.vessel_clock import VESSEL_GMT_OFFSETS_MINUTES, format_gmt_offset, vessel_local_time


LOGGER = logging.getLogger(__name__)


# Zero-valued fields omitted here are storage/engine fallbacks rather than
# vessel defaults. Use Defaults must not overwrite operator values with them.
KNOWN_PERFORMANCE_DEFAULT_FIELDS = (
    "main_engine_slip_percent",
    "speed_rpm_factor",
    "power_coefficient",
    "mcr_power_kw",
    "main_engine_loss_allowance_mt_per_day",
    "auxiliary_engine_loss_allowance_mt_per_day",
)
NO_DEFAULT_PERFORMANCE_FIELDS = (
    "generator_rated_kw",
    "port_running_generators",
    "sea_running_generators",
    "port_base_load_kw",
    "sea_base_load_kw",
    "reefer_kw_per_unit",
    "aux_boiler_mt_per_hour",
)

UNAVAILABLE_READINESS_LABELS = {
    VESSEL_CONFIGURED: "Vessel not configured",
    PERFORMANCE_CONFIGURED: "Performance model not configured",
    INITIAL_FUEL_STATE_CONFIGURED: "Initial machinery fuel state not configured",
    AGGREGATE_ROB_AVAILABLE: "Aggregate ROB anchor unavailable",
    TANK_CONFIGURATION_AVAILABLE: "Tank set not configured",
    SCHEDULE_AVAILABLE: "Schedule unavailable",
    VOYAGE_PROJECTION_AVAILABLE: "Voyage projection unavailable",
}


class SetupWizard(QDialog):
    """Nine-step, resumable setup orchestrator backed by existing services."""

    completed = Signal()
    page_requested = Signal(int)

    STEP_TITLES = (
        "Vessel Details",
        "Performance / Vessel Profile",
        "Initial Machinery Fuel State",
        "ROB Anchor",
        "Fuel Tank Configuration",
        "Initial Tank ROB — Manual MT",
        "Schedule",
        "Voyage Operational Readiness",
        "System Readiness",
    )

    def __init__(
        self,
        vessel_service,
        schedule_service,
        consumption_service,
        voyage_service,
        rob_service,
        fuel_tank_service,
        settings_service,
        readiness_service,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._vessel_service = vessel_service
        self._schedule_service = schedule_service
        self._consumption_service = consumption_service
        self._voyage_service = voyage_service
        self._rob_service = rob_service
        self._fuel_tank_service = fuel_tank_service
        self._settings_service = settings_service
        self._readiness_service = readiness_service
        self._landing_page: int | None = None
        self._energy_inputs: dict[str, QDoubleSpinBox] = {}
        self._maneuvering_inputs: dict[str, QLineEdit] = {}
        self._fuel_inputs: dict[str, QComboBox] = {}
        self._rob_inputs: dict[str, QDoubleSpinBox] = {}
        self._tank_rob_rows: dict[int, tuple[QComboBox, QLineEdit]] = {}
        self._tank_rob_original: dict[int, tuple[str, float] | None] = {}

        self.setWindowTitle("Initialization / Setup Wizard")
        self.setModal(True)
        self.setMinimumSize(780, 610)
        self.resize(860, 680)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(12)
        self.progress_label = QLabel()
        self.progress_label.setObjectName("pageEyebrow")
        self.title_label = QLabel()
        self.title_label.setObjectName("pageTitle")
        root.addWidget(self.progress_label)
        root.addWidget(self.title_label)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.stack.addWidget(self._build_vessel_page())
        self.stack.addWidget(self._build_performance_page())
        self.stack.addWidget(self._build_fuel_page())
        self.stack.addWidget(self._build_rob_page())
        self.stack.addWidget(self._build_tanks_page())
        self.stack.addWidget(self._build_tank_rob_page())
        self.stack.addWidget(self._build_schedule_page())
        self.stack.addWidget(self._build_operational_page())
        self.stack.addWidget(self._build_readiness_page())

        actions = QHBoxLayout()
        self.finish_later_button = QPushButton("Finish Later")
        self.finish_later_button.clicked.connect(self._finish_later)
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self._back)
        self.next_button = QPushButton("Next")
        self.next_button.setObjectName("primaryButton")
        self.next_button.clicked.connect(self._next)
        actions.addWidget(self.finish_later_button)
        actions.addStretch()
        actions.addWidget(self.back_button)
        actions.addWidget(self.next_button)
        root.addLayout(actions)

        self._settings_service.save_initialization_wizard_state(seen=True)
        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self._refresh_time_preview)
        self._preview_timer.start(1000)
        self.preload()
        self._show_step(0)

    def preload(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        self.vessel_name_input.setText(vessel.name if vessel else "")
        self.imo_input.setText(vessel.imo if vessel else "")
        offset = self._settings_service.vessel_time_offset_minutes()
        offset_index = self.timezone_input.findData(offset)
        if offset_index < 0:
            self.timezone_input.addItem(format_gmt_offset(offset), offset)
            offset_index = self.timezone_input.count() - 1
        self.timezone_input.setCurrentIndex(offset_index)
        self._refresh_time_preview()
        if vessel is None:
            self._clear_vessel_dependent_inputs()
            return
        self._load_performance(vessel.id)
        state = self._voyage_service.load_initial_fuel_state(vessel.id)
        for machinery, combo in self._fuel_inputs.items():
            combo.setCurrentText(state.fuel_for(machinery)) if state else combo.setCurrentIndex(-1)
        has_anchor = self._rob_service.has_starting_rob(vessel.id)
        self.use_starting_rob.setChecked(has_anchor)
        if has_anchor:
            anchor = self._rob_service.load_starting_rob(vessel.id)
            for fuel, widget in self._rob_inputs.items():
                widget.setValue(anchor.quantity_for(fuel))
        self._populate_tank_rob_rows()
        self._refresh_inline_statuses()

    def _build_vessel_page(self) -> QWidget:
        page, layout = _page("Configure the vessel identity and primary vessel-clock offset. Existing values are preserved and prefilled.")
        form = QFormLayout()
        self.vessel_name_input = QLineEdit()
        self.vessel_name_input.setPlaceholderText("Vessel name")
        self.imo_input = QLineEdit()
        self.imo_input.setMaxLength(7)
        self.imo_input.setPlaceholderText("7 digit IMO")
        self.timezone_input = QComboBox()
        for offset in VESSEL_GMT_OFFSETS_MINUTES:
            self.timezone_input.addItem(format_gmt_offset(offset), offset)
        self.timezone_input.currentIndexChanged.connect(self._refresh_time_preview)
        form.addRow("Vessel name", self.vessel_name_input)
        form.addRow("IMO", self.imo_input)
        form.addRow("Vessel GMT offset", self.timezone_input)
        layout.addLayout(form)
        self.time_preview = QLabel()
        self.time_preview.setObjectName("cardValue")
        layout.addWidget(self.time_preview)
        layout.addWidget(_muted("Manually selected vessel local clock. Voyage calculations and persisted operational timestamps remain UTC."))
        self.vessel_validation = _warning("")
        self.vessel_validation.hide()
        layout.addWidget(self.vessel_validation)
        layout.addStretch()
        return page

    def _build_performance_page(self) -> QWidget:
        page, layout = _scroll_page(
            "Review the current technical profile. The engine remains authoritative; no voyage calculations are implemented here."
        )
        top = QHBoxLayout()
        self.profile_type_label = QLabel("DEFAULT PROFILE")
        self.profile_type_label.setObjectName("sectionCardTitle")
        defaults = QPushButton("Use Defaults")
        defaults.clicked.connect(self._use_performance_defaults)
        top.addWidget(self.profile_type_label)
        top.addStretch()
        top.addWidget(defaults)
        layout.addLayout(top)
        note = _muted(
            "Defaults are only values already defined by the application. Missing DG and maneuvering data remain missing; no unexplained technical values are invented."
        )
        layout.addWidget(note)
        grid = QGridLayout()
        specifications = (
            ("MCR kW", "mcr_power_kw"),
            ("ME slip %", "main_engine_slip_percent"),
            ("Speed/RPM factor", "speed_rpm_factor"),
            ("Power coefficient", "power_coefficient"),
            ("DG rated kW", "generator_rated_kw"),
            ("Port DG count", "port_running_generators"),
            ("Sea DG count", "sea_running_generators"),
            ("Port base load kW", "port_base_load_kw"),
            ("Sea base load kW", "sea_base_load_kw"),
            ("Reefer kW/unit", "reefer_kw_per_unit"),
            ("Aux boiler MT/h", "aux_boiler_mt_per_hour"),
            ("ME loss MT/day", "main_engine_loss_allowance_mt_per_day"),
            ("AE loss MT/day", "auxiliary_engine_loss_allowance_mt_per_day"),
        )
        for index, (label, key) in enumerate(specifications):
            row, column = divmod(index, 2)
            wrapper = QWidget()
            form = QFormLayout(wrapper)
            form.setContentsMargins(0, 0, 8, 4)
            spin = QDoubleSpinBox()
            spin.setRange(0, 999999)
            spin.setDecimals(7 if key in ("speed_rpm_factor", "power_coefficient") else 3)
            if key in NO_DEFAULT_PERFORMANCE_FIELDS:
                spin.setSpecialValueText("Unconfigured")
            form.addRow(label, spin)
            grid.addWidget(wrapper, row, column)
            self._energy_inputs[key] = spin
        layout.addLayout(grid)
        maneuver = QFormLayout()
        for label, key in (
            ("ME maneuvering MT/h", "maneuvering_main_engine_mt_per_hour"),
            ("DG maneuvering MT/h", "maneuvering_generators_mt_per_hour"),
            ("Aux Boiler maneuvering MT/h", "maneuvering_aux_boiler_mt_per_hour"),
        ):
            value = QLineEdit()
            value.setPlaceholderText("Not configured")
            maneuver.addRow(label, value)
            self._maneuvering_inputs[key] = value
        layout.addLayout(maneuver)
        curves = QFormLayout()
        self.me_curve_input = QLineEdit()
        self.me_curve_input.setPlaceholderText("load:sfoc, load:sfoc")
        self.dg_curve_input = QLineEdit()
        self.dg_curve_input.setPlaceholderText("load:sfoc, load:sfoc")
        curves.addRow("ME load / SFOC curve", self.me_curve_input)
        curves.addRow("DG load / SFOC curve", self.dg_curve_input)
        layout.addLayout(curves)
        layout.addWidget(_muted("Curve format example: 25:205, 50:195, 75:190. Existing points are prefilled."))
        self.performance_status = _warning("")
        layout.addWidget(self.performance_status)
        layout.addStretch()
        return page

    def _build_fuel_page(self) -> QWidget:
        page, layout = _page(
            "Select the fuel physically in use by each machinery group at the start of the planning timeline. No fuel is assumed."
        )
        form = QFormLayout()
        for machinery, label in (
            ("MAIN_ENGINE", "Main Engine"),
            ("GENERATORS", "Generators"),
            ("AUX_BOILER", "Auxiliary Boiler"),
        ):
            combo = QComboBox()
            combo.addItems(FUEL_TYPES)
            combo.setCurrentIndex(-1)
            combo.setPlaceholderText("Select fuel")
            self._fuel_inputs[machinery] = combo
            form.addRow(label, combo)
        layout.addLayout(form)
        layout.addWidget(_warning("Required for complete consumption attribution. Choose Finish Later if the current fuels are not known."))
        layout.addStretch()
        return page

    def _build_rob_page(self) -> QWidget:
        page, layout = _page(
            "Enter an aggregate Projection Starting ROB only when known. Existing Actual ROB observations also provide an anchor."
        )
        self.use_starting_rob = QCheckBox("Enter / update Projection Starting ROB")
        self.use_starting_rob.toggled.connect(self._set_rob_inputs_enabled)
        layout.addWidget(self.use_starting_rob)
        row = QHBoxLayout()
        for fuel in FUEL_TYPES:
            box = QDoubleSpinBox()
            box.setRange(0, 999999.99)
            box.setDecimals(2)
            box.setSuffix(" MT")
            box.setSpecialValueText("Unknown")
            wrapper = QFrame()
            inner = QVBoxLayout(wrapper)
            inner.addWidget(QLabel(fuel))
            inner.addWidget(box)
            row.addWidget(wrapper)
            self._rob_inputs[fuel] = box
        layout.addLayout(row)
        self._set_rob_inputs_enabled(False)
        layout.addWidget(_warning("Skip for now keeps aggregate ROB unknown. Zeroes are saved only when you explicitly select this option and confirm them."))
        layout.addStretch()
        return page

    def _build_tanks_page(self) -> QWidget:
        page, layout = _page(
            "Load the application's verified vessel tank definitions, or configure physical tanks later. Existing tanks are detected and preserved."
        )
        load_button = QPushButton("Use Standard Vessel Tank Set")
        load_button.setObjectName("primaryButton")
        load_button.clicked.connect(self._load_standard_tanks)
        layout.addWidget(load_button)
        self.tank_status = QLabel()
        layout.addWidget(self.tank_status)
        layout.addStretch()
        return page

    def _build_tank_rob_page(self) -> QWidget:
        page, layout = _page(
            "Enter current physical tank quantities in MT. Calibration and sounding data can be configured later."
        )
        self.tank_rob_table = QTableWidget(0, 3)
        self.tank_rob_table.setHorizontalHeaderLabels(("Tank", "Fuel", "Initial ROB (MT)"))
        self.tank_rob_table.verticalHeader().hide()
        self.tank_rob_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tank_rob_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tank_rob_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.tank_rob_table, 1)
        self.tank_rob_summary = QLabel()
        self.tank_rob_summary.setWordWrap(True)
        layout.addWidget(self.tank_rob_summary)
        self.tank_rob_status = QLabel()
        self.tank_rob_status.setWordWrap(True)
        layout.addWidget(self.tank_rob_status)
        layout.addWidget(_warning("Blank means unknown. Enter 0 only when the tank is confirmed empty."))
        layout.addWidget(_muted("Physical tank ROB is optional for setup and never changes aggregate vessel ROB."))
        return page

    def _build_schedule_page(self) -> QWidget:
        page, layout = _page(
            "Use the existing Schedule screen for provider refresh or manual entry. Scraper success is never required to finish setup."
        )
        fetch = QPushButton("Update / Fetch Schedule")
        manual = QPushButton("Manual Schedule")
        fetch.clicked.connect(lambda: self._request_page(1))
        manual.clicked.connect(lambda: self._request_page(1))
        layout.addWidget(fetch)
        layout.addWidget(manual)
        self.schedule_status = QLabel()
        layout.addWidget(self.schedule_status)
        layout.addStretch()
        return page

    def _build_operational_page(self) -> QWidget:
        page, layout = _page(
            "The application evaluates the existing voyage stages in chronological order using the current calculation engines."
        )
        self.operational_status = QLabel()
        self.operational_status.setWordWrap(True)
        layout.addWidget(self.operational_status)
        layout.addStretch()
        return page

    def _build_readiness_page(self) -> QWidget:
        page, layout = _scroll_page(
            "Required and optional capabilities are calculated dynamically. Completing the wizard never overrides actual readiness."
        )
        self.readiness_labels: dict[str, QLabel] = {}
        for key in (
            VESSEL_CONFIGURED,
            PERFORMANCE_CONFIGURED,
            INITIAL_FUEL_STATE_CONFIGURED,
            AGGREGATE_ROB_AVAILABLE,
            TANK_CONFIGURATION_AVAILABLE,
            TANK_PHYSICAL_ROB_AVAILABLE,
            SCHEDULE_AVAILABLE,
            VOYAGE_PROJECTION_AVAILABLE,
        ):
            label = QLabel()
            label.setWordWrap(True)
            layout.addWidget(label)
            self.readiness_labels[key] = label
        self.blocker_label = QLabel()
        self.blocker_label.setWordWrap(True)
        layout.addWidget(self.blocker_label)
        layout.addStretch()
        return page

    def _show_step(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.progress_label.setText(f"Step {index + 1} of {self.stack.count()}")
        self.title_label.setText(self.STEP_TITLES[index])
        self.back_button.setEnabled(index > 0)
        self.next_button.setText("Finish Setup" if index == self.stack.count() - 1 else "Next")
        if index >= 4:
            self._refresh_inline_statuses()
        if index >= 7:
            self._refresh_readiness()

    def _next(self) -> None:
        index = self.stack.currentIndex()
        if not self._save_step(index):
            return
        if index == self.stack.count() - 1:
            self._settings_service.save_initialization_wizard_state(seen=True, completed=True)
            self.completed.emit()
            self.accept()
            if self._landing_page is not None:
                self.page_requested.emit(self._landing_page)
            return
        self._show_step(index + 1)

    def _back(self) -> None:
        self._show_step(max(0, self.stack.currentIndex() - 1))

    def _save_step(self, index: int) -> bool:
        try:
            if index == 0:
                vessel = self._vessel_service.configure_active_vessel(
                    self.vessel_name_input.text(), self.imo_input.text(),
                )
                self._settings_service.save_vessel_time_offset_minutes(int(self.timezone_input.currentData()))
                self._load_performance(vessel.id)
                self.vessel_validation.clear()
                self.vessel_validation.hide()
            elif index == 1:
                self._save_performance()
            elif index == 2:
                selections = {key: combo.currentText() for key, combo in self._fuel_inputs.items()}
                if all(selections.values()):
                    vessel_id = self._required_vessel_id()
                    self._voyage_service.save_initial_fuel_state(MachineryFuelState(
                        vessel_id,
                        selections["MAIN_ENGINE"],
                        selections["GENERATORS"],
                        selections["AUX_BOILER"],
                    ))
            elif index == 3 and self.use_starting_rob.isChecked():
                vessel_id = self._required_vessel_id()
                if all(widget.value() == 0 for widget in self._rob_inputs.values()):
                    answer = QMessageBox.question(
                        self,
                        "Confirm zero ROB",
                        "All aggregate ROB values are zero. Save this explicit zero snapshot?",
                    )
                    if answer != QMessageBox.StandardButton.Yes:
                        return False
                anchor = self._rob_service.build_starting_rob(
                    vessel_id, {fuel: widget.value() for fuel, widget in self._rob_inputs.items()},
                )
                self._rob_service.save_starting_rob(anchor)
            elif index == 5:
                self._save_manual_tank_rob()
            return True
        except ValueError as exc:
            if index == 0:
                self.vessel_validation.setText(str(exc))
                self.vessel_validation.show()
            else:
                QMessageBox.warning(self, "Setup step not saved", str(exc))
            return False
        except Exception:
            LOGGER.exception("Setup wizard step %s could not be saved", index + 1)
            QMessageBox.critical(self, "Setup step not saved", "The step could not be saved. Technical details were written to the application log.")
            return False

    def _save_performance(self) -> None:
        vessel_id = self._required_vessel_id()
        existing = self._voyage_service.load_energy_config(vessel_id)
        values = {key: widget.value() for key, widget in self._energy_inputs.items()}
        optionals = {key: _optional_number(widget.text()) for key, widget in self._maneuvering_inputs.items()}
        self._voyage_service.save_energy_config(VesselEnergyConfig(
            vessel_id=vessel_id,
            generator_fuel_type=existing.generator_fuel_type,
            boiler_fuel_type=existing.boiler_fuel_type,
            port_ambient_c=existing.port_ambient_c,
            sea_ambient_c=existing.sea_ambient_c,
            **values,
            **optionals,
        ))
        me_points = _parse_curve(self.me_curve_input.text(), "Main Engine")
        dg_points = _parse_curve(self.dg_curve_input.text(), "Generator")
        self._voyage_service.save_main_engine_sfoc_points(
            vessel_id,
            [MainEngineSfocPoint(vessel_id, load, sfoc) for load, sfoc in me_points],
        )
        self._voyage_service.save_generator_sfoc_points(
            vessel_id,
            [GeneratorSfocPoint(vessel_id, load, sfoc) for load, sfoc in dg_points],
        )

    def _load_performance(self, vessel_id: int) -> None:
        config = self._voyage_service.load_energy_config(vessel_id)
        has_user_config = self._voyage_service.has_energy_config(vessel_id)
        for key, widget in self._energy_inputs.items():
            if key in NO_DEFAULT_PERFORMANCE_FIELDS:
                widget.setSpecialValueText("" if has_user_config else "Unconfigured")
            widget.setValue(float(getattr(config, key)))
        for key, widget in self._maneuvering_inputs.items():
            value = getattr(config, key)
            widget.setText("" if value is None else str(value))
        self.me_curve_input.setText(_format_curve(self._voyage_service.list_main_engine_sfoc_points(vessel_id)))
        self.dg_curve_input.setText(_format_curve(self._voyage_service.list_generator_sfoc_points(vessel_id)))
        self.profile_type_label.setText(
            "USER CONFIGURED" if has_user_config else "DEFAULT PROFILE"
        )

    def _use_performance_defaults(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        has_user_config = bool(vessel and self._voyage_service.has_energy_config(vessel.id))
        if has_user_config:
            answer = QMessageBox.question(
                self,
                "Apply available technical defaults?",
                "Apply known application defaults? Technical values with no defined default will be preserved. Values are saved only when you choose Next.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        defaults = VesselEnergyConfig(vessel_id=vessel.id if vessel else 0)
        for key in KNOWN_PERFORMANCE_DEFAULT_FIELDS:
            widget = self._energy_inputs[key]
            widget.setValue(float(getattr(defaults, key)))
        self.me_curve_input.setText(", ".join(f"{load:g}:{sfoc:g}" for load, sfoc in DEFAULT_ME_SFOC_POINTS))
        self.profile_type_label.setText("DEFAULTS + USER VALUES" if has_user_config else "APPLICATION DEFAULTS")
        self.performance_status.setText(
            "Known application defaults applied. Values without defined defaults were preserved; missing values remain unconfigured."
        )

    def _load_standard_tanks(self) -> None:
        try:
            dialog = VesselTankSetDialog(self._fuel_tank_service, self._required_vessel_id(), self)
            dialog.exec()
            self._populate_tank_rob_rows()
            self._refresh_inline_statuses()
        except Exception:
            LOGGER.exception("Standard vessel tank set could not be loaded")
            QMessageBox.critical(self, "Tank set unavailable", "The tank setup could not be opened. Check the application log for details.")

    def _populate_tank_rob_rows(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            self.tank_rob_table.setRowCount(0)
            self._tank_rob_rows.clear()
            self._tank_rob_original.clear()
            self._refresh_tank_rob_summary()
            return
        tanks = [
            tank for tank in self._fuel_tank_service.list_tanks(vessel.id)
            if tank.tank_type == "BUNKER"
        ]
        batches = {batch.id: batch for batch in self._fuel_tank_service.list_fuel_batches(vessel.id)}
        self.tank_rob_table.setRowCount(len(tanks))
        self._tank_rob_rows.clear()
        self._tank_rob_original.clear()
        for row, tank in enumerate(tanks):
            self.tank_rob_table.setItem(row, 0, QTableWidgetItem(tank.name))
            anchor = self._fuel_tank_service.get_latest_physical_mass_anchor(tank.id)
            assigned = batches.get(tank.current_fuel_batch_id)
            fuel = assigned.fuel_type if assigned else (anchor.fuel_type if anchor else "")
            fuel_input = QComboBox()
            fuel_input.addItems(FUEL_TYPES)
            fuel_input.setCurrentText(fuel) if fuel else fuel_input.setCurrentIndex(-1)
            fuel_input.setPlaceholderText("Select fuel")
            fuel_input.setEnabled(assigned is None)
            mass_input = QLineEdit()
            mass_input.setPlaceholderText("Unknown")
            if anchor is not None:
                mass_input.setText(f"{anchor.mass_mt:.2f}")
                original: tuple[str, float] | None = (fuel, float(mass_input.text()))
            else:
                original = None
            mass_input.textChanged.connect(self._refresh_tank_rob_summary)
            fuel_input.currentTextChanged.connect(self._refresh_tank_rob_summary)
            self.tank_rob_table.setCellWidget(row, 1, fuel_input)
            self.tank_rob_table.setCellWidget(row, 2, mass_input)
            self._tank_rob_rows[tank.id] = (fuel_input, mass_input)
            self._tank_rob_original[tank.id] = original
        self._refresh_tank_rob_summary()

    def _save_manual_tank_rob(self) -> None:
        observed_at = datetime.now(timezone.utc)
        saved_any = False
        for tank_id, (fuel_input, mass_input) in self._tank_rob_rows.items():
            mass_text = mass_input.text().strip()
            if not mass_text:
                continue
            try:
                mass = float(mass_text)
            except ValueError as exc:
                raise ValueError("Initial tank ROB must be a number or left blank.") from exc
            fuel = fuel_input.currentText()
            if not fuel:
                raise ValueError("Select a fuel for every tank with a manual ROB value.")
            original = self._tank_rob_original.get(tank_id)
            if original is not None and original == (fuel, mass):
                continue
            saved = self._fuel_tank_service.save_manual_tank_rob(
                tank_id=tank_id,
                fuel_type=fuel,
                mass_mt=mass,
                observed_at_utc=observed_at,
                remarks="Initialization wizard manual tank ROB",
            )
            self._tank_rob_original[tank_id] = (saved.fuel_type, saved.mass_mt)
            saved_any = True
        if saved_any:
            self._refresh_inline_statuses()

    def _refresh_tank_rob_summary(self) -> None:
        known_values: list[float] = []
        for _fuel, mass_input in self._tank_rob_rows.values():
            text = mass_input.text().strip()
            if not text:
                continue
            try:
                value = float(text)
            except ValueError:
                continue
            if value >= 0:
                known_values.append(value)
        total = len(self._tank_rob_rows)
        known = len(known_values)
        self.tank_rob_summary.setText(
            f"Known mass: {sum(known_values):.2f} MT    "
            f"Known tanks: {known} / {total}    Unknown tanks: {total - known}"
        )

    def _request_page(self, page_index: int) -> None:
        self._landing_page = page_index
        self.schedule_status.setText("Schedule screen selected. Finish setup or choose Finish Later to continue there.")

    def _refresh_inline_statuses(self) -> None:
        readiness = self._readiness_service.evaluate()
        tank = readiness.check(TANK_CONFIGURATION_AVAILABLE)
        physical = readiness.check(TANK_PHYSICAL_ROB_AVAILABLE)
        schedule = readiness.check(SCHEDULE_AVAILABLE)
        performance = readiness.check(PERFORMANCE_CONFIGURED)
        self.tank_status.setText(("✓ " if tank.available else "⚠ ") + _readiness_label(tank) + (f" — {tank.reason}" if not tank.available and tank.reason else ""))
        self.tank_rob_status.setText(("✓ " if physical.available else "⚠ ") + physical.label + (f" — {physical.reason}" if not physical.available and physical.reason else ""))
        self.schedule_status.setText(("✓ " if schedule.available else "⚠ ") + _readiness_label(schedule) + (f" — {schedule.reason}" if not schedule.available and schedule.reason else ""))
        self.performance_status.setText(("✓ " if performance.available else "⚠ ") + _readiness_label(performance) + ("" if performance.available else ": " + ", ".join(performance.missing_inputs)))

    def _refresh_readiness(self) -> None:
        readiness = self._readiness_service.evaluate()
        for check in readiness.checks:
            marker = "✓" if check.available else ("✕" if check.required else "⚠")
            suffix = "" if check.available or not check.reason else f" — {check.reason}"
            self.readiness_labels[check.key].setText(f"{marker} {_readiness_label(check)}{suffix}")
        if readiness.first_blocking_stage:
            message = f"First blocking stage: {readiness.first_blocking_stage}\nReason: {readiness.blocking_reason}"
            if readiness.calculation_available_until:
                message += f"\nCalculation available until: {readiness.calculation_available_until}"
        elif readiness.blocking_reason:
            message = f"Reason: {readiness.blocking_reason}"
        else:
            message = "READY — voyage projection is available."
        self.blocker_label.setText(message)
        voyage = readiness.check(VOYAGE_PROJECTION_AVAILABLE)
        self.operational_status.setText(
            "✓ Voyage projection can proceed through the scheduled stages."
            if voyage.available else message
        )

    def _set_rob_inputs_enabled(self, enabled: bool) -> None:
        for widget in self._rob_inputs.values():
            widget.setEnabled(enabled)
            widget.setSpecialValueText("" if enabled else "Unknown")

    def _refresh_time_preview(self) -> None:
        offset = self.timezone_input.currentData()
        if offset is None:
            return
        utc_now = datetime.now(timezone.utc)
        local_now = vessel_local_time(utc_now, int(offset))
        self.time_preview.setText(
            f"Vessel Local: {local_now:%d %b %Y %H:%M}\n"
            f"UTC:          {utc_now:%d %b %Y %H:%M}"
        )

    def _finish_later(self) -> None:
        self._save_step(self.stack.currentIndex())
        self._settings_service.save_initialization_wizard_state(seen=True, completed=False)
        self.reject()
        if self._landing_page is not None:
            self.page_requested.emit(self._landing_page)

    def _required_vessel_id(self) -> int:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None or vessel.id is None:
            raise ValueError("Configure vessel details first.")
        return vessel.id

    def _clear_vessel_dependent_inputs(self) -> None:
        defaults = VesselEnergyConfig(vessel_id=0)
        for key, widget in self._energy_inputs.items():
            widget.setValue(float(getattr(defaults, key)))
        for widget in self._maneuvering_inputs.values():
            widget.clear()
        self.me_curve_input.setText(", ".join(f"{load:g}:{sfoc:g}" for load, sfoc in DEFAULT_ME_SFOC_POINTS))
        self.dg_curve_input.clear()
        for combo in self._fuel_inputs.values():
            combo.setCurrentIndex(-1)
        self.use_starting_rob.setChecked(False)
        self._refresh_inline_statuses()


def _page(description: str) -> tuple[QWidget, QVBoxLayout]:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(4, 10, 4, 4)
    layout.setSpacing(14)
    note = _muted(description)
    layout.addWidget(note)
    return page, layout


def _scroll_page(description: str) -> tuple[QWidget, QVBoxLayout]:
    page = QWidget()
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    content, layout = _page(description)
    scroll.setWidget(content)
    outer.addWidget(scroll)
    return page, layout


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("mutedText")
    label.setWordWrap(True)
    return label


def _warning(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("notConfiguredStatus")
    label.setWordWrap(True)
    return label


def _optional_number(value: str) -> float | None:
    clean = value.strip()
    if not clean:
        return None
    number = float(clean)
    if number < 0:
        raise ValueError("Maneuvering rates cannot be negative.")
    return number


def _readiness_label(check) -> str:
    return check.label if check.available else UNAVAILABLE_READINESS_LABELS.get(check.key, check.label)


def _parse_curve(value: str, label: str) -> list[tuple[float, float]]:
    clean = value.strip()
    if not clean:
        return []
    points: list[tuple[float, float]] = []
    try:
        for item in clean.split(","):
            load_text, sfoc_text = item.strip().split(":", 1)
            points.append((float(load_text), float(sfoc_text)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} SFOC curve must use load:sfoc pairs separated by commas.") from exc
    if any(load < 0 or sfoc < 0 for load, sfoc in points):
        raise ValueError(f"{label} SFOC curve values cannot be negative.")
    return points


def _format_curve(points) -> str:
    return ", ".join(f"{point.load_percent:g}:{point.sfoc_g_per_kwh:g}" for point in points)
