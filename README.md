# aa-fuelalert

WhatsApp or Telegram alerts for corporation structures and POS (control towers) in [Alliance Auth](https://gitlab.com/allianceauth/allianceauth) when they run low on fuel or go offline.

The app makes **no ESI calls of its own**. It reads the structure data that [allianceauth-corptools](https://github.com/Solar-Helix-Independent-Transport/allianceauth-corp-tools) already collects (Upwell structures with `fuel_expires`, state and services; POS with their fuel bay) and sends messages through the free CallMeBot APIs for [WhatsApp](https://www.callmebot.com/blog/free-api-whatsapp-messages/) and [Telegram](https://www.callmebot.com/blog/telegram-text-messages/).

## Features

- Dashboard with fuel status of all structures and POS you may see, most urgent first
- POS fuel end time calculated from the fuel bay (size, faction tier, sovereignty discount)
- Every user picks WhatsApp or Telegram and manages their own contact data and the corporations they follow
- Alerts at configurable thresholds (default 7 days, 3 days, 24 hours, 6 hours) and when fuel runs out
- One combined message per user and run, each threshold fires once per refuel cycle
- Test message button

## Setting up a channel (per user)

**Telegram**
1. Open Telegram and send `/start` to [@CallMeBot_txtbot](https://t.me/CallMeBot_txtbot).
2. Make sure you have a Telegram username (Telegram → Settings → Username).
3. In Fuel Alert choose *Telegram*, enter the username and save, then press *Send test*.

**WhatsApp**
1. Add the CallMeBot number from [callmebot.com](https://www.callmebot.com/blog/free-api-whatsapp-messages/) to your contacts. When the bot is full, the page hides the number; try again in a few days or use Telegram.
2. Send it `I allow callmebot to send me messages` and wait for your API key.
3. In Fuel Alert choose *WhatsApp*, enter your number (`+49…`) and the key, save, then press *Send test*.

## Requirements

- Alliance Auth 5.x
- allianceauth-corptools 3.4+ with **corporation audits** for the corps you want to watch:
  - **Structures:** a token with the *Structures* scope from a character with the **Director** or **Station Manager** role.
  - **POS:** a token with the *Starbases* scope from a character with the **Director** role (EVE only gives starbase details to directors).
- The Corptools corporation update must run regularly, otherwise refuels and new structures are never seen. If your `local.py` has no entry for it yet:

  ```python
  CELERYBEAT_SCHEDULE["corptools_update_all_corps"] = {
      "task": "corptools.tasks.update_all_corps",
      "schedule": crontab(minute=30),
  }
  ```

## Installation

1. Install the package into your Auth virtual environment:

   ```bash
   pip install git+https://github.com/Zer0C0ol1337/aa-fuelalert.git@v0.3.0
   ```

2. Add the app and the periodic task to `local.py`:

   ```python
   INSTALLED_APPS += ["fuelalert"]

   CELERYBEAT_SCHEDULE["fuelalert_check_fuel_levels"] = {
       "task": "fuelalert.tasks.check_fuel_levels",
       "schedule": crontab(minute="*/10"),
   }
   ```

3. Run migrations and restart:

   ```bash
   python manage.py migrate fuelalert
   ```

   The app ships no static files, `collectstatic` is not needed.

   Then restart your Auth web and worker processes (e.g. `supervisorctl restart myauth:` or the Docker containers).

4. Give the permission `fuelalert | general | Can access Fuel Alert` to the groups or states that should use the app.

**Note:** On the first run, structures that are already below a threshold or out of fuel send one alert each.

## Permissions and visibility

| Permission | Effect |
|---|---|
| `fuelalert.basic_access` | Shows the menu entry, the dashboard and the user's own alert settings |

Which **structures** a user sees and can subscribe to is decided entirely by the Corptools corporation permissions, the same as on the Corptools structures page:

| Corptools permission | Visible corporations |
|---|---|
| none | none (the dashboard stays empty) |
| `corptools.own_corp_manager` | own main's corporation |
| `corptools.show_if_director` | corps where the user has a director character |
| `corptools.alliance_corp_manager` | all corps of the own alliance |
| `corptools.state_corp_manager` | all corps of members in the same state |
| `corptools.global_corp_manager` | all corps |
| `corptools.holding_corp_structures` | adds the holding corps from the Corptools config |

Superusers see everything. Permissions are checked again every time a message is sent, so users who lose access stop receiving alerts.

## Task

| Task | What it does |
|---|---|
| `fuelalert.tasks.check_fuel_levels` | Compares every Corptools structure and POS with the thresholds, stores which alerts were sent and queues messages. Database only, no ESI. Recommended every 10 minutes. |
| `fuelalert.tasks.send_message` | Sends one message over the user's channel (WhatsApp or Telegram), retried 3 times on network errors. Queued by the task above and by the test button. |

## Settings

All optional, set in `local.py`:

| Setting | Default | Meaning |
|---|---|---|
| `FUELALERT_THRESHOLDS_HOURS` | `[168, 72, 24, 6]` | Hours of fuel left that trigger an alert |
| `FUELALERT_ALERT_OFFLINE` | `True` | Alert when a structure runs out of fuel or has none, or a POS is offline |
| `FUELALERT_IGNORE_STATES` | `["anchoring", "anchor_vulnerable", "unanchored"]` | Structure states without alerts |
| `FUELALERT_POS_ENABLED` | `True` | Watch POS as well |
| `FUELALERT_POS_SOV_DISCOUNT` | `True` | Count 25 % less fuel where the owner's alliance has a sovereignty hub |
| `FUELALERT_POS_IGNORE_STATES` | `["unanchoring", "reinforced"]` | POS states without alerts |
| `FUELALERT_REARM_MARGIN_HOURS` | `2` | Fuel must rise this far above a threshold before it can fire again |
| `FUELALERT_SEND_DELAY_SECONDS` | `5` | Delay between messages to different users |
| `FUELALERT_STALE_HOURS` | `24` | Corptools data older than this is marked on the dashboard |
| `FUELALERT_CALLMEBOT_URL` | `https://api.callmebot.com/whatsapp.php` | CallMeBot WhatsApp endpoint |
| `FUELALERT_CALLMEBOT_TELEGRAM_URL` | `https://api.callmebot.com/text.php` | CallMeBot Telegram endpoint |
| `FUELALERT_HTTP_TIMEOUT` | `30` | HTTP timeout in seconds |

## How alerts work

- Alerts are based on `fuel_expires` from Corptools. The time is absolute, so the remaining fuel is always current, even between Corptools updates.
- A structure whose `fuel_expires` has passed (or that has none) counts as out of fuel and sends one offline alert.
- Each threshold fires once. After refueling above the threshold it is armed again.
- Structures of the same run are combined into one message per user.

## How POS fuel is calculated

ESI reports only what is in a POS fuel bay, not when it runs dry. The app calculates it:

| Tower | Fuel blocks per hour |
|---|---|
| Small | 10 |
| Medium | 20 |
| Large | 40 |

- Faction towers use less: tier 1 (Angel, Blood, Guristas, Sansha, Serpentis) 10 % less, tier 2 (Dark Blood, Domination, Dread Guristas, True Sansha, Shadow) 20 % less.
- 25 % less when the owner's alliance holds sovereignty in the system. The app treats a system as "own sov" when Corptools has a sovereignty hub there for an audited corp of the same alliance. Hubs of corps without a Corptools audit are not seen.
- The time is counted from the last Corptools starbase update. Strontium is not watched.
- Source of the rates: [EVE University – POS Setup](https://wiki.eveuniversity.org/POS_Setup). The dashboard shows the rate used per POS; compare it once with the game.

## Data protection

The app stores per user: the chosen channel, the phone number and CallMeBot API key (WhatsApp) or the Telegram username, all in plain text because they are needed to send, plus the chosen corporations. Phone numbers are masked in the admin list; contact data is never written to the log. Messages are sent through CallMeBot, an external free service. Users can delete their data at any time with the delete button on the dashboard.

## Updating

```bash
pip install -U git+https://github.com/Zer0C0ol1337/aa-fuelalert.git@<tag>
python manage.py migrate fuelalert
```

Then restart web and workers.

## Uninstalling

1. Remove the `fuelalert_check_fuel_levels` entry from `CELERYBEAT_SCHEDULE`.
2. Remove the tables and permissions:

   ```bash
   python manage.py migrate fuelalert zero
   ```

3. Remove `"fuelalert"` from `INSTALLED_APPS`, then `pip uninstall aa-fuelalert` and restart.
4. If left over, delete the content types of the app only: in the Django shell `ContentType.objects.filter(app_label="fuelalert").delete()`.

## License

GPL-3.0-or-later
