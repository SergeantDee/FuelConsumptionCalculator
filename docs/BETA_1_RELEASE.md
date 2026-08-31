# Beta 1 Release Preparation

Target display version: `1.4.0-beta.1`. The Python package version is the PEP 440 equivalent `1.4.0b1`.

Build from the repository root only after the release-readiness checks pass:

```powershell
.\.venv\Scripts\pyinstaller.exe --clean --noconfirm --workpath beta_build --distpath beta_dist FuelConsumptionCalculator.spec
```

The ONEDIR result will be `beta_dist\FuelConsumptionCalculator-1.4.0-beta.1\`, containing `FuelConsumptionCalculator.exe` and `_internal\`. The spec deliberately has no `datas` entries: do not add `data\`, `logs\`, `backups\`, `exports\`, or a development database to the build.

## Post-build smoke test

1. Start the executable on a machine without Python or an IDE.
2. Confirm a fresh `data\fuel_consumption_calculator.db` is created at schema v19 with no vessel, schedule, ROB, tanks, batches, soundings, transfers, bunker plans, or changeovers.
3. Create a vessel and settings; close and reopen to verify persistence.
4. Create a simple schedule, configure Performance, enter Actual ROB, and verify voyage/consumption projection.
5. Create a fuel changeover; configure a tank, batch, calibration, and sounding survey.
6. Exercise Consumption Tanks, Internal Transfer, Bunker Planner/Receiving Tanks/Max Lift, bunker confirmation, and Bunker Distribution.
7. Close and reopen; verify all newly created state persists, no development data appears, and the log has no critical/raw exception.
