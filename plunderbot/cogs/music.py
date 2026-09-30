"""Music (1.3.0): PlunderBot plays music in voice channels, the way Pancake does.

/play a song name or a link, and PlunderBot joins your voice channel and plays it; everything else is
under /music (queue, skip, pause, stop, remove, move, shuffle, repeat, seek, volume, lyrics). A Now
Playing card with buttons goes up in the channel /play was used in (or the music channel, if one's set).

Audio comes through yt-dlp and FFmpeg (see music_sources.py): YouTube (when a Quartermaster switches it
on), SoundCloud, Bandcamp, Twitch, internet radio and plain audio links, plus Spotify links looked up
elsewhere. Voice uses discord.py's own client, which speaks Discord's end-to-end encrypted voice (DAVE).

Who can steer: anyone in the voice channel with PlunderBot. With a DJ role set, skipping someone else's
track, stopping, clearing, moving, removing, shuffling, repeat, seek and volume need that role (or
Manage Channels), unless you're the only listener.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .. import voice
from ..music_logic import MAX_QUEUE, REPEATS, Queue, Track, clock, ffmpeg_options, parse_position, progress_bar
from ..music_sources import MusicConfig, ResolveError, Resolver, Stream, lyrics

log = logging.getLogger("plunderbot.music")

COLOUR = discord.Colour(0x8E44AD)
SOURCE_LABEL = {"youtube": "YouTube", "soundcloud": "SoundCloud", "bandcamp": "Bandcamp", "twitch": "Twitch",
                "spotify": "Spotify (played from elsewhere)", "radio": "Radio", "link": "Link"}
BUTTONS = {"pause": ("⏯️", discord.ButtonStyle.secondary), "skip": ("⏭️", discord.ButtonStyle.secondary),
           "stop": ("⏹️", discord.ButtonStyle.danger), "shuffle": ("🔀", discord.ButtonStyle.secondary),
           "repeat": ("🔁", discord.ButtonStyle.secondary)}
REPEAT_CHOICES = [app_commands.Choice(name=n, value=v) for n, v in
                  (("Off", "off"), ("This track", "one"), ("The whole queue", "all"))]


class MusicButton(discord.ui.DynamicItem[discord.ui.Button], template=r"music:(?P<action>pause|skip|stop|shuffle|repeat)"):
    def __init__(self, action: str):
        emoji, style = BUTTONS[action]
        super().__init__(discord.ui.Button(emoji=emoji, style=style, custom_id=f"music:{action}"))
        self.action = action

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str]):
        return cls(match["action"])

    async def callback(self, interaction: discord.Interaction) -> None:
        cog = interaction.client.get_cog("Music")
        if cog is None:
            await interaction.response.send_message(voice.say("music_off"), ephemeral=True)
            return
        await cog.on_button(interaction, self.action)


def np_view() -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for action in BUTTONS:
        view.add_item(MusicButton(action))
    return view


class Player:
    """One server's music: its queue, and where the current track is up to."""

    def __init__(self, guild_id: int, volume: float):
        self.guild_id = guild_id
        self.queue = Queue()
        self.volume = volume
        self.text_channel_id: int | None = None
        self.np_message: discord.Message | None = None
        self.stream: Stream | None = None
        self.started = 0.0          # monotonic time the current track (re)started
        self.offset = 0             # where in the track it (re)started, in seconds
        self.paused_at: float | None = None
        self.skip = False           # the next stop was a skip
        self.seek_to: int | None = None
        self.stopping = False
        self.idle_since: float | None = None
        self.lock = asyncio.Lock()

    def position(self, now: float | None = None) -> float:
        if self.queue.current is None:
            return 0.0
        now = time.monotonic() if now is None else now
        end = self.paused_at if self.paused_at is not None else now
        return self.offset + max(0.0, end - self.started)


def _is_mod(member) -> bool:
    p = getattr(member, "guild_permissions", None)
    return bool(p and (p.manage_guild or p.manage_channels or p.move_members or p.administrator))


class Music(commands.Cog):
    music = app_commands.Group(name="music", description="Music in voice channels", guild_only=True)

    def __init__(self, bot):
        self.bot = bot
        self.players: dict[int, Player] = {}
        self.resolver = Resolver(MusicConfig.from_env())

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(MusicButton)
        self.watch.start()

    async def cog_unload(self) -> None:
        self.watch.cancel()
        self.bot.remove_dynamic_items(MusicButton)
        for guild in list(self.bot.guilds):
            if guild.voice_client is not None:
                try:
                    await guild.voice_client.disconnect(force=True)
                except Exception:
                    pass

    # ------------------------------------------------------------ helpers
    def player(self, guild_id: int, volume_pct: int = 60) -> Player:
        p = self.players.get(guild_id)
        if p is None:
            p = self.players[guild_id] = Player(guild_id, volume_pct / 100)
        return p

    async def settings(self, guild_id: int):
        s = await self.bot.db.get_settings(guild_id)
        self.resolver.cfg.youtube = bool(s.music_youtube)
        return s

    def listeners(self, guild: discord.Guild) -> list:
        vc = guild.voice_client
        return [m for m in getattr(getattr(vc, "channel", None), "members", []) if not m.bot] if vc else []

    async def gate(self, interaction: discord.Interaction, dj: bool = False, track: Track | None = None) -> str | None:
        """Why this member can't steer the music right now, or None if they can."""
        s = await self.settings(interaction.guild_id)
        if not s.music_enabled:
            return voice.say("music_off")
        guild, member = interaction.guild, interaction.user
        vc = guild.voice_client
        p = self.players.get(guild.id)
        if vc is None or p is None or (p.queue.current is None and not p.queue.tracks):
            return voice.say("music_nothing")
        if _is_mod(member):
            return None
        here = getattr(getattr(member, "voice", None), "channel", None)
        if here is None or here.id != vc.channel.id:
            return voice.say("music_same_channel", channel=vc.channel.mention)
        if dj and s.music_dj_role_id:
            wears = any(r.id == s.music_dj_role_id for r in getattr(member, "roles", []))
            own = track is not None and track.requester_id == member.id
            alone = [m.id for m in self.listeners(guild)] == [member.id]
            if not (wears or own or alone):
                return voice.say("music_dj_only")
        return None

    async def reply(self, interaction: discord.Interaction, text: str, ephemeral: bool = True) -> None:
        try:
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=ephemeral, allowed_mentions=discord.AllowedMentions.none())
            else:
                await interaction.response.send_message(text, ephemeral=ephemeral,
                                                        allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as e:
            log.warning("Couldn't answer a music command: %s", e)

    def text_channel(self, guild: discord.Guild, p: Player):
        return guild.get_channel(p.text_channel_id) if p.text_channel_id else None

    async def say_in_channel(self, guild: discord.Guild, p: Player, text: str) -> None:
        channel = self.text_channel(guild, p)
        if channel is None:
            return
        try:
            await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as e:
            log.warning("Couldn't post in the music channel: %s", e)

    # ------------------------------------------------------------ /play
    @app_commands.command(name="play", description="Play a song or a playlist in your voice channel")
    @app_commands.describe(song="A song name, or a link (SoundCloud, Bandcamp, Twitch, Spotify, radio, YouTube if it's on)",
                           next="Put it at the front of the queue")
    @app_commands.guild_only()
    async def play_cmd(self, interaction: discord.Interaction, song: app_commands.Range[str, 1, 300],
                       next: bool = False) -> None:
        await self.play(interaction, song, next)

    async def play(self, interaction: discord.Interaction, query: str, front: bool = False) -> None:
        guild, member = interaction.guild, interaction.user
        s = await self.settings(guild.id)
        if not s.music_enabled:
            await self.reply(interaction, voice.say("music_off"))
            return
        target = getattr(getattr(member, "voice", None), "channel", None)
        if target is None:
            await self.reply(interaction, voice.say("music_need_voice"))
            return
        vc = guild.voice_client
        p = self.player(guild.id, s.music_volume)
        busy = vc is not None and (p.queue.current is not None or p.queue.tracks)
        if vc is not None and vc.channel.id != target.id and busy and not _is_mod(member):
            await self.reply(interaction, voice.say("music_elsewhere", channel=vc.channel.mention))
            return
        perms = target.permissions_for(guild.me)
        if not (perms.connect and perms.speak):
            await self.reply(interaction, voice.say("music_cant_join"))
            return
        if len(p.queue.tracks) >= MAX_QUEUE:
            await self.reply(interaction, voice.say("music_queue_full"))
            return
        await interaction.response.defer(thinking=True)
        try:
            tracks, name = await self.resolver.resolve(query, member.id)
        except ResolveError as e:
            await interaction.followup.send(f"{voice.cuss(None)} {e}", ephemeral=True)
            return
        try:
            if vc is None:
                vc = await target.connect(self_deaf=True, timeout=20)
            elif vc.channel.id != target.id:
                await vc.move_to(target)
        except (discord.ClientException, asyncio.TimeoutError, discord.HTTPException) as e:
            log.warning("Couldn't join voice channel %s: %s", target.id, e)
            await interaction.followup.send(voice.say("music_cant_join"), ephemeral=True)
            return
        p.stopping = False
        p.idle_since = None
        music_channel = guild.get_channel(s.music_channel_id) if s.music_channel_id else None
        p.text_channel_id = (music_channel or interaction.channel).id
        if front:
            added = min(len(tracks), MAX_QUEUE - len(p.queue.tracks))
            p.queue.tracks[0:0] = tracks[:added]
            position = 1
        else:
            added = p.queue.add(tracks)
            position = len(p.queue.tracks) - added + 1
        idle = p.queue.current is None and not vc.is_playing() and not vc.is_paused()
        if name:
            text = voice.say("music_queued_many", count=added, name=name)
        elif idle:
            text = voice.say("music_now", title=tracks[0].title)
        else:
            text = voice.say("music_queued", title=tracks[0].title, position=position)
        await interaction.followup.send(text, allowed_mentions=discord.AllowedMentions.none())
        if idle:
            await self.advance(guild, p)

    # ------------------------------------------------------------ playing
    async def advance(self, guild: discord.Guild, p: Player, skipped: bool = False) -> None:
        """Move to the next track and start it. Tracks that won't play are skipped, with a note."""
        async with p.lock:
            failures = 0
            while True:
                track = p.queue.next(skipped=skipped)
                skipped = False
                if track is None:
                    p.stream = None
                    p.idle_since = time.monotonic()
                    await self.clear_np(p)
                    await self.say_in_channel(guild, p, voice.say("music_queue_end"))
                    return
                if await self.start(guild, p, track, 0):
                    return
                failures += 1
                skipped = True                  # repeat-one must not retry a track that won't play
                if failures > len(p.queue.tracks) + 1:
                    p.queue.current = None      # everything left is failing: stop trying
                    p.queue.clear()
                    return

    async def start(self, guild: discord.Guild, p: Player, track: Track, at: int) -> bool:
        vc = guild.voice_client
        if vc is None or p.stopping:
            return False
        try:
            stream = await self.resolver.stream(track)
        except ResolveError as e:
            await self.say_in_channel(guild, p, voice.say("music_failed_track", title=track.title, reason=str(e).rstrip(".")))
            return False
        before, options = ffmpeg_options(at, stream.headers, live=stream.duration is None)
        try:
            source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(stream.url, before_options=before, options=options), volume=p.volume)
        except discord.ClientException as e:     # FFmpeg missing: nothing will ever play
            log.error("FFmpeg couldn't start: %s", e)
            await self.say_in_channel(guild, p, voice.say("music_failed_track", title=track.title, reason="no FFmpeg"))
            return False
        loop = asyncio.get_running_loop()

        def after(error: Exception | None) -> None:
            if error:
                log.warning("Playback error in guild %s: %s", guild.id, error)
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.after(guild.id)))

        if vc.is_playing() or vc.is_paused():   # shouldn't happen: only an ended track starts the next
            source.cleanup()
            return True
        vc.play(source, after=after)
        p.stream, p.started, p.offset, p.paused_at, p.idle_since = stream, time.monotonic(), at, None, None
        if track.duration is None and stream.duration:
            track.duration = stream.duration
        if at == 0:
            await self.post_np(guild, p)
        return True

    async def after(self, guild_id: int) -> None:
        """A track stopped: it ended, was skipped, is being seeked, or the music was stopped."""
        p = self.players.get(guild_id)
        guild = self.bot.get_guild(guild_id)
        if p is None or guild is None or p.stopping:
            return
        if p.seek_to is not None and p.queue.current is not None:
            at, p.seek_to = p.seek_to, None
            if not await self.start(guild, p, p.queue.current, at):
                await self.advance(guild, p, skipped=True)
            return
        skipped, p.skip = p.skip, False
        await self.advance(guild, p, skipped=skipped)

    async def stop(self, guild: discord.Guild, p: Player) -> None:
        p.stopping = True
        p.queue.clear()
        p.queue.current = None
        vc = guild.voice_client
        if vc is not None:
            vc.stop()
            try:
                await vc.disconnect(force=False)
            except Exception as e:
                log.warning("Couldn't leave voice in guild %s: %s", guild.id, e)
        await self.clear_np(p)
        self.players.pop(guild.id, None)

    # ------------------------------------------------------------ the Now Playing card
    def np_embed(self, p: Player) -> discord.Embed:
        t = p.queue.current
        e = discord.Embed(colour=COLOUR, title="Now playing", description=f"**[{t.title}]({t.url})**")
        e.add_field(name="Asked for by", value=f"<@{t.requester_id}>")
        e.add_field(name="Length", value=clock(t.duration))
        e.add_field(name="From", value=SOURCE_LABEL.get(t.source, "Link"))
        up = p.queue.tracks[:3]
        if up:
            e.add_field(name="Up next", value="\n".join(f"{i}. {x.title[:80]}" for i, x in enumerate(up, 1)), inline=False)
        if t.thumbnail:
            e.set_thumbnail(url=t.thumbnail)
        more = len(p.queue.tracks)
        e.set_footer(text=f"Repeat: {dict((c.value, c.name) for c in REPEAT_CHOICES)[p.queue.repeat]} · "
                          f"Volume: {round(p.volume * 100)}% · {more} in the queue")
        return e

    async def post_np(self, guild: discord.Guild, p: Player) -> None:
        await self.clear_np(p)
        channel = self.text_channel(guild, p)
        if channel is None or p.queue.current is None:
            return
        try:
            p.np_message = await channel.send(embed=self.np_embed(p), view=np_view(),
                                              allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as e:
            log.warning("Couldn't post the Now Playing card: %s", e)

    async def refresh_np(self, p: Player) -> None:
        if p.np_message is not None and p.queue.current is not None:
            try:
                await p.np_message.edit(embed=self.np_embed(p), view=np_view())
            except discord.HTTPException:
                pass

    async def clear_np(self, p: Player) -> None:
        if p.np_message is not None:
            msg, p.np_message = p.np_message, None
            try:
                await msg.delete()
            except discord.HTTPException:
                pass

    # ------------------------------------------------------------ the buttons
    async def on_button(self, interaction: discord.Interaction, action: str) -> None:
        cmd = {"pause": self._toggle, "skip": self._skip, "stop": self._stop, "shuffle": self._shuffle,
               "repeat": self._cycle_repeat}[action]
        await cmd(interaction)

    async def _toggle(self, interaction: discord.Interaction) -> None:
        vc = interaction.guild.voice_client
        if vc is not None and vc.is_paused():
            await self._resume(interaction)
        else:
            await self._pause(interaction)

    async def _cycle_repeat(self, interaction: discord.Interaction) -> None:
        p = self.players.get(interaction.guild_id)
        mode = REPEATS[(REPEATS.index(p.queue.repeat) + 1) % len(REPEATS)] if p else "off"
        await self._repeat(interaction, mode)

    # ------------------------------------------------------------ /music …
    @music.command(name="queue", description="What's playing and what's coming up")
    @app_commands.describe(page="Page of the queue (10 a page)")
    async def queue_cmd(self, interaction: discord.Interaction, page: app_commands.Range[int, 1, 50] = 1) -> None:
        p = self.players.get(interaction.guild_id)
        if p is None or p.queue.current is None:
            await self.reply(interaction, voice.say("music_nothing"))
            return
        lines = [f"**Now:** {p.queue.current.title} ({clock(p.position())} / {clock(p.queue.current.duration)})"]
        start = (page - 1) * 10
        for i, t in enumerate(p.queue.tracks[start:start + 10], start + 1):
            lines.append(f"`{i}.` {t.title[:90]} · {clock(t.duration)} · <@{t.requester_id}>")
        pages = max(1, -(-len(p.queue.tracks) // 10))
        lines.append(f"\n{len(p.queue.tracks)} waiting ({clock(p.queue.total_seconds())}) · repeat {p.queue.repeat}"
                     f" · page {min(page, pages)} of {pages}")
        await self.reply(interaction, "\n".join(lines)[:1990])

    @music.command(name="nowplaying", description="What's playing right now")
    async def nowplaying_cmd(self, interaction: discord.Interaction) -> None:
        p = self.players.get(interaction.guild_id)
        if p is None or p.queue.current is None:
            await self.reply(interaction, voice.say("music_nothing"))
            return
        e = self.np_embed(p)
        e.add_field(name="Where we're up to",
                    value=f"{progress_bar(p.position(), p.queue.current.duration)} "
                          f"{clock(p.position())} / {clock(p.queue.current.duration)}", inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @music.command(name="skip", description="Skip to the next track")
    async def skip_cmd(self, interaction: discord.Interaction) -> None:
        await self._skip(interaction)

    async def _skip(self, interaction: discord.Interaction) -> None:
        p = self.players.get(interaction.guild_id)
        problem = await self.gate(interaction, dj=True, track=p.queue.current if p else None)
        if problem:
            await self.reply(interaction, problem)
            return
        title = p.queue.current.title if p.queue.current else "that"
        p.skip = True
        interaction.guild.voice_client.stop()
        await self.reply(interaction, voice.say("music_skipped", title=title), ephemeral=False)

    @music.command(name="pause", description="Pause the music")
    async def pause_cmd(self, interaction: discord.Interaction) -> None:
        await self._pause(interaction)

    async def _pause(self, interaction: discord.Interaction) -> None:
        problem = await self.gate(interaction)
        if problem:
            await self.reply(interaction, problem)
            return
        vc, p = interaction.guild.voice_client, self.players[interaction.guild_id]
        if vc.is_playing():
            vc.pause()
            p.paused_at = time.monotonic()
        await self.reply(interaction, voice.say("music_paused"))

    @music.command(name="resume", description="Carry on playing")
    async def resume_cmd(self, interaction: discord.Interaction) -> None:
        await self._resume(interaction)

    async def _resume(self, interaction: discord.Interaction) -> None:
        problem = await self.gate(interaction)
        if problem:
            await self.reply(interaction, problem)
            return
        vc, p = interaction.guild.voice_client, self.players[interaction.guild_id]
        if vc.is_paused():
            if p.paused_at is not None:
                p.started += time.monotonic() - p.paused_at
                p.paused_at = None
            vc.resume()
        await self.reply(interaction, voice.say("music_resumed"))

    @music.command(name="stop", description="Stop the music, clear the queue and leave the voice channel")
    async def stop_cmd(self, interaction: discord.Interaction) -> None:
        await self._stop(interaction)

    async def _stop(self, interaction: discord.Interaction) -> None:
        problem = await self.gate(interaction, dj=True)
        if problem:
            await self.reply(interaction, problem)
            return
        await self.reply(interaction, voice.say("music_stopped"), ephemeral=False)
        await self.stop(interaction.guild, self.players[interaction.guild_id])

    @music.command(name="clear", description="Empty the queue (the current track keeps playing)")
    async def clear_cmd(self, interaction: discord.Interaction) -> None:
        problem = await self.gate(interaction, dj=True)
        if problem:
            await self.reply(interaction, problem)
            return
        n = self.players[interaction.guild_id].queue.clear()
        await self.reply(interaction, f"Cleared {n} track{'s' if n != 1 else ''} from the queue.", ephemeral=False)
        await self.refresh_np(self.players[interaction.guild_id])

    @music.command(name="remove", description="Take a track out of the queue")
    @app_commands.describe(position="Its number in /music queue")
    async def remove_cmd(self, interaction: discord.Interaction, position: app_commands.Range[int, 1, MAX_QUEUE]) -> None:
        p = self.players.get(interaction.guild_id)
        track = p.queue.tracks[position - 1] if p and 0 < position <= len(p.queue.tracks) else None
        problem = await self.gate(interaction, dj=True, track=track)
        if problem:
            await self.reply(interaction, problem)
            return
        if track is None:
            await self.reply(interaction, f"There's no number {position} in the queue.")
            return
        p.queue.remove(position)
        await self.reply(interaction, f"Took **{track.title}** out of the queue.", ephemeral=False)
        await self.refresh_np(p)

    @music.command(name="move", description="Move a track to another place in the queue")
    @app_commands.describe(position="Its number in /music queue", to="Where it should go (1 is next)")
    async def move_cmd(self, interaction: discord.Interaction, position: app_commands.Range[int, 1, MAX_QUEUE],
                       to: app_commands.Range[int, 1, MAX_QUEUE]) -> None:
        problem = await self.gate(interaction, dj=True)
        if problem:
            await self.reply(interaction, problem)
            return
        p = self.players[interaction.guild_id]
        t = p.queue.move(position, to)
        if t is None:
            await self.reply(interaction, f"There's no number {position} in the queue.")
            return
        await self.reply(interaction, f"Moved **{t.title}** to number {min(to, len(p.queue.tracks))}.", ephemeral=False)
        await self.refresh_np(p)

    @music.command(name="shuffle", description="Shuffle the queue")
    async def shuffle_cmd(self, interaction: discord.Interaction) -> None:
        await self._shuffle(interaction)

    async def _shuffle(self, interaction: discord.Interaction) -> None:
        problem = await self.gate(interaction, dj=True)
        if problem:
            await self.reply(interaction, problem)
            return
        p = self.players[interaction.guild_id]
        p.queue.shuffle()
        await self.reply(interaction, f"Shuffled {len(p.queue.tracks)} tracks. 🔀", ephemeral=False)
        await self.refresh_np(p)

    @music.command(name="repeat", description="Repeat nothing, this track, or the whole queue")
    @app_commands.choices(mode=REPEAT_CHOICES)
    async def repeat_cmd(self, interaction: discord.Interaction, mode: app_commands.Choice[str]) -> None:
        await self._repeat(interaction, mode.value)

    async def _repeat(self, interaction: discord.Interaction, mode: str) -> None:
        problem = await self.gate(interaction, dj=True)
        if problem:
            await self.reply(interaction, problem)
            return
        p = self.players[interaction.guild_id]
        p.queue.repeat = mode
        label = dict((c.value, c.name) for c in REPEAT_CHOICES)[mode]
        await self.reply(interaction, f"Repeat: **{label}**.", ephemeral=False)
        await self.refresh_np(p)

    @music.command(name="seek", description="Jump to a point in the current track")
    @app_commands.describe(to="Like 1:30, 90 or 2m10s")
    async def seek_cmd(self, interaction: discord.Interaction, to: app_commands.Range[str, 1, 12]) -> None:
        p = self.players.get(interaction.guild_id)
        problem = await self.gate(interaction, dj=True, track=p.queue.current if p else None)
        if problem:
            await self.reply(interaction, problem)
            return
        seconds, t = parse_position(to), p.queue.current
        if seconds is None:
            await self.reply(interaction, "Give me a time like 1:30, 90 or 2m10s.")
            return
        if t is None or t.live:
            await self.reply(interaction, "You can't seek in a live stream.")
            return
        if seconds >= (t.duration or 0):
            await self.reply(interaction, f"That track is only {clock(t.duration)} long.")
            return
        p.seek_to = seconds
        interaction.guild.voice_client.stop()
        await self.reply(interaction, f"Jumping to {clock(seconds)}.", ephemeral=False)

    @music.command(name="volume", description="Turn it up or down (for everyone)")
    @app_commands.describe(percent="1 to 150; 100 is the track as it is")
    async def volume_cmd(self, interaction: discord.Interaction, percent: app_commands.Range[int, 1, 150]) -> None:
        problem = await self.gate(interaction, dj=True)
        if problem:
            await self.reply(interaction, problem)
            return
        p = self.players[interaction.guild_id]
        p.volume = percent / 100
        source = getattr(interaction.guild.voice_client, "source", None)
        if source is not None and hasattr(source, "volume"):
            source.volume = p.volume
        await self.reply(interaction, f"Volume: **{percent}%**.", ephemeral=False)
        await self.refresh_np(p)

    @music.command(name="lyrics", description="Lyrics for what's playing (or another song), just for you")
    @app_commands.describe(song="Another song, if not the one playing")
    async def lyrics_cmd(self, interaction: discord.Interaction, song: str | None = None) -> None:
        p = self.players.get(interaction.guild_id)
        if not song and (p is None or p.queue.current is None):
            await self.reply(interaction, voice.say("music_nothing"))
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        title = song or re.sub(r"\s*[\(\[][^)\]]*(official|video|audio|lyric|hd|remaster)[^)\]]*[\)\]]", "",
                               p.queue.current.title, flags=re.I)
        found = await lyrics(title)
        if not found:
            await interaction.followup.send(f"{voice.cuss(None)} I couldn't find lyrics for **{title[:100]}**.", ephemeral=True)
            return
        chunks = [found[i:i + 4000] for i in range(0, min(len(found), 12000), 4000)]
        embeds = [discord.Embed(colour=COLOUR, title=title[:250] if i == 0 else None, description=c)
                  for i, c in enumerate(chunks)]
        embeds[-1].set_footer(text="Lyrics from LRCLIB")
        await interaction.followup.send(embeds=embeds, ephemeral=True)

    @music.command(name="leave", description="Send PlunderBot out of the voice channel")
    async def leave_cmd(self, interaction: discord.Interaction) -> None:
        await self._stop(interaction)

    # ------------------------------------------------------------ leaving when nobody's listening
    @tasks.loop(seconds=30)
    async def watch(self) -> None:
        now = time.monotonic()
        for guild_id, p in list(self.players.items()):
            guild = self.bot.get_guild(guild_id)
            if guild is None or guild.voice_client is None:
                self.players.pop(guild_id, None)
                continue
            s = await self.bot.db.get_settings(guild_id)
            vc = guild.voice_client
            playing = vc.is_playing() or vc.is_paused()
            if s.music_stay and self.listeners(guild):
                p.idle_since = None
                continue
            if playing and self.listeners(guild):
                p.idle_since = None
                continue
            p.idle_since = p.idle_since or now
            if now - p.idle_since >= max(1, s.music_idle_minutes) * 60 and not s.music_stay:
                await self.say_in_channel(guild, p, voice.say("music_left_idle"))
                await self.stop(guild, p)

    @watch.before_loop
    async def _wait_until_ready(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after) -> None:
        """Forget the queue if PlunderBot is disconnected (kicked out of the channel, say)."""
        if member.id != getattr(self.bot.user, "id", None) or after.channel is not None:
            return
        p = self.players.pop(member.guild.id, None)
        if p is not None:
            p.stopping = True
            await self.clear_np(p)


async def setup(bot) -> None:
    await bot.add_cog(Music(bot))
