"""Voyages: parsing, reminders, repeats, RSVPs, and the whole life of a voyage with fake Discord objects."""
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import discord
import pytest

from plunderbot import games
from plunderbot.voyage_logic import (ParseError, Rsvps, due_reminder, format_reminders, next_occurrence,
                                     overdue_reminders, parse_date, parse_reminders, parse_time, placement, to_utc)
from tests.test_crew import FakeGuild, FakeResponse, FakeTextChannel, interaction_for

PT = ZoneInfo("America/Los_Angeles")
TUE = date(2026, 9, 29)  # a Tuesday


# ------------------------------------------------------------ parsing
def test_dates():
    assert parse_date("today", TUE) == TUE
    assert parse_date("tomorrow", TUE) == date(2026, 9, 30)
    assert parse_date("friday", TUE) == date(2026, 10, 2)
    assert parse_date("Fri", TUE) == date(2026, 10, 2)
    assert parse_date("tue", TUE) == TUE
    assert parse_date("10/3", TUE) == date(2026, 10, 3)
    assert parse_date("1/5", TUE) == date(2027, 1, 5)  # already passed this year
    assert parse_date("2026-12-24", TUE) == date(2026, 12, 24)
    assert parse_date("12/24/26", TUE) == date(2026, 12, 24)
    for bad in ("someday", "2/30", "13/1"):
        with pytest.raises(ParseError):
            parse_date(bad, TUE)


def test_times():
    assert parse_time("8pm") == time(20, 0)
    assert parse_time("8:30 PM") == time(20, 30)
    assert parse_time("12am") == time(0, 0) and parse_time("12pm") == time(12, 0)
    assert parse_time("20:15") == time(20, 15) and parse_time("7") == time(7, 0)
    assert parse_time("noon") == time(12, 0)
    for bad in ("25:00", "13pm", "8:75", "evening"):
        with pytest.raises(ParseError):
            parse_time(bad)


def test_reminder_parsing():
    assert parse_reminders(None) == [1440, 60]
    assert parse_reminders("2d, 3h 15m, start") == [2880, 180, 15]
    assert parse_reminders("none") == []
    assert format_reminders([1440, 60]) == "1 day, 1 hour before"
    assert format_reminders([2880, 90]) == "2 days, 90 min before"
    for bad in ("soon", "1m", "20d", "1h,2h,3h,4h,5h,6h"):
        with pytest.raises(ParseError):
            parse_reminders(bad)


# ------------------------------------------------------------ reminders and repeats
def test_due_reminders():
    starts = datetime(2026, 10, 2, 3, 0, tzinfo=timezone.utc)
    created = starts - timedelta(days=3)
    mins = [1440, 60]
    assert due_reminder(starts, created, mins, [], starts - timedelta(days=2)) is None
    assert due_reminder(starts, created, mins, [], starts - timedelta(hours=23)) == 1440
    assert due_reminder(starts, created, mins, [1440], starts - timedelta(minutes=59)) == 60
    assert due_reminder(starts, created, mins, [1440, 60], starts - timedelta(minutes=5)) is None
    # Created 2 hours before the start: the 1-day reminder is skipped, not fired late.
    late = starts - timedelta(hours=2)
    assert overdue_reminders(starts, late, mins, [], late) == [1440]
    assert due_reminder(starts, late, mins, [], late) is None
    assert due_reminder(starts, late, mins, [1440], starts - timedelta(minutes=30)) == 60


def test_repeats_keep_local_time_across_daylight_saving():
    first = to_utc(date(2026, 10, 30), time(20, 0), PT)   # PDT
    second = next_occurrence(first, "weekly", PT)           # Nov 6: PST
    assert second.astimezone(PT).hour == 20 and second.astimezone(PT).date() == date(2026, 11, 6)
    assert next_occurrence(first, "biweekly", PT).astimezone(PT).date() == date(2026, 11, 13)
    jan31 = to_utc(date(2027, 1, 31), time(20, 0), PT)
    assert next_occurrence(jan31, "monthly", PT).astimezone(PT).date() == date(2027, 2, 28)
    assert next_occurrence(first, "none", PT) is None


def test_placement():
    r = Rsvps(aboard=[1, 2])
    assert placement("aboard", r, 3) == "aboard"
    assert placement("aboard", r, 2) == "waitlist"
    assert placement("aboard", r, None) == "aboard"
    assert placement("maybe", r, 2) == "maybe"


# ------------------------------------------------------------ the whole voyage, with fakes
class FakeEvent:
    def __init__(self, eid, **fields):
        self.id, self.fields, self.status = eid, fields, discord.EventStatus.scheduled

    async def edit(self, **fields):
        self.fields.update(fields)

    async def start(self):
        self.status = discord.EventStatus.active

    async def end(self):
        self.status = discord.EventStatus.completed

    async def cancel(self):
        self.status = discord.EventStatus.cancelled


class VoyageGuild(FakeGuild):
    def __init__(self, gid, text):
        super().__init__(gid, text)
        self.events = {}
        self.me = SimpleNamespace()
        text.name = "brimstone-events"
        text.permissions_for = lambda me: SimpleNamespace(view_channel=True, send_messages=True, embed_links=True)

    async def create_scheduled_event(self, **fields):
        e = FakeEvent(9000 + len(self.events), **fields)
        self.events[e.id] = e
        return e

    def get_scheduled_event(self, eid):
        return self.events.get(eid)


@pytest.fixture
async def env(tmp_path):
    from plunderbot.bot import COGS, PlunderBot
    from tests.test_bot import make_config
    bot = PlunderBot(make_config(tmp_path))
    await bot.db.connect()
    for cog in COGS:
        await bot.load_extension(cog)
    bot.get_cog("Birthdays").announcer.cancel()
    bot.get_cog("CrewCall").upkeep.cancel()
    cog = bot.get_cog("Voyages")
    cog.clock.cancel()
    bot.get_cog("Gangplank").upkeep.cancel()
    bot.get_cog("ShipsLog").clock.cancel()
    bot.get_cog("CrowsNest").watch.cancel()
    text = FakeTextChannel(20)
    guild = VoyageGuild(10, text)
    guild.members[1] = SimpleNamespace(id=1, display_name="Boxer")
    bot.get_guild = lambda gid: guild if gid == 10 else None
    yield bot, cog, guild, text
    await bot.db.close()


def organizer(guild, uid=1):
    inter = interaction_for(guild, uid, SimpleNamespace(manage_events=False, manage_guild=False,
                                                        administrator=False, manage_channels=False))
    inter.channel = guild.text
    sent = []

    async def followup(content=None, **kw):
        sent.append(content)

    inter.followup = SimpleNamespace(send=followup, sent=sent)
    return inter


async def make_voyage(cog, guild, **kw):
    inter = organizer(guild)
    args = dict(title="Fort Night", date="friday", time="8pm", game=SimpleNamespace(value="sot", name="Sea of Thieves"),
                size="Galleon", seats=None, description="Bring snacks", reminders=None, repeat=None, duration=120)
    args.update(kw)
    await cog.create.callback(cog, inter, **args)
    return inter


async def test_create_rsvp_waitlist_and_promotion(env):
    bot, cog, guild, text = env
    inter = await make_voyage(cog, guild)
    assert inter.followup.sent and "scheduled" in inter.followup.sent[0].lower()
    (v,) = await bot.db.voyages_with_status("scheduled")
    assert v.capacity == 4 and v.reminder_minutes == [1440, 60] and v.message_id and v.event_id
    event = guild.events[v.event_id]
    assert event.fields["name"] == "Fort Night" and "RSVP here" in event.fields["description"]
    assert (await bot.db.rsvps(v.id)).aboard == [1]  # the organizer is aboard

    for uid in (2, 3, 4, 5, 6):
        await cog.on_button(interaction_for(guild, uid), "aboard", v.id)
    r = await bot.db.rsvps(v.id)
    assert r.aboard == [1, 2, 3, 4] and r.waitlist == [5, 6]

    await cog.on_button(interaction_for(guild, 3), "cant", v.id)  # a seat opens
    r = await bot.db.rsvps(v.id)
    assert r.aboard == [1, 2, 4, 5] and r.waitlist == [6] and r.cant == [3]
    assert any("<@5>" in (c or "") and "seat opened" in c for c, _ in text.sent)

    press_again = interaction_for(guild, 2)
    await cog.on_button(press_again, "aboard", v.id)  # pressing your answer again clears it
    assert "cleared" in press_again.response.messages[0].lower()
    r = await bot.db.rsvps(v.id)
    assert 2 not in r.aboard and r.aboard[-1] == 6


async def test_reminders_start_and_end(env):
    bot, cog, guild, text = env
    await make_voyage(cog, guild, repeat=SimpleNamespace(value="weekly", name="Every week"))
    (v,) = await bot.db.voyages_with_status("scheduled")
    await cog.on_button(interaction_for(guild, 2), "aboard", v.id)
    await cog.on_button(interaction_for(guild, 7), "maybe", v.id)
    starts = datetime.fromisoformat(v.starts_at)

    before = len(text.sent)
    await cog.tick(guild, v.id, starts - timedelta(hours=23))
    reminder = text.sent[-1][0]
    assert len(text.sent) == before + 1 and "<@2>" in reminder and "<@7>" in reminder
    v = await bot.db.get_voyage(v.id)
    await cog.tick(guild, v.id, starts - timedelta(hours=22))  # nothing new
    assert len(text.sent) == before + 1

    v = await bot.db.get_voyage(v.id)
    await cog.tick(guild, v.id, starts + timedelta(seconds=30))
    v = await bot.db.get_voyage(v.id)
    assert v.status == "started" and v.crew_id
    crew = await bot.db.get_crew(v.crew_id)
    assert crew.status == "sailing" and set(crew.members) == {1, 2} and crew.title == "Fort Night"
    vc = guild.voices[crew.voice_channel_id]
    assert vc.name == "🚢 | Fort Night"
    assert guild.events[v.event_id].status == discord.EventStatus.active
    assert any("<@7>" in (c or "") and "starting now" in c for c, _ in text.sent)  # the maybe is nudged

    # The weekly repeat was posted with its own card and event.
    upcoming = await bot.db.voyages_with_status("scheduled")
    assert len(upcoming) == 1 and upcoming[0].series_id == v.id
    assert datetime.fromisoformat(upcoming[0].starts_at) - starts == timedelta(days=7)

    await bot.get_cog("CrewCall").end(guild, crew.id, "closed")
    v = await bot.db.get_voyage(v.id)
    assert v.status == "ended" and guild.events[v.event_id].status == discord.EventStatus.completed
    assert vc.deleted


async def test_cancel_and_permissions(env):
    bot, cog, guild, text = env
    await make_voyage(cog, guild, game=None, size=None, repeat=SimpleNamespace(value="weekly", name="Every week"))
    (v,) = await bot.db.voyages_with_status("scheduled")
    assert v.capacity is None and v.game_key is None  # a general event: no seat limit
    await cog.on_button(interaction_for(guild, 2), "aboard", v.id)

    stranger = organizer(guild, uid=2)
    await cog.cancel.callback(cog, stranger, voyage=str(v.id))
    assert "organizer" in stranger.response.messages[0].lower()

    await cog.cancel.callback(cog, organizer(guild), voyage=str(v.id), whole_series=True)
    v = await bot.db.get_voyage(v.id)
    assert v.status == "cancelled" and guild.events[v.event_id].status == discord.EventStatus.cancelled
    assert any("<@2>" in (c or "") and "cancelled" in c for c, _ in text.sent)
    assert await bot.db.voyages_with_status("scheduled") == []  # whole series stopped


async def test_edit_moves_time_and_resets_reminders(env):
    bot, cog, guild, text = env
    await make_voyage(cog, guild)
    (v,) = await bot.db.voyages_with_status("scheduled")
    await bot.db.update_voyage(v.id, reminders_sent="1440")
    await cog.edit.callback(cog, organizer(guild), voyage=str(v.id), time="9:30pm", reminders="2h, 15m", seats=6)
    v2 = await bot.db.get_voyage(v.id)
    assert datetime.fromisoformat(v2.starts_at) - datetime.fromisoformat(v.starts_at) == timedelta(minutes=90)
    assert v2.reminder_minutes == [120, 15] and v2.sent_minutes == [] and v2.capacity == 6
    assert guild.events[v2.event_id].fields["start_time"] == datetime.fromisoformat(v2.starts_at)


async def test_bad_input_is_explained(env):
    bot, cog, guild, text = env
    inter = await make_voyage(cog, guild, date="someday")
    assert "date" in inter.response.messages[0].lower()
    inter = await make_voyage(cog, guild, date="2020-01-01")
    assert "past" in inter.response.messages[0].lower()
    assert await bot.db.voyages_with_status("scheduled") == []


async def test_late_start_is_not_launched(env):
    bot, cog, guild, text = env
    await make_voyage(cog, guild)
    (v,) = await bot.db.voyages_with_status("scheduled")
    await cog.tick(guild, v.id, datetime.fromisoformat(v.starts_at) + timedelta(hours=3))
    v = await bot.db.get_voyage(v.id)
    assert v.status == "ended" and v.crew_id is None and not guild.voices


async def test_autocomplete_lists_only_manageable(env):
    bot, cog, guild, text = env
    await make_voyage(cog, guild)
    mine = organizer(guild)
    choices = await cog._manageable(mine, "")
    assert len(choices) == 1 and choices[0].name.startswith("Fort Night")
    assert await cog._manageable(organizer(guild, uid=99), "") == []


# ------------------------------------------------------------ fixes from review
def test_monthly_repeat_keeps_the_original_day():
    jan31 = to_utc(date(2027, 1, 31), time(20, 0), PT)
    feb = next_occurrence(jan31, "monthly", PT, anchor_day=31)
    mar = next_occurrence(feb, "monthly", PT, anchor_day=31)
    assert feb.astimezone(PT).date() == date(2027, 2, 28) and mar.astimezone(PT).date() == date(2027, 3, 31)


def test_mention_batches_fit_discord_limits():
    from plunderbot.mentions import batches
    ids = list(range(10**17, 10**17 + 200))
    groups = batches(ids, 1800)
    assert sum(len(g) for g in groups) == 200 and len(groups) > 1
    assert all(len(", ".join(f"<@{u}>" for u in g)) <= 1900 for g in groups)


async def test_many_pings_are_split(env):
    bot, cog, guild, text = env
    from plunderbot.mentions import send_pinging
    await send_pinging(text, lambda names: f"Ahoy {names}!", list(range(10**17, 10**17 + 120)))
    assert len(text.sent) > 1 and all(len(c) <= 2000 for c, _ in text.sent)


def test_big_crew_cards_fit():
    from plunderbot.crew_logic import render_card
    from plunderbot.db import Crew
    crew = Crew(id=1, guild_id=1, channel_id=1, message_id=None, captain_id=10**17, game_key="sot",
                size_label="Galleon", capacity=99, activity=None, note=None, status="sailing", voice_channel_id=None,
                voice_empty_since=None, voice_occupied=0, created_at="2026-01-01T00:00:00+00:00",
                expires_at="2026-01-01T01:00:00+00:00", sailed_at=None, ended_at=None,
                members=list(range(10**17, 10**17 + 70)))
    embed = render_card(crew, games.get("sot"))
    assert all(len(f.value) <= 1024 for f in embed.fields) and len(embed) <= 6000


async def test_no_duplicate_repeats_and_cancel_after_start(env):
    bot, cog, guild, text = env
    await make_voyage(cog, guild, repeat=SimpleNamespace(value="weekly", name="Every week"))
    (v,) = await bot.db.voyages_with_status("scheduled")
    await cog.tick(guild, v.id, datetime.fromisoformat(v.starts_at) + timedelta(seconds=5))
    started = await bot.db.get_voyage(v.id)
    await cog.schedule_next(guild, started)  # e.g. the sweep: must not add a second one
    assert len(await bot.db.voyages_with_status("scheduled")) == 1
    late = organizer(guild)
    await cog.cancel.callback(cog, late, voyage=str(v.id))
    assert (await bot.db.get_voyage(v.id)).status == "started"
    assert len(await bot.db.voyages_with_status("scheduled")) == 1


async def test_failed_launch_ends_the_voyage(env):
    bot, cog, guild, text = env
    await make_voyage(cog, guild)
    (v,) = await bot.db.voyages_with_status("scheduled")

    async def boom(*a, **k):
        raise RuntimeError("no crew today")

    bot.get_cog("CrewCall").launch_for_voyage = boom
    await cog.tick(guild, v.id, datetime.fromisoformat(v.starts_at) + timedelta(seconds=5))
    v = await bot.db.get_voyage(v.id)
    assert v.status == "ended" and guild.events[v.event_id].status == discord.EventStatus.completed


async def test_weekday_today_after_the_time_means_next_week(env):
    bot, cog, guild, text = env
    now_local = datetime.now(PT)
    today_name = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][now_local.weekday()]
    past = (now_local - timedelta(minutes=10))
    if past.date() != now_local.date():
        pytest.skip("too close to midnight")
    await make_voyage(cog, guild, date=today_name, time=past.strftime("%H:%M"))
    (v,) = await bot.db.voyages_with_status("scheduled")
    assert datetime.fromisoformat(v.starts_at).astimezone(PT).date() == now_local.date() + timedelta(days=7)


async def test_voyage_crew_card_goes_to_the_crew_channel(env):
    bot, cog, guild, text = env
    lfg = FakeTextChannel(30)
    lfg.name = "looking-for-group"
    lfg.permissions_for = text.permissions_for
    crew_cog = bot.get_cog("CrewCall")
    crew_cog.crew_channel = lambda g, s: lfg if s.crew_channel_id == 30 else None
    real_get = guild.get_channel
    guild.get_channel = lambda cid: lfg if cid == 30 else real_get(cid)
    await bot.db.update_settings(10, crew_channel_id=30)
    await make_voyage(cog, guild)
    (v,) = await bot.db.voyages_with_status("scheduled")
    assert v.channel_id == 20  # the voyage card stays in #brimstone-events
    await cog.tick(guild, v.id, datetime.fromisoformat(v.starts_at) + timedelta(seconds=5))
    v = await bot.db.get_voyage(v.id)
    crew = await bot.db.get_crew(v.crew_id)
    assert crew.channel_id == 30 and lfg.sent  # crew card and sailing ping in #looking-for-group
    edits = text.get_partial_message(v.message_id).edits
    crew_field = [f for f in edits[-1]["embed"].fields if f.name == "Crew"]
    assert crew_field and "/30/" in crew_field[0].value


# ------------------------------------------------------------ time zones
def test_typed_zones():
    from plunderbot.voyage_logic import split_zone, zone_label
    assert split_zone("8pm") == ("8pm", None)
    t, tz = split_zone("8pm ET")
    assert t == "8pm" and tz.key == "America/New_York"
    assert split_zone("20:00 Europe/London")[1].key == "Europe/London"
    assert split_zone("8 pm")[1] is None and split_zone("8 pm")[0] == "8 pm"
    with pytest.raises(ParseError):
        split_zone("8pm Narnia")
    assert zone_label(ZoneInfo("America/Los_Angeles"), datetime(2026, 7, 1, tzinfo=timezone.utc)) == \
        "America/Los_Angeles (PDT)"


async def test_times_are_read_in_the_members_zone(env):
    bot, cog, guild, text = env
    await bot.db.set_member_timezone(1, "America/New_York")
    inter = await make_voyage(cog, guild, date="2026-12-24", time="8pm")
    (v,) = await bot.db.voyages_with_status("scheduled")
    assert datetime.fromisoformat(v.starts_at) == datetime(2026, 12, 25, 1, 0, tzinfo=timezone.utc)
    assert "<t:" in inter.followup.sent[0] and "your saved time zone" in inter.followup.sent[0]
    # A zone typed with the time beats the saved one.
    await cog.cancel.callback(cog, organizer(guild), voyage=str(v.id), whole_series=True)
    inter = await make_voyage(cog, guild, date="2026-12-24", time="8pm PT")
    (v,) = await bot.db.voyages_with_status("scheduled")
    assert datetime.fromisoformat(v.starts_at) == datetime(2026, 12, 25, 4, 0, tzinfo=timezone.utc)
    # Without a saved zone, the server's is used and the reply says so.
    await bot.db.set_member_timezone(1, None)
    await cog.edit.callback(cog, organizer(guild), voyage=str(v.id), time="9pm")
    v = await bot.db.get_voyage(v.id)
    assert datetime.fromisoformat(v.starts_at) == datetime(2026, 12, 25, 5, 0, tzinfo=timezone.utc)


async def test_timezone_commands(env):
    bot, cog, guild, text = env
    core = bot.get_cog("Core")
    inter = interaction_for(guild, 5)
    await core.tz_set.callback(core, inter, zone="ET")
    assert await bot.db.member_timezone(5) == "America/New_York"
    bad = interaction_for(guild, 5)
    await core.tz_set.callback(core, bad, zone="Narnia")
    assert "don't know" in bad.response.messages[0]
    choices = await core.tz_ac.callback(core, inter, "chicago") if hasattr(core.tz_ac, "callback") else \
        await core.tz_ac(inter, "chicago")
    assert any(c.value == "America/Chicago" for c in choices)
