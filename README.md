# PlunderBot

**P**irate **L**ogistics, **U**nsolicited **N**autical **D**rivel & **E**vent **R**eminders: the bright, bubbly robot butler of Brimstone Hill Fortress.

A Python Discord bot (discord.py 2.x) that runs fenced in under Exocomp and reports telemetry to The Magical Samurai. Version 1.6.1 covers **all nine phases**: the foundation, Birthdays, Crew Call, Voyages, Gangplank and the Notice Board, the Ship's Log and Crow's Nest, Parley, the Ship's Ledger, Articles, and its screens in The Magical Samurai (Daisho), plus **music** in voice channels. The full plan is the *PlunderBot Scope & Design* doc.

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
| `/voyage create` | Everyone | Schedule a voyage: title, date (friday, tomorrow, 10/3), time (8pm), optional game and size, seats, details, reminders (default 1 day and 1 hour before; e.g. `2d, 3h, 15m` or `none`), repeat (every week, every 2 to 12 weeks, every month on the same date, or the same weekday like the 2nd Saturday or the last Friday) and an optional last date (`repeat_ends`), length, a picture, and when to tag the game's ping role (when posted by default; or also at each reminder and when it sails; or never) |
| `/voyage edit` | Organizer or mod | Change the title, date, time, details, reminders, seats, picture (or remove it) or when the game's role is tagged; for a repeating voyage, how it repeats, its last date, and skip or unskip a date (skipping this voyage's own date cancels just it) |
| `/voyage series` | Everyone | A repeating voyage's coming dates, skipped ones struck through |
| `/voyage cancel` | Organizer or mod | Cancel one voyage, or with `whole_series:True` a repeating series |
| `/voyage list` | Everyone | Upcoming voyages |
| `/play` | Everyone in voice | Play a song name or a link in your voice channel (SoundCloud, Bandcamp, Twitch, radio, plain audio links, Spotify links, and YouTube when it's on). Playlists and albums load up to 50 tracks. `next:True` puts it at the front of the queue |
| `/music queue` | Everyone | What's playing and what's next (10 a page). Also `nowplaying` (with how far in), `lyrics` (just for you) |
| `/music skip` | Listeners | Skip. Also `pause`, `resume`. With a DJ role set, skipping someone else's track needs it |
| `/music stop` | Listeners (DJ) | Stop, clear the queue and leave. Also `leave`, `clear`, `remove`, `move`, `shuffle`, `repeat` (off, this track, the whole queue), `seek` (1:30), `volume` (1 to 150%) |
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
| `/admin music status` | Manage Server | How music is set up. Also `enable`, `youtube` (on or off), `djrole`, `channel` (where Now Playing cards go), `settings` (starting volume, minutes before leaving when it's quiet, 24/7) |
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

### How music works

- `/play` joins your voice channel and plays, or adds to the queue. A **Now Playing** card goes up where `/play` was used (or in the music channel from `/admin music channel`) with buttons: pause/resume, skip, stop, shuffle and repeat. Each new track replaces the card.
- **Sources:** SoundCloud, Bandcamp, Twitch (live too), internet radio and plain audio links, through [yt-dlp](https://github.com/yt-dlp/yt-dlp) and FFmpeg. Song names are searched on SoundCloud, or on YouTube once it's on. **Spotify** only shares song details, never audio: with a Spotify key, a Spotify track, album or playlist becomes a list of songs that are found on YouTube (or SoundCloud) when their turn comes. Spotify's own editorial playlists are off limits to apps.
- **YouTube** is off until a Quartermaster runs `/admin music youtube on`. Restreaming YouTube is against YouTube's terms, and YouTube turns away servers it thinks are bots, so PlunderBot signs in with a **throwaway** account's cookies (never a real account: YouTube can close accounts it thinks are automated). When YouTube refuses, the track is skipped with a note; everything else keeps working.
- **Who steers:** anyone in the voice channel with PlunderBot, and anyone with Manage Channels. With a DJ role (`/admin music djrole`), skipping someone else's track, stop, clear, remove, move, shuffle, repeat, seek and volume need that role, unless you're the only one listening; you can always skip your own track.
- PlunderBot leaves after 5 quiet minutes (nothing playing, or nobody listening), unless **24/7** is on. Tracks over 3 hours are turned away, in playlists too (live streams are fine). The queue holds 200, and one member can have at most 50 waiting (mods and Daisho crew aren't limited).
- **Links stay on the public internet** (1.4.1): a link whose address is PlunderBot's own network (127.0.0.1, private addresses, the cloud metadata address) is refused, and so is a page that hands back a stream address like that or a local file. FFmpeg only ever opens web addresses.
- **The Jukebox screen** (1.4.0): Daisho's PlunderBot screens have a **Jukebox** (`plunderbot.magicalsamurai.com/jukebox`) showing what's playing, how far in, who asked for it and the queue, updating itself. Members add songs there (with nothing playing, PlunderBot joins the voice channel they're in) and steer with the same buttons as in Discord plus **Next** and **✕** per queued track, as themselves and by the same rules: be in PlunderBot's voice channel, and the DJ role applies. Daisho crew with its Voyages permission steer from anywhere, like a mod. While PlunderBot is in voice it checks Daisho every 3 seconds instead of 15, so button presses land in a few seconds.
- **Ask PlunderBot** (1.3.1, all controls from 1.6.0): @mention it with "play something piratey", "queue Wellerman next", "skip this", "a bit quieter", "shuffle" or "stop", and Parley does it as you, through `Music.control` with the same checks as the buttons (be in its voice channel; the DJ role applies). Lyrics stay with `/music lyrics`, which only you see.
- Lyrics come from [LRCLIB](https://lrclib.net), an open lyrics database, and are shown only to whoever asks.
- Voice uses discord.py's own client, which speaks Discord's end-to-end encrypted voice (DAVE); it needs the `davey` package, which `discord.py[voice]` brings.

### How Colours (role menus) work

- Each menu's card lists its roles with one button. Pressing it opens a private dropdown already ticked with the roles you wear; save it and you wear exactly those. Menus can be pick-one (regions) or pick-any.
- Menus marked with `/colours onboarding` appear as buttons on the welcome-aboard message, alongside **Follow games**. Other menus live wherever they're posted (for Brimstone, #pirate-profile), and the welcome-aboard message points there.
- A region role sets the time zone PlunderBot reads your typed times in (see [How Voyages work](#how-voyages-work)). Picking a region too broad for one zone (Asia, South America) asks which zone is closest.
- `/colours import` copies a MEE6 reaction-role message (emoji and roles) into a new menu; the old message is left alone until you delete it.
- PlunderBot won't hand out roles with moderator permissions, roles above its own, or the Gangplank's Pending and Harbormaster roles (so nobody can let themselves aboard). The same goes for **Follow games** and article role actions.
- Menus can also be built and edited on Daisho's **Role menus** screen (1.1.0), with a live preview of the card, how many members wear each role, a colour for the card and the button's own words and emoji. Only Daisho Commanders can edit them there.

### How the Notice Board works

- A page is a list of sections; each is one embed with a heading, text (Markdown), colour and optional picture, either inside the section or as a banner above it. Write them in a pop-up form, or `/noticeboard import` existing messages (a picture on its own becomes a banner above the text after it).
- `/noticeboard post` posts the page; posting again edits the same messages in place. Long pages spill over several messages.
- `/noticeboard gameindex` posts the Game Index: every game with its forum thread and ping role, and a **Follow games** button. Run it again after adding threads or roles.

### How Parley works

- @mention PlunderBot, or reply to one of its messages, and it answers in character. Replying keeps the conversation going (it sees up to six earlier messages in the reply chain).
- Claude Haiku does the talking. Server facts (voyages, crews, birthdays, games and threads, the Notice Board pages, its own commands) come from PlunderBot's database, never guessed. Without a Kagi key (the current setup) it answers other questions from what Claude knows and says when that may be out of date; with `KAGI_API_KEY` set it can search the web, capped per day. Slash commands never use AI.
- **It can do things for you** (1.3.1; everything a member can do from 1.6.0), always as you and never for anyone else, through the same code and checks as the commands and buttons. Eight grouped tools: **voyage** (plan, answer, edit, see a series, skip or restore a date, cancel), **crew** (start, join, leave, rename, close), **music** (play, queue, skip, pause, resume, stop, clear, remove, move, shuffle, repeat, seek, volume), **me** (your time zone and birthday), **follow** (games), **roles** (from posted role menus only), **ship** (register, edit, retire, show) and **pirate** (profiles). It asks when something it needs is missing, and looks numbers up before acting. Changing a voyage or ship by chat is for its organizer or owner only, even for mods (they keep the slash commands), and anything posted where not everyone can see is out of reach.
- **Confirm buttons** (1.6.0): cancelling a voyage (or a whole series) and retiring a ship tell other people or can't be undone by asking, so PlunderBot replies with **Yes** and **No** buttons that only the member who asked can press, within 10 minutes; nothing happens until they do. (The held action lives in memory: after a restart the button says to ask again.)
- Not by chat: pictures, lyrics, server settings (`/admin`, `/colours`, `/noticeboard`, `/articles`), Gangplank decisions, removing ledger entries, and anything for other people. Newcomers still on the Gangplank can't use it.
- The tools and the rules are sent with prompt caching (1.6.0), so they're billed at a tenth of the price on later questions within a few minutes, once they're long enough for the model to cache (Haiku 4.5 needs about 4,000 tokens; they're a little under, so for now each question costs about a tenth of a cent more than in 1.5.0).
- Limits: a monthly dollar budget (default $5) and replies per member per day (default 20); with Kagi, also web searches per day (default 25, about 1.5¢ each, billed by Kagi). When a limit is hit, it says so in character.
- It only answers in channels everyone can see, so staff channels are left out, and not to newcomers still on the gangplank. Quartermasters can switch it off per channel.
- Set a spend limit in the Anthropic Console as well, as a backstop.

### How the Daisho screens work

- PlunderBot's module in The Magical Samurai (Daisho, `daisho.magicalsamurai.com`) has screens for its settings, role menus, articles, Notice Board pages, voyages, crews, the Ship's Ledger and the jukebox, short link `plunderbot.magicalsamurai.com`. Crew with access to the PlunderBot unit see what their permission keys allow; with open sign-in on, any server member past the Gangplank can sign in as a **Swabbie** and see Voyages, Crews, the Ship's Ledger and the Jukebox. The crew's manual is in Daisho under **Manual › PlunderBot**; Swabbies get their own **Swabbie's guide**.
- PlunderBot keeps its own data and sends Daisho a copy: what changed every five minutes, everything every half hour. Changes made on the screens are picked up within about 15 seconds (3 while PlunderBot is in a voice channel, from 1.4.0), applied with the same checks as the slash commands, and reported back (done, or refused and why). PlunderBot remembers which changes it has applied, so a restart never applies one twice, and skips anything garbled.
- PlunderBot can't see who made a change on the screens: Daisho's permission keys decide that. Editing role menus, articles and Notice Board pages there is Commander-only by default, since in Discord they need Manage Roles or Manage Server.
- From 1.2.0, members can also plan voyages, call crews, sign up, join, and look after their own voyages and crews on those screens, as themselves: Daisho sends their Discord account with the change, and PlunderBot applies it exactly as `/voyage create`, `/crew start` and the card buttons would. Cards go to the voyage and crew channels set with `/admin voyages channel` and `/admin crew channel`.
- To connect it: on the unit's page in Daisho, the Captain picks **PlunderBot** as its module and issues a module token with all three scopes, then refits. Exocomp hands over `SAMURAI_URL`, `SAMURAI_PUBLIC_URL` and `SAMURAI_MODULE_TOKEN`.
- Once connected, voyage and crew cards get a **Manage** button that opens them in Daisho (it works for crew with access to the unit there, and for Swabbies; anyone else is asked to sign in, and turned away if they can't).
- If Daisho is down, PlunderBot carries on and catches up when it's back.

### How Articles work

- An article is a rule: **when** something happens, PlunderBot **does** one or more things, within **limits**.
- When: someone says words or phrases (whole word, anywhere, the whole message, or the start), a member joins, leaves, gets or loses a role, or boosts, a message gets an emoji reaction (optionally only once it has several, like a starboard), or on a schedule in server time (`every 6h`, `daily 8pm`, `weekdays 9am`, `mon,fri 20:00`).
- Does: reply, or post in a chosen channel (a random pick from a list, separated in the form by a line with just `---`, with an optional picture); react; give or take a role, for good or for some minutes; count (per member or server-wide); repost the message in another channel; pin it. Reacting, pinning and reposting need a message, so they work with word and reaction triggers only; joins, leaves, role changes, boosts and schedules post in a channel.
- Server emoji: type their name, like `:Bruh:`, in replies or reactions (the pop-up form has no emoji picker). A reply can be just an emoji.
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
- A **Harbormaster** reacts to their introduction (or to PlunderBot's welcome for them) with **Yar** to let them aboard: Pending comes off and PlunderBot points them to the orientation channel (#pirate-profile at Brimstone) for roles, including a region role for their time zone. **Nar** kicks them. Nobody else's reactions count.
- Newcomers who never say anything get a reminder ping after 3 days and are kicked after 7 (with a friendly DM if their DMs are open). Anyone who has introduced themselves is never kicked automatically; that's the Harbormasters' call.
- If Pending is taken off by hand, or the newcomer leaves, PlunderBot stops tracking them.
- While they're Pending, newcomers can't use PlunderBot's slash commands (1.4.1; `/plunderbot` still says hello), Parley doesn't answer them, and the Daisho screens turn them away.
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
2. **Bot** tab: turn on **Server Members Intent** and **Message Content Intent** (for importing old posts, Parley and Articles). Leave Presence off.
3. **Bot** tab: **Reset Token** and keep the token for step 3. Never paste it in chat or commit it.
4. **OAuth2 › URL Generator**: scopes `bot` and `applications.commands`; permissions **View Channels**, **Send Messages**, **Embed Links**, **Manage Roles**, **Manage Channels**, **Manage Events**, **Kick Members**, **Read Message History**, **Add Reactions**, **Attach Files**, **Manage Threads**, **Manage Messages** (for articles that pin), **Connect** and **Speak** (for music). Open the URL and add PlunderBot to Brimstone Hill Fortress.
5. In **Server Settings › Roles**, drag PlunderBot's role **above** any role it should hand out (the birthday role, the Colours roles, the Gangplank's Pending role, and any role an article gives).

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
| Secrets | `DISCORD_TOKEN=<the bot token>`; for Parley, `ANTHROPIC_API_KEY` (optional: `KAGI_API_KEY` for web search, `PARLEY_MODEL` setting, default `claude-haiku-4-5`); for music, optionally `YOUTUBE_COOKIES`, `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` (see below) |
| Memory limit | 1024 MB (music needs the room; 512 MB is enough without it) |

Press **Fabricate unit** and watch the job log. SUCCESS means the health check passed, which only happens once PlunderBot has connected to Discord. Then, on the unit's **Chief and departments** page, name Twiddles as Chief.

Exocomp supplies `EXOCOMP_URL` and `EXOCOMP_TELEMETRY_TOKEN`, so telemetry needs no setup; the unit's telemetry chip should read REPORTING within a minute. Without `DEV_GUILD_ID`, slash commands sync globally and can take a while to appear the first time.

The bot keeps its database at `/data/plunderbot.db` and runs as user 10001. Exocomp's per-unit `/data` volume handles that; if the unit ever uses a host folder instead, that folder must be owned by 10001.

### Music: the YouTube account and the Spotify key (optional)

**YouTube cookies, from a throwaway account.** Never use your own Google account.

1. Make a new Google account just for PlunderBot, and open YouTube with it once to accept the terms.
2. Open a **private (incognito) window**, sign in to YouTube with that account, then go to `https://www.youtube.com/robots.txt` in the same tab. This keeps YouTube from swapping the session out from under PlunderBot.
3. Export that window's cookies as a `cookies.txt` file (Netscape format) with a browser extension such as *Get cookies.txt LOCALLY*, then **close the private window without signing out**.
4. Turn the file into one line of text in PowerShell: `[Convert]::ToBase64String([IO.File]::ReadAllBytes("$HOME\Downloads\cookies.txt")) | Set-Clipboard`
5. In Exocomp, add the secret `YOUTUBE_COOKIES=<paste>` to the PlunderBot unit and refit. Delete the `cookies.txt` file.
6. In Discord: `/admin music youtube on`. `/admin music status` shows whether the cookies were read.

If YouTube starts refusing ("YouTube is turning PlunderBot away"), repeat steps 2 to 5 for fresh cookies.

**Spotify key.** At [developer.spotify.com](https://developer.spotify.com/dashboard), create an app (any name; redirect URI `http://127.0.0.1/`, it isn't used), and copy its Client ID and Client Secret into the secrets `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET`. Refit.

### 4. First run on the server

```
/admin timezone America/Los_Angeles
/admin birthdays channel #general
/admin birthdays hour 9
/admin birthdays role @Birthday Pirate      (optional)
/birthday set
/admin music status                         (music: see "Music" above for YouTube and Spotify)
/admin music youtube on                     (optional, once YOUTUBE_COOKIES is set)
```

## Telemetry

On top of Exocomp's standard numbers (latency, servers, commands, errors), PlunderBot reports the gauges `birthdays_on_file`, `crews_mustering`, `crews_sailing`, `voyages_scheduled` and `gangplank_waiting`. Background errors are reported as `birthday-announcer`, `crew-upkeep`, `crew-voice`, `voyage-clock`, `articles-clock` and `daisho`.

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
| `plunderbot/links.py` | Manage links into Daisho |
| `plunderbot/articles_logic.py` | Articles: matching words, schedules, reply templates, which actions fit which trigger |
| `plunderbot/ledger_logic.py` | The Ship's Ledger: reading a Captain's Log, profiles and hauls |
| `plunderbot/cogs/` | Features: `core`, `admin`, `birthdays`, `crew`, `voyages`, `regions`, `gangplank`, `colours`, `noticeboard`, `shipslog`, `crowsnest`, `parley`, `ledger`, `articles`, `daisho` |
| `exocomp_telemetry.py` | Exocomp's telemetry helper, vendored |

## Rules of the ship

- Member-facing text lives in `voice.py`: upbeat butler, mild pirate cusses, original lines only. Admin replies and logs stay plain English.
- PlunderBot never pings @everyone. The only role pings are opt-in game roles on crew calls. Toasts ping only the birthday members; sailing pings only the crew.
- Schema changes are new entries at the end of `MIGRATIONS`; never edit one that has shipped.
- Version in `VERSION`, changes in `CHANGELOG.md`, a `vX.Y.Z` tag per release.
- Every check lives in one place and every way in uses it: slash commands, buttons, Parley and the Daisho screens all go through the same function (`Music.control`/`may_steer`, `Voyages.launch`/`plan_edit`/`apply_series`, `CrewCall.open_call`/`rename_as`, `Core.tz_set_as`, `Birthdays.set_as`, `Noticeboard.follow_as`, `Colours.apply_as`, `ShipLedger.register_as`/`edit_as`/`retire_as`, `self_serve_problem` plus `above_their_reach` for roles). A new way in calls that function; it never re-implements the rule.
- Anything a member types that PlunderBot fetches (a song link, a picture URL) goes through `netguard.public_url` first, and again on whatever address the fetch hands back. FFmpeg gets `-protocol_whitelist`.
- Members still on the Gangplank can't use commands (`PlunderTree.interaction_check`), Parley or the screens. Buttons don't pass through that check, so anything a Pending member could reach must check for themselves.
- Anything that costs money (Parley, Ledger reads) counts against the member's daily limit **before** the call, and against the month's budget.
- Daisho change handlers never wait on Discord rate limits or slow lookups: background tasks or `asyncio.wait_for`.
- Pictures are size-checked (pixels, not just bytes) before decoding, and decoded off the event loop.
