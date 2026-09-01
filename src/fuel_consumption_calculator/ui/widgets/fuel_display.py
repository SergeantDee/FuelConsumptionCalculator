from __future__ import annotations

from html import escape

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QTextDocument, QAbstractTextDocumentLayout
from PySide6.QtWidgets import (
    QLabel,
    QStyle,
    QStyledItemDelegate,
)

from fuel_consumption_calculator.ui.theme import COLORS


FUEL_COLORS = {
    "ULSFO": "#58C5E8",
    "VLSFO": "#9B86E6",
    "MDO": "#F08A22",
}

FUEL_BADGE_BACKGROUNDS = {
    "ULSFO": "#183E4A",
    "VLSFO": "#332D4D",
    "MDO": "#4A2D13",
}

FUEL_ORDER = ("ULSFO", "VLSFO", "MDO")


def fuel_color(fuel_type: str) -> str:
    return FUEL_COLORS.get(str(fuel_type).upper(), COLORS["secondary_text"])


def fuel_badge_html(fuel_type: str) -> str:
    """Compact shared fuel chip suitable for labels and dense table delegates."""
    fuel = str(fuel_type).upper()
    background = FUEL_BADGE_BACKGROUNDS.get(fuel, "#34434d")
    foreground = FUEL_COLORS.get(fuel, COLORS["secondary_text"])
    return f'<span style="background-color:{background}; color:{foreground}; font-weight:700; padding:2px 6px;">{escape(fuel)}</span>'


class FuelBadge(QLabel):
    """Small, readable badge for a single fuel identity."""
    def __init__(self, fuel_type: str | None, parent=None) -> None:
        super().__init__(parent)
        self.set_fuel_type(fuel_type)

    def set_fuel_type(self, fuel_type: str | None) -> None:
        self.setText(str(fuel_type or "UNKNOWN").upper())
        fuel = self.text()
        self.setObjectName("fuelBadge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "QLabel#fuelBadge {"
            f" background: {FUEL_BADGE_BACKGROUNDS.get(fuel, '#34434d')};"
            f" color: {FUEL_COLORS.get(fuel, COLORS['secondary_text'])};"
            " border-radius: 4px; padding: 2px 6px; font-size: 8pt; font-weight: 700; }"
        )


def format_fuel_plain(
    values: dict[str, float | None],
    *,
    decimals: int = 2,
    show_unit: bool = False,
    zero_blank: bool = False,
) -> str:
    parts: list[str] = []

    for fuel_type in FUEL_ORDER:
        value = values.get(fuel_type)

        if zero_blank and value == 0:
            continue

        if value is None:
            quantity = "-"
        else:
            quantity = f"{float(value):.{decimals}f}"

        if show_unit and quantity != "-":
            quantity += " MT"

        parts.append(f"{fuel_type} {quantity}")

    return "  |  ".join(parts) if parts else "-"


def format_fuel_html(
    values: dict[str, float | None],
    *,
    decimals: int = 2,
    show_unit: bool = False,
    prefix: str = "",
    zero_blank: bool = False,
) -> str:
    parts: list[str] = []

    for fuel_type in FUEL_ORDER:
        value = values.get(fuel_type)

        if zero_blank and value == 0:
            continue

        if value is None:
            quantity = "-"
        else:
            quantity = f"{float(value):.{decimals}f}"

        if show_unit and quantity != "-":
            quantity += " MT"

        parts.append(
            fuel_badge_html(fuel_type) +
            f'&nbsp;<span style="color:{COLORS["text"]};">{escape(quantity)}</span>'
        )

    body = f'&nbsp;&nbsp;<span style="color:{COLORS["muted_text"]};">|</span>&nbsp;&nbsp;'.join(parts)

    if prefix:
        return (
            f'<span style="color:{COLORS["secondary_text"]};">{escape(prefix)}</span>'
            f'{body}'
        )

    return body or "-"


class FuelTextDelegate(QStyledItemDelegate):
    """Paint fuel strings with colored ULSFO / VLSFO / MDO labels."""

    def paint(self, painter: QPainter, option, index) -> None:
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")

        if not any(fuel in text for fuel in FUEL_ORDER):
            super().paint(painter, option, index)
            return

        opt = option
        self.initStyleOption(opt, index)

        style = opt.widget.style() if opt.widget is not None else None
        if style is None:
            super().paint(painter, option, index)
            return

        painter.save()

        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem,
            opt,
            painter,
            opt.widget,
        )

        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        value_color = "#ffffff" if selected else COLORS["text"]
        separator_color = "#d9efff" if selected else COLORS["muted_text"]

        html_text = escape(text)

        for fuel_type in FUEL_ORDER:
            color = "#ffffff" if selected else fuel_color(fuel_type)
            background = "transparent" if selected else FUEL_BADGE_BACKGROUNDS.get(fuel_type, COLORS["border"])
            html_text = html_text.replace(
                fuel_type,
                (
                    f'<span style="background-color:{background}; color:{color}; font-weight:700;">'
                    f'{fuel_type}</span>'
                ),
            )

        html_text = html_text.replace(
            " | ",
            (
                f' <span style="color:{separator_color};">|</span> '
            ),
        )

        document = QTextDocument()
        document.setDefaultFont(opt.font)
        document.setDocumentMargin(0)
        document.setHtml(
            f'<span style="color:{value_color};">{html_text}</span>'
        )

        text_rect = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemText,
            opt,
            opt.widget,
        )

        painter.translate(text_rect.topLeft())

        context = QAbstractTextDocumentLayout.PaintContext()
        context.clip = QRectF(
            0,
            0,
            text_rect.width(),
            text_rect.height(),
        )

        document.documentLayout().draw(painter, context)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return super().sizeHint(option, index)
