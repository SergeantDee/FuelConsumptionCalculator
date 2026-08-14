from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget

from fuel_consumption_calculator.services.vessel_service import VesselService, VesselValidationError
from fuel_consumption_calculator.ui.widgets.page_header import PageHeader


LOGGER = logging.getLogger(__name__)


class SettingsPage(QWidget):
    vessel_saved = Signal()

    def __init__(self, vessel_service: VesselService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vessel_service = vessel_service

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
