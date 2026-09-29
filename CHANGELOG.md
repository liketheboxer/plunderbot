# Changelog

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
