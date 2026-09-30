# PlunderBot

**P**irate **L**ogistics, **U**nsolicited **N**autical **D**rivel & **E**vent **R**eminders: the bright, bubbly robot butler of Brimstone Hill Fortress.

A Python Discord bot (discord.py 2.x) that runs fenced in under Exocomp and reports telemetry to The Magical Samurai. Version 0.9.0 covers **phases 1 to 8 of 9**: the foundation, Birthdays, Crew Call, Voyages, Gangplank and the Notice Board, the Ship's Log and Crow's Nest, Parley, the Ship's Ledger, and Articles. The full plan is the *PlunderBot Scope & Design* doc.

## Commands

| Command | Who | What it does |
|---|---|---|
| `/plunderbot` | Everyone | Meet the butler; shows the version |
| `/timezone set` | Everyone | Save your time zone (Pacific, ET, Europe/London…) so the times you type are read correctly. `/timezone show` and `/timezone clear` too |
| `/birthday set` | Everyone | Save your month and day (no year). After the first hour, you can change it once every 30 days |
| `/birthday mine` | Everyone | See what PlunderBot has for you |
| `/birthday remove` | Everyone | Take your birthday off the ledger |
| `/birthday upcoming` | Everyone | The next 10 birthdays (shows names, pings nobody) |
| `/crew start` | Everyone | Post a crew call: pick the game, then its crew size and activity from the suggestions, plus an optional note, session name, picture, and whether to tag the game's ping role (on by default) |
| `/crew rename` | Captain | Rename your session and its voice channel ("⛵ | Fort Night"); leave empty for the default |
| `/crew close` | Captain | Close your crew call and its voice channel |
| `/crew list` | Everyone | Crews mustering or sailing right now |
| `/ship register` | Everyone | Add your Sea of Thieves ship: name, Sloop/Brigantine/Galleon, optional motto and picture. Also `edit`, `retire` (her ledger stays) |
| `/ship log` | Everyone | Log a voyage from a Captain's Log screenshot (the two-page spread with your Gold). PlunderBot reads it and shows you privately; Confirm, Edit or Cancel. Leave the screenshot out to type it in |
| `/ship show` | Everyone | A ship's profile: captain, plunder, best haul, trusted crew, latest voyages |
| `/ship fleet` | Everyone | The richest ships and pirates |
| `/pirate profile` | Everyone | A pirate's profile: crews sailed, favourite games, ships, plunder. `/pirate set` for your gamertag and motto |
| `/voyage create` | Everyone | Schedule a voyage: title, date (friday, tomorrow, 10/3), time (8pm), optional game and size, seats, details, reminders (default 1 day and 1 hour before; e.g. `2d, 3h, 15m` or `none`), repeat (weekly, every 2 weeks, monthly), length, a picture, and when to tag the game's ping role (when posted by default; or also at each reminder and when it sails; or never) |
| `/voyage edit` | Organizer or mod | Change the title, date, time, details, reminders, seats, picture (or remove it) or when the game's role is tagged |
| `/voyage cancel` | Organizer or mod | Cancel one voyage, or with `whole_series:True` a repeating series |
| `/voyage list` | Everyone | Upcoming voyages |
| `/admin settings` | Manage Server | Show this server's settings |
| `/admin timezone` | Manage Server | Server time zone (default America/Los_Angeles) |
| `/follow` | Everyone | Pick the games you follow: their ping roles, plus their threads in the game forum |
| `/colours create` | Manage Roles | Role menus: `create`, `add` (role, emoji, label, description), `remove`, `move`, `edit`, `onboarding` (offer it to newcomers), `post`, `preview`, `import` (copy a MEE6 reaction-role message), `list`, `delete` |
| `/noticeboard create` | Manage Server | Pages: `create`, `section add/edit/image/remove/move` (a pop-up form), `import` (copy an existing message, or a run of them with `through`, such as the welcome and rules), `starter` (a draft Pirate's Guide), `post`, `preview`, `gameindex`, `list`, `delete` |
| `/admin gangplank setup` | Manage Server | Intro channel, Pending role, Harbormasters role, rules and orientation channels, optional alert channel. Then `on`/`off`, `emoji`, `timing`, `status` |
| `/admin shipslog channel` | Manage Server | The weekly Ship's Log roundup: `channel` (empty turns it off), `when` (day and hour), `preview`, `post` |
| `/admin crowsnest on` | Manage Server | Game news in each game's forum thread: `on`, `off`, `check`, `source` (Steam app, RSS/Atom feed, none or default), `preview` |
| `/admin parley on` | Manage Server | Parley (PlunderBot answering in chat): `on`, `off`, `status` (spend and usage), `channel` (switch off in one channel), `limits` (monthly budget, replies per member a day, web searches a day) |
| `/articles new` | Manage Server | The server's own rules: `new` (a name and a trigger), then what it does: `reply` (a pop-up list, one picked at random), `react`, `role` (give or take, optionally for a while), `count`, `repost`, `pin`. Also `edit`, `remove` (an action), `limits` (cooldown, chance, required role), `where` (channels), `on`, `off`, `show`, `list`, `delete` |
| `/admin ledger reminders` | Manage Server | Captain's Log nudges for Sea of Thieves crews at sail and back in port (on by default). `/admin ledger remove` takes a haul out by its entry number |
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

### How Colours (role menus) work

- Each menu's card lists its roles with one button. Pressing it opens a private dropdown already ticked with the roles you wear; save it and you wear exactly those. Menus can be pick-one (regions) or pick-any.
- Menus marked with `/colours onboarding` appear as buttons on the welcome-aboard message, alongside **Follow games**.
- Picking a region too broad for one time zone (Asia, South America) asks which zone is closest.
- `/colours import` copies a MEE6 reaction-role message (emoji and roles) into a new menu; the old message is left alone until you delete it.
- PlunderBot won't hand out roles with moderator permissions, or roles above its own.

### How the Notice Board works

- A page is a list of sections; each is one embed with a heading, text (Markdown), colour and optional picture, either inside the section or as a banner above it. Write them in a pop-up form, or `/noticeboard import` existing messages (a picture on its own becomes a banner above the text after it).
- `/noticeboard post` posts the page; posting again edits the same messages in place. Long pages spill over several messages.
- `/noticeboard gameindex` posts the Game Index: every game with its forum thread and ping role, and a **Follow games** button. Run it again after adding threads or roles.

### How Parley works

- @mention PlunderBot, or reply to one of its messages, and it answers in character. Replying keeps the conversation going (it sees up to six earlier messages in the reply chain).
- Claude Haiku does the talking. Server facts (voyages, crews, birthdays, games and threads, the Notice Board pages, its own commands) come from PlunderBot's database, never guessed. Without a Kagi key (the current setup) it answers other questions from what Claude knows and says when that may be out of date; with `KAGI_API_KEY` set it can search the web, capped per day. Slash commands never use AI.
- Limits: a monthly dollar budget (default $5) and replies per member per day (default 20); with Kagi, also web searches per day (default 25, about 1.5¢ each, billed by Kagi). When a limit is hit, it says so in character.
- It only answers in channels everyone can see, so staff channels are left out, and not to newcomers still on the gangplank. Quartermasters can switch it off per channel.
- Set a spend limit in the Anthropic Console as well, as a backstop.

### How Articles work

- An article is a rule: **when** something happens, PlunderBot **does** one or more things, within **limits**.
- When: someone says words or phrases (whole word, anywhere, the whole message, or the start), a member joins, leaves, gets or loses a role, or boosts, a message gets an emoji reaction (optionally only once it has several, like a starboard), or on a schedule in server time (`every 6h`, `daily 8pm`, `weekdays 9am`, `mon,fri 20:00`).
- Does: reply, or post in a chosen channel (a random pick from a list, separated in the form by a line with just `---`, with an optional picture); react; give or take a role, for good or for some minutes; count (per member or server-wide); repost the message in another channel; pin it. Reacting, pinning and reposting need a message, so they work with word and reaction triggers only; joins, leaves, role changes, boosts and schedules post in a channel.
- Replies can use `{member}` (pings them), `{name}` (doesn't), `{author}` (who wrote a reacted message), `{count}` and `{nth}` (1st, 2nd…), `{server}`, `{channel}`, `{role}` and `{cuss}`.
- Limits: a cooldown per channel, per member or server-wide (word triggers start at 60 seconds per channel), a chance (fires 30% of the time, say), a required role, and which channels it works in (a category covers its channels). PlunderBot ignores other bots, so articles can't set each other off.
- Word triggers need the Message Content Intent, which is on.

### How the Ship's Ledger works

- Pirates register their ships with `/ship register`. `/crew start` for Sea of Thieves sails your ship automatically if you have just one (pick another with `ship`); a ship also sets the crew size when you don't.
- When a Sea of Thieves crew sets sail, PlunderBot reminds the ship's owner (or the captain) to screenshot the Captain's Log two-page spread before logging off. When the crew is back in port (it sailed at least 15 minutes with someone in voice), it asks for the screenshot with `/ship log`.
- Or skip the command: reply to PlunderBot's reminder (or @mention it) with the screenshot. The reading appears as a reply with the same buttons, which only you can press, and once confirmed that message is the ledger entry.
- `/ship log` picks the crew you sailed with most recently (within 18 hours; or pick one), reads the screenshot with Claude Haiku (gold, doubloons, emissary, reputation, voyage stats), and shows it only to you with **Confirm**, **Edit** (a form to fix anything) and **Cancel**. Nothing is saved until you confirm.
- A confirmed haul is posted as a reply to the crew card, shown on the card, and credited in full to the ship and every pirate aboard (as in the game, everyone gets the full haul). One haul per crew: logging again replaces it, if you're the captain, the ship's owner or whoever logged it.
- Reading a screenshot costs about a third of a cent and counts toward Parley's monthly budget (`/admin parley limits`). With the budget spent, or no Anthropic key, you type the haul in instead. Screenshots aren't kept.
- The weekly Ship's Log adds the week's plunder, and Parley can answer "who's the richest pirate?".

### How the Ship's Log and Crow's Nest work

- Every week (Sunday 6 PM server time by default) the Ship's Log posts a roundup: crews that sailed, voyages sailed and coming up, birthdays this week, new pirates, the liveliest game threads, and game news.
- The Crow's Nest checks each game's official news every 30 minutes and posts anything new in its thread in the game forum. Steam games and Fortnite (Epic's in-game news) are built in; other games need an RSS or Atom feed. When it's turned on (or a game is first seen) it only notes what's already out, so old posts don't flood in. At most three new posts per game per check.

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
- A picture attached to a voyage shows on its card, on every repeat, and on the crew card when it sets sail. PlunderBot keeps its own copy (Discord's attachment links expire), and needs **Attach Files** in the card channels.
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
2. **Bot** tab: turn on **Server Members Intent** and **Message Content Intent** (for importing old posts, and later Parley and Articles). Leave Presence off.
3. **Bot** tab: **Reset Token** and keep the token for step 3. Never paste it in chat or commit it.
4. **OAuth2 › URL Generator**: scopes `bot` and `applications.commands`; permissions **View Channels**, **Send Messages**, **Embed Links**, **Manage Roles**, **Manage Channels**, **Manage Events**, **Kick Members**, **Read Message History**, **Add Reactions**, **Attach Files**, **Manage Threads**. Open the URL and add PlunderBot to Brimstone Hill Fortress.
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
| Secrets | `DISCORD_TOKEN=<the bot token>`; for Parley, `ANTHROPIC_API_KEY` (optional: `KAGI_API_KEY` for web search, `PARLEY_MODEL` setting, default `claude-haiku-4-5`) |
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
| `plunderbot/articles_logic.py` | Articles: matching words, schedules, reply templates, which actions fit which trigger |
| `plunderbot/ledger_logic.py` | The Ship's Ledger: reading a Captain's Log, profiles and hauls |
| `plunderbot/cogs/` | Features: `core`, `admin`, `birthdays`, `crew`, `voyages`, `regions`, `gangplank`, `colours`, `noticeboard`, `shipslog`, `crowsnest`, `parley`, `ledger`, `articles` |
| `exocomp_telemetry.py` | Exocomp's telemetry helper, vendored |

## Rules of the ship

- Member-facing text lives in `voice.py`: upbeat butler, mild pirate cusses, original lines only. Admin replies and logs stay plain English.
- PlunderBot never pings @everyone. The only role pings are opt-in game roles on crew calls. Toasts ping only the birthday members; sailing pings only the crew.
- Schema changes are new entries at the end of `MIGRATIONS`; never edit one that has shipped.
- Version in `VERSION`, changes in `CHANGELOG.md`, a `vX.Y.Z` tag per release.
