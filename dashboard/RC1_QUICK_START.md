# SaltGuard RC1 quick start (Windows)

1. One-time test setup: double-click `SETUP_RC1_TEST_ENV.bat`.
2. Start Backend using `start_windows.bat` (or your established launcher).
3. Open Wokwi with `../firmware_wokwi/sketch.ino` and `../firmware_wokwi/diagram.json`; keep MASTER OFF at boot.
4. Start simulation, wait for MQTT CONNECTED and fresh telemetry, then set MASTER ON when ready.
5. Double-click `RUN_RC1_CHECK.bat`; require `RESULT: PASS`.
6. Follow `../PHASE48_DEMO_RUNBOOK.md`; record results in `../PHASE48_DEMO_SIGNOFF.md`.

The check is read-only. It does not send irrigation commands, modify DB, or operate pumps.
