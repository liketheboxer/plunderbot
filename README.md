# PlunderBot

**P**irate **L**ogistics, **U**nsolicited **N**autical **D**rivel & **E**vent **R**eminders: the bright, bubbly robot butler of Brimstone Hill Fortress.

A Python Discord bot (discord.py 2.x) that runs fenced in under Exocomp and reports telemetry to The Magical Samurai. Version 0.3.0 covers **phases 1 to 3 of 9**: the foundation, Birthdays, Crew Call and Voyages. The full plan is the *PlunderBot Scope & Design* doc.

## Commands

| Command | Who | What it does |
|---|---|---|
| `/plunderbot` | Everyone | Meet the butler; shows the version |
| `/timezone set` | Everyone | Save your time zone (Pacific, ET, Europe/London…) so the times you type are read correctly. `/timezone show` and `/timezone clear` too |
| `/birthday set` | Everyone | Save your month and day (no year). After the first hour, you can change it once every 30 days |
| `/birthday mine` | Everyone | See what PlunderBot has for you |
| `/birthday remove` | Everyone | Take your birthday off the ledger |
| `/birthday upcoming` | Everyone | The next 10 birthdays (shows names, pings nobody) |
| `/crew start` | Everyone | Post a crew call: pick the game, then its crew size and activity from the suggestions, plus an optional note and session name |
| `/crew rename` | Captain | Rename your session and its voice channel ("⛵ | Fort Night"); leave empty for the default |
| `/crew close` | Captain | Close your crew call and its voice channel |
| `/crew list` | Everyone | Crews mustering or sailing right now |
| `/voyage create` | Everyone | Schedule a voyage: title, date (friday, tomorrow, 10/3), time (8pm), optional game and size, seats, details, reminders (default 1 day and 1 hour before; e.g. `2d, 3h, 15m` or `none`), repeat (weekly, every 2 weeks, monthly) and length |
| `/voyage edit` | Organizer or mod | Change the title, date, time, details, reminders or seats |
| `/voyage cancel` | Organizer or mod | Cancel one voyage, or with `whole_series:True` a repeating series |
| `/voyage list` | Everyone | Upcoming voyages |
| `/admin settings` | Manage Server | Show this server's settings |
| `/admin timezone` | Manage Server | Server time zone (default America/Los_Angeles) |
| `/admin gangplank setup` | Manage Server | Intro channel, Pending role, Harbormasters role, rules and orientation channels, optional alert channel. Then `on`/`off`, `emoji`, `timing`, `status` |
| `/admin regions auto` | Manage Server | Match region roles to time zones by name and update members. Also `set` (one role → a zone), `clear` and `list` |
| `/admin birthdays channel` | Manage Server | Where toasts are posted; this turns toasts on |
| `/admin birthdays hour` | Manage Server | Hour the toast goes out, 0 to 23 (default 9 = 9:00 AM) |
| `/admin birthdays role` | Manage Server | Optional role worn for the day. Must be cosmetic, below PlunderBot's role, and below yours |
| `/admin birthdays off` | Manage Server | Stop toasts |
| `/admin crew channel` | Manage Server | Where every crew card goes, including voyages when they set sail (e.g. #looking-for-group); empty = where `/crew start` is used |
| `/admin crew category` | Manage Server | Category for crew voice channels (default: same category as the card) |
| `/admin crew cleanup` | Manage Server | Minutes an empty crew voice channel waits before it's removed (default 5; always at least 15 before anyone joins) |
| `/admin crew expire` | Manage Server | Minutes before an unfilled crew call closes (default 60) |
| `/admin crew autopings` | Manage Server | Match every game to its ping role by name (ignores case, spaces and punctuation); with `create_missing:True`, create mentionable, permission-free roles for games that have none |
| `/admin crew emoji` | Manage Server | Emoji for a game's crew cards and voice channels, for every size or one size (e.g. separate Sloop, Brigantine and Galleon emoji). Standard emoji or server emoji; `reset` restores the default |
| `/admin crew pingrole` | Manage Server | Opt-in role pinged when a crew call opens for a game (at most every 15 minutes per game) |

| `/admin voyages channel` | Manage Server | Where voyage cards are posted (e.g. #brimstone-events); empty = wherever `/voyage create` is used |

### How Gangplank works

- A newcomer joins, gets the **Pending** role, and PlunderBot welcomes them in #introductions: read the rules in #welcome, then introduce yourself and name your favorite game.
- A **Harbormaster** reacts to their introduction (or to PlunderBot's welcome for them) with **Yar** to let them aboard: Pending comes off and PlunderBot points them to #new-pirate-orientation for roles, including a region role for their time zone. **Nar** kicks them. Nobody else's reactions count.
- Newcomers who never say anything get a reminder ping after 3 days and are kicked after 7 (with a friendly DM if their DMs are open). Anyone who has introduced themselves is never kicked automatically; that's the Harbormasters' call.
- If Pending is taken off by hand, or the newcomer leaves, PlunderBot stops tracking them.
- An optional alert channel tells Harbormasters about new introductions, approvals, rejections and kicks.

### How Voyages work

- Picking a region role (e.g. North America - East) sets your time zone to match, whichever bot hands out the role. A zone you choose with `/timezone set` always wins; `/timezone clear` falls back to your region role.
- Times are typed in your own time zone (`/timezone set` or your region role), or with a zone added (`8pm ET`); without either, the server's zone is used and the confirmation says so. Every time PlunderBot shows is a Discord timestamp, which each member sees in their own local time.
- The card has **Aboard**, **Maybe** and **Can't make it**. Pressing your current answer clears it. When the seats are full, Aboard goes on a waitlist, and the first in line is moved up (and pinged) when a seat opens.
- Each voyage gets a matching Discord Event in the server's Events list, kept in step with edits and cancellations.
- Reminders ping everyone Aboard or Maybe. Reminders whose time had passed when the voyage was made are skipped.
- At the start, Aboard becomes a crew: a crew card goes up for latecomers in the crew channel (and the voyage card links to it), the voice channel opens (named after the voyage, e.g. "🚢 | Fort Night") and the crew is pinged; Maybes get a nudge. When the crew's voice channel closes, the voyage and its Discord Event end.
- Repeating voyages post the next one when the current one starts. With no game, a voyage is a general server event (🗓️) with no seat limit.
- Mods are members with Manage Events or Manage Server.

### How Crew Call works

- The card lists the seats and has **Join**, **Leave**, **Set Sail** and **Close** buttons. Buttons keep working after PlunderBot restarts.
- A full crew sets sail on its own; the captain can sail early. Sailing opens a voice channel with no user limit (spectators welcome) and pings the crew with it. Channels follow the server's style: "⛵ | Boxer's Sloop", "🪂 | Boxer's Fortnite Squad".
- Discord only allows standard emoji in channel names. A server emoji picked with `/admin crew emoji` shows on the crew card; the channel keeps the standard one.
- An empty crew voice channel is removed after the cleanup time. Unsailed calls close at the expiry time.
- One active crew per captain. Only the captain can sail; the captain or a mod (Manage Channels) can close. Crew calls can't be started in threads.
- The 15 game profiles (crew sizes and activity tags) live in `plunderbot/games.py`.
- **1 Player Hangout** is for parallel play: no crew size, the voice channel opens as soon as it's posted, anyone can join, and there's no Set Sail button. It pings the 1 Player Hangout role like any game.

`/admin` commands are only shown to members with **Manage Server**. To give them to the Quartermaster role instead, go to **Server Settings › Integrations › PlunderBot**.

## Setting it up

### 1. Discord application

1. In the [Discord Developer Portal](https://discord.com/developers/applications), create an application named **PlunderBot** and give it an avatar.
2. **Bot** tab: turn on **Server Members Intent**. Leave Presence and Message Content off for now.
3. **Bot** tab: **Reset Token** and keep the token for step 3. Never paste it in chat or commit it.
4. **OAuth2 › URL Generator**: scopes `bot` and `applications.commands`; permissions **View Channels**, **Send Messages**, **Embed Links**, **Manage Roles**, **Manage Channels**, **Manage Events**, **Kick Members**, **Read Message History**, **Add Reactions**. Open the URL and add PlunderBot to Brimstone Hill Fortress.
5. In **Server Settings › Roles**, drag PlunderBot's role **above** any role it should hand out (the birthday role now, the Colours roles later).

### 2. GitHub

1. On GitHub, create **liketheboxer/plunderbot** (private is fine). Don't add a README, .gitignore or licence; the repo must start empty.
2. In PowerShell:

```powershell
cd S:\Projects\magicalsamurai.com\plunderbot
git init
git add .
git commit -m "PlunderBot 0.1.0: hull and birthdays"
git branch -M main
git remote add origin https://github.com/liketheboxer/plunderbot.git
git push -u origin main
git tag v0.1.0
git push --tags
```

3. If the repo is private, Exocomp needs a GitHub key that can read it: a fine-grained token with **Contents: Read-only** on `plunderbot`, saved under **Sidebar › GitHub keys**. If you already have a key for other bots, add `plunderbot` to that token's repository access on GitHub instead.

### 3. Exocomp

The Brimstone department must exist first (**Departments**, Captain only), and Twiddles must be on the Crew Roster.

**Sidebar › Fabricate unit:**

| Field | Value |
|---|---|
| Unit name | PlunderBot |
| Short name | `plunderbot` (can't be changed later) |
| Department | Brimstone |
| GitHub repo | `liketheboxer/plunderbot` |
| Branch or tag | `main` |
| GitHub key | the key from step 2, if the repo is private |
| How is it built? | Repo has its own Dockerfile |
| Settings | `DEV_GUILD_ID=<Brimstone Hill's server ID>` for the first run (commands appear instantly); optional `DEFAULT_TIMEZONE`, `LOG_LEVEL` |
| Secrets | `DISCORD_TOKEN=<the bot token>` |
| Memory limit | 512 MB |

Press **Fabricate unit** and watch the job log. SUCCESS means the health check passed, which only happens once PlunderBot has connected to Discord. Then, on the unit's **Chief and departments** page, name Twiddles as Chief.

Exocomp supplies `EXOCOMP_URL` and `EXOCOMP_TELEMETRY_TOKEN`, so telemetry needs no setup; the unit's telemetry chip should read REPORTING within a minute. Without `DEV_GUILD_ID`, slash commands sync globally and can take a while to appear the first time.

The bot keeps its database at `/data/plunderbot.db` and runs as user 10001. Exocomp's per-unit `/data` volume handles that; if the unit ever uses a host folder instead, that folder must be owned by 10001.

### 4. First run on the server

```
/admin timezone America/Los_Angeles
/admin birthdays channel #general
/admin birthdays hour 9
/admin birthdays role @Birthday Pirate      (optional)
/birthday set
```

## Telemetry

On top of Exocomp's standard numbers (latency, servers, commands, errors), PlunderBot reports the gauges `birthdays_on_file`, `crews_mustering` and `crews_sailing`. Background errors are reported as `birthday-announcer`, `crew-upkeep` and `crew-voice`.

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
| `plunderbot/games.py` | The game profiles |
| `plunderbot/crew_logic.py` | Crew Call rules and the crew card |
| `plunderbot/cogs/` | Features: `core`, `admin`, `birthdays`, `crew` |
| `exocomp_telemetry.py` | Exocomp's telemetry helper, vendored |

## Rules of the ship

- Member-facing text lives in `voice.py`: upbeat butler, mild pirate cusses, original lines only. Admin replies and logs stay plain English.
- PlunderBot never pings @everyone. The only role pings are opt-in game roles on crew calls. Toasts ping only the birthday members; sailing pings only the crew.
- Schema changes are new entries at the end of `MIGRATIONS`; never edit one that has shipped.
- Version in `VERSION`, changes in `CHANGELOG.md`, a `vX.Y.Z` tag per release.
