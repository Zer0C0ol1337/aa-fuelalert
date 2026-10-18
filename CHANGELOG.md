# Changelog

All notable changes to this project are documented in this file.

## [0.3.0] - 2026-10-18

### Added

- POS (control towers) are watched too. ESI only reports a POS's fuel bay, so the end time is calculated from the fuel blocks: small 10, medium 20, large 40 blocks per hour, faction towers 10 % (tier 1) or 20 % (tier 2) less, 25 % less when the owner's alliance has a sovereignty hub in the system (from Corptools hub data)
- Dashboard table "POS fuel (calculated)" with fuel blocks, blocks per hour and a "Sov −25%" marker, so the rate can be compared with the game
- Offline POS send an offline alert; reinforced and unanchoring POS are skipped
- Settings `FUELALERT_POS_ENABLED`, `FUELALERT_POS_SOV_DISCOUNT`, `FUELALERT_POS_IGNORE_STATES`

### Changed

- Alerts for structures and POS are sorted together, most urgent first

## [0.2.0] - 2026-10-18

### Added

- Telegram as a second alert channel (via CallMeBot's free Telegram API, `@CallMeBot_txtbot`). Every user picks WhatsApp or Telegram in their settings
- Setting `FUELALERT_CALLMEBOT_TELEGRAM_URL`

### Changed

- Settings card only shows the fields of the selected channel
- Phone number and WhatsApp key are only required when WhatsApp is selected; existing settings stay on WhatsApp

## [0.1.0] - 2026-10-18

### Added

- Dashboard with the fuel status of all visible corporation structures (data from Corptools)
- Self-service WhatsApp settings per user (phone number, CallMeBot API key, corporations to follow)
- Celery task `fuelalert.tasks.check_fuel_levels`: alerts at configurable fuel thresholds (default 168/72/24/6 hours) and when a structure runs out of fuel
- One combined message per user and run, no duplicate alerts per threshold until the structure is refueled
- Test message button, retry on network errors
- Visibility follows the Corptools corporation permissions
