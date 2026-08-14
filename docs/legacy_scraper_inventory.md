# Legacy schedule scraper technical inventory

## Scope and inspection basis

This is a read-only inventory of `C:\Users\danie\Documents\Projects\Active\FOapp`. No scraper code is included in v0.1.0 of the new application. The findings below come from the actual source at legacy Git HEAD `4d3eb96398d379b9beca39e9a7551e8f5052087b`. The legacy worktree already contained unrelated modified and untracked web/voyage-plan files before this inspection.

## True desktop execution flow

The original desktop path is:

```text
FOapp/main.py: VesselApp.trigger_scraper()
    -> FOapp/scraper.py: run_scraper_job()
        -> for each requested month (default: 3)
            -> fetch_schedule_source()
                -> sync_playwright()
                -> Chromium launcher using installed Microsoft Edge channel
                -> _fetch_month_source()
                    -> open Maersk vessel schedules page
                    -> select vessel and From Date
                    -> submit search
                    -> read rendered result-card text
                    -> parse_schedule_source()
            -> normalize_schedule_rows()
    -> VesselApp.restructure_to_wide_format()
    -> VesselApp.merge_historical_data()
    -> pandas.DataFrame.to_sql("schedule", if_exists="replace")
    -> VesselApp.populate_table()
```

The expected names `trigger_scraper()` and `run_scraper_job()` are therefore correct for the desktop application. `trigger_scraper()` is the UI entry point, while `run_scraper_job()` is the reusable scraping entry point. The scraper can also be run directly through the `if __name__ == "__main__"` block in `scraper.py`.

The later web shell does not define a separate scraper engine. Its path is `ScheduleUpdateService._run_fetch_job()` -> `PlaywrightScheduleProvider.fetch_schedule()` -> the same `scraper.fetch_schedule_source()`. It adds worker-thread job state, cancellation, diagnostics, preview, comparison, confirmation, backup, and transactional repository behavior around the shared browser function.

## Relevant legacy source files

| File | Responsibility | Future relevance |
|---|---|---|
| `scraper.py` | Playwright browser session, site interaction, rendered-text parsing, raw-row normalization, multi-month orchestration, cancellation and optional diagnostics | Primary source to transplant selectively |
| `main.py` | Desktop trigger plus `restructure_to_wide_format`, `merge_historical_data`, and route-specific default helper functions | Logic reference only; do not transplant the UI class |
| `fo_core/schedule/normalization.py` | UI-independent version of raw-port-to-wide-row restructuring, defaults, manual-field preservation, and historical merge | Strongest reference for extracting future domain logic |
| `fo_core/schedule/validation.py` | Legacy date parsing and schedule validation helpers | Select only helpers required by the future schedule boundary |
| `fo_core/schedule/models.py` | Raw/source/wide row contracts and preview/job models | Contract reference; avoid importing Pydantic solely for these models |
| `fo_web/providers/schedule/playwright_provider.py` | Adapter around `fetch_schedule_source`, multi-month loop, headless/visible mode, cancellation and error mapping | Design reference; do not port the FastAPI-facing adapter wholesale |
| `fo_web/providers/schedule/base.py` | Provider result/error contract | Design reference only |
| `fo_web/services/schedule_update_service.py` | Background execution, preview construction, normalization/merge and confirmation workflow | Design reference for a later Qt worker/service, not v0.2 copy material |
| `fo_web/config.py` | Provider URL, Edge channel, browser mode, month count, fetch/diagnostics directories | Configuration reference only |
| `fo_web/repositories/schedule_repository.py` | Schedule persistence, fingerprint and backup behavior | Later persistence reference; outside the scraper itself |
| `tests/test_fastapi_foundation.py` | Existing test coverage that stubs or exercises schedule provider behavior | Characterization-test reference |

## Browser behavior and inputs

- Default URL: `https://www.maersk.com/schedules/vesselSchedules`.
- Default browser channel: `msedge` through `playwright.chromium.launch(channel="msedge")`.
- Desktop mode is visible (`headless=False`). The web wrapper supports visible/headless/automatic modes, with visible fallback flags for several headless failures.
- Default timeout is 60 seconds. Vessel option waits use 15 seconds; cookie interactions use shorter 3–8 second waits.
- Desktop default vessel is hard-coded as `Maersk Labrea`. The default starting date is tomorrow and the default range is three monthly searches. A future integration must pass the vessel configured in SQLite and must not retain the hard-coded vessel default.
- The browser is opened and closed once per requested month, not once for the full three-month job.
- Site interaction relies on accessible labels (`Vessel name`, `Date from`, `Search`), an option ID derived from the upper-cased vessel name, and result selector `[data-test="vessel-title-arriving"]`.
- Cookie handling first tries the `coi` decline button, can remove the overlay with JavaScript as fallback, and optionally accepts a secondary `Accept All` banner.
- There is no credential, cookie-file, token, CAPTCHA, external API, or downloaded schedule-file input in the working scraper path.

## Outputs and transformations

`parse_schedule_source()` scans rendered text lines. Each line beginning `Arrival -` produces a raw dictionary with exactly `Port`, `Arrival`, and `Departure`. Port is inferred from two lines earlier, and dates from fixed following-line positions.

`normalize_schedule_rows()` converts raw rows to a pandas DataFrame, parses `%d %b %Y %H:%M` timestamps, removes duplicates on all three fields, sorts by arrival, and returns the DataFrame. No CSV is created by the desktop flow.

`VesselApp.restructure_to_wide_format()` then creates the legacy 22-column event timeline. It inserts ECA IN/OUT events around Tangier and a hard-coded list of European ports, derives pilot timestamps, and supplies route-specific defaults for pilot distance, sea distance, reefers, fuel type, SFOC and boiler consumption. The UI-independent equivalent is `fo_core.schedule.normalization.normalize_source_records()`.

`VesselApp.merge_historical_data()` reads the current on-screen schedule, preserves rows earlier than the new schedule's first arrival, restores non-empty/non-zero manual inputs by `(event type, location, occurrence number)`, concatenates new rows, and collapses adjacent duplicate ECA events. The equivalent service-layer function is `fo_core.schedule.normalization.merge_historical_data()`.

Finally, the desktop trigger replaces the complete SQLite `schedule` table with `DataFrame.to_sql(..., if_exists="replace")`. That write is not part of the scraper and should not be retained as-is.

## Temporary files and diagnostics

- The desktop `run_scraper_job()` path normally creates no CSV or temporary schedule file and configures no diagnostics directory.
- When a diagnostics directory is supplied, failures in vessel selection, result waiting, or parsing can create a timestamped full-page PNG and a text file containing up to 4,000 characters from the page's `main` element.
- The web wrapper uses `runtime/schedule_update/fetches/<job-id>` and `runtime/schedule_update/diagnostics`. It cleans ordinary job files after completion but preserves diagnostics directories. Rendered source rows are serialized in memory for a SHA-256 fingerprint; the advertised `.txt` source filename is metadata, not necessarily a persisted source file.
- The provider can also return a CSV, but the current Playwright provider returns `source_rows` and `csv_path=None`. CSV upload/import is a separate fallback workflow, not part of the proven scraper.

## Direct dependencies

The shared `scraper.py` directly requires:

- `playwright` synchronous Python API;
- Microsoft Edge installed and addressable through Playwright's `msedge` channel;
- `pandas` for the `run_scraper_job()` DataFrame boundary;
- `python-dateutil` for `relativedelta` month increments;
- Python standard library modules (`datetime`, `re`, `dataclasses`, `pathlib`, `threading`).

The legacy `desktop` dependency group also includes PyQt6, folium and PyInstaller, but none of those are required by the scraper engine itself. The future PySide6 application should not inherit PyQt6, folium, FastAPI, Jinja, Uvicorn, or the web shell. Playwright browser binaries must not be downloaded at application runtime; using the system Edge channel is the current compatible approach, with installation readiness checked during deployment.

## Recommended future transplant boundary

Transplant or adapt only:

1. The Playwright session and stage-specific error concepts from `scraper.py`.
2. `fetch_schedule_source()` and its private site-interaction, parsing, cancellation, and diagnostic helpers.
3. A UI-independent raw-row contract using standard-library dataclasses.
4. The normalization/restructure and historical-merge behavior from `fo_core/schedule/normalization.py`, after characterization tests lock down expected rows.
5. Only the date parsing and validation helpers those transformations actually need.
6. A new Qt worker/service adapter so synchronous Playwright work never blocks the GUI thread.

Consider removing pandas and python-dateutil from the scraper boundary: the browser function already returns plain row dictionaries, standard `datetime` can support month stepping, and repository/domain layers can consume dataclasses. Keep pandas only if characterization demonstrates that its parsing/deduplication behavior is operationally significant.

Do not transplant:

- `main.py` or the `VesselApp` UI/calculation class;
- the legacy SQLite database or its full schema;
- direct `to_sql(..., if_exists="replace")` persistence;
- FastAPI routers, templates, static assets, dependency wiring, Uvicorn, or Jinja;
- folium/map code, fuel calculations, voyage planning, soundings, tank tables, reports, or unrelated settings;
- the web CSV-upload workflow unless separately approved;
- the hard-coded vessel name, legacy relative database path, or UI-table-dependent merge method;
- Pydantic solely to carry schedule records in this Qt application.

## Technical risks to address before integration

- The external page structure and labels can change. The positional rendered-text parser and provider-specific selector are brittle and require fixture-based characterization tests plus readable diagnostics.
- Synchronous Playwright blocks the calling thread. The legacy desktop trigger runs it directly from a button handler and can freeze the UI; the new application needs a worker thread, progress events, cancellation and guaranteed UI reset.
- Browser launch assumes a compatible installed Edge. Packaging Playwright Python modules does not guarantee that the Edge channel is available or policy permits automation.
- The current desktop trigger has no robust try/finally around its disabled button state or database write.
- Three months currently means three separate browser launches and repeated page setup, increasing latency and failure exposure.
- Route/ECA/default-distance rules are operational business data embedded in code. They should be tested and owned by the domain layer, not treated as generic scraping helpers.
- Manual-value preservation keyed by event/location occurrence can associate values incorrectly if the provider inserts, removes, or reorders repeated port calls.
- Full-table replacement is too risky for the new repository architecture. A later sprint should define preview, backup, transaction and rollback behavior before schedule persistence is enabled.
- Visible mode appears to be the proven operational path. Headless behavior should not be assumed equivalent until separately verified.
