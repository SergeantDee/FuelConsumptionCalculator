# Scraper Architecture

## Boundary

The v0.2 scraper is a local application capability. It is not a web service and it does not import or depend on the legacy `FOapp` repository at runtime.

The runtime path is:

```text
Schedule UI
    -> ScraperService
    -> Qt background worker
    -> scraper provider
    -> normalized ScheduleCandidate objects
    -> preview dialog
    -> ScheduleService
    -> ScheduleRepository
    -> SQLite
```

The scraper never writes SQLite directly. Qt widgets never call SQLite directly.

## Legacy-Derived Components

The Playwright provider, cookie handling, vessel option selection, result selector, and rendered-text parser are materially derived from `FOapp/scraper.py`. The new implementation keeps the proven Maersk URL, visible Microsoft Edge browser channel, accessible labels, and `[data-test="vessel-title-arriving"]` result selector.

The new normalization layer keeps the legacy raw-row meaning: `Port`, `Arrival`, and `Departure`, parsed with `%d %b %Y %H:%M`, deduplicated, sorted by arrival time, and converted into structured schedule candidates.

The legacy 22-column fuel-planning timeline, route defaults, historical manual merge, FastAPI/web workflow, CSV upload path, maps, and direct full-table replacement were deliberately not transplanted for v0.2.

## Worker Model

`SchedulePage` starts a `QRunnable` through `QThreadPool`. The worker calls `ScraperService.scrape_schedule()` and emits progress, success, or failure signals. UI widgets are updated only from the main Qt thread.

Duplicate runs are prevented while a scrape is active. Failures are logged by `ScraperService` and surfaced to the user through the Schedule page.

## Inputs and Outputs

Inputs:

- configured active vessel name
- selected From Date from `QDateEdit`
- static provider URL, Edge channel, selectors, and timeout

Output:

- `list[ScheduleCandidate]`, containing sequence, port, event type, arrival/departure datetimes, source, vessel name, and source From Date

The normal pytest suite uses mocked provider results and does not require browser or internet access.

## Preview and Transaction

Scraped candidates are displayed in `SchedulePreviewDialog`. Cancel performs no database write.

Confirm calls `ScheduleService.confirm_schedule_update()`, which validates the candidate list and asks `ScheduleRepository` to replace the active vessel schedule inside one SQLite transaction. If any insert fails, the database rollback preserves the previous schedule.

## Known Risks

The Maersk page selectors and rendered-text line positions are brittle because they depend on an external site. Diagnostics are available from the provider when a diagnostics directory is configured.

Browser automation assumes Microsoft Edge is installed and policy allows Playwright to launch the `msedge` channel. The app packages Playwright as a dependency but does not download browsers at runtime.

Route rules and ECA/default-distance behavior remain embedded in the legacy planning layer and are intentionally deferred. They need their own tested domain design before consumption and ROB features are added.
