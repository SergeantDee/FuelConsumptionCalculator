from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from fuel_consumption_calculator.ui.widgets.fuel_display import FuelBadge, fuel_color


class AppCard(QFrame):
    """V2 raised surface with a consistent compact header/body hierarchy."""
    def __init__(self, title: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("v2AppCard")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(14, 12, 14, 12)
        self.body.setSpacing(8)
        if title:
            heading = QLabel(title)
            heading.setObjectName("v2CardHeading")
            self.body.addWidget(heading)


class FuelMetricCard(AppCard):
    def __init__(self, fuel: str, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        accent = QFrame(); accent.setObjectName("fuelAccent"); accent.setStyleSheet(f"background:{fuel_color(fuel)};")
        self.body.addWidget(accent)
        self.body.addWidget(FuelBadge(fuel))
        self.value = QLabel("— MT"); self.value.setObjectName("v2FuelMetric"); self.body.addWidget(self.value)
        self.meta = QLabel("Unavailable"); self.meta.setObjectName("v2CardMeta"); self.meta.setWordWrap(True); self.body.addWidget(self.meta)

    def set_value(self, value: float | None, metadata: str) -> None:
        self.value.setText(f"{float(value):.2f} MT" if value is not None else "— MT")
        self.meta.setText(metadata)


class MetricCard(AppCard):
    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(label, parent)
        self.value = QLabel("—"); self.value.setObjectName("v2MetricValue"); self.body.addWidget(self.value)
        self.meta = QLabel(""); self.meta.setObjectName("v2CardMeta"); self.meta.setWordWrap(True); self.body.addWidget(self.meta)

    def set_data(self, value: str, metadata: str) -> None:
        self.value.setText(value)
        self.meta.setText(metadata)


class EmptyState(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("v2EmptyState"); self.setWordWrap(True)


class PrimaryButton(QPushButton):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent); self.setObjectName("primaryButton")


class SecondaryButton(QPushButton):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("v2OutlineButton")
