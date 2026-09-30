"""Parley: PlunderBot answering in chat. Claude and Kagi are faked; no network, no money."""
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import discord
import pytest

from plunderbot.parley_logic import build_messages, cost, refusal, reply_text, safe, strip_bot_mention, system_prompt

BOT_ID = 999


# ------------------------------------------------------------ rules
def test_cost():
    assert cost({"input_tokens": 1_000_000, "output_tokens": 0}) == pytest.approx(1.0)
    assert cost({"input_tokens": 2000, "output_tokens": 300}) == pytest.approx(0.0035)


def test_refusal():
    assert refusal(4.99, 5.0, 19, 20) is None
    assert refusal(5.0, 5.0, 0, 20) == "broke"
    assert refusal(1.0, 5.0, 20, 20) == "tired"


def test_messages_alternate_and_start_with_the_user():
    history = [("assistant", "Earlier answer"), ("user", "Boxer: a"), ("user", "Twiddles: b"),
               ("assistant", "Arr!")]
    msgs = build_messages(history, "what's next?", "Boxer")
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant", "user"]
    assert msgs[1]["content"] == "Earlier answer" and msgs[2]["content"] == "Boxer: a\n\nTwiddles: b"
    assert msgs[-1]["content"] == "Boxer: what's next?"


def test_text_helpers():
    assert strip_bot_mention(f"<@{BOT_ID}> hi <@!{BOT_ID}>", BOT_ID) == "hi"
    assert safe("hey @everyone and @here") == "hey @​everyone and @​here"
    assert len(safe("word " * 1000)) <= 1901
    assert reply_text([{"type": "text", "text": "A"}, {"type": "tool_use"}, {"type": "text", "text": "B"}]) == "A\nB"
    p = system_prompt(server="Brimstone Hill Fortress", now_local=datetime(2026, 9, 29, 18, tzinfo=ZoneInfo("UTC")),
                      zone_label="PDT", asker="Boxer", asker_zone="Pacific (PDT)", lookups_left=0,
                      cusses=["Barnacles!"])
    assert "PlunderBot" in p and "used up" in p and "Boxer" in p
    none = system_prompt(server="B", now_local=datetime(2026, 9, 29, 18, tzinfo=ZoneInfo("UTC")), zone_label="PDT",
                         asker="Boxer", asker_zone="", lookups_left=None, cusses=["Barnacles!"])
    assert "can't search the web" in none and "used up" not in none


# ------------------------------------------------------------ the cog, with fakes
class FakeClaude:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    async def create(self, *, system, messages, tools=None, max_tokens=600, allow_tools=True):
        self.calls.append({"system": system, "messages": [dict(m) for m in messages], "tools": tools,
                           "allow_tools": allow_tools})
        return self.script.pop(0)

    async def close(self):
        pass


class FakeKagi:
    def __init__(self):
        self.queries = []

    async def fastgpt(self, query):
        self.queries.append(query)
        return "Season 18 launched on September 25.", [{"title": "Sea of Thieves news", "url": "https://x"}]

    async def close(self):
        pass


def said(text, stop="end_turn"):
    return {"content": [{"type": "text", "text": text}], "stop_reason": stop,
            "usage": {"input_tokens": 1000, "output_tokens": 100}}


def tool_call(name, args, tid="t1"):
    return {"content": [{"type": "tool_use", "id": tid, "name": name, "input": args}], "stop_reason": "tool_use",
            "usage": {"input_tokens": 1200, "output_tokens": 40}}


class Typing:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class Chan:
    def __init__(self, cid=70, public=True):
        self.id, self.public, self.parent = cid, public, None

    def permissions_for(self, who):
        return SimpleNamespace(view_channel=self.public)

    def typing(self):
        return Typing()

    async def fetch_message(self, mid):
        raise discord.NotFound(SimpleNamespace(status=404, reason="x"), "x")


class Msg:
    def __init__(self, guild, author, content, channel, reference=None):
        self.guild, self.author, self.content, self.channel = guild, author, content, channel
        self.reference = reference
        self.raw_mentions = [BOT_ID] if f"<@{BOT_ID}>" in content else []
        self.replies = []

    async def reply(self, text, **kw):
        self.replies.append(text)
        return SimpleNamespace(id=1, author=SimpleNamespace(id=BOT_ID), content=text, reference=None)


def member(uid=1, roles=()):
    return SimpleNamespace(id=uid, bot=False, display_name="Boxer", get_role=lambda r: r if r in roles else None)


@pytest.fixture
async def env(tmp_path, monkeypatch):
    from dataclasses import replace
    from tests.test_bot import make_config
    from plunderbot.bot import PlunderBot
    cfg = replace(make_config(tmp_path), anthropic_api_key="sk-test", kagi_api_key="kagi-test")
    bot = PlunderBot(cfg)
    await bot.db.connect()
    await bot.load_extension("plunderbot.cogs.parley")
    cog = bot.get_cog("Parley")
    monkeypatch.setattr(type(bot), "user", property(lambda self: SimpleNamespace(id=BOT_ID)))
    monkeypatch.setattr(discord, "Member", SimpleNamespace)  # isinstance(author, Member) for the pending check
    await bot.db.update_settings(5, parley_enabled=1, timezone="America/Los_Angeles", pending_role_id=50)
    guild = SimpleNamespace(id=5, name="Brimstone Hill Fortress", default_role=object(), get_member=lambda u: None)
    yield bot, cog, guild
    await bot.db.close()


async def test_answers_with_a_web_search(env):
    bot, cog, guild = env
    cog.claude = FakeClaude([tool_call("search_web", {"query": "Sea of Thieves latest season"}),
                             said("Barnacles! Season 18 set sail on September 25.")])
    cog.kagi = FakeKagi()
    msg = Msg(guild, member(), f"<@{BOT_ID}> what's the newest SoT season?", Chan())
    await cog.on_message(msg)
    assert msg.replies == ["Barnacles! Season 18 set sail on September 25."]
    assert cog.kagi.queries == ["Sea of Thieves latest season"]
    second = cog.claude.calls[1]["messages"]
    assert second[0]["content"].startswith("Boxer: what's the newest SoT season?")
    assert second[-1]["content"][0]["type"] == "tool_result" and "Season 18" in second[-1]["content"][0]["content"]
    day, month, _ = cog.today(await bot.db.get_settings(5))
    spent, calls = await bot.db.parley_spend(5, month)
    assert calls == 2 and spent == pytest.approx(cost({"input_tokens": 2200, "output_tokens": 140}))
    assert await bot.db.parley_replies(5, 1, day) == 1
    assert await bot.db.parley_lookups(5, day) == 1


async def test_server_tools_read_the_database(env):
    bot, cog, guild = env
    s = await bot.db.get_settings(5)
    out = await cog.run_tool(guild, s, "upcoming_voyages", {}, "2026-09-29")
    assert "No voyages scheduled" in out
    assert "/crew start" in await cog.run_tool(guild, s, "plunderbot_commands", {}, "2026-09-29")
    await bot.db.update_settings(5, parley_kagi_daily=0)
    s = await bot.db.get_settings(5)
    cog.kagi = FakeKagi()
    assert "used up" in await cog.run_tool(guild, s, "search_web", {"query": "x"}, "2026-09-29")
    assert cog.kagi.queries == []


async def test_stays_quiet_unless_addressed_allowed_and_on(env):
    bot, cog, guild = env
    cog.claude = FakeClaude([said("hi")] * 5)
    plain = Msg(guild, member(), "just chatting", Chan())
    await cog.on_message(plain)
    staff = Msg(guild, member(2), f"<@{BOT_ID}> hi", Chan(public=False))
    await cog.on_message(staff)
    newcomer = Msg(guild, member(3, roles=(50,)), f"<@{BOT_ID}> hi", Chan())
    await cog.on_message(newcomer)
    await bot.db.set_parley_channel(5, 71, False)
    muted = Msg(guild, member(4), f"<@{BOT_ID}> hi", Chan(71))
    await cog.on_message(muted)
    assert not (plain.replies or staff.replies or newcomer.replies or muted.replies) and not cog.claude.calls
    await bot.db.update_settings(5, parley_enabled=0)
    off = Msg(guild, member(6), f"<@{BOT_ID}> hi", Chan())
    await cog.on_message(off)
    assert not off.replies


async def test_limits(env):
    bot, cog, guild = env
    cog.claude = FakeClaude([said("one")])
    s = await bot.db.get_settings(5)
    day, month, _ = cog.today(s)
    for _ in range(20):
        await bot.db.add_parley_reply(5, 1, day)
    tired = Msg(guild, member(), f"<@{BOT_ID}> another?", Chan())
    await cog.on_message(tired)
    assert "20 chats" in tired.replies[0] and not cog.claude.calls
    await bot.db.add_parley_spend(5, month, 5.0, 0, 0)
    broke = Msg(guild, member(2), f"<@{BOT_ID}> hello", Chan())
    await cog.on_message(broke)
    assert "budget" in broke.replies[0]


async def test_reply_chain_is_context_and_cooldown(env):
    bot, cog, guild = env
    cog.claude = FakeClaude([said("Aye, Sunday!"), said("never")])
    earlier = object.__new__(discord.Message)  # a real Message type, so it counts as a reply to PlunderBot
    earlier.id, earlier.content, earlier.reference = 10, "Fort Night is Friday.", None
    earlier.author = SimpleNamespace(id=BOT_ID, display_name="PlunderBot")
    ref = SimpleNamespace(message_id=10, resolved=earlier)
    msg = Msg(guild, member(), "and the next one?", Chan(), reference=ref)  # a reply, no @mention
    await cog.on_message(msg)
    assert msg.replies == ["Aye, Sunday!"]
    sent = cog.claude.calls[0]["messages"]
    # PlunderBot's earlier line is kept as context for the follow-up question.
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]
    assert sent[1]["content"] == "Fort Night is Friday." and sent[2]["content"] == "Boxer: and the next one?"
    again = Msg(guild, member(), f"<@{BOT_ID}> quick one", Chan())
    await cog.on_message(again)  # within the cooldown
    assert not again.replies


async def test_empty_mention_says_hello_without_calling_claude(env):
    bot, cog, guild = env
    cog.claude = FakeClaude([])
    msg = Msg(guild, member(), f"<@{BOT_ID}>", Chan())
    await cog.on_message(msg)
    assert msg.replies and not cog.claude.calls


async def test_must_answer_after_too_many_tool_calls(env):
    bot, cog, guild = env
    cog.claude = FakeClaude([tool_call("open_crews", {}, f"t{i}") for i in range(4)] + [said("Here's what I found!")])
    msg = Msg(guild, member(), f"<@{BOT_ID}> who's sailing?", Chan())
    await cog.on_message(msg)
    assert msg.replies == ["Here's what I found!"]
    assert [c["allow_tools"] for c in cog.claude.calls] == [True, True, True, True, False]


async def test_without_kagi_there_is_no_search_tool(env):
    bot, cog, guild = env
    cog.kagi = None
    cog.claude = FakeClaude([said("From what I know, Season 18 is the latest, but that may be out of date!")])
    msg = Msg(guild, member(), f"<@{BOT_ID}> newest SoT season?", Chan())
    await cog.on_message(msg)
    call = cog.claude.calls[0]
    assert "search_web" not in [t["name"] for t in call["tools"]] and "can't search the web" in call["system"]
    assert msg.replies[0].startswith("From what I know")


async def test_game_activity_counts_crews_and_followers(env):
    from datetime import datetime, timedelta, timezone
    from plunderbot.crew_logic import iso
    bot, cog, guild = env
    now = datetime.now(timezone.utc)
    for cap, game in ((1, "sot"), (2, "sot"), (3, "drg")):
        c = await bot.db.create_crew(guild_id=5, channel_id=1, captain_id=cap, game_key=game, size_label="x",
                                     capacity=4, activity=None, note=None, created_at=iso(now), expires_at=iso(now))
        await bot.db.update_crew(c.id, sailed_at=iso(now - timedelta(days=2)))
    await bot.db.set_game_ping_role(5, "helldivers", 77)
    guild.get_role = lambda rid: SimpleNamespace(members=[1, 2, 3, 4]) if rid == 77 else None
    out = await cog.run_tool(guild, await bot.db.get_settings(5), "game_activity", {}, "2026-09-29")
    lines = out.splitlines()[1:]
    assert lines[0].startswith("- Sea of Thieves: 2 crew(s) set sail with 2 different pirate(s)")
    assert lines[1].startswith("- Deep Rock Galactic: 1 crew(s)")
    assert "- Helldivers 2: 0 crew(s) set sail with 0 different pirate(s) in the last 30 days, 4 follower(s)" in out
