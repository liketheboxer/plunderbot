"""Daisho sync: snapshots out, changes in. Daisho and Discord are faked."""
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import discord
import pytest

from plunderbot import links
from plunderbot.crew_logic import iso


# ------------------------------------------------------------ fakes
class FakeClient:
    def __init__(self, changes=()):
        self.queue = list(changes)
        self.results, self.snapshots = [], []

    async def changes(self):
        out, self.queue = self.queue, []
        return out

    async def result(self, cid, status, message):
        self.results.append((cid, status, message))

    async def snapshot(self, guild_id, sections):
        self.snapshots.append(sections)
        return {"ok": True}

    async def close(self):
        pass


PERMS = SimpleNamespace(view_channel=True, send_messages=True, embed_links=True, attach_files=True,
                        manage_channels=True)


class Text(discord.TextChannel):
    def __init__(self, cid, name, category=None):
        self.id, self.name, self._type, self.position = cid, name, 0, cid
        self._cat, self.sent = category, []

    @property
    def category(self):
        return self._cat

    def permissions_for(self, who):
        return PERMS

    async def send(self, content=None, **kw):
        self.sent.append((content, kw))
        return SimpleNamespace(id=5000 + len(self.sent))

    def get_partial_message(self, mid):
        async def edit(**kw):
            pass

        async def delete():
            pass
        return SimpleNamespace(id=mid, edit=edit, delete=delete)


class Category(discord.CategoryChannel):
    def __init__(self, cid, name):
        self.id, self.name, self.position = cid, name, cid

    @property
    def type(self):
        return discord.ChannelType.category

    @property
    def category(self):
        return None

    def permissions_for(self, who):
        return PERMS


class Role:
    def __init__(self, rid, name, position=1, default=False):
        self.id, self.name, self.position, self.managed, self._default = rid, name, position, False, default
        self.permissions = discord.Permissions.none()

    def is_default(self):
        return self._default

    def __ge__(self, other):
        return self.position >= other.position


class Guild:
    def __init__(self):
        self.id, self.name, self.member_count, self.unavailable = 10, "Brimstone Hill Fortress", 65, False
        cat = Category(7, "◑~ Voice Channels")
        self.chans = {20: Text(20, "looking-for-group"), 21: Text(21, "announcements"), 7: cat}
        self.roles = [Role(1, "@everyone", 0, default=True), Role(30, "Harbormasters", 5), Role(31, "Bruh Lord", 2)]
        self.me = SimpleNamespace(id=999, top_role=Role(0, "PlunderBot", 50))
        self.emojis = []
        self.members = {1: SimpleNamespace(id=1, display_name="Boxer")}

    @property
    def channels(self):
        return list(self.chans.values())

    def get_channel(self, cid):
        return self.chans.get(cid)

    get_channel_or_thread = get_channel

    def get_role(self, rid):
        return next((r for r in self.roles if r.id == rid), None)

    def get_member(self, uid):
        return self.members.get(uid)


@pytest.fixture
async def env(tmp_path):
    from tests.test_bot import make_config
    from plunderbot.bot import COGS, PlunderBot
    cfg = replace(make_config(tmp_path), samurai_url="https://daisho.test", module_token="tmm1.x",
                  samurai_public_url="https://daisho.test", unit="plunderbot")
    bot = PlunderBot(cfg)
    await bot.db.connect()
    for c in COGS:
        await bot.load_extension(c)
    for name, loop in (("Birthdays", "announcer"), ("CrewCall", "upkeep"), ("Voyages", "clock"),
                       ("Gangplank", "upkeep"), ("ShipsLog", "clock"), ("CrowsNest", "watch"), ("Articles", "clock"),
                       ("Daisho", "loop")):
        getattr(bot.get_cog(name), loop).cancel()
    cog = bot.get_cog("Daisho")
    cog.client = FakeClient()
    guild = Guild()
    yield bot, cog, guild
    links.configure(None, "plunderbot", False)
    await bot.db.close()


# ------------------------------------------------------------ snapshots
async def test_snapshots_go_out_once_then_only_when_changed(env):
    bot, cog, guild = env
    await bot.db.update_settings(10, crew_channel_id=20, timezone="America/Los_Angeles")
    await cog.run_once(guild, now=0)
    sent = cog.client.snapshots[-1]
    assert set(sent) == {"guild", "settings", "articles", "pages", "voyages", "crews", "ledger", "menus"}
    g = sent["guild"]
    assert {"id": 20, "name": "looking-for-group", "type": "text", "category": None} in g["channels"]
    assert {"id": 7, "name": "◑~ Voice Channels", "type": "category", "category": None} in g["channels"]
    assert [r["name"] for r in g["roles"]] == ["Harbormasters", "Bruh Lord"]   # no @everyone
    assert sent["settings"]["crew_channel_id"] == 20 and "parley_spend" in sent["settings"]
    json.dumps(sent)                                                              # all JSON-friendly

    await cog.run_once(guild, now=10)          # nothing changed, nothing marked: nothing sent
    assert len(cog.client.snapshots) == 1
    await bot.db.create_ship(guild_id=10, owner_id=1, name="Depth Charge", kind="Sloop", motto=None, image=None,
                             created_at=iso(datetime.now(timezone.utc)))
    await cog.run_once(guild, now=400)         # the five-minute pass sends what changed, and only that
    assert set(cog.client.snapshots[-1]) == {"ledger"}
    assert cog.client.snapshots[-1]["ledger"]["ships"][0]["name"] == "Depth Charge"
    await cog.run_once(guild, now=2000)        # the half-hour pass sends everything
    assert len(cog.client.snapshots[-1]) == 8


async def test_daisho_down_never_stops_the_bot(env):
    bot, cog, guild = env

    class Down(FakeClient):
        async def changes(self):
            raise RuntimeError("connection refused")
    cog.client = Down()
    bot.get_guild = lambda gid: guild
    type(bot).guilds = property(lambda self: [guild])
    try:
        await cog.loop.coro(cog)       # logs once and carries on
        assert cog.failing
    finally:
        del type(bot).guilds


# ------------------------------------------------------------ changes
_ids = iter(range(1, 10_000))


async def run(cog, guild, *changes):
    cog.client.queue = [dict(id=next(_ids), section=c[0], action=c[1], payload=c[2], by="Boxer") for c in changes]
    cog.client.results.clear()
    await cog.run_once(guild, now=0)
    return cog.client.results


async def test_settings_changes_are_checked_and_applied(env):
    bot, cog, guild = env
    res = await run(cog, guild,
                    ("settings", "settings.update", {"fields": {"crew_category_id": 7, "crew_cleanup_minutes": 10}}),
                    ("settings", "settings.update", {"fields": {"crew_cleanup_minutes": 500}}),
                    ("settings", "settings.update", {"fields": {"crew_channel_id": 404}}),
                    ("settings", "settings.update", {"fields": {"is_owner": 1}}),
                    ("settings", "settings.update", {"fields": {"gangplank_enabled": 1}}),
                    ("settings", "settings.update", {"fields": {"parley_enabled": 1}}),
                    ("settings", "settings.update", {"fields": {"timezone": "Mars/Olympus"}}))
    assert [r[1] for r in res] == ["applied", "failed", "failed", "failed", "failed", "failed", "failed"]
    s = await bot.db.get_settings(10)
    assert s.crew_category_id == 7 and s.crew_cleanup_minutes == 10
    assert "between 1 and 120" in res[1][2] and "no longer exists" in res[2][2]
    assert "Gangplank needs" in res[4][2] and "ANTHROPIC_API_KEY" in res[5][2]
    assert cog.client.snapshots[-1]["settings"]["crew_category_id"] == 7        # sent straight back
    res = await run(cog, guild, ("x", "planet.destroy", {}))
    assert res[0][1] == "failed" and "Refit" in res[0][2]


async def test_articles_saved_from_daisho_follow_the_same_rules(env):
    bot, cog, guild = env
    guild.emojis = [SimpleNamespace(id=77, name="Bruh", animated=False, __str__=lambda self: "<:Bruh:77>")]

    class E:
        id, name, animated = 77, "Bruh", False

        def __str__(self):
            return "<:Bruh:77>"
    guild.emojis = [E()]
    art = {"name": "Bruh", "trigger": "keyword", "value": "bruh, Bruv", "match": "word", "threshold": 1,
           "cooldown": 0, "cooldown_scope": "channel", "chance": 100, "channels": [20], "only_role_id": None,
           "enabled": True, "actions": [{"type": "reply", "texts": [":Bruh:"]}, {"type": "count", "scope": "member"}]}
    res = await run(cog, guild, ("articles", "article.save", art),
                    ("articles", "article.save", {**art, "name": "Other", "actions": [{"type": "pin"}] * 9}),
                    ("articles", "article.save", {**art, "name": "Joiner", "trigger": "join",
                                                  "actions": [{"type": "pin"}]}),
                    ("articles", "article.save", {**art, "name": "bruh"}))
    assert [r[1] for r in res] == ["applied", "failed", "failed", "failed"]
    assert "at most 8" in res[1][2] and "no message" in res[2][2] and "already" in res[3][2]
    a = await bot.db.article_named(10, "Bruh")
    assert a.value == "bruh, bruv" and a.channel_ids == [20]
    assert a.action_list[0]["texts"] == [":Bruh:"] and a.action_list[1] == {"type": "count", "scope": "member"}
    sent = cog.client.snapshots[-1]["articles"]
    assert sent[0]["name"] == "Bruh" and sent[0]["actions"][1]["type"] == "count"

    res = await run(cog, guild, ("articles", "article.save", {**art, "id": a.id, "enabled": False, "chance": 50,
                                                               "actions": [{"type": "react", "emoji": ":Bruh:"}]}))
    a = await bot.db.get_article(a.id)
    assert res[0][1] == "applied" and not a.enabled and a.chance == 50
    assert a.action_list == [{"type": "react", "emoji": "<:Bruh:77>"}]
    sched = {**art, "name": "Supplies", "trigger": "schedule", "value": "daily 8pm",
             "actions": [{"type": "reply", "texts": ["Supplies must be dwindling!"], "channel_id": 21}]}
    res = await run(cog, guild, ("articles", "article.save", sched))
    assert res[0][1] == "applied" and (await bot.db.article_named(10, "Supplies")).next_run
    res = await run(cog, guild, ("articles", "article.delete", {"id": a.id}),
                    ("articles", "article.delete", {"id": a.id}))
    assert [r[1] for r in res] == ["applied", "applied"] and await bot.db.get_article(a.id) is None


async def test_pages_saved_and_posted_from_daisho(env):
    bot, cog, guild = env
    page = await bot.db.create_page(10, "guide", "Pirate's Guide")
    first = await bot.db.add_section(page.id, "Ahoy", "Welcome aboard.")
    second = await bot.db.add_section(page.id, "Rules", "Be kind.")
    res = await run(cog, guild, ("pages", "page.save", {"id": page.id, "title": "The Pirate's Guide", "sections": [
        {"id": second.id, "heading": "Rules", "body": "Be kind. Share the loot.", "colour": "#D4A017"},
        {"heading": "New!", "body": "Fresh section", "image_style": "inside"}]}))
    assert res[0][1] == "applied"
    page = await bot.db.get_page(page.id)
    assert page.title == "The Pirate's Guide"
    assert [s.heading for s in page.sections] == ["Rules", "New!"]
    assert page.sections[0].colour == 0xD4A017 and first.id not in [s.id for s in page.sections]
    res = await run(cog, guild, ("pages", "page.save", {"id": page.id, "sections": [{"heading": "", "body": ""}]}),
                    ("pages", "page.save", {"id": page.id, "sections": [{"heading": "x", "colour": "blurple"}]}))
    assert [r[1] for r in res] == ["failed", "failed"]
    res = await run(cog, guild, ("pages", "page.post", {"id": page.id}),
                    ("pages", "page.post", {"id": page.id, "channel_id": 21}))
    assert res[0][1] == "failed" and "channel" in res[0][2]
    assert res[1][1] == "applied" and guild.chans[21].sent
    assert (await bot.db.get_page(page.id)).channel_id == 21


async def test_voyages_crews_and_the_ledger_from_daisho(env, monkeypatch):
    bot, cog, guild = env
    vcog = bot.get_cog("Voyages")
    edits, cancels = [], []

    async def fake_edit(g, vid, changes):
        edits.append(changes)
        return await bot.db.update_voyage(vid, **changes)

    async def fake_cancel(g, vid, whole):
        cancels.append((vid, whole))
        return True
    monkeypatch.setattr(vcog, "apply_edit", fake_edit)
    monkeypatch.setattr(vcog, "apply_cancel", fake_cancel)
    now = datetime.now(timezone.utc)
    v = await bot.db.create_voyage(guild_id=10, channel_id=21, organizer_id=1, title="Fort Night", description=None,
                                   game_key="sot", size_label="Galleon", capacity=4, starts_at=iso(now + timedelta(days=2)),
                                   duration_min=120, reminders="1440,60", reminders_sent="", repeat="none",
                                   series_id=None, status="scheduled", created_at=iso(now))
    later = (now + timedelta(days=3)).replace(microsecond=0)
    res = await run(cog, guild, ("voyages", "voyage.update", {"id": v.id, "title": "Fort Night!", "starts_at": later.isoformat(),
                                                             "reminders": "2h, 15m", "capacity": 6}),
                    ("voyages", "voyage.update", {"id": v.id, "starts_at": (now - timedelta(hours=1)).isoformat()}),
                    ("voyages", "voyage.update", {"id": v.id, "reminders": "every tuesday"}),
                    ("voyages", "voyage.cancel", {"id": v.id, "whole_series": True}))
    assert [r[1] for r in res] == ["applied", "failed", "failed", "applied"]
    assert edits[0] == {"title": "Fort Night!", "starts_at": iso(later), "reminders_sent": "", "reminders": "120,15",
                        "capacity": 6}
    assert cancels == [(v.id, True)]
    sent = cog.client.snapshots[-1]["voyages"][0]
    assert sent["title"] == "Fort Night!" and sent["reminders"] == "2h, 15m"

    crew = await bot.db.create_crew(guild_id=10, channel_id=20, captain_id=1, game_key="sot", size_label="Sloop",
                                    capacity=2, activity=None, note=None, created_at=iso(now),
                                    expires_at=iso(now + timedelta(hours=1)))
    ended = []

    async def fake_end(g, cid, status):
        ended.append(cid)
        await bot.db.update_crew(cid, status=status)
    monkeypatch.setattr(bot.get_cog("CrewCall"), "end", fake_end)
    res = await run(cog, guild, ("crews", "crew.close", {"id": crew.id}), ("crews", "crew.close", {"id": crew.id}))
    assert [r[1] for r in res] == ["applied", "applied"] and ended == [crew.id]

    ship = await bot.db.create_ship(guild_id=10, owner_id=1, name="Depth Charge", kind="Sloop", motto=None,
                                    image=None, created_at=iso(now))
    e = await bot.db.create_log(guild_id=10, crew_id=None, ship_id=ship.id, logged_by=1, created_at=iso(now),
                                source="manual", gold=392040, doubloons=0, emissary=None, reputation="[]",
                                stats="[]", pirates=[1])
    await bot.db.update_log(e.id, status="confirmed", confirmed_at=iso(now))
    res = await run(cog, guild, ("ledger", "ship.update", {"id": ship.id, "name": "Depth Charge II", "kind": "Brigantine"}),
                    ("ledger", "ship.update", {"id": ship.id, "kind": "Rowboat"}),
                    ("ledger", "log.remove", {"id": e.id}))
    assert [r[1] for r in res] == ["applied", "failed", "applied"]
    assert (await bot.db.get_ship(ship.id)).kind == "Brigantine" and await bot.db.get_log(e.id) is None


# ------------------------------------------------------------ Manage buttons
async def test_manage_buttons_only_once_connected(env):
    from plunderbot.cogs.voyages import voyage_view
    from plunderbot.cogs.crew import card_view
    bot, cog, guild = env
    assert links.manage("voyages", 5) == "https://daisho.test/m/plunderbot/plunderbot/voyages/5"
    v = SimpleNamespace(id=5, status="scheduled")
    view = voyage_view(v)
    assert [getattr(i, "url", None) for i in view.children][-1] == "https://daisho.test/m/plunderbot/plunderbot/voyages/5"
    crew = SimpleNamespace(id=9, active=True, full=False, status="open", game_key="sot")
    assert card_view(crew).children[-1].url.endswith("/crews/9")
    links.configure("https://daisho.test", "plunderbot", False)
    assert all(getattr(i, "url", None) is None for i in voyage_view(v).children)


async def test_a_change_is_never_applied_twice(env):
    bot, cog, guild = env

    class Flaky(FakeClient):
        fail = True

        async def result(self, cid, status, message):
            if self.fail:
                self.fail = False
                raise RuntimeError("Daisho hiccup")
            await super().result(cid, status, message)
    cog.client = Flaky()
    art = {"name": "Once", "trigger": "keyword", "value": "once", "actions": [{"type": "reply", "texts": ["hi"]}]}
    change = dict(id=90001, section="articles", action="article.save", payload=art, by="Boxer")
    cog.client.queue = [change]
    with pytest.raises(RuntimeError):
        await cog.run_once(guild, now=0)
    cog.client.queue = [change]          # Daisho sends it again, never having heard
    await cog.run_once(guild, now=1)
    assert cog.client.results == [(90001, "applied", "Article Once created.")]
    assert len(await bot.db.articles(10)) == 1


async def test_applied_changes_survive_a_restart(env):
    """1.0.1: what was applied is remembered in the database, not just in memory."""
    bot, cog, guild = env
    art = {"name": "Twice", "trigger": "keyword", "value": "twice", "actions": [{"type": "reply", "texts": ["hi"]}]}
    change = dict(id=90002, section="articles", action="article.save", payload=art, by="Boxer")
    cog.client.queue = [change]
    await cog.run_once(guild, now=0)
    cog.done.clear()                     # as if PlunderBot restarted before Daisho heard
    cog.client.queue = [change]
    cog.client.results.clear()
    await cog.run_once(guild, now=1)
    assert cog.client.results == [(90002, "applied", "Article Twice created.")]
    assert len([a for a in await bot.db.articles(10) if a.name == "Twice"]) == 1


async def test_a_garbled_change_never_blocks_the_rest(env):
    bot, cog, guild = env
    cog.client.queue = ["garbage", {"id": "x"}, {"id": True},
                        dict(id=90003, section="settings", action="settings.update", payload="nope", by="Boxer"),
                        dict(id=90004, section="settings", action="settings.update",
                             payload={"fields": {"crew_cleanup_minutes": 12}}, by="Boxer")]
    cog.client.results.clear()
    await cog.run_once(guild, now=0)
    assert [(c, s) for c, s, _ in cog.client.results] == [(90003, "failed"), (90004, "applied")]


async def test_roles_from_daisho_get_the_slash_command_checks(env):
    """1.0.1: @everyone, or a role above PlunderBot's, can't be set as a Gangplank role from Daisho."""
    bot, cog, guild = env
    res = await run(cog, guild,
                    ("settings", "settings.update", {"fields": {"pending_role_id": 1}}),
                    ("settings", "settings.update", {"fields": {"harbormaster_role_id": 1}}),
                    ("settings", "settings.update", {"fields": {"harbormaster_role_id": 30}}))
    assert [s for _, s, _ in res] == ["failed", "failed", "applied"]
    guild.roles.append(Role(60, "Admiralty", 60))
    guild.me.guild_permissions = SimpleNamespace(manage_roles=True, kick_members=True)
    res = await run(cog, guild, ("settings", "settings.update", {"fields": {"pending_role_id": 60}}),
                    ("settings", "settings.update", {"fields": {"pending_role_id": 31}}))
    assert [s for _, s, _ in res] == ["failed", "applied"]



async def test_role_menus_from_daisho(env):
    """1.1.0: the role-menu editor: save (with the card's colour and button), post, delete."""
    bot, cog, guild = env
    res = await run(cog, guild, ("menus", "menu.save", {
        "title": "Pick your platforms", "description": "What do you play on?", "mode": "multi", "colour": "#1ABC9C",
        "button_label": "Pick platforms", "button_emoji": "🎮", "onboarding": True,
        "options": [{"role_id": 31, "emoji": "🖥️", "label": "PC", "description": "Keyboard and mouse"},
                    {"role_id": 30, "emoji": None}]}))
    assert res[0][1] == "applied", res
    m = (await bot.db.menus(10))[0]
    assert (m.title, m.colour, m.button_label, m.button_emoji, m.onboarding) == \
        ("Pick your platforms", 0x1ABC9C, "Pick platforms", "🎮", 1)
    assert [o.role_id for o in m.options] == [31, 30] and m.options[0].label == "PC"
    snap = (await cog.snap_menus(guild))[0]
    assert snap["button_text"] == "Pick platforms" and snap["options"][0]["role"] == "Bruh Lord"
    # the checks the slash commands make
    bad = await run(cog, guild,
                    ("menus", "menu.save", {"id": m.id, "title": "X", "options": [{"role_id": 1}]}),    # @everyone
                    ("menus", "menu.save", {"id": m.id, "title": "X", "options": [{"role_id": 31, "emoji": "joystick"}]}),
                    ("menus", "menu.save", {"id": m.id, "title": "X", "options": [{"role_id": 31}, {"role_id": 31}]}),
                    ("menus", "menu.save", {"id": m.id, "title": "", "options": []}))
    assert [s for _, s, _ in bad] == ["failed"] * 4
    assert "isn't an emoji" in bad[1][2]
    # post it, then post again in the same place: the card is updated in place
    res = await run(cog, guild, ("menus", "menu.post", {"id": m.id, "channel_id": 20}))
    assert res[0][1] == "applied" and guild.chans[20].sent
    m = await bot.db.get_menu(m.id)
    assert m.channel_id == 20 and m.message_id
    res = await run(cog, guild, ("menus", "menu.delete", {"id": m.id}))
    assert res[0][1] == "applied" and await bot.db.menus(10) == []


async def test_gangplank_roles_are_never_self_serve(env):
    """1.1.2: the Pending and Harbormaster roles can't go on a menu, or a newcomer could untick Pending."""
    bot, cog, guild = env
    await bot.db.update_settings(guild.id, pending_role_id=31, harbormaster_role_id=30)
    res = await run(cog, guild, ("menus", "menu.save", {"title": "Sneaky", "options": [{"role_id": 31}]}),
                    ("menus", "menu.save", {"title": "Sneakier", "options": [{"role_id": 30}]}))
    assert [s for _, s, _ in res] == ["failed", "failed"]
    assert "Gangplank's Pending role" in res[0][2] and "Harbormaster" in res[1][2]
    roles = {r["id"]: r["assignable"] for r in (await cog.snap_guild(guild))["roles"]}
    assert roles[31] is False and roles[30] is False
    await bot.db.update_settings(guild.id, pending_role_id=None, harbormaster_role_id=None)
    roles = {r["id"]: r["assignable"] for r in (await cog.snap_guild(guild))["roles"]}
    assert roles[31] is True


def test_is_emoji():
    from plunderbot.menu_logic import is_emoji
    assert is_emoji("🎮") and is_emoji("🇺🇸") and is_emoji("<:Bruh:123456789012345678>") and is_emoji("👍🏽")
    assert not is_emoji("joystick") and not is_emoji("🎮 PC") and not is_emoji("")
