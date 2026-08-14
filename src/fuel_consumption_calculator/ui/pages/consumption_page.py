from __future__ import annotations

from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from fuel_consumption_calculator.domain.consumption import FUEL_TYPES, OPERATING_MODES
from fuel_consumption_calculator.services.consumption_service import ConsumptionService
from fuel_consumption_calculator.services.vessel_service import VesselService
from fuel_consumption_calculator.ui.widgets.page_header import PageHeader


class ConsumptionPage(QWidget):
    def __init__(self, vessel_service: VesselService, consumption_service: ConsumptionService) -> None:
        super().__init__()
        self._vessel_service = vessel_service
        self._consumption_service = consumption_service
        self._rate_inputs: dict[tuple[str, str], QDoubleSpinBox] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)
        layout.addWidget(PageHeader("Consumption", "Configure vessel fuel consumption rates."))

        self.vessel_label = QLabel("Vessel: Not configured")
        self.vessel_label.setObjectName("fieldLabel")
        layout.addWidget(self.vessel_label)

        matrix = QFrame()
        matrix.setObjectName("panel")
        grid = QGridLayout(matrix)
        grid.setContentsMargins(18, 16, 18, 16)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)

        grid.addWidget(QLabel("Mode"), 0, 0)
        for column, fuel_type in enumerate(FUEL_TYPES, start=1):
            header = QLabel(f"{fuel_type} MT/day")
            header.setObjectName("fieldLabel")
            grid.addWidget(header, 0, column)

        for row, operating_mode in enumerate(OPERATING_MODES, start=1):
            mode_label = QLabel(operating_mode)
            mode_label.setObjectName("fieldLabel")
            grid.addWidget(mode_label, row, 0)
            for column, fuel_type in enumerate(FUEL_TYPES, start=1):
                spinbox = QDoubleSpinBox()
                spinbox.setDecimals(2)
                spinbox.setRange(0.0, 9999.99)
                spinbox.setSingleStep(0.25)
                spinbox.setSuffix(" MT/day")
                grid.addWidget(spinbox, row, column)
                self._rate_inputs[(operating_mode, fuel_type)] = spinbox

        layout.addWidget(matrix)

        actions = QHBoxLayout()
        self.save_button = QPushButton("Save Consumption Profile")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save_profile)
        actions.addWidget(self.save_button)
        actions.addStretch()
        layout.addLayout(actions)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("mutedText")
        layout.addWidget(self.status_label)
        layout.addStretch()

        self.refresh()

    def refresh(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            self.vessel_label.setText("Vessel: Not configured")
            self.save_button.setEnabled(False)
            self._set_inputs_enabled(False)
            self._set_rates_to_zero()
            self.status_label.setText("Configure a vessel before saving consumption rates.")
            return

        self.vessel_label.setText(f"Vessel: {vessel.name}  |  IMO {vessel.imo}")
        self.save_button.setEnabled(True)
        self._set_inputs_enabled(True)
        profile = self._consumption_service.load_profile(vessel.id)
        for key, spinbox in self._rate_inputs.items():
            spinbox.setValue(profile.rate_for(*key))
        self.status_label.setText("Consumption profile loaded.")

    def _save_profile(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            QMessageBox.warning(self, "Vessel required", "Configure a vessel before saving consumption rates.")
            return

        rates = {
            key: spinbox.value()
            for key, spinbox in self._rate_inputs.items()
        }
        try:
            profile = self._consumption_service.build_profile(vessel.id, rates)
            saved_profile = self._consumption_service.save_profile(profile)
        except Exception as exc:
            QMessageBox.warning(self, "Consumption profile not saved", str(exc))
            return

        for key, spinbox in self._rate_inputs.items():
            spinbox.setValue(saved_profile.rate_for(*key))
        self.status_label.setText("Consumption profile saved.")

    def _set_inputs_enabled(self, enabled: bool) -> None:
        for spinbox in self._rate_inputs.values():
            spinbox.setEnabled(enabled)

    def _set_rates_to_zero(self) -> None:
        for spinbox in self._rate_inputs.values():
            spinbox.setValue(0.0)
