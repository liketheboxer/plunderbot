# PlunderBot

**P**irate **L**ogistics, **U**nsolicited **N**autical **D**rivel & **E**vent **R**eminders: the bright, bubbly robot butler of Brimstone Hill Fortress.

A Python Discord bot (discord.py 2.x) that runs fenced in under Exocomp and reports telemetry to The Magical Samurai. Version 0.1.0 is **phase 1 of 8, "Hull"**: the foundation plus Birthdays. The full plan is the *PlunderBot Scope & Design* doc.

## Commands

| Command | Who | What it does |
|---|---|---|
| `/plunderbot` | Everyone | Meet the butler; shows the version |
| `/birthday set` | Everyone | Save your month and day (no year). After the first hour, you can change it once every 30 days |
| `/birthday mine` | Everyone | See what PlunderBot has for you |
| `/birthday remove` | Everyone | Take your birthday off the ledger |
| `/birthday upcoming` | Everyone | The next 10 birthdays (shows names, pings nobody) |
| `/admin settings` | Manage Server | Show this server's settings |
| `/admin timezone` | Manage Server | Server time zone (default America/Los_Angeles) |
| `/admin birthdays channel` | Manage Server | Where toasts are posted; this turns toasts on |
| `/admin birthdays hour` | Manage Server | Hour the toast goes out, 0 to 23 (default 9 = 9:00 AM) |
| `/admin birthdays role` | Manage Server | Optional role worn for the day. Must be cosmetic, below PlunderBot's role, and below yours |
| `/admin birthdays off` | Manage Server | Stop toasts |

`/admin` commands are only shown to members with **Manage Server**. To give them to the Quartermaster role instead, go to **Server Settings › Integrations › PlunderBot**.

## Setting it up

### 1. Discord application

1. In the [Discord Developer Portal](https://discord.com/developers/applications), create an application named **PlunderBot** and give it an avatar.
2. **Bot** tab: turn on **Server Members Intent**. Leave Presence and Message Content off for now.
3. **Bot** tab: **Reset Token** and keep the token for step 3. Never paste it in chat or commit it.
4. **OAuth2 › URL Generator**: scopes `bot` and `applications.commands`; permissions **View Channels**, **Send Messages**, **Embed Links**, **Manage Roles**, **Manage Channels**, **Manage Events**. Open the URL and add PlunderBot to Brimstone Hill Fortress.
5. In **Server Settings › Roles**, drag PlunderBot's role **above** any role it should hand out (the birthday role now, the Colours roles later).

### 2. GitHub

Create an empty repo (private is fine) and push this folder:

```bash
git init
git add .
git commit -m "PlunderBot 0.1.0: hull and birthdays"
git branch -M main
git remote add origin git@github.com:<owner>/plunderbot.git
git push -u origin main
git tag v0.1.0 && git push --tags
```

### 3. Exocomp

Install it as a new unit in the **Brimstone** department, with Twiddles as Chief:

- **Repo:** `<owner>/plunderbot`, branch `main` (or tag `v0.1.0`)
- **Build:** Dockerfile (the repo's own; it carries the health check)
- **Secret:** `DISCORD_TOKEN`
- **Settings (optional):** `DEFAULT_TIMEZONE` (defaults to `America/Los_Angeles`), `LOG_LEVEL`
- **Memory:** the default 512 MB is plenty

Exocomp supplies `EXOCOMP_URL` and `EXOCOMP_TELEMETRY_TOKEN`, so telemetry needs no setup. Slash commands sync globally on start, and can take a few minutes to appear the first time.

The bot keeps its database at `/data/plunderbot.db` and runs as user 10001. On a named volume that just works; if the unit ever uses a host folder instead, that folder must be owned by 10001.

### 4. First run on the server

```
/admin timezone America/Los_Angeles
/admin birthdays channel #general
/admin birthdays hour 9
/admin birthdays role @Birthday Pirate      (optional)
/birthday set
```

## Telemetry

On top of Exocomp's standard numbers (latency, servers, commands, errors), PlunderBot reports the `birthdays_on_file` gauge. Errors in the birthday announcer are reported as `birthday-announcer`.

## Developing

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m pytest -q
cp .env.example .env    # add a token for a test bot and your test server's ID as DEV_GUILD_ID
python bot.py
```

With `DEV_GUILD_ID` set, commands sync to that one server instantly instead of globally.

## Layout

| Path | What |
|---|---|
| `bot.py` | Start file: logging, telemetry, run |
| `plunderbot/bot.py` | The client, command sync, error replies, health-check file |
| `plunderbot/db.py` | SQLite in `/data` and its migrations (append only) |
| `plunderbot/voice.py` | Every member-facing line in PlunderBot's voice |
| `plunderbot/birthday_logic.py` | Date rules: leap days, next birthday, when to toast, change limits |
| `plunderbot/cogs/` | Features: `core`, `admin`, `birthdays` |
| `exocomp_telemetry.py` | Exocomp's telemetry helper, vendored |

## Rules of the ship

- Member-facing text lives in `voice.py`: upbeat butler, mild pirate cusses, original lines only. Admin replies and logs stay plain English.
- PlunderBot never pings @everyone or roles. Toasts ping only the birthday members.
- Schema changes are new entries at the end of `MIGRATIONS`; never edit one that has shipped.
- Version in `VERSION`, changes in `CHANGELOG.md`, a `vX.Y.Z` tag per release.
