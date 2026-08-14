from __future__ import annotations

from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from fuel_consumption_calculator.services.vessel_service import VesselService
from fuel_consumption_calculator.ui.widgets.page_header import PageHeader


class DashboardPage(QWidget):
    def __init__(self, vessel_service: VesselService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vessel_service = vessel_service

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(18)
        layout.addWidget(PageHeader("Fuel Consumption Calculator", "Vessel fuel planning workspace"))

        identity = QFrame()
        identity.setObjectName("card")
        identity_layout = QGridLayout(identity)
        identity_layout.setContentsMargins(20, 18, 20, 18)
        identity_layout.addWidget(self._label("VESSEL"), 0, 0)
        identity_layout.addWidget(self._label("IMO NUMBER"), 0, 1)
        self.vessel_name_value = QLabel("Not configured")
        self.vessel_name_value.setObjectName("cardValue")
        self.imo_value = QLabel("—")
        self.imo_value.setObjectName("cardValue")
        identity_layout.addWidget(self.vessel_name_value, 1, 0)
        identity_layout.addWidget(self.imo_value, 1, 1)
        layout.addWidget(identity)

        fuel_cards = QHBoxLayout()
        fuel_cards.setSpacing(14)
        for fuel in ("ULSFO ROB", "VLSFO ROB", "MDO ROB"):
            fuel_cards.addWidget(self._fuel_card(fuel))
        layout.addLayout(fuel_cards)

        self.status_label = QLabel()
        layout.addWidget(self.status_label)
        layout.addStretch()
        self.refresh()

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("cardLabel")
        return label

    def _fuel_card(self, fuel: str) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.addWidget(self._label(fuel))
        value = QLabel("— MT")
        value.setObjectName("cardValue")
        card_layout.addWidget(value)
        return card

    def refresh(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            self.vessel_name_value.setText("Not configured")
            self.imo_value.setText("—")
            self.status_label.setText("Vessel not configured — open Settings to get started.")
            self.status_label.setObjectName("notConfiguredStatus")
        else:
            self.vessel_name_value.setText(vessel.name)
            self.imo_value.setText(vessel.imo)
            self.status_label.setText("Vessel configuration is ready.")
            self.status_label.setObjectName("configuredStatus")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
