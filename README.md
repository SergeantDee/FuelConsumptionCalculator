# Fuel Consumption Calculator

Version 0.2.0 is the standalone Windows desktop foundation for vessel fuel planning. It provides a dark Qt Widgets shell, persistent vessel identity, centralized runtime paths, SQLite migrations, bounded application logging, and local vessel schedule scraping with preview/confirm persistence.

## Requirements

- Windows
- Python 3.12 or newer
- PySide6
- Playwright Python package
- Microsoft Edge installed for Playwright's `msedge` browser channel

The application does not download browsers at runtime. Schedule scraping uses the locally installed Edge browser through Playwright.

## Set up and launch

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

Configure the active vessel from **Settings**. The database is created at `data/fuel_consumption_calculator.db`, and logs are written to `logs/fuel_consumption_calculator.log`.

## Schedule Updates

Open **Schedule**, choose a **From Date**, and select **Update Schedule**. The app runs the legacy-derived Maersk schedule scraper in a Qt background worker, returns normalized schedule events, and shows a preview table.

Cancel leaves the existing SQLite schedule untouched. Confirm validates the candidates and atomically replaces the active vessel schedule in SQLite.

## Test

```powershell
python -m pip install -r requirements-dev.txt
pytest
```

## Packaging preparation

The included `FuelConsumptionCalculator.spec` targets a PyInstaller onedir build:

```powershell
pyinstaller FuelConsumptionCalculator.spec
```

Writable directories are resolved beside the executable for a future onedir deployment. A onefile build is not supported by design.
