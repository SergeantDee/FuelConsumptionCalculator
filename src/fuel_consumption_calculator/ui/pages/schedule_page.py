from __future__ import annotations

import datetime as dt
from threading import Event

from PySide6.QtCore import QAbstractTableModel, QDate, QDateTime, QObject, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDateEdit,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from fuel_consumption_calculator.domain.schedule import ScheduleCandidate, ScheduleEvent, ScheduleEventDraft
from fuel_consumption_calculator.services.schedule_service import ScheduleService
from fuel_consumption_calculator.services.scraper_service import ScraperService
from fuel_consumption_calculator.services.vessel_service import VesselService
from fuel_consumption_calculator.ui.widgets.page_header import PageHeader


class ScheduleTableModel(QAbstractTableModel):
    HEADERS = ("#", "Port", "Event", "Arrival", "Departure", "Source")

    def __init__(self, rows: list[ScheduleCandidate | ScheduleEvent] | None = None) -> None:
        super().__init__()
        self._rows = rows or []

    def rowCount(self, parent=None) -> int:
        return len(self._rows)

    def columnCount(self, parent=None) -> int:
        return len(self.HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        row = self._rows[index.row()]
        values = (
            row.sequence_number,
            row.port,
            row.event_type,
            row.arrival_at.strftime("%d %b %Y %H:%M"),
            row.departure_at.strftime("%d %b %Y %H:%M") if row.departure_at else "",
            row.source,
        )
        return str(values[index.column()])

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return str(section + 1)

    def set_rows(self, rows: list[ScheduleCandidate | ScheduleEvent]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def row_at(self, index: int) -> ScheduleCandidate | ScheduleEvent | None:
        if not 0 <= index < len(self._rows):
            return None
        return self._rows[index]


class ScrapeWorkerSignals(QObject):
    progress = Signal(str, str)
    success = Signal(object)
    failure = Signal(str)


class ScrapeWorker(QRunnable):
    def __init__(
        self,
        scraper_service: ScraperService,
        vessel_name: str,
        from_date: dt.date,
        cancel_event: Event,
    ) -> None:
        super().__init__()
        self.signals = ScrapeWorkerSignals()
        self._scraper_service = scraper_service
        self._vessel_name = vessel_name
        self._from_date = from_date
        self._cancel_event = cancel_event

    @Slot()
    def run(self) -> None:
        try:
            candidates = self._scraper_service.scrape_schedule(
                self._vessel_name,
                self._from_date,
                progress_callback=self.signals.progress.emit,
                cancel_event=self._cancel_event,
            )
        except Exception as exc:
            self.signals.failure.emit(str(exc))
            return
        self.signals.success.emit(candidates)


class SchedulePreviewDialog(QDialog):
    def __init__(self, candidates: list[ScheduleCandidate], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preview Schedule Update")
        self.resize(900, 520)

        layout = QVBoxLayout(self)
        title = QLabel(f"Preview {len(candidates)} schedule events")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        table = QTableView()
        table.setModel(ScheduleTableModel(candidates))
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setStretchLastSection(True)
        table.resizeColumnsToContents()
        layout.addWidget(table, 1)

        buttons = QDialogButtonBox()
        self.cancel_button = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        self.confirm_button = buttons.addButton("Confirm Update", QDialogButtonBox.ButtonRole.AcceptRole)
        self.confirm_button.setObjectName("primaryButton")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class ScheduleEventDialog(QDialog):
    def __init__(
        self,
        *,
        max_sequence: int,
        source_vessel_name: str,
        default_date: dt.date,
        event: ScheduleEvent | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Schedule Event" if event else "Add Schedule Event")
        self.resize(460, 360)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.sequence_input = QSpinBox()
        self.sequence_input.setMinimum(1)
        self.sequence_input.setMaximum(max(1, max_sequence))
        self.sequence_input.setValue(event.sequence_number if event else max_sequence)
        form.addRow("Sequence", self.sequence_input)

        self.port_input = QLineEdit(event.port if event else "")
        form.addRow("Port", self.port_input)

        self.terminal_input = QLineEdit(event.terminal or "" if event else "")
        form.addRow("Terminal", self.terminal_input)

        self.event_type_input = QLineEdit(event.event_type if event else "Port Call")
        form.addRow("Event", self.event_type_input)

        self.arrival_input = QDateTimeEdit()
        self.arrival_input.setCalendarPopup(True)
        self.arrival_input.setDisplayFormat("dd MMM yyyy HH:mm")
        arrival = event.arrival_at if event else dt.datetime.combine(default_date, dt.time(hour=8))
        self.arrival_input.setDateTime(QDateTime(arrival))
        form.addRow("Arrival", self.arrival_input)

        self.has_departure_input = QCheckBox("Set departure")
        self.has_departure_input.setChecked(event.departure_at is not None if event else True)
        form.addRow("", self.has_departure_input)

        self.departure_input = QDateTimeEdit()
        self.departure_input.setCalendarPopup(True)
        self.departure_input.setDisplayFormat("dd MMM yyyy HH:mm")
        departure = event.departure_at if event and event.departure_at else dt.datetime.combine(default_date, dt.time(hour=20))
        self.departure_input.setDateTime(QDateTime(departure))
        self.departure_input.setEnabled(self.has_departure_input.isChecked())
        self.has_departure_input.toggled.connect(self.departure_input.setEnabled)
        form.addRow("Departure", self.departure_input)

        self.source_input = QLineEdit(event.source if event else "manual")
        form.addRow("Source", self.source_input)

        self.source_vessel_input = QLineEdit(event.source_vessel_name if event else source_vessel_name)
        form.addRow("Source Vessel", self.source_vessel_input)

        self.source_from_date_input = QDateEdit()
        self.source_from_date_input.setCalendarPopup(True)
        self.source_from_date_input.setDisplayFormat("dd MMM yyyy")
        source_date = event.source_from_date if event else default_date
        self.source_from_date_input.setDate(QDate(source_date))
        form.addRow("Source From Date", self.source_from_date_input)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def draft(self) -> ScheduleEventDraft:
        terminal = self.terminal_input.text().strip()
        return ScheduleEventDraft(
            sequence_number=self.sequence_input.value(),
            port=self.port_input.text().strip(),
            terminal=terminal or None,
            event_type=self.event_type_input.text().strip(),
            arrival_at=self.arrival_input.dateTime().toPython(),
            departure_at=self.departure_input.dateTime().toPython() if self.has_departure_input.isChecked() else None,
            source=self.source_input.text().strip(),
            source_vessel_name=self.source_vessel_input.text().strip(),
            source_from_date=self.source_from_date_input.date().toPython(),
        )


class SchedulePage(QWidget):
    def __init__(
        self,
        vessel_service: VesselService,
        schedule_service: ScheduleService,
        scraper_service: ScraperService,
    ) -> None:
        super().__init__()
        self._vessel_service = vessel_service
        self._schedule_service = schedule_service
        self._scraper_service = scraper_service
        self._thread_pool = QThreadPool.globalInstance()
        self._scrape_running = False
        self._cancel_event: Event | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)
        layout.addWidget(PageHeader("Schedule", "Fetch, preview, and confirm vessel schedule updates."))

        controls = QFrame()
        controls.setObjectName("panel")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(18, 16, 18, 16)
        controls_layout.setSpacing(14)

        self.vessel_label = QLabel("Vessel: Not configured")
        self.vessel_label.setObjectName("fieldLabel")
        controls_layout.addWidget(self.vessel_label, 1)

        controls_layout.addWidget(QLabel("From Date"))
        self.from_date_edit = QDateEdit()
        self.from_date_edit.setCalendarPopup(True)
        self.from_date_edit.setDisplayFormat("dd MMM yyyy")
        tomorrow = QDate.currentDate().addDays(1)
        self.from_date_edit.setDate(tomorrow)
        controls_layout.addWidget(self.from_date_edit)

        self.update_button = QPushButton("Update Schedule")
        self.update_button.setObjectName("primaryButton")
        self.update_button.clicked.connect(self._start_update)
        controls_layout.addWidget(self.update_button)
        layout.addWidget(controls)

        edit_controls = QFrame()
        edit_controls.setObjectName("panel")
        edit_controls_layout = QHBoxLayout(edit_controls)
        edit_controls_layout.setContentsMargins(18, 12, 18, 12)
        edit_controls_layout.setSpacing(10)
        self.add_button = QPushButton("Add Event")
        self.add_button.clicked.connect(self._add_event)
        self.edit_button = QPushButton("Edit Event")
        self.edit_button.clicked.connect(self._edit_event)
        self.delete_button = QPushButton("Delete Event")
        self.delete_button.clicked.connect(self._delete_event)
        edit_controls_layout.addWidget(self.add_button)
        edit_controls_layout.addWidget(self.edit_button)
        edit_controls_layout.addWidget(self.delete_button)
        edit_controls_layout.addStretch()
        layout.addWidget(edit_controls)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("mutedText")
        layout.addWidget(self.status_label)

        self.empty_state = QLabel("No schedule saved yet. Choose a From Date and update the schedule to preview results.")
        self.empty_state.setObjectName("emptyState")
        layout.addWidget(self.empty_state)

        self.table_model = ScheduleTableModel()
        self.table_view = QTableView()
        self.table_view.setModel(self.table_model)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table_view, 1)

        self.refresh()

    def refresh(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            self.vessel_label.setText("Vessel: Not configured")
            self.update_button.setEnabled(False)
            self.add_button.setEnabled(False)
            self.edit_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            self.table_model.set_rows([])
            self._set_empty_state(True)
            self.status_label.setText("Configure a vessel before updating the schedule.")
            return

        self.vessel_label.setText(f"Vessel: {vessel.name}  |  IMO {vessel.imo}")
        self.update_button.setEnabled(not self._scrape_running)
        self.add_button.setEnabled(True)
        self.edit_button.setEnabled(True)
        self.delete_button.setEnabled(True)
        events = self._schedule_service.list_events(vessel.id)
        self.table_model.set_rows(events)
        self._set_empty_state(len(events) == 0)
        if not self._scrape_running:
            self.status_label.setText(f"{len(events)} saved schedule events.")

    def _set_empty_state(self, is_empty: bool) -> None:
        self.empty_state.setVisible(is_empty)
        self.table_view.setVisible(not is_empty)

    def _start_update(self) -> None:
        if self._scrape_running:
            return
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            QMessageBox.warning(self, "Vessel required", "Configure a vessel before updating the schedule.")
            return

        selected_date = self.from_date_edit.date().toPython()
        self._scrape_running = True
        self._cancel_event = Event()
        self.update_button.setEnabled(False)
        self.status_label.setText("Starting schedule update...")

        worker = ScrapeWorker(self._scraper_service, vessel.name, selected_date, self._cancel_event)
        worker.signals.progress.connect(self._scrape_progress)
        worker.signals.success.connect(self._scrape_success)
        worker.signals.failure.connect(self._scrape_failure)
        self._thread_pool.start(worker)

    @Slot(str, str)
    def _scrape_progress(self, stage: str, message: str) -> None:
        self.status_label.setText(f"{stage}: {message}")

    @Slot(object)
    def _scrape_success(self, candidates: object) -> None:
        self._scrape_running = False
        self.update_button.setEnabled(True)
        candidate_rows = list(candidates)
        self.status_label.setText(f"Preview ready with {len(candidate_rows)} events.")
        dialog = SchedulePreviewDialog(candidate_rows, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.status_label.setText("Schedule update cancelled. Existing saved schedule was not changed.")
            return

        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            QMessageBox.warning(self, "Vessel required", "The active vessel is no longer configured.")
            self.status_label.setText("Schedule update could not be confirmed.")
            return
        try:
            events = self._schedule_service.confirm_schedule_update(vessel.id, candidate_rows)
        except Exception as exc:
            QMessageBox.critical(self, "Schedule update failed", str(exc))
            self.status_label.setText("Schedule update failed. Existing saved schedule was preserved.")
            return
        self.table_model.set_rows(events)
        self._set_empty_state(len(events) == 0)
        self.status_label.setText(f"Schedule updated with {len(events)} events.")

    @Slot(str)
    def _scrape_failure(self, message: str) -> None:
        self._scrape_running = False
        self.update_button.setEnabled(True)
        self.status_label.setText("Schedule update failed.")
        QMessageBox.critical(self, "Schedule update failed", message)

    def _active_vessel_or_warn(self):
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            QMessageBox.warning(self, "Vessel required", "Configure a vessel before editing the schedule.")
        return vessel

    def _selected_event_or_warn(self) -> ScheduleEvent | None:
        selected_rows = self.table_view.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(self, "Select an event", "Select a schedule event first.")
            return None
        row = self.table_model.row_at(selected_rows[0].row())
        if not isinstance(row, ScheduleEvent):
            QMessageBox.information(self, "Select an event", "Select a saved schedule event first.")
            return None
        return row

    def _add_event(self) -> None:
        vessel = self._active_vessel_or_warn()
        if vessel is None:
            return
        row_count = self.table_model.rowCount()
        dialog = ScheduleEventDialog(
            max_sequence=row_count + 1,
            source_vessel_name=vessel.name,
            default_date=self.from_date_edit.date().toPython(),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            events = self._schedule_service.create_event(vessel.id, dialog.draft())
        except Exception as exc:
            QMessageBox.warning(self, "Event not saved", str(exc))
            return
        self._apply_events(events, "Schedule event added.")

    def _edit_event(self) -> None:
        vessel = self._active_vessel_or_warn()
        if vessel is None:
            return
        event = self._selected_event_or_warn()
        if event is None:
            return
        dialog = ScheduleEventDialog(
            max_sequence=max(1, self.table_model.rowCount()),
            source_vessel_name=vessel.name,
            default_date=self.from_date_edit.date().toPython(),
            event=event,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            events = self._schedule_service.update_event(vessel.id, event.id, dialog.draft())
        except Exception as exc:
            QMessageBox.warning(self, "Event not saved", str(exc))
            return
        self._apply_events(events, "Schedule event updated.")

    def _delete_event(self) -> None:
        vessel = self._active_vessel_or_warn()
        if vessel is None:
            return
        event = self._selected_event_or_warn()
        if event is None:
            return
        if QMessageBox.question(
            self,
            "Delete schedule event",
            f"Delete sequence {event.sequence_number} - {event.port}?",
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            events = self._schedule_service.delete_event(vessel.id, event.id)
        except Exception as exc:
            QMessageBox.warning(self, "Event not deleted", str(exc))
            return
        self._apply_events(events, "Schedule event deleted.")

    def _apply_events(self, events: list[ScheduleEvent], message: str) -> None:
        self.table_model.set_rows(events)
        self._set_empty_state(len(events) == 0)
        self.status_label.setText(message)
