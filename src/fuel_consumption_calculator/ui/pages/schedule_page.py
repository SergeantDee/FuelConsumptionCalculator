from __future__ import annotations

import datetime as dt
from threading import Event

from PySide6.QtCore import QAbstractTableModel, QDate, QObject, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from fuel_consumption_calculator.domain.schedule import ScheduleCandidate, ScheduleEvent
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
        self.table_view.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table_view, 1)

        self.refresh()

    def refresh(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            self.vessel_label.setText("Vessel: Not configured")
            self.update_button.setEnabled(False)
            self.table_model.set_rows([])
            self._set_empty_state(True)
            self.status_label.setText("Configure a vessel before updating the schedule.")
            return

        self.vessel_label.setText(f"Vessel: {vessel.name}  |  IMO {vessel.imo}")
        self.update_button.setEnabled(not self._scrape_running)
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
