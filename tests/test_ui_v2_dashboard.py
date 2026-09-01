from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from fuel_consumption_calculator.app import build_main_window
from fuel_consumption_calculator.paths import AppPaths
from fuel_consumption_calculator.ui_v2.pages.dashboard_page import DashboardV2


def _app():
    return QApplication.instance() or QApplication([])


class _NoVesselService:
    def get_active_vessel(self):
        return None


class _VesselService:
    def get_active_vessel(self):
        return SimpleNamespace(id=7, name="Test Vessel", imo="1234567")


class _ScheduleService:
    def __init__(self, events=()): self.events = events
    def list_events(self, vessel_id): return self.events


def _page(vessel_service, events=()):
    _app()
    return DashboardV2(vessel_service, _ScheduleService(events), object(), object(), object())


def test_dashboard_v2_constructs_with_deliberate_fresh_state():
    page = _page(_NoVesselService())
    assert page.vessel_name_value.text() == "Not configured"
    assert page.schedule_empty.isVisible() or page.schedule_table.rowCount() == 0
    assert set(page._rob_cards) == {"ULSFO", "VLSFO", "MDO"}
    assert all(card.value.text() == "— MT" for card in page._rob_cards.values())


def test_dashboard_v2_schedule_preview_is_capped_and_has_no_source_column():
    now = datetime.now(timezone.utc)
    events = [SimpleNamespace(event_type="Port Call", port=f"Port {index}", effective_arrival_at=now + timedelta(days=index), effective_departure_at=now + timedelta(days=index, hours=8)) for index in range(7)]
    page = _page(_VesselService(), events)
    assert page.vessel_name_value.text() == "Test Vessel"
    assert page.schedule_table.rowCount() == 6
    assert [page.schedule_table.horizontalHeaderItem(index).text() for index in range(page.schedule_table.columnCount())] == ["Event", "Port", "Arrival", "Departure", "Status"]


def test_dashboard_v2_open_voyage_signal_is_exposed():
    page = _page(_NoVesselService())
    received = []
    page.open_voyage_requested.connect(lambda: received.append(True))
    page.open_voyage_button.click()
    assert received == [True]


def test_main_window_v2_sidebar_routes_and_clock_controls(tmp_path):
    app = _app()
    window = build_main_window(AppPaths(tmp_path / "v2-shell"))
    assert type(window).__name__ == "MainWindowV2"
    assert window.page_stack.currentWidget() is window.dashboard_page
    assert len(window.navigation_buttons) == 7
    window.select_page(2)
    assert window.page_stack.currentWidget() is window.voyage_page
    before = window._vessel_time_offset_minutes
    window.vessel_time_plus_button.click()
    assert window._vessel_time_offset_minutes == before + 60
    window.close()
    app.processEvents()
