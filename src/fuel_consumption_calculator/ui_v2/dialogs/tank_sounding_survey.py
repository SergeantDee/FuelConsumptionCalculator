from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from fuel_consumption_calculator.ui.pages.fuel_tanks_page import TankSoundingSurveyDialog
from fuel_consumption_calculator.ui.widgets.fuel_display import FuelBadge
from fuel_consumption_calculator.ui_v2.components import SecondaryButton


class TankSoundingSurveyV2(TankSoundingSurveyDialog):
    """V2 survey presentation retaining the established validation and save workflow."""
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setObjectName("v2SurveyDialog")
        self.resize(1100, 660)
        self.setMinimumSize(980, 620)
        self.table.setObjectName("v2SurveyTable")
        self.table.setHorizontalHeaderLabels(("Include", "Tank", "Fuel / Basis", "Measure", "Reading", "Temp °C", "VCF", "Volume m³", "MT", "Status"))
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.completeness.setObjectName("v2SurveyStatus")
        self.totals.setObjectName("v2SurveyTotals")
        self.use_actual.setObjectName("v2SurveyActualOption")
        title = self.layout().itemAt(0).widget()
        if isinstance(title, QLabel): title.setObjectName("v2DialogTitle")
        self.save_button.setObjectName("primaryButton")
        for button in self.findChildren(QPushButton):
            if button.text() == "Cancel":
                button.setObjectName("v2OutlineButton")
        self._replace_fuel_basis_cells()

    def _refresh_totals(self) -> None:
        super()._refresh_totals()
        status = self.completeness.text()
        if "COMPLETE" in status and "INCOMPLETE" not in status:
            self.completeness.setText(f"●  {status}")
            self.completeness.setStyleSheet("color: #61C98A; font-weight: 600;")
        else:
            self.completeness.setText(f"●  {status}")
            self.completeness.setStyleSheet("color: #F0A03B; font-weight: 600;")

    def _replace_fuel_basis_cells(self) -> None:
        for index, row in enumerate(self._rows):
            _tank, _include, _kind, _reading, _temp, _vcf, _status, batch, _volume, _mass = row
            holder = QWidget(); layout = QVBoxLayout(holder); layout.setContentsMargins(5, 3, 5, 3); layout.setSpacing(2)
            fuel = batch.fuel_type if batch else "UNKNOWN"
            badge = FuelBadge(fuel); layout.addWidget(badge, alignment=Qt.AlignmentFlag.AlignLeft)
            basis = QLabel(batch.batch_name if batch else "No batch")
            basis.setObjectName("v2SurveyBasis"); basis.setToolTip(basis.text()); layout.addWidget(basis)
            self.table.setCellWidget(index, 2, holder)
