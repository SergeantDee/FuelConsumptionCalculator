from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from fuel_consumption_calculator.ui.widgets.page_header import PageHeader


class PlaceholderPage(QWidget):
    def __init__(self, title: str, description: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.addWidget(PageHeader(title, description))
        message = QLabel("Planned for a later sprint")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setObjectName("card")
        message.setMinimumHeight(180)
        layout.addWidget(message)
        layout.addStretch()
