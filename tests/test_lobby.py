"""1.8.0: the lobby thread, opened on a voyage's card a while before it sails."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import discord
import pytest

from plunderbot.voyage_logic import ParseError, format_lobby, lobby_due, lobby_for, parse_lobby
from tests.test_crew import interaction_for
from tests.test_voyages import env, make_voyage, planned_days_ago  # noqa: F401


def test_when_the_lobby_opens():
    assert lobby_for(None, 60) == 60 and lobby_for(0, 60) == 0 and lobby_for(30, 0) == 30
    assert lobby_for(None, 0) == 0 and lobby_for(99999, 60) == 0
    starts = datetime(2026, 10, 2, 20, 0)
    assert lobby_due(starts, 60, "", starts - timedelta(minutes=60))
    assert not lobby_due(starts, 60, "", starts - timedelta(minutes=61))
    assert not lobby_due(starts, 60, "open", starts - timedelta(minutes=30))
    assert not lobby_due(starts, 0, "", starts - timedelta(minutes=30))
    assert not lobby_due(starts, 60, "", starts)                      # sailing: too late for a lobby
    assert parse_lobby("1h") == 60 and parse_lobby("off") == 0 and parse_lobby(None) is None
    assert parse_lobby("default") is None and format_lobby(60) == "1 hour before" and format_lobby(0) == "no lobby"
    for bad in ("1h, 15m", "2d", "soon"):
        with pytest.raises(ParseError):
            parse_lobby(bad)


class FakeThread:
    def __init__(self, tid, name):
        self.id, self.name, self.sent, self.added, self.archived = tid, name, [], [], False
        self.mention = f"<#{tid}>"

    async def send(self, content=None, **kw):
        self.sent.append((content, kw))

    async def add_user(self, user):
        self.added.append(user.id)

    async def edit(self, archived=None, **kw):
        self.archived = bool(archived)


env_threads: dict = {}


@pytest.fixture
def threads(env, monkeypatch):
    """The card can grow a thread (or refuse to, when `refuse` holds something)."""
    bot, cog, guild, text = env
    made, refuse, during = {}, [], []
    original = text.get_partial_message

    def get_partial_message(mid):
        msg = original(mid)

        async def create_thread(name, auto_archive_duration=None, reason=None):
            if during:
                await during.pop()()
            if mid in made:      # one thread per message, as in Discord
                raise discord.HTTPException(SimpleNamespace(status=400, reason="exists"), "Thread already created")
            if refuse:
                raise discord.Forbidden(SimpleNamespace(status=403, reason="no"), "Missing Permissions")
            made[mid] = FakeThread(mid, name)
            return made[mid]
        msg.create_thread = create_thread
        return msg
    monkeypatch.setattr(text, "get_partial_message", get_partial_message)
    guild.get_thread = lambda tid: made.get(tid)
    env_threads[id(env)] = during
    return made, refuse


async def voyage(bot, cog, guild, **kw):
    await make_voyage(cog, guild, **kw)
    v = [x for x in await bot.db.voyages_with_status("scheduled") if x.title == kw.get("title", "Fort Night")][0]
    await planned_days_ago(bot, v)
    await cog.on_button(interaction_for(guild, 2), "aboard", v.id)
    await cog.on_button(interaction_for(guild, 7), "maybe", v.id)
    return await bot.db.get_voyage(v.id), datetime.fromisoformat(v.starts_at)


async def test_the_lobby_opens_an_hour_before_in_place_of_the_reminder(env, threads):
    bot, cog, guild, text = env
    made, _ = threads
    v, starts = await voyage(bot, cog, guild)
    await cog.tick(guild, v.id, starts - timedelta(hours=23))        # the day-before reminder, in the channel
    assert "<@2>" in text.sent[-1][0]
    before = len(text.sent)
    await cog.tick(guild, v.id, starts - timedelta(minutes=59))
    assert len(text.sent) == before                                 # no 1-hour reminder in the channel
    t = made[v.message_id]
    assert t.name == "⚓ Fort Night" and isinstance(t.sent[0][1]["view"], discord.ui.View)
    pings = " ".join(c for c, _ in t.sent[1:])
    assert "<@1>" in pings and "<@2>" in pings and "<@7>" in pings and "maybe" in t.sent[-1][0]
    v = await bot.db.get_voyage(v.id)
    assert v.lobby_state == "open" and v.lobby_thread_id == t.id and 60 in v.sent_minutes
    await cog.tick(guild, v.id, starts - timedelta(minutes=58))      # once only
    assert len(made) == 1 and len(t.sent) == 3
    # answering now brings you in; clearing your answer doesn't
    await cog.on_button(interaction_for(guild, 9), "maybe", v.id)
    await cog.on_button(interaction_for(guild, 11), "cant", v.id)
    assert t.added == [9]
    # sailing: the lobby hears where to go, and the maybes are nudged in there, not the channel
    before = len(text.sent)
    await cog.tick(guild, v.id, starts + timedelta(seconds=30))
    said = " ".join(c for c, _ in t.sent)
    assert "setting sail" in said and "<#" in said and "starting now" in said
    assert not any("starting now" in (c or "") for c, _ in text.sent[before:])
    # over: a last line and archived
    v = await bot.db.get_voyage(v.id)
    await bot.get_cog("CrewCall").end(guild, v.crew_id, "closed")
    assert t.archived and "made port" in t.sent[-1][0]
    assert (await bot.db.get_voyage(v.id)).lobby_state == "closed"


async def test_later_reminders_and_calling_it_off_go_into_the_lobby(env, threads):
    bot, cog, guild, text = env
    made, _ = threads
    v, starts = await voyage(bot, cog, guild, reminders="1h, 15m")
    await cog.tick(guild, v.id, starts - timedelta(minutes=50))
    t = made[v.message_id]
    before = len(text.sent)
    await cog.tick(guild, v.id, starts - timedelta(minutes=14))
    assert len(text.sent) == before and "<@2>" in t.sent[-1][0]       # the 15-minute one, in the thread
    assert await cog.apply_cancel(guild, v.id)
    assert "cancelled" in " ".join(c for c, _ in t.sent[-2:]) and t.archived
    assert not any("cancelled" in (c or "") for c, _ in text.sent[before:])


async def test_without_thread_permission_the_reminder_still_goes_out(env, threads):
    bot, cog, guild, text = env
    made, refuse = threads
    refuse.append(True)
    v, starts = await voyage(bot, cog, guild)
    await cog.tick(guild, v.id, starts - timedelta(minutes=59))
    assert not made and "<@2>" in text.sent[-1][0]
    assert (await bot.db.get_voyage(v.id)).lobby_state == "failed"


async def test_server_default_and_each_voyages_own(env, threads):
    bot, cog, guild, text = env
    made, _ = threads
    off = SimpleNamespace(value="off", name="No lobby thread")
    v, starts = await voyage(bot, cog, guild, title="Quiet", lobby=off)
    await cog.tick(guild, v.id, starts - timedelta(minutes=59))
    assert not made and "<@2>" in text.sent[-1][0]                    # the ordinary 1-hour reminder
    await bot.db.update_settings(10, lobby_minutes=0)
    v, starts = await voyage(bot, cog, guild, title="Plain")
    await cog.tick(guild, v.id, starts - timedelta(minutes=59))
    assert not made
    half = SimpleNamespace(value="30m", name="30 minutes before")
    v, starts = await voyage(bot, cog, guild, title="Half", lobby=half)
    await cog.tick(guild, v.id, starts - timedelta(minutes=59))       # the 1-hour reminder, as usual
    assert not made
    await cog.tick(guild, v.id, starts - timedelta(minutes=29))
    assert made[v.message_id].name == "⚓ Half"
    # moving it after the lobby opened tells the lobby
    from tests.test_voyages import organizer
    await cog.edit.callback(cog, organizer(guild), voyage=str(v.id), time="9pm")
    assert "Change of plans" in made[v.message_id].sent[-1][0]


async def test_the_role_hears_of_the_lobby_in_the_channel(env, threads):
    bot, cog, guild, text = env
    made, _ = threads
    role = SimpleNamespace(id=77, mention="<@&77>")
    guild.get_role = lambda rid: role if rid == 77 else None
    await bot.db.set_game_ping_role(10, "sot", 77)
    v, starts = await voyage(bot, cog, guild, notify=SimpleNamespace(value="reminders", name="r"))
    await cog.tick(guild, v.id, starts - timedelta(minutes=59))
    content, kw = text.sent[-1]
    assert content.startswith("<@&77>") and f"<#{v.message_id}>" in content and kw["allowed_mentions"].roles == [role]
    assert not any("<@&77>" in (c or "") for c, _ in made[v.message_id].sent)


async def test_the_server_default_command(env):
    bot, cog, guild, text = env
    admin = bot.get_cog("Admin")
    inter = interaction_for(guild, 1)
    await admin.voyages_lobby.callback(admin, inter, SimpleNamespace(value=30, name="30 minutes before"))
    assert (await bot.db.get_settings(10)).lobby_minutes == 30
    await admin.voyages_lobby.callback(admin, inter, SimpleNamespace(value=0, name="Off"))
    assert (await bot.db.get_settings(10)).lobby_minutes == 0




async def test_no_reminders_means_no_fallback_ping(env, threads):
    bot, cog, guild, text = env
    made, refuse = threads
    refuse.append(True)
    v, starts = await voyage(bot, cog, guild, reminders="none")
    before = len(text.sent)
    await cog.tick(guild, v.id, starts - timedelta(minutes=59))
    assert len(text.sent) == before and (await bot.db.get_voyage(v.id)).lobby_state == "failed"


async def test_a_late_clock_doesnt_ping_twice(env, threads):
    bot, cog, guild, text = env
    made, _ = threads
    v, starts = await voyage(bot, cog, guild, reminders="1h, 15m")
    await cog.tick(guild, v.id, starts - timedelta(minutes=12))      # PlunderBot was down till now
    t = made[v.message_id]
    n = len(t.sent)
    await cog.tick(guild, v.id, starts - timedelta(minutes=11))
    assert len(t.sent) == n and 15 in (await bot.db.get_voyage(v.id)).sent_minutes


async def test_called_off_while_the_thread_was_being_made(env, threads):
    bot, cog, guild, text = env
    made, _ = threads
    v, starts = await voyage(bot, cog, guild)

    async def cancel():
        assert await cog.apply_cancel(guild, v.id)
    env_threads[id(env)].append(cancel)
    await cog.tick(guild, v.id, starts - timedelta(minutes=59))
    t = made[v.message_id]
    assert t.archived and t.sent == [] and (await bot.db.get_voyage(v.id)).lobby_state == "closed"


async def test_left_half_made_by_a_restart_it_tries_again(env, threads):
    bot, cog, guild, text = env
    made, _ = threads
    v, starts = await voyage(bot, cog, guild)
    await bot.db.update_voyage(v.id, lobby_state="opening")
    await cog.tick(guild, v.id, starts - timedelta(minutes=50))
    assert v.message_id in made and (await bot.db.get_voyage(v.id)).lobby_state == "open"


async def test_moved_out_of_its_window_it_opens_again_in_time(env, threads):
    bot, cog, guild, text = env
    made, _ = threads
    v, starts = await voyage(bot, cog, guild)
    await cog.tick(guild, v.id, starts - timedelta(minutes=59))
    t = made[v.message_id]
    from tests.test_voyages import organizer
    nxt = (starts + timedelta(days=7)).astimezone(await cog.tz(10))
    await cog.edit.callback(cog, organizer(guild), voyage=str(v.id), date=nxt.strftime("%Y-%m-%d"))
    v = await bot.db.get_voyage(v.id)
    assert t.archived and v.lobby_state == "" and "Change of plans" in t.sent[-1][0]
    n = len(t.sent)
    await planned_days_ago(bot, v)
    await cog.tick(guild, v.id, datetime.fromisoformat(v.starts_at) - timedelta(minutes=59))
    assert not t.archived and len(t.sent) > n and (await bot.db.get_voyage(v.id)).lobby_state == "open"
    assert len(made) == 1                                           # the same thread, woken up
