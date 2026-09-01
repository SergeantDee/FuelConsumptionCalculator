from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from fuel_consumption_calculator.ui.widgets.fuel_display import FuelBadge, fuel_color


class DashboardCard(QFrame):
    """Small reusable raised surface for dashboard content."""

    def __init__(self, title: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dashboardCard")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(14, 12, 14, 12)
        self.layout.setSpacing(8)
        if title:
            heading = QLabel(title)
            heading.setObjectName("dashboardSectionTitle")
            self.layout.addWidget(heading)


class FuelRobCard(DashboardCard):
    """Compact, fuel-identified operational metric card."""

    def __init__(self, fuel: str, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.setObjectName("fuelRobCard")
        accent = QFrame()
        accent.setObjectName("fuelAccent")
        accent.setStyleSheet(f"background-color: {fuel_color(fuel)};")
        self.layout.addWidget(accent)
        self.layout.addWidget(FuelBadge(fuel))
        self.value_label = QLabel("- MT")
        self.value_label.setObjectName("dashboardMetric")
        self.layout.addWidget(self.value_label)
        self.meta_label = QLabel("Unavailable")
        self.meta_label.setObjectName("dashboardMeta")
        self.layout.addWidget(self.meta_label)
        self.layout.addStretch()

    def set_value(self, value: float | None, metadata: str) -> None:
        self.value_label.setText(f"{float(value):.2f} MT" if value is not None else "- MT")
        self.meta_label.setText(metadata)


class InfoMetricCard(DashboardCard):
    """A concise title/value/metadata card for existing operational data."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.value_label = QLabel("-")
        self.value_label.setObjectName("dashboardValue")
        self.value_label.setWordWrap(True)
        self.meta_label = QLabel("")
        self.meta_label.setObjectName("dashboardMeta")
        self.meta_label.setWordWrap(True)
        self.layout.addWidget(self.value_label)
        self.layout.addWidget(self.meta_label)
        self.layout.addStretch()

    def set_data(self, value: str, metadata: str = "") -> None:
        self.value_label.setText(value)
        self.meta_label.setText(metadata)


class EmptyState(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("dashboardEmptyState")
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)


class StatusBadge(QLabel):
    """Small presentation-only badge for an existing status value."""

    _STYLES = {"CURRENT": ("#263847", "#51B9DD"), "CONFIRMED": ("#29443C", "#A7D6C6"), "UPCOMING": ("#3A3A2B", "#DCC487"), "DRAFT": ("#303840", "#B4BEC7"), "PLANNED": ("#303840", "#B4BEC7"), "STALE": ("#46322C", "#E2B28B")}

    def __init__(self, status: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.set_status(status)

    def set_status(self, status: str) -> None:
        normalized = str(status or "-").upper()
        background, foreground = self._STYLES.get(normalized, ("#303840", "#B4BEC7"))
        self.setText(normalized.title())
        self.setStyleSheet(f"background:{background}; color:{foreground}; border-radius:4px; padding:2px 6px; font-size:8pt; font-weight:700;")


class InfoBanner(EmptyState):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("infoBanner")


class FormSection(DashboardCard):
    """A named card used to group related native Qt form controls."""
    pass


AppCard = DashboardCard
SectionCard = DashboardCard
MetricCard = InfoMetricCard
FuelMetricCard = FuelRobCard
