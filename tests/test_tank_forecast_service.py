from datetime import datetime, timedelta, timezone

from fuel_consumption_calculator.domain.tank_forecast import FuelDepletionInterval, TankForecast
from fuel_consumption_calculator.services.tank_forecast_service import TankForecastService


def test_plan_completion_passes_existing_intervals_and_returns_forecasts(monkeypatch):
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    intervals = [FuelDepletionInterval(start, start + timedelta(hours=10), {"VLSFO": 10.0})]
    expected = [TankForecast(1, "VLSFO", start, 10.0, 5.0, 5.0, active_phase_sequence=1)]

    class Tanks:
        def __init__(self):
            self.received = None

        def predict_tank_rob_at(self, vessel_id, target_utc, received_intervals):
            self.received = (vessel_id, target_utc, received_intervals)
            return expected

    tanks = Tanks()
    service = TankForecastService(tanks, None, None, None)
    monkeypatch.setattr(service, "_future_intervals", lambda vessel_id: intervals)

    assert service.predict_plan_completion(7) == expected
    assert tanks.received == (7, intervals[0].end_utc, intervals)
