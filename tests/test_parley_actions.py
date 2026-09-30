"""1.3.1: Parley plans voyages, calls crews and signs people up in plain speech, as whoever asked."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from plunderbot.parley_actions import ACTION_TOOLS, act, find_game
from tests.test_daisho import Role, env  # noqa: F401


def who(uid, roles=()):
    return SimpleNamespace(id=uid, display_name=f"m{uid}", voice=None, roles=[Role(r, "r") for r in roles])


def test_finding_games_by_how_people_say_them():
    assert find_game("SoT").key == "sot" and find_game("sea of thieves").key == "sot"
    assert find_game("nope") is None and find_game(None) is None
    assert find_game("Server event").key == "event" and find_game("Server event", crew_call=True) is None
    names = {t["name"] for t in ACTION_TOOLS}
    assert names == {"plan_voyage", "answer_voyage", "cancel_voyage", "start_crew", "join_crew", "close_crew"}


async def test_plan_answer_cancel_and_crews(env, monkeypatch):
    bot, cog, guild = env

    async def no_event(*a, **kw):
        return None
    monkeypatch.setattr(bot.get_cog("Voyages"), "sync_event", no_event)
    await bot.db.update_settings(10, voyage_channel_id=21, crew_channel_id=20, pending_role_id=50,
                                 timezone="America/Los_Angeles")
    here = guild.chans[20]
    boxer, twiddles, newbie = who(1), who(2), who(3, roles=[50])
    out = await act(bot, guild, newbie, here, "plan_voyage", {"title": "x", "date": "tomorrow", "time": "8pm"})
    assert "Gangplank" in out
    out = await act(bot, guild, boxer, here, "plan_voyage", {"title": "Fort Night", "date": "tomorrow", "time": "8pm",
                                                             "game": "SoT", "size": "Galleon"})
    assert out.startswith("Planned voyage #") and "server's time zone" in out, out
    v = (await bot.db.voyages_with_status("scheduled", guild_id=10))[0]
    assert (v.organizer_id, v.capacity, v.channel_id, v.game_key) == (1, 4, 21, "sot")
    starts = datetime.fromisoformat(v.starts_at)
    assert starts.astimezone(timezone(timedelta(hours=-7))).hour in (19, 20)   # 8pm Pacific
    out = await act(bot, guild, boxer, here, "plan_voyage", {"title": "x", "date": "today", "time": "12:01am"})
    assert "past" in out, out
    assert "don't know the game" in await act(bot, guild, boxer, here, "plan_voyage",
                                              {"title": "x", "date": "tomorrow", "time": "8pm", "game": "Tetris 99"})
    # answers, and only the organizer cancels
    await act(bot, guild, twiddles, here, "answer_voyage", {"voyage": v.id, "answer": "aboard"})
    assert (await bot.db.rsvps(v.id)).aboard == [1, 2]
    assert "Only its organizer" in await act(bot, guild, twiddles, here, "cancel_voyage", {"voyage": v.id})
    assert "Cancelled" in await act(bot, guild, boxer, here, "cancel_voyage", {"voyage": v.id})
    # crews
    out = await act(bot, guild, twiddles, here, "start_crew", {"game": "sea of thieves", "size": "Galleon", "note": "chill"})
    assert out.startswith("Called crew #"), out
    crew = (await bot.db.active_crews(10))[0]
    assert (crew.captain_id, crew.capacity, crew.note) == (2, 4, "chill")
    assert "already captaining" in await act(bot, guild, twiddles, here, "start_crew", {"game": "SoT"})
    await act(bot, guild, boxer, here, "join_crew", {"crew": crew.id})
    assert 1 in (await bot.db.get_crew(crew.id)).members
    assert "aren't captaining" in await act(bot, guild, boxer, here, "close_crew", {})
    assert "Closed" in await act(bot, guild, twiddles, here, "close_crew", {})
    assert not (await bot.db.get_crew(crew.id)).active


async def test_parley_offers_the_actions(env):
    bot, cog, guild = env
    parley = bot.get_cog("Parley")
    out = await parley.run_tool(guild, await bot.db.get_settings(10), "close_crew", {}, "2026-09-30", who(9), None)
    assert "aren't captaining" in out
    from plunderbot.parley_logic import system_prompt
    text = system_prompt(server="B", now_local=datetime.now(), zone_label="PDT", asker="Boxer", asker_zone="",
                         lookups_left=None, cusses=["Sink me!"])
    assert "plan_voyage" in text and "never for anyone else" in text
