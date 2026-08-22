from __future__ import annotations

from html import escape

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QTextDocument, QAbstractTextDocumentLayout
from PySide6.QtWidgets import (
    QStyle,
    QStyledItemDelegate,
)


FUEL_COLORS = {
    "ULSFO": "#7dd3fc",
    "VLSFO": "#c084fc",
    "MDO": "#facc15",
}

FUEL_ORDER = ("ULSFO", "VLSFO", "MDO")


def fuel_color(fuel_type: str) -> str:
    return FUEL_COLORS.get(str(fuel_type).upper(), "#eef7ff")


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

        color = fuel_color(fuel_type)

        parts.append(
            f'<span style="color:{color}; font-weight:700;">'
            f'{escape(fuel_type)}</span>'
            f'&nbsp;<span style="color:#eef7ff;">{escape(quantity)}</span>'
        )

    body = '&nbsp;&nbsp;<span style="color:#617b8c;">|</span>&nbsp;&nbsp;'.join(parts)

    if prefix:
        return (
            f'<span style="color:#dce8f2;">{escape(prefix)}</span>'
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
        value_color = "#ffffff" if selected else "#eef7ff"
        separator_color = "#d9efff" if selected else "#617b8c"

        html_text = escape(text)

        for fuel_type in FUEL_ORDER:
            color = "#ffffff" if selected else fuel_color(fuel_type)
            html_text = html_text.replace(
                fuel_type,
                (
                    f'<span style="color:{color}; font-weight:700;">'
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
