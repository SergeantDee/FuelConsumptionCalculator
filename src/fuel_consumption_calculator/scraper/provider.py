from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from threading import Event
from typing import Callable

from fuel_consumption_calculator.scraper.models import (
    RESULT_CARD_SELECTOR,
    ScraperFetchMetadata,
    ScraperSessionConfig,
    ScraperSourceResult,
    ScraperStageError,
)
from fuel_consumption_calculator.scraper.normalization import parse_schedule_source


ProgressCallback = Callable[[str, str], None]


def fetch_schedule_source(
    vessel_name: str,
    start_date: dt.date,
    *,
    session_config: ScraperSessionConfig | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_event: Event | None = None,
) -> ScraperSourceResult:
    # Materially derived from FOapp/scraper.py, keeping visible Edge and Maersk selectors.
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ScraperStageError(
            "launch_browser",
            "Playwright is not installed. Install the development/runtime dependencies before updating schedules.",
        ) from exc

    config = session_config or ScraperSessionConfig()
    _report(progress_callback, "launch_browser", f"Launching {'headless' if config.headless else 'visible'} browser.")
    _check_cancel(cancel_event)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=config.headless, channel=config.browser_channel)
        context = browser.new_context()
        page = context.new_page()
        try:
            date_string = start_date.strftime("%d/%m/%Y")
            _report(progress_callback, "open_provider", "Opening Maersk vessel schedule page.")
            page.goto(config.provider_url, timeout=config.timeout_ms, wait_until="domcontentloaded")
            _report(progress_callback, "wait_for_page", "Waiting for schedule search form.")
            page.get_by_role("combobox", name="Vessel name").wait_for(timeout=config.timeout_ms)
            _dismiss_cookie_overlay(page)
            _check_cancel(cancel_event)

            _report(progress_callback, "enter_vessel", f"Selecting vessel {vessel_name}.")
            vessel_box = page.get_by_role("combobox", name="Vessel name")
            vessel_box.click()
            vessel_box.fill(vessel_name)
            _select_vessel_option(page, vessel_name, config, PlaywrightTimeoutError)
            _check_cancel(cancel_event)

            _report(progress_callback, "enter_from_date", f"Entering From Date {date_string}.")
            _dismiss_cookie_overlay(page)
            from_date = page.get_by_role("textbox", name="Date from")
            from_date.click(force=True)
            from_date.fill(date_string)
            from_date.press("Enter")
            _check_cancel(cancel_event)

            login_required = _accept_secondary_cookie_banner(page)

            _report(progress_callback, "submit_search", "Submitting schedule search.")
            _submit_search(page)
            _report(progress_callback, "wait_for_results", "Waiting for rendered schedule results.")
            result_locator = page.locator(RESULT_CARD_SELECTOR).first
            try:
                result_locator.wait_for(timeout=config.timeout_ms)
            except PlaywrightTimeoutError as exc:
                diagnostics_path, html_fragment_path = _capture_diagnostics(page, config, stage="wait_for_results")
                raise ScraperStageError(
                    "wait_for_results",
                    "Rendered schedule results did not appear.",
                    diagnostics_path=diagnostics_path,
                    html_fragment_path=html_fragment_path,
                ) from exc

            _report(progress_callback, "collect_page_text", "Collecting rendered schedule text.")
            raw_text = result_locator.locator("xpath=../../..").inner_text(timeout=config.timeout_ms)
            raw_rows = parse_schedule_source(raw_text)
            if not raw_rows:
                diagnostics_path, html_fragment_path = _capture_diagnostics(page, config, stage="parse_results")
                raise ScraperStageError(
                    "parse_results",
                    "Rendered schedule text did not contain any schedule rows.",
                    diagnostics_path=diagnostics_path,
                    html_fragment_path=html_fragment_path,
                )
            return ScraperSourceResult(
                vessel_name=vessel_name,
                start_date=start_date,
                raw_text=raw_text,
                raw_rows=raw_rows,
                metadata=ScraperFetchMetadata(
                    vessel_name=vessel_name,
                    browser_channel=config.browser_channel,
                    provider_url=config.provider_url,
                    browser_mode="headless" if config.headless else "visible",
                    login_required=login_required,
                    current_url=page.url,
                ),
            )
        finally:
            _report(progress_callback, "cleanup", "Closing browser context.")
            context.close()
            browser.close()


def _dismiss_cookie_overlay(page) -> None:
    try:
        page.locator('[data-test="coi-decline-all-button"]').click(timeout=8000)
        page.locator("#coiOverlay").wait_for(state="hidden", timeout=5000)
    except Exception:
        try:
            page.evaluate("document.getElementById('coiOverlay')?.remove();")
        except Exception:
            pass


def _accept_secondary_cookie_banner(page) -> bool:
    try:
        page.get_by_role("button", name="Accept All").click(timeout=3000)
        return True
    except Exception:
        return False


def _submit_search(page) -> None:
    search_button = page.get_by_role("button", name="Search")
    search_button.click(force=True)
    try:
        page.locator(RESULT_CARD_SELECTOR).first.wait_for(timeout=5000)
        return
    except Exception:
        pass
    try:
        search_button.evaluate("element => element.click()")
    except Exception:
        search_button.click(force=True)


def _select_vessel_option(page, vessel_name: str, session_config: ScraperSessionConfig, timeout_error_type: type[Exception]) -> None:
    option_id = re.sub(r"[^A-Z0-9 ]", "", vessel_name.upper()).strip()
    option_locator = page.locator(f'[id="option-{option_id}"]').get_by_role("option")
    fallback_locator = page.get_by_role("option", name=re.compile(re.escape(vessel_name), re.IGNORECASE)).first
    try:
        option_locator.wait_for(timeout=15000)
        option_locator.click(force=True, timeout=15000)
    except timeout_error_type:
        try:
            fallback_locator.wait_for(timeout=15000)
            fallback_locator.click(force=True, timeout=15000)
        except timeout_error_type as exc:
            diagnostics_path, html_fragment_path = _capture_diagnostics(page, session_config, stage="enter_vessel")
            raise ScraperStageError(
                "enter_vessel",
                f'Vessel option "{vessel_name}" did not become selectable.',
                diagnostics_path=diagnostics_path,
                html_fragment_path=html_fragment_path,
            ) from exc


def _capture_diagnostics(page, session_config: ScraperSessionConfig, *, stage: str) -> tuple[Path | None, Path | None]:
    if session_config.diagnostics_dir is None:
        return None, None
    session_config.diagnostics_dir.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    screenshot_path = session_config.diagnostics_dir / f"{timestamp}_{stage}.png"
    html_fragment_path = session_config.diagnostics_dir / f"{timestamp}_{stage}.txt"
    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
    except Exception:
        screenshot_path = None
    try:
        html_fragment = page.locator("main").inner_text(timeout=5000)
        html_fragment_path.write_text(html_fragment[:4000], encoding="utf-8")
    except Exception:
        html_fragment_path = None
    return screenshot_path, html_fragment_path


def _report(progress_callback: ProgressCallback | None, stage: str, message: str) -> None:
    if progress_callback is not None:
        progress_callback(stage, message)


def _check_cancel(cancel_event: Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ScraperStageError("cleanup", "Schedule fetch was cancelled.")
