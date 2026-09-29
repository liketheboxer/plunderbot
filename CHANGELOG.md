# Changelog

## 0.1.0 (2026-09-29): Hull

First build, phase 1 of 8.

- Runs under Exocomp: Dockerfile on `python:3.12-slim` as a non-root user, SQLite in `/data` with append-only migrations, logs to stdout, health check on `/tmp/ready`, Exocomp telemetry attached.
- PlunderBot's voice: a bright, bubbly robot butler with mild pirate cusses, all in `voice.py`.
- `/plunderbot` introduces the butler.
- Birthdays: `/birthday set`, `mine`, `remove` and `upcoming`. Month and day only, no years. February 29 birthdays are toasted on February 28 in common years. A saved birthday can change once every 30 days, with a one-hour window for typo fixes.
- Daily birthday toast at a set hour in the server's time zone, and an optional birthday role worn for the day. It still toasts if the bot was offline at the set hour, and never twice for the same day.
- `/admin` settings for Manage Server: time zone, birthday channel, hour, role, off. The birthday role must be cosmetic and below both PlunderBot's role and the admin's.
