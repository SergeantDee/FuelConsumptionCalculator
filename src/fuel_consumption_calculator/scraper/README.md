# Schedule scraper subsystem

The v0.2.0 scraper subsystem is self-contained in this package. It adapts the
proven Maersk/Playwright browser flow from the legacy FO scraper without
importing the legacy repository at runtime.

The scraper returns structured schedule candidates only. SQLite persistence is
handled later by the schedule service/repository after preview confirmation.
