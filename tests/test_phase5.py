"""Phase 5: the Ship's Log weekly roundup and the Crow's Nest game news."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import discord
import pytest

from plunderbot.crew_logic import iso
from plunderbot.news_logic import (NewsItem, clean, first_image, new_items, parse_feed, parse_steam, source_for,
                                   STEAM_APPS)
from plunderbot.shipslog_logic import WeekStats, crew_lines, is_due, render

PT = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 10, 4, 18, 5, tzinfo=PT).astimezone(timezone.utc)  # a Sunday evening


# ------------------------------------------------------------ Ship's Log rules
def test_is_due():
    sun6 = datetime(2026, 10, 4, 18, 0, tzinfo=PT)
    assert is_due(sun6, 6, 18, None)
    assert not is_due(sun6, 6, 18, "2026-10-04")  # already posted today
    assert is_due(sun6, 6, 18, "2026-09-27")
    assert not is_due(sun6 - timedelta(hours=1), 6, 18, None)  # too early
    assert not is_due(sun6 + timedelta(days=1), 6, 18, None)  # Monday


def crew(cid, captain, game, members):
    return SimpleNamespace(id=cid, captain_id=captain, game_key=game, members=members)


def test_crew_lines():
    lines = crew_lines([crew(1, 7, "sot", [7, 8]), crew(2, 7, "sot", [7, 9]), crew(3, 8, "drg", [8])])
    assert lines[0] == "**3** crews set sail with **3** pirates aboard."
    assert "Sea of Thieves (2)" in lines[1] and "Deep Rock Galactic (1)" in lines[1]
    assert lines[2] == "Busiest captain: <@7> with 2 crews"
    assert crew_lines([]) == []


def test_render_all_sections_and_quiet():
    v = SimpleNamespace(starts_at=iso(NOW), guild_id=1, channel_id=2, message_id=3, title="Fort Night")
    stats = WeekStats(week_start=date(2026, 9, 27), crews=[crew(1, 7, "sot", [7])], voyages_done=[v],
                      voyages_ahead=[v], birthdays=[(7, date(2026, 10, 6))], newcomers=[9], threads={55: 12},
                      news=[("sot", "Season 18", "https://x")])
    e = render(stats, "Ahoy!")
    assert e.title == "Ship's Log · week of September 27"
    names = [f.name for f in e.fields]
    assert names == ["⚓ On the water", "🗺️ Voyages sailed", "🧭 Coming up this week", "🎂 Birthdays this week",
                     "🏴‍☠️ New pirates aboard", "💬 Liveliest game threads", "🔭 From the Crow's Nest"]
    assert "[Fort Night](https://discord.com/channels/1/2/3)" in e.fields[1].value
    assert "Tuesday October 6" in e.fields[3].value
    assert "Sea of Thieves: [Season 18](https://x)" in e.fields[6].value
    assert len(e) <= 6000
    assert WeekStats(week_start=date(2026, 9, 27)).quiet


def test_long_lists_are_trimmed():
    v = SimpleNamespace(starts_at=iso(NOW), guild_id=1, channel_id=2, message_id=3, title="x" * 80)
    e = render(WeekStats(week_start=date(2026, 9, 27), voyages_done=[v] * 40), "Ahoy!")
    assert len(e.fields[0].value) <= 1024 and "more" in e.fields[0].value


# ------------------------------------------------------------ Crow's Nest parsing
STEAM = {"appnews": {"newsitems": [
    {"gid": "111", "title": "Patch 3.2 Notes", "url": "https://store.steampowered.com/news/1",
     "feedname": "steam_community_announcements", "date": 1790000000,
     "contents": "[img]{STEAM_CLAN_IMAGE}/42/banner.png[/img][p]Ahoy pirates![/p][list][*]Fixed sails[*]New "
                 "cosmetics[/list][url=https://x.com]Read more[/url]"},
    {"gid": "222", "title": "Press coverage", "url": "https://pc.example", "feedname": "pcgamer",
     "date": 1790000500, "contents": "Someone else's article"},
]}}


def test_parse_steam():
    (item,) = parse_steam(STEAM)
    assert item.id == "111" and item.title == "Patch 3.2 Notes"
    assert item.image == "https://clan.akamai.steamstatic.com/images/42/banner.png"
    assert "Ahoy pirates!" in item.summary and "• Fixed sails" in item.summary and "[" not in item.summary
    assert item.published.year == 2026


RSS = """<?xml version="1.0"?><rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel>
<item><title>Patch 25.19 notes</title><link>https://lol.example/patch-25-19</link>
<guid>lol-2519</guid><pubDate>Tue, 29 Sep 2026 17:00:00 GMT</pubDate>
<description>&lt;p&gt;Big &lt;b&gt;changes&lt;/b&gt; to the jungle.&lt;/p&gt;</description>
<media:thumbnail url="https://lol.example/2519.jpg"/></item></channel></rss>"""

ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>v1.2 is out</title>
<link rel="alternate" href="https://game.example/v12"/><id>tag:game,2026:12</id>
<updated>2026-09-28T10:00:00Z</updated><summary>New map &amp; fixes</summary></entry></feed>"""


def test_parse_rss_and_atom():
    (r,) = parse_feed(RSS)
    assert (r.id, r.title, r.url) == ("lol-2519", "Patch 25.19 notes", "https://lol.example/patch-25-19")
    assert r.summary == "Big changes to the jungle." and r.image == "https://lol.example/2519.jpg"
    assert r.published == datetime(2026, 9, 29, 17, tzinfo=timezone.utc)
    (a,) = parse_feed(ATOM)
    assert (a.id, a.url, a.summary) == ("tag:game,2026:12", "https://game.example/v12", "New map & fixes")


def test_clean_and_images():
    assert clean("word " * 200).endswith("…") and len(clean("word " * 200)) <= 351
    assert first_image('<p><img src="https://x/y.png"></p>') == "https://x/y.png"
    assert first_image("no pictures") is None


def test_sources_and_new_items():
    assert source_for("sot", {}) == ("steam", "1172620")
    assert source_for("fortnite", {}) is None
    assert source_for("fortnite", {"fortnite": ("feed", "https://f.example/rss")}) == ("feed", "https://f.example/rss")
    assert source_for("sot", {"sot": ("none", None)}) is None
    assert all(isinstance(v, int) for v in STEAM_APPS.values())
    t = lambda d: datetime(2026, 9, d, tzinfo=timezone.utc)  # noqa: E731
    items = [NewsItem(str(d), f"n{d}", "", t(d), "") for d in (5, 3, 4, 1, 2)]
    assert [i.id for i in new_items(items, {"1"}, limit=3)] == ["2", "3", "4"]


# ------------------------------------------------------------ the cogs, with fakes
@pytest.fixture
async def bot(tmp_path):
    from tests.test_bot import make_config
    from plunderbot.bot import PlunderBot
    b = PlunderBot(make_config(tmp_path))
    await b.db.connect()
    for ext in ("noticeboard", "shipslog", "crowsnest"):
        await b.load_extension(f"plunderbot.cogs.{ext}")
    b.get_cog("ShipsLog").clock.cancel()
    b.get_cog("CrowsNest").watch.cancel()
    yield b
    await b.db.close()


class Channel:
    def __init__(self, cid):
        self.id, self.sent = cid, []

    async def send(self, content=None, **kw):
        self.sent.append((content, kw))
        return SimpleNamespace(jump_url="https://discord.com/x")


async def test_shipslog_gathers_the_week(bot):
    db = bot.db
    await db.update_settings(5, timezone="America/Los_Angeles", shipslog_channel_id=80, forum_channel_id=60,
                             pending_role_id=50)
    c = await db.create_crew(guild_id=5, channel_id=1, captain_id=7, game_key="sot", size_label="Sloop",
                             capacity=2, activity=None, note=None, created_at=iso(NOW - timedelta(days=2)),
                             expires_at=iso(NOW))
    await db.update_crew(c.id, sailed_at=iso(NOW - timedelta(days=2)))
    old = await db.create_crew(guild_id=5, channel_id=1, captain_id=8, game_key="drg", size_label="Team",
                               capacity=4, activity=None, note=None, created_at=iso(NOW - timedelta(days=9)),
                               expires_at=iso(NOW))
    await db.update_crew(old.id, sailed_at=iso(NOW - timedelta(days=9)))  # last week's: left out
    await db.set_birthday(5, 7, 10, 6)
    day = (NOW - timedelta(days=1)).date().isoformat()
    for _ in range(3):
        await db.count_thread_message(5, day, 61)
    pending = SimpleNamespace(id=50)
    members = {7: SimpleNamespace(id=7, bot=False, joined_at=NOW - timedelta(days=400), get_role=lambda r: None),
               9: SimpleNamespace(id=9, bot=False, joined_at=NOW - timedelta(days=2), get_role=lambda r: None),
               10: SimpleNamespace(id=10, bot=False, joined_at=NOW - timedelta(days=1),
                                   get_role=lambda r: pending if r == 50 else None)}
    channel = Channel(80)
    guild = SimpleNamespace(id=5, members=list(members.values()), get_member=members.get,
                            get_channel=lambda cid: channel if cid == 80 else None,
                            get_channel_or_thread=lambda cid: object() if cid == 61 else None)
    cog = bot.get_cog("ShipsLog")
    stats = await cog.gather(guild, NOW)
    assert [x.id for x in stats.crews] == [c.id]
    assert [u for u, _ in stats.birthdays] == [7]
    assert stats.newcomers == [9]  # 10 is still on the gangplank
    assert stats.threads == {61: 3}
    await cog.post(guild, NOW)
    (_, kw), = channel.sent
    assert kw["embed"].title.startswith("Ship's Log") and kw["allowed_mentions"].users is False


async def test_thread_messages_are_counted_only_in_the_game_forum(bot):
    await bot.db.update_settings(5, forum_channel_id=60)
    cog = bot.get_cog("ShipsLog")

    class Thread(discord.Thread):
        def __init__(self, tid, parent):
            self.id, self.parent_id = tid, parent

    def msg(channel):
        return SimpleNamespace(guild=SimpleNamespace(id=5), author=SimpleNamespace(bot=False), channel=channel,
                               created_at=NOW)

    await cog.on_message(msg(Thread(61, 60)))
    await cog.on_message(msg(Thread(62, 99)))  # a thread elsewhere
    await cog.on_message(msg(SimpleNamespace(id=70)))  # a plain channel
    assert await bot.db.thread_activity(5, "2026-01-01", "2027-01-01") == {61: 1}


async def test_crowsnest_first_look_then_new_posts(bot, monkeypatch):
    await bot.db.update_settings(5, forum_channel_id=60, crowsnest_enabled=1)
    cog = bot.get_cog("CrowsNest")
    thread = Channel(61)
    entries = [{"key": "sot", "name": "Sea of Thieves", "thread": thread},
               {"key": "fortnite", "name": "Fortnite", "thread": Channel(62)},
               {"key": "drg", "name": "Deep Rock Galactic", "thread": None}]

    async def fake_entries(guild):
        return entries

    feed = [NewsItem("1", "Old news", "https://x/1", datetime(2026, 9, 1, tzinfo=timezone.utc), "old")]

    async def fake_fetch(source):
        assert source == ("steam", "1172620")
        return list(feed)

    monkeypatch.setattr(cog, "entries", fake_entries)
    monkeypatch.setattr(cog, "fetch", fake_fetch)
    guild = SimpleNamespace(id=5)
    notes = await cog.check(guild)
    assert notes["sot"].startswith("watching") and not thread.sent
    assert notes["fortnite"] == "no news source" and notes["drg"] == "no forum thread"
    feed.append(NewsItem("2", "Season 18", "https://x/2", datetime(2026, 10, 1, tzinfo=timezone.utc), "Ahoy",
                         "https://x/2.png"))
    notes = await cog.check(guild)
    assert notes["sot"] == "1 new post(s)"
    content, kw = thread.sent[0]
    assert "Sea of Thieves" in content and kw["embed"].title == "Season 18" and kw["embed"].image.url
    assert (await cog.check(guild))["sot"] == "nothing new"
    logged = await bot.db.news_posted_between(5, "2026-01-01", "2030-01-01")
    assert logged == [("sot", "Season 18", "https://x/2")]
