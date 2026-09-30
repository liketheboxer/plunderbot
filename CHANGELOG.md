# Changelog

## 1.3.1 (2026-09-30): Ask PlunderBot to do things

- Parley can now act for the member who asked, in plain speech, through the same code as the commands and buttons: **plan a voyage** ("plan a Sea of Thieves galleon run Friday at 8"), **answer** a voyage (Aboard, Maybe, Can't make it, or take it back), **cancel** a voyage they organized, **call a crew** ("start a sloop for fort"), **join or leave** a crew, and **close** their own crew. It asks when a voyage's date or time is missing, reads times in the member's own time zone (as `/voyage create` does) and says which zone it used. It never acts for anyone else, and members still on the Gangplank can't use it. Voyage and crew lists it reads now carry their numbers (#12) so it can pick the right one.
- Parley can queue music: "@PlunderBot pick me a song about pirates" and it chooses one and adds it to the queue, as if you'd used `/play` (same checks: you must be in a voice channel, and the usual queue limits). It can also say what's playing and what's next. Skipping and stopping stay with the buttons and `/music`.
- Parley now knows the music commands, so it points people to `/play` and `/music` correctly.
- `/noticeboard starter`'s draft Pirate's Guide has a Music section.

## 1.3.0 (2026-09-30): Music

- **Music in voice channels**, like Pancake: `/play` a song name or a link and PlunderBot joins your voice channel. `/music` has queue, nowplaying, skip, pause, resume, stop, leave, clear, remove, move, shuffle, repeat (off, this track, the whole queue), seek, volume (1 to 150%) and lyrics. A **Now Playing** card with pause, skip, stop, shuffle and repeat buttons goes up for each track. Volume and 24/7 are free.
- Sources: SoundCloud, Bandcamp, Twitch, internet radio and plain audio links, plus Spotify links (with a Spotify key: the songs are found elsewhere, since Spotify never shares audio). **YouTube** is a Quartermaster's switch (`/admin music youtube`), played through a throwaway account's cookies (the `YOUTUBE_COOKIES` secret). Song names are searched on YouTube when it's on, SoundCloud when it's off.
- Optional DJ role: with one set, skipping someone else's track, stop, clear, remove, move, shuffle, repeat, seek and volume need it, unless you're the only listener.
- PlunderBot leaves after 5 quiet minutes (settable), unless 24/7 is on. `/admin music` has `status`, `enable`, `youtube`, `djrole`, `channel` and `settings`; the same settings are on Daisho's Settings screen.
- Voice uses discord.py's own client with Discord's end-to-end encrypted voice (DAVE). New in the image: FFmpeg, libopus, yt-dlp (with its YouTube scripts) and Deno. Give the unit **1024 MB** of memory, and re-invite (or add **Connect** and **Speak** to PlunderBot's role) if it can't join voice.

## 1.2.0 (2026-09-30): Voyages and crews from the web

Pairs with The Magical Samurai 1.15.0.

- Members can plan voyages, call crews, answer Aboard/Maybe/Can't make it, and join or leave crews on Daisho's screens, and edit or cancel their own voyages and rename or close their own crews there. PlunderBot does it exactly as the slash commands and buttons would, with the same checks, and posts the cards in the voyage channel (`/admin voyages channel`) and crew channel (`/admin crew channel`); without those set, the screens are told so.
- Changes made as a member carry their Discord account (set by Daisho from their sign-in). PlunderBot refuses them if the member has left the server or is still Pending, and only lets an organizer or captain change their own voyage or crew.
- Daisho is sent each game's crew sizes and activities, each voyage's answers and each crew's members, so its screens can show people where they stand.
- Under the hood: creating a voyage, answering one, calling a crew and joining one now share their code between Discord and Daisho (no change in how the commands and buttons behave).

## 1.1.3 (2026-09-30): Game Index threads

- The Game Index links each game's forum thread by its address ("💬 thread") instead of mentioning it. Discord shows a mention of a thread that has gone quiet (archived after a week without posts) as "#unknown" to anyone who hasn't opened it, so most quieter games showed "#unknown". Run `/noticeboard gameindex` (or Post it on Daisho) after the refit to rebuild it.

## 1.1.2 (2026-09-30): Gangplank roles stay off menus

- The Gangplank's **Pending** and **Harbormaster** roles can no longer be self-serve: not on a role menu (from `/colours add`, `/colours import` or Daisho's editor), not in Follow games, and not in an article's role action. Before, a Pending role put on a menu would have let a newcomer untick it and skip the Gangplank. Daisho's editor stops offering them.

## 1.1.1 (2026-09-30): Onboarding wording

- The welcome-aboard message and the "which zone is closest?" prompt no longer say a region role makes PlunderBot show times in your zone (Discord timestamps already do that for everyone). They now say what it does: sets the zone PlunderBot reads the times you type in.
- The welcome-aboard message with buttons no longer says the Pirate's Guide is in the orientation channel; it points there for the rest of the role menus.
- `/noticeboard starter`'s draft Pirate's Guide: the roles section explains the role-menu buttons in #new-pirate-orientation and `/follow` (the guide itself has no role buttons), a new Ship's Ledger section, and "@mention me" instead of `/plunderbot` for asking PlunderBot things.

## 1.1.0 (2026-09-30): Role menus on Daisho

Pairs with The Magical Samurai 1.14.0.

- Role menus (Colours) can be built and edited on Daisho's new **Role menus** screen, with a live preview of the card: title, text, pick-one or pick-any, and each role's emoji, name in the list and the line under it, in any order; then posted, moved or deleted. The same checks as `/colours add` apply (no moderator roles, nothing above PlunderBot's role, real emoji only).
- A menu's card can have its own **colour**, and its button its own **words and emoji**, instead of the fixed "Choose <title>". The welcome-aboard buttons use them too.
- An option's emoji must now be a real emoji (or a server emoji): a word like "joystick" left over from an import is refused on Daisho, so it can be fixed there.
- Daisho is sent the menus, and how many members wear each role, with the rest of PlunderBot's data.

## 1.0.1 (2026-09-30): Daisho hardening

Fixes from a security check of PlunderBot and its Daisho screens. Pairs with The Magical Samurai 1.12.1.

- A Gangplank role set from Daisho gets the same checks as `/admin gangplank setup`: never @everyone or a role another app manages, and for the Pending role, PlunderBot needs Manage Roles, Kick Members and its role above it.
- PlunderBot remembers the Daisho changes it has applied in its database (for 30 days), so a restart between applying one and reporting it never applies it twice.
- A garbled change from Daisho is skipped (or refused with a reason) instead of holding up the ones behind it.
- README: the invite permissions include Manage Messages (articles that pin), the full telemetry list, and what the Daisho screens can and can't check.

## 1.0.0 (2026-09-29): Daisho

Phase 9, the last of the plan. Needs The Magical Samurai 1.11.0.

- PlunderBot has management screens in The Magical Samurai (Daisho): Settings, Articles, the Notice Board, Voyages, Crews and the Ship's Ledger.
- PlunderBot stays the source of truth. It sends Daisho its data (what changed every five minutes, everything every half hour), picks up changes made there every 15 seconds, applies them with the same checks as its slash commands, and reports back how each went. If Daisho is down, PlunderBot carries on and catches up later.
- Voyage and crew cards get a **Manage** link button that opens them in Daisho (only once the module is connected).
- `/voyage edit` and `/voyage cancel` now share their work with Daisho's edits (no change in how they behave).
- New settings, all set by Exocomp at each refit once the Captain has issued the module token: `SAMURAI_URL`, `SAMURAI_PUBLIC_URL`, `SAMURAI_MODULE_TOKEN`. Without them nothing changes.

## 0.9.1 (2026-09-29): Server emoji in articles

- Type a server emoji's name, like `:Bruh:`, in an article's replies (the pop-up form has no emoji picker) or in `/articles react`, and PlunderBot uses the real emoji. A reply can be just the emoji.
- Fixed: the reply form's hint text was over Discord's 100-character limit, which could stop the form opening.

## 0.9.0 (2026-09-29): Articles

Phase 8.

- `/articles`: the server's own if-this-then-that rules, for Quartermasters.
- Triggers: words or phrases (whole word, anywhere, exact, or at the start), a member joining, leaving, getting or losing a role, or boosting, an emoji reaction (optionally once a message has several, for a starboard), or a schedule in server time.
- Actions: reply or post (picked at random from a list, with an optional picture), react, give or take a role (optionally for a while), count (per member or server-wide, for `{count}` and `{nth}`), repost in another channel, pin. Up to 8 per article.
- Limits: cooldown per channel, member or server; chance; a required role; which channels (categories count).
- Replies can use `{member}`, `{name}`, `{author}`, `{count}`, `{nth}`, `{server}`, `{channel}`, `{role}`, `{cuss}`.
- Parley knows about `/articles`. Database migration 17.

## 0.8.1 (2026-09-29): Hand PlunderBot your Captain's Log

- Reply to PlunderBot (or @mention it) with a Captain's Log screenshot and it reads it right there: no words needed, or words like "here are my stats". The reading gets Confirm / Edit / Cancel buttons that only the poster can press; confirmed, that message becomes the ledger entry.
- Parley no longer invents commands (it suggested a `/plunder submit` that doesn't exist): the full command list is in its instructions, and it knows it can't see pictures.
- The screenshot reader knows the Captain's Log "Current Voyage" pages (days at sea, miles sailed, quests, fish, gold earned).

## 0.8.0 (2026-09-29): The Ship's Ledger

Phase 7.

- Ships: `/ship register` (name, Sloop/Brigantine/Galleon, motto, picture), `edit`, `retire`, `show` (profile with plunder, best haul, trusted crew and latest voyages) and `fleet` (richest ships and pirates).
- `/crew start` has a `ship` option for Sea of Thieves; your only ship is picked for you, and a ship sets the crew size. The crew card shows the ship, and the haul once it's logged.
- Captain's Log reminders: when a Sea of Thieves crew sets sail, the ship's owner (or the captain) is reminded to screenshot the Captain's Log before logging off; back in port, they're asked to post it. `/admin ledger reminders` turns them off.
- `/ship log`: Claude Haiku reads the screenshot (gold, doubloons, emissary, reputation, voyage stats) and shows it privately with Confirm, Edit and Cancel. A confirmed haul replies to the crew card and counts in full for the ship and everyone aboard. One haul per crew; the captain, ship owner or logger can replace it. Works without a screenshot (type it in). Readings count toward Parley's monthly budget. `/admin ledger remove` takes one out.
- `/pirate profile` and `/pirate set` (gamertag and motto): crews sailed, favourite games, ships and plunder.
- The weekly Ship's Log adds the week's plunder; Parley has a `ship_ledger` tool.
- New dependency: Pillow, to shrink big screenshots before they're read. Database migration 16.

## 0.7.2 (2026-09-29): Parley knows what's popular

- New Parley tool, game activity: for each game, crews that set sail and different pirates who sailed in the last 30 days, members following it, and voyages planned in the next 14 days. Ask "what do people play here?"
- Parley always writes slash commands in full (`/crew start`, never just `/crew`).

## 0.7.1 (2026-09-29): Parley without web search

- Kagi is optional. Without `KAGI_API_KEY`, PlunderBot answers from what it knows, says when something may be out of date, and points to the game's forum thread for official news. `/admin parley on` and `status` describe it that way.

## 0.7.0 (2026-09-29): Parley

Phase 6.

- @mention PlunderBot or reply to it and it answers in character, using Claude Haiku 4.5. Replies keep the conversation going.
- Server questions are answered from PlunderBot's own records through tools (voyages, crews, birthdays, games and threads, Notice Board pages, commands); current questions use a Kagi FastGPT web search.
- Limits: $5 a month, 20 replies per member a day, 25 web searches a day, all adjustable with `/admin parley limits`. Spending is tracked per call.
- Public channels only (staff channels left out), not for newcomers on the gangplank, off per channel with `/admin parley channel`. Off until `/admin parley on`.
- New secrets: `ANTHROPIC_API_KEY`, `KAGI_API_KEY`. Without them Parley stays off; everything else carries on.

## 0.6.2 (2026-09-29): Fortnite news

- Fortnite's news now comes built in: Epic's in-game news (the lobby news screen), via fortnite-api.com. No key needed.

## 0.6.1 (2026-09-29): Sturdier news feeds

- The Crow's Nest reads feeds with the usual mistakes in them (HTML entities like `&nbsp;`, stray `&` and control characters), and says plainly when an address sends a web page instead of a feed.

## 0.6.0 (2026-09-29): The Ship's Log and the Crow's Nest

Phase 5.

- The Ship's Log: a weekly roundup (Sunday 6 PM server time by default) of crews that set sail and the busiest games and captain, voyages sailed and coming up, birthdays in the week ahead, new pirates let aboard, the liveliest game threads, and the week's game news. `/admin shipslog channel|when|preview|post`.
- The Crow's Nest: official news and patch notes for each game, posted in its thread in the game forum, checked every 30 minutes. Steam games work out of the box; Fortnite and League of Legends need a feed (`/admin crowsnest source`). Turning it on only notes what's already out, so old posts don't flood the threads. `/admin crowsnest on|off|check|source|preview`.
- Messages in game threads are counted per day (just the count, never the text) for the roundup, and kept 60 days.

## 0.5.5 (2026-09-29): Faster pickers

- Follow games and role-menu pickers answer Discord straight away, so picking many at once no longer times out ("PlunderBot didn't respond in time"). Joining and leaving game threads happens just after the reply.

## 0.5.4 (2026-09-29): Importing MEE6 role menus

- `/colours import` reads menus that list role names instead of mentioning roles (as MEE6's do). Each line's role is found by its name, or, if the role has been renamed since, by the role most of the people who reacted with that emoji wear.
- The reply lists how each role was found and any lines it couldn't match.

## 0.5.3 (2026-09-29): Picture uploads

- Uploaded pictures are recognised from the file itself rather than Discord's label for it, so GIFs and other pictures Discord labels oddly are accepted.
- When a picture is refused, `/noticeboard section image` says why, and the reason is logged.

## 0.5.2 (2026-09-29): Reading old posts

- PlunderBot asks for Discord's Message Content Intent so it can read posts made by other apps (such as MEE6's welcome and rules) when importing them. It's also needed later for Parley and Articles. If the intent is off in the Developer Portal, PlunderBot starts without it and says so in its log.
- `/noticeboard import` and `/colours import` explain when messages look empty because of that setting, instead of importing only the parts they can see.

## 0.5.1 (2026-09-29): Importing picture-and-text posts

- `/noticeboard import` takes an optional `through` link to copy a whole run of messages (up to 50), such as MEE6's welcome post of banner, text, banner, text.
- A picture that stands on its own is kept as a banner above the section that follows it, and posted the same way: the picture, then the text.
- `/noticeboard section image` has a `style` option: a banner above the section, or inside it.
- Pictures are fetched through Discord's own copy first, and the reply says which ones couldn't be copied. A failed import no longer leaves an empty page behind.

## 0.5.0 (2026-09-29): Colours and the Notice Board

Phase 4 complete. Replaces MEE6's reaction roles and embed posts.

- Colours: role menus with a private, pre-ticked picker; pick-one or pick-any; `/colours` to build, post, reorder and import MEE6 reaction-role messages. Mod-level roles and roles above PlunderBot can't be added.
- Onboarding: menus marked for onboarding, and Follow games, appear as buttons on the welcome-aboard message.
- Picking Asia or South America asks which time zone is closest.
- Notice Board: pages of sections written in a pop-up form or imported from an existing message (pictures copied too), posted and then updated in place. `/noticeboard starter` drafts a Pirate's Guide.
- Game Index: every game with its forum thread and ping role, and a Follow games button. `/follow` and the button give a game's ping role and add you to its forum thread.

## 0.4.2 (2026-09-29): Category picker

- `/admin crew category` lists the server's categories itself, since Discord's channel picker often won't select a category (especially one with symbols in its name).

## 0.4.1 (2026-09-29): Pictures and role tags

- `/voyage create`, `/voyage edit` and `/crew start` take a picture for the card. A voyage's picture carries over to its repeats and to the crew card when it sets sail. PlunderBot stores its own copy under /data/images, since Discord's attachment links expire. PNG, JPG, GIF or WEBP up to 10 MB; needs Attach Files.
- Voyages choose when to tag the game's ping role: when posted (default), also at each reminder and when it sails, or never. `/crew start` can skip the role ping with `notify:False`.

## 0.4.0 (2026-09-29): Gangplank

Phase 4, part 1: the airlock in #introductions. Replaces MEE6's welcome message and its "Pending to Full" automation.

- New members get the Pending role and a welcome asking them to read the rules and introduce themselves.
- Harbormasters react Yar to let someone aboard (Pending comes off; they're pointed to role selection, including a region role for their time zone) or Nar to kick them. Works on the introduction or on PlunderBot's welcome.
- No introduction: a reminder after 3 days and a kick after 7, both adjustable. Anyone who has introduced themselves is never auto-kicked.
- Members already wearing Pending are picked up when Gangplank is turned on; their clock starts then, and anyone who already posted in #introductions counts as introduced.
- `/admin gangplank setup|emoji|timing|on|off|status`. Off until turned on.

## 0.3.3 (2026-09-29): More region zones

- Region roles for every North American and Australian zone are recognised by `/admin regions auto`: Hawaii, Alaska, Pacific, Arizona, Mountain, Central, Eastern, Atlantic and Newfoundland; Western, Northern Territory, South Australia, Queensland and Eastern Australia. Arizona, Queensland and the Northern Territory keep their no-daylight-saving time.

## 0.3.2 (2026-09-29): Region roles set time zones

- Region roles now stand for time zones: picking "North America - East" (from the existing reaction menu, or PlunderBot's own menus and onboarding in phase 4) saves Eastern time for that member.
- `/admin regions auto` matches region roles to zones by name; `set`, `clear` and `list` adjust them. Regions too broad for one zone (Asia, South/Central America) are left for members to set themselves.
- Members who already hold a region role are filled in when the mapping changes and whenever PlunderBot starts.
- A zone chosen with `/timezone set` is never overwritten by a role. `/timezone show` says when a zone came from a region role; `/timezone clear` falls back to it.

## 0.3.1 (2026-09-29): Time zones

- Members can save their own time zone with `/timezone set` (Pacific, ET, America/Chicago…), and check or clear it with `/timezone show` and `/timezone clear`.
- Times typed into `/voyage create` and `/voyage edit` are read in the member's own time zone, or in a zone typed with the time (`8pm ET`, `20:00 Europe/London`), falling back to the server's.
- Every time PlunderBot shows is a Discord timestamp, so each member sees it in their own time. The organizer's confirmation shows the time and which zone their typing was read in.
- Autocomplete lists (which can't show timestamps) write times in the member's own zone, with its abbreviation.

## 0.3.0 (2026-09-29): Voyages

Phase 3 of 9. Replaces Apollo.

- `/voyage create|edit|cancel|list`: scheduled sessions for any game, or general server events with no game.
- RSVP card with Aboard, Maybe and Can't make it; seat limits with a waitlist that moves people up automatically.
- A matching Discord Event for every voyage, updated, started, ended and cancelled along with it.
- Reminders before the start (default 1 day and 1 hour; each organizer can set their own or turn them off), pinging Aboard and Maybe.
- At the start the voyage becomes a Crew Call crew: voice channel, crew card for latecomers, pings. The voyage ends when the crew's channel closes.
- Weekly, every-2-weeks and monthly repeats that keep the local time across daylight saving.
- `/admin voyages channel` to post every voyage card in one channel, and `/admin crew channel` for every crew card, including voyages once they set sail.
- Pings to large groups are split across messages to stay under Discord's limits; big crew cards list a few open seats and a count.
- New gauge: `voyages_scheduled`.

## 0.2.1 (2026-09-29): Crew emoji and session names

- Captains can name a session with `/crew start name:` or `/crew rename`; the name goes on the card and the voice channel ("⛵ | Fort Night").
- Crew voice channels are named in the server's style ("⛵ | Boxer's Sloop") with an emoji per game, and per size where a game has named sizes. `/admin crew emoji` picks them, including server emoji for crew cards.

## 0.2.0 (2026-09-29): Crew Call

Phase 2 of 8.

- Game profiles for all 15 of Brimstone Hill's games, with each game's crew sizes and activity tags.
- `/crew start` posts a crew card with Join, Leave, Set Sail and Close buttons that survive restarts. Size and activity are suggested per game as you type.
- A full crew sets sail by itself; sailing opens a voice channel with no user limit, so others can drop in to watch, and pings the crew. Empty crew voice channels are removed after a set time (15 minutes' grace before anyone joins); unsailed calls expire.
- 1 Player Hangout for parallel play: no size limit, voice channel open at once, anyone can join.
- Opt-in ping roles per game, at most one ping per game every 15 minutes.
- `/crew close`, `/crew list`, and `/admin crew category|cleanup|expire|pingrole|autopings`. `autopings` matches existing game roles by name and can create the missing ones.
- New gauges: `crews_mustering`, `crews_sailing`.

## 0.1.0 (2026-09-29): Hull

First build, phase 1 of 8.

- Runs under Exocomp: Dockerfile on `python:3.12-slim` as a non-root user, SQLite in `/data` with append-only migrations, logs to stdout, health check on `/tmp/ready`, Exocomp telemetry attached.
- PlunderBot's voice: a bright, bubbly robot butler with mild pirate cusses, all in `voice.py`.
- `/plunderbot` introduces the butler.
- Birthdays: `/birthday set`, `mine`, `remove` and `upcoming`. Month and day only, no years. February 29 birthdays are toasted on February 28 in common years. A saved birthday can change once every 30 days, with a one-hour window for typo fixes.
- Daily birthday toast at a set hour in the server's time zone, and an optional birthday role worn for the day. It still toasts if the bot was offline at the set hour, and never twice for the same day.
- `/admin` settings for Manage Server: time zone, birthday channel, hour, role, off. The birthday role must be cosmetic and below both PlunderBot's role and the admin's.
