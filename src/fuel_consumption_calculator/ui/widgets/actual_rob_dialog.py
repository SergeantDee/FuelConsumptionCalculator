from __future__ import annotations

from datetime import timezone

from PySide6.QtCore import QDateTime, QTimeZone
from PySide6.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from fuel_consumption_calculator.domain.consumption import FUEL_TYPES


class ActualROBDialog(QDialog):
    """Shared, validated editor for one authoritative Actual ROB observation."""

    def __init__(
        self,
        quantities_mt: dict[str, float | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Update Actual ROB")
        self._quantity_inputs: dict[str, QLineEdit] = {}

        layout = QVBoxLayout(self)
        grid = QGridLayout()
        layout.addLayout(grid)
        self.time_input = QDateTimeEdit()
        self.time_input.setCalendarPopup(True)
        self.time_input.setDisplayFormat("dd MMM yyyy HH:mm")
        self.time_input.setTimeZone(QTimeZone.utc())
        self.time_input.setDateTime(QDateTime.currentDateTimeUtc())
        grid.addWidget(QLabel("Observation Time UTC"), 0, 0)
        grid.addWidget(self.time_input, 0, 1)

        for row, fuel_type in enumerate(FUEL_TYPES, start=1):
            input_widget = QLineEdit()
            value = quantities_mt.get(fuel_type) if quantities_mt is not None else None
            if value is not None:
                input_widget.setText(f"{float(value):.2f}")
            input_widget.setPlaceholderText("Enter actual ROB (MT)")
            self._quantity_inputs[fuel_type] = input_widget
            grid.addWidget(QLabel(f"{fuel_type} Actual ROB"), row, 0)
            grid.addWidget(input_widget, row, 1)

        self.remarks_input = QComboBox()
        self.remarks_input.setEditable(True)
        self.remarks_input.addItem("")
        grid.addWidget(QLabel("Remarks"), 4, 0)
        grid.addWidget(self.remarks_input, 4, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        for fuel_type, input_widget in self._quantity_inputs.items():
            text = input_widget.text().strip()
            if not text:
                QMessageBox.warning(self, "Actual ROB incomplete", f"Enter the actual {fuel_type} ROB before saving.")
                input_widget.setFocus()
                return
            try:
                value = float(text)
            except ValueError:
                QMessageBox.warning(self, "Invalid Actual ROB", f"{fuel_type} ROB must be a number.")
                input_widget.setFocus()
                return
            if value < 0:
                QMessageBox.warning(self, "Invalid Actual ROB", f"{fuel_type} ROB cannot be negative.")
                input_widget.setFocus()
                return
        super().accept()

    def values(self) -> dict[str, object]:
        return {
            "effective_at_utc": self.time_input.dateTime().toUTC().toPython().replace(tzinfo=timezone.utc),
            **{fuel: float(self._quantity_inputs[fuel].text().strip()) for fuel in FUEL_TYPES},
            "remarks": self.remarks_input.currentText().strip() or None,
        }
