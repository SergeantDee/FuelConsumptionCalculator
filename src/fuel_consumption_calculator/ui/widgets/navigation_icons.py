from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap


def navigation_icon(kind: str, color: str) -> QIcon:
    """Small dependency-free line icons for the application navigation."""
    pixmap = QPixmap(18, 18)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(color), 1.5))
    box = QRectF(3, 3, 12, 12)

    if kind == "dashboard":
        for x, y in ((3, 3), (10, 3), (3, 10), (10, 10)):
            painter.drawRect(QRectF(x, y, 5, 5))
    elif kind == "schedule":
        painter.drawRoundedRect(box, 1, 1); painter.drawLine(3, 7, 15, 7); painter.drawLine(6, 2, 6, 5); painter.drawLine(12, 2, 12, 5)
    elif kind == "voyage":
        painter.drawEllipse(3, 12, 3, 3); painter.drawEllipse(12, 3, 3, 3); painter.drawLine(5, 13, 13, 5)
    elif kind == "consumption":
        painter.drawLine(4, 14, 4, 10); painter.drawLine(9, 14, 9, 6); painter.drawLine(14, 14, 14, 3)
    elif kind == "tanks":
        painter.drawRoundedRect(QRectF(4, 3, 10, 12), 2, 2); painter.drawLine(4, 7, 14, 7); painter.drawLine(4, 11, 14, 11)
    elif kind == "bunker":
        painter.drawRect(QRectF(5, 7, 8, 7)); painter.drawLine(7, 7, 7, 4); painter.drawLine(7, 4, 11, 4); painter.drawLine(11, 4, 11, 7)
    else:
        painter.drawEllipse(box); painter.drawLine(9, 1, 9, 4); painter.drawLine(9, 14, 9, 17); painter.drawLine(1, 9, 4, 9); painter.drawLine(14, 9, 17, 9)
    painter.end()
    return QIcon(pixmap)
