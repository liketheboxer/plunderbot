"""The Ship's Ledger: pirates' ships, their Sea of Thieves hauls, and pirate profiles.

/ship register|edit|retire|show|fleet|log and /pirate profile|set.
A Sea of Thieves crew is reminded at sail to screenshot the Captain's Log before logging off, and
asked for it when the voyage is over. /ship log reads the screenshot with Claude (Haiku), shows
what it read privately with Confirm / Edit / Cancel, and a confirmed haul goes up as a reply to
the crew card and into the ship's and every pirate aboard's totals (everyone aboard gets the
full haul, as in the game). Reading costs a fraction of a cent and counts toward Parley's
monthly budget.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from .. import images, voice
from ..ai import AIError
from ..crew_logic import iso, now_utc
from ..discord_util import addressed_to
from ..ledger_logic import (KINDS, PENDING_LIFETIME, READ_SYSTEM, READ_TOOL, RECENT_CREW, ask_at_end, can_change,
                            dump_rows, haul_line, ledger_summary, load_rows, log_keeper, parse_number,
                            parse_reputation, parse_stats, pick_crew, prepare_image, read_messages, read_response,
                            render_fleet, render_log, render_pirate, render_ship, reputation_text, ship_label,
                            stats_text)
from ..parley_logic import cost

log = logging.getLogger("plunderbot.ledger")

MAX_SHIPS = 10
LOG_WORDS = re.compile(r"\b(log|logs|ledger|stats?|plunder|gold|haul|voyage|captain'?s?|loot|doubloons?)\b", re.I)
PICTURE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def screenshot_of(message):
    """The first picture attached to a message, if any."""
    for a in getattr(message, "attachments", None) or []:
        kind = (a.content_type or "").lower()
        if kind.startswith("image/") or (a.filename or "").lower().endswith(PICTURE_EXT):
            return a
    return None
MAX_UPLOAD = 25 * 1024 * 1024
KIND_CHOICES = [app_commands.Choice(name=k, value=k) for k in KINDS]


def _is_mod(member) -> bool:
    p = getattr(member, "guild_permissions", None)
    return bool(p and (p.manage_guild or p.manage_messages or p.administrator))


def _clean(text: str | None, limit: int) -> str | None:
    cleaned = " ".join((text or "").replace("`", "'").split())[:limit].strip()
    return cleaned or None


class LedgerButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ledger:(?P<action>ok|edit|drop):(?P<id>\d+)"):
    """Confirm / Edit / Cancel under a Captain's Log reading. Survives restarts."""
    LOOK = {"ok": ("Confirm", discord.ButtonStyle.success), "edit": ("Edit", discord.ButtonStyle.primary),
            "drop": ("Cancel", discord.ButtonStyle.secondary)}

    def __init__(self, action: str, log_id: int, disabled: bool = False):
        label, style = self.LOOK[action]
        super().__init__(discord.ui.Button(label=label, style=style, custom_id=f"ledger:{action}:{log_id}",
                                           disabled=disabled))
        self.action, self.log_id = action, log_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str]):
        return cls(match["action"], int(match["id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        cog = interaction.client.get_cog("ShipLedger")
        if cog is None:
            await interaction.response.send_message(voice.say("error"), ephemeral=True)
            return
        await cog.on_button(interaction, self.action, self.log_id)


def reading_view(entry) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    empty = not (entry.gold or entry.doubloons or entry.emissary or load_rows(entry.stats) or load_rows(entry.reputation))
    view.add_item(LedgerButton("ok", entry.id, disabled=empty))
    view.add_item(LedgerButton("edit", entry.id))
    view.add_item(LedgerButton("drop", entry.id))
    return view


class HaulForm(discord.ui.Modal, title="Captain's Log"):
    def __init__(self, cog, entry):
        super().__init__(timeout=900)
        self.cog, self.log_id = cog, entry.id
        self.gold = discord.ui.TextInput(label="Gold", default=f"{entry.gold:,}" if entry.gold else None,
                                         placeholder="12,345", max_length=20, required=False)
        self.doubloons = discord.ui.TextInput(label="Doubloons", default=f"{entry.doubloons:,}" if entry.doubloons else None,
                                              placeholder="0", max_length=20, required=False)
        self.emissary = discord.ui.TextInput(label="Emissary", default=entry.emissary, required=False, max_length=100,
                                             placeholder="Gold Hoarders, grade 5")
        self.reputation = discord.ui.TextInput(label="Reputation (one per line)", style=discord.TextStyle.paragraph,
                                               default=reputation_text(load_rows(entry.reputation)) or None,
                                               required=False, max_length=600, placeholder="Merchant Alliance: 1,200")
        self.stats = discord.ui.TextInput(label="Voyage stats (one per line)", style=discord.TextStyle.paragraph,
                                          default=stats_text(load_rows(entry.stats)) or None, required=False,
                                          max_length=800, placeholder="Islands visited: 6\nShips sunk: 2")
        for item in (self.gold, self.doubloons, self.emissary, self.reputation, self.stats):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.apply_form(interaction, self.log_id, gold=self.gold.value, doubloons=self.doubloons.value,
                                  emissary=self.emissary.value, reputation=self.reputation.value,
                                  stats=self.stats.value)


class ShipLedger(commands.Cog):
    ship = app_commands.Group(name="ship", description="Your ships and their plunder", guild_only=True)
    pirate = app_commands.Group(name="pirate", description="Pirate profiles", guild_only=True)

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(LedgerButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(LedgerButton)

    # ------------------------------------------------------------ helpers
    async def ship_choices(self, guild_id: int, user_id: int, current: str, *, own_only: bool,
                           include_retired: bool = False) -> list[app_commands.Choice[str]]:
        ships = await self.bot.db.ships(guild_id, None if not own_only else user_id, include_retired)
        ships.sort(key=lambda s: (s.owner_id != user_id, s.name.lower()))
        out = []
        for s in ships:
            if current.lower() not in s.name.lower():
                continue
            owner = ""
            if s.owner_id != user_id:
                guild = self.bot.get_guild(guild_id)
                m = guild.get_member(s.owner_id) if guild else None
                owner = f" · {m.display_name}'s" if m else ""
            out.append(app_commands.Choice(name=f"{s.name} ({s.kind}){owner}"[:100], value=str(s.id)))
        return out[:25]

    async def find_ship(self, guild_id: int, value: str | None):
        if not value:
            return None
        ship = await self.bot.db.get_ship(int(value)) if value.isdigit() else None
        if ship is None:  # typed a name instead of picking
            matches = [s for s in await self.bot.db.ships(guild_id) if s.name.lower() == value.strip().lower()]
            ship = matches[0] if len(matches) == 1 else None
        return ship if ship is not None and ship.guild_id == guild_id else None

    def image_file(self, name: str | None) -> dict:
        f = images.file_for(name, self.bot.config.data_dir)
        return {"file": f} if f else {}

    # ------------------------------------------------------------ /ship
    @ship.command(name="register", description="Add your Sea of Thieves ship to the fleet")
    @app_commands.describe(name="Her name", kind="Sloop, Brigantine or Galleon", motto="A line for her profile",
                           image="A picture of her for her profile")
    @app_commands.choices(kind=KIND_CHOICES)
    async def ship_register(self, interaction: discord.Interaction, name: app_commands.Range[str, 1, 60],
                            kind: app_commands.Choice[str], motto: app_commands.Range[str, 1, 150] | None = None,
                            image: discord.Attachment | None = None) -> None:
        name = _clean(name, 60)
        mine = await self.bot.db.ships(interaction.guild_id, interaction.user.id)
        if len(mine) >= MAX_SHIPS:
            await interaction.response.send_message(voice.say("ship_too_many"), ephemeral=True)
            return
        if any(s.name.lower() == (name or "").lower() for s in mine):
            await interaction.response.send_message(voice.say("ship_name_taken", ship=name), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        picture = await self._save_image(interaction, image)
        if picture is False:
            return
        ship = await self.bot.db.create_ship(guild_id=interaction.guild_id, owner_id=interaction.user.id, name=name,
                                             kind=kind.value, motto=_clean(motto, 150), image=picture,
                                             created_at=iso(now_utc()))
        await interaction.followup.send(voice.say("ship_registered", ship=ship_label(ship)), ephemeral=True)

    async def _save_image(self, interaction, image):
        """The stored picture name, None for none, or False after telling the member it won't do."""
        if image is None:
            return None
        try:
            return await images.save(image, self.bot.config.data_dir)
        except (images.ImageError, discord.HTTPException, OSError) as e:
            log.warning("Ship picture refused: %r", e)
            await interaction.followup.send(voice.say("image_bad"), ephemeral=True)
            return False

    @ship.command(name="edit", description="Change one of your ships")
    @app_commands.describe(ship="Which of your ships", name="A new name", kind="A new class",
                           motto="A new motto (a single dash clears it)", image="A new picture")
    @app_commands.choices(kind=KIND_CHOICES)
    async def ship_edit(self, interaction: discord.Interaction, ship: str,
                        name: app_commands.Range[str, 1, 60] | None = None,
                        kind: app_commands.Choice[str] | None = None,
                        motto: app_commands.Range[str, 1, 150] | None = None,
                        image: discord.Attachment | None = None) -> None:
        found = await self.find_ship(interaction.guild_id, ship)
        if found is None:
            await interaction.response.send_message(voice.say("ship_unknown"), ephemeral=True)
            return
        if found.owner_id != interaction.user.id and not _is_mod(interaction.user):
            await interaction.response.send_message(voice.say("ship_not_yours"), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        changes = {}
        if name:
            changes["name"] = _clean(name, 60)
        if kind:
            changes["kind"] = kind.value
        if motto:
            changes["motto"] = None if motto.strip() == "-" else _clean(motto, 150)
        picture = await self._save_image(interaction, image)
        if picture is False:
            return
        if picture:
            changes["image"] = picture
        found = await self.bot.db.update_ship(found.id, **changes)
        await interaction.followup.send(voice.say("ship_updated", ship=ship_label(found)), ephemeral=True)

    @ship.command(name="retire", description="Retire one of your ships (her ledger stays)")
    async def ship_retire(self, interaction: discord.Interaction, ship: str) -> None:
        found = await self.find_ship(interaction.guild_id, ship)
        if found is None or found.retired:
            await interaction.response.send_message(voice.say("ship_unknown"), ephemeral=True)
            return
        if found.owner_id != interaction.user.id and not _is_mod(interaction.user):
            await interaction.response.send_message(voice.say("ship_not_yours"), ephemeral=True)
            return
        await self.bot.db.update_ship(found.id, retired=1)
        await interaction.response.send_message(voice.say("ship_retired", ship=ship_label(found)), ephemeral=True)

    @ship.command(name="show", description="A ship's profile: her captain, plunder and trusted crew")
    @app_commands.describe(ship="Which ship (leave empty for your own)")
    async def ship_show(self, interaction: discord.Interaction, ship: str | None = None) -> None:
        if ship:
            found = await self.find_ship(interaction.guild_id, ship)
        else:
            mine = await self.bot.db.ships(interaction.guild_id, interaction.user.id)
            found = mine[0] if mine else None
            if found is None:
                await interaction.response.send_message(voice.say("ship_none"), ephemeral=True)
                return
        if found is None:
            await interaction.response.send_message(voice.say("ship_unknown"), ephemeral=True)
            return
        embed = await self.ship_embed(interaction.guild, found)
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none(),
                                                **self.image_file(found.image))

    async def ship_embed(self, guild, ship) -> discord.Embed:
        db = self.bot.db
        owner = guild.get_member(ship.owner_id) if guild else None
        embed = render_ship(ship, totals=await db.ledger_totals(ship.guild_id, ship_id=ship.id),
                            shipmates=await db.shipmates(ship.guild_id, ship.id),
                            recent=await db.recent_logs(ship.guild_id, ship_id=ship.id),
                            owner_name=owner.display_name if owner else "a pirate")
        return images.show(embed, ship.image, self.bot.config.data_dir)

    @ship.command(name="fleet", description="The richest ships and pirates in the ledger")
    async def ship_fleet(self, interaction: discord.Interaction) -> None:
        embed = await self.fleet_embed(interaction.guild_id)
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    async def ship_names(self, guild_id: int) -> dict[int, str]:
        return {s.id: ship_label(s) for s in await self.bot.db.ships(guild_id, include_retired=True)}

    async def fleet_embed(self, guild_id: int) -> discord.Embed:
        db = self.bot.db
        return render_fleet(await db.ship_leaderboard(guild_id), await db.pirate_leaderboard(guild_id),
                            await self.ship_names(guild_id))

    async def summary(self, guild_id: int) -> str:
        """The ledger in a few lines, for Parley."""
        db = self.bot.db
        return ledger_summary(await db.ship_leaderboard(guild_id), await db.pirate_leaderboard(guild_id),
                              {k: v.split(" ", 1)[-1] for k, v in (await self.ship_names(guild_id)).items()},
                              await db.ledger_totals(guild_id))

    @ship_edit.autocomplete("ship")
    @ship_retire.autocomplete("ship")
    async def own_ship_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.ship_choices(interaction.guild_id, interaction.user.id, current,
                                       own_only=not _is_mod(interaction.user))

    @ship_show.autocomplete("ship")
    async def any_ship_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.ship_choices(interaction.guild_id, interaction.user.id, current, own_only=False,
                                       include_retired=True)

    # ------------------------------------------------------------ /ship log
    @ship.command(name="log", description="Log a Sea of Thieves voyage from your Captain's Log screenshot")
    @app_commands.describe(screenshot="The Captain's Log two-page spread with your Gold (leave empty to type it in)",
                           crew="Which crew (default: the one you sailed with most recently)",
                           ship="Which ship (default: the crew's ship)")
    async def ship_log(self, interaction: discord.Interaction, screenshot: discord.Attachment | None = None,
                       crew: str | None = None, ship: str | None = None) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        text, embed, view = await self.start_reading(interaction.guild, interaction.user, screenshot, crew, ship)
        kw = {"embed": embed, "view": view} if embed is not None else {}
        await interaction.followup.send(text, ephemeral=True, **kw)

    async def start_reading(self, guild, user, screenshot=None, crew: str | None = None, ship: str | None = None):
        """Read a Captain's Log into a pending ledger entry. Returns (text, embed, view) to show the member;
        embed and view are None when there's nothing to confirm."""
        now, db = now_utc(), self.bot.db
        await db.prune_pending_logs(iso(now - PENDING_LIFETIME))

        chosen = None
        if crew and crew.isdigit():
            chosen = await db.get_crew(int(crew))
            if chosen is not None and (chosen.guild_id != guild.id or
                                       (user.id not in chosen.members and not _is_mod(user))):
                chosen = None
        if chosen is None and not crew:
            recent = await db.crews_sailed_between(guild.id, iso(now - RECENT_CREW), iso(now + timedelta(minutes=1)))
            chosen = pick_crew([c for c in recent if user.id in c.members], now)

        found = await self.find_ship(guild.id, ship) if ship else None
        if found is None and chosen is not None and chosen.ship_id:
            found = await db.get_ship(chosen.ship_id)
        if found is None and not ship:
            mine = await db.ships(guild.id, user.id)
            if len(mine) == 1 and (chosen is None or log_keeper(chosen, mine[0]) == user.id):
                found = mine[0]

        if chosen is not None:
            existing = await db.confirmed_log_for_crew(chosen.id)
            if existing and not can_change(user.id, existing, chosen, found, _is_mod(user)):
                return voice.say("ledger_replace_denied"), None, None

        haul, line, notes = None, "ledger_manual", None
        if screenshot is not None:
            haul, line, error = await self.read(guild.id, screenshot)
            if error:  # a picture that wouldn't open
                return voice.say(line, error=error), None, None
        entry = await db.create_log(
            guild_id=guild.id, crew_id=chosen.id if chosen else None, ship_id=found.id if found else None,
            logged_by=user.id, created_at=iso(now), source="screenshot" if haul else "manual",
            gold=haul.gold if haul else 0, doubloons=haul.doubloons if haul else 0,
            emissary=haul.emissary if haul else None, reputation=dump_rows(haul.reputation if haul else []),
            stats=dump_rows(haul.stats if haul else []), pirates=list(chosen.members) if chosen else [user.id])
        if haul is not None:
            notes = haul.notes
        return (voice.say(line), render_log(entry, ship=found, crew=chosen, pending=True, notes=notes),
                reading_view(entry))

    async def read(self, guild_id: int, screenshot):
        """(haul or None, the voice line to show, why the picture wouldn't open or None)."""
        claude = self.claude
        if claude is None:
            return None, "ledger_read_failed", None
        s = await self.bot.db.get_settings(guild_id)
        parley = self.bot.get_cog("Parley")
        month = parley.today(s)[1] if parley else datetime.now(timezone.utc).strftime("%Y-%m")
        spent, _ = await self.bot.db.parley_spend(guild_id, month)
        if spent >= s.parley_budget_cents / 100:
            return None, "ledger_no_budget", None
        try:
            if (screenshot.size or 0) > MAX_UPLOAD:
                raise images.ImageError("over 25 MB")
            media_type, b64 = prepare_image(await screenshot.read())
        except (images.ImageError, discord.HTTPException, OSError) as e:
            return None, "ledger_bad_image", images.reason(e).rstrip(".")
        try:
            resp = await claude.create(system=READ_SYSTEM, messages=read_messages(media_type, b64), tools=[READ_TOOL],
                                       tool_choice={"type": "tool", "name": READ_TOOL["name"]}, max_tokens=800)
        except (AIError, OSError, TimeoutError) as e:
            log.warning("Couldn't read a Captain's Log: %s", e)
            return None, "ledger_read_failed", None
        usage = resp.get("usage") or {}
        await self.bot.db.add_parley_spend(guild_id, month, cost(usage), usage.get("input_tokens", 0),
                                           usage.get("output_tokens", 0))
        haul = read_response(resp)
        if haul is None:
            return None, "ledger_read_failed", None
        if not haul.is_log:
            return haul, "ledger_not_a_log", None
        return haul, "ledger_check", None

    # ------------------------------------------------------------ a screenshot posted to PlunderBot in chat
    def wants(self, message) -> bool:
        """A message PlunderBot should read as a Captain's Log: addressed to it (an @mention or a reply), with a
        picture, and either no words, words about the log, or a reply to one of its ledger messages."""
        me = self.bot.user
        if me is None or message.guild is None or message.author.bot or not addressed_to(me.id, message):
            return False
        if screenshot_of(message) is None:
            return False
        text = re.sub(rf"<@!?{me.id}>", "", message.content or "").strip()
        ref = message.reference
        replied = getattr(ref, "resolved", None) if ref else None
        if isinstance(replied, discord.Message) and replied.author.id == me.id and (
                "Captain's Log" in (replied.content or "") or "/ship log" in (replied.content or "")
                or any("Captain's Log" in (e.title or "") for e in replied.embeds)):
            return True
        return not text or bool(LOG_WORDS.search(text))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not self.wants(message):
            return
        s = await self.bot.db.get_settings(message.guild.id)
        author = message.author
        if s.pending_role_id and hasattr(author, "get_role") and author.get_role(s.pending_role_id):
            return
        try:
            async with message.channel.typing():
                text, embed, view = await self.start_reading(message.guild, author, screenshot_of(message))
            kw = {"embed": embed, "view": view} if embed is not None else {}
            await message.reply(text, mention_author=False, allowed_mentions=discord.AllowedMentions.none(), **kw)
        except Exception:
            log.exception("Couldn't read a Captain's Log posted in chat")
            try:
                await message.reply(voice.say("ledger_read_failed"), mention_author=False,
                                    allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass

    @property
    def claude(self):
        parley = self.bot.get_cog("Parley")
        return getattr(parley, "claude", None)

    @ship_log.autocomplete("crew")
    async def crew_autocomplete(self, interaction: discord.Interaction, current: str):
        now = now_utc()
        crews = await self.bot.db.crews_sailed_between(interaction.guild_id, iso(now - timedelta(days=7)),
                                                       iso(now + timedelta(minutes=1)))
        out = []
        for c in sorted(crews, key=lambda c: c.sailed_at or "", reverse=True):
            if c.game_key != "sot" or interaction.user.id not in c.members:
                continue
            when = datetime.fromisoformat(c.sailed_at)
            label = f"{c.title or c.size_label} · {when.strftime('%a %b')} {when.day}"
            if current.lower() in label.lower():
                out.append(app_commands.Choice(name=label[:100], value=str(c.id)))
        return out[:25]

    @ship_log.autocomplete("ship")
    async def log_ship_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.ship_choices(interaction.guild_id, interaction.user.id, current, own_only=False)

    # ------------------------------------------------------------ Confirm / Edit / Cancel
    async def on_button(self, interaction: discord.Interaction, action: str, log_id: int) -> None:
        entry = await self.bot.db.get_log(log_id)
        if entry is None or entry.status != "pending":
            await interaction.response.send_message(voice.say("ledger_gone"), ephemeral=True)
            return
        if interaction.user.id != entry.logged_by:
            await interaction.response.send_message(voice.say("ledger_not_yours"), ephemeral=True)
            return
        if action == "edit":
            await interaction.response.send_modal(HaulForm(self, entry))
        elif action == "drop":
            await self.bot.db.delete_log(entry.id)
            await interaction.response.edit_message(content=voice.say("ledger_cancelled"), embed=None, view=None)
        elif action == "ok":
            await self.confirm(interaction, entry)

    async def apply_form(self, interaction: discord.Interaction, log_id: int, *, gold: str, doubloons: str,
                         emissary: str, reputation: str, stats: str) -> None:
        entry = await self.bot.db.get_log(log_id)
        if entry is None or entry.status != "pending" or interaction.user.id != entry.logged_by:
            await interaction.response.send_message(voice.say("ledger_gone"), ephemeral=True)
            return
        numbers = {}
        for field_name, text in (("gold", gold), ("doubloons", doubloons)):
            value = parse_number(text) if (text or "").strip() else 0
            if value is None or value < 0:
                await interaction.response.send_message(voice.say("ledger_bad_number", error=f"“{text}”"),
                                                        ephemeral=True)
                return
            numbers[field_name] = value
        entry = await self.bot.db.update_log(entry.id, **numbers, emissary=_clean(emissary, 100),
                                             reputation=dump_rows(parse_reputation(reputation)),
                                             stats=dump_rows(parse_stats(stats)))
        ship = await self.bot.db.get_ship(entry.ship_id)
        crew = await self.bot.db.get_crew(entry.crew_id) if entry.crew_id else None
        await interaction.response.edit_message(content=voice.say("ledger_check"),
                                                embed=render_log(entry, ship=ship, crew=crew, pending=True),
                                                view=reading_view(entry))

    async def confirm(self, interaction: discord.Interaction, entry) -> None:
        db, guild = self.bot.db, interaction.guild
        crew = await db.get_crew(entry.crew_id) if entry.crew_id else None
        ship = await db.get_ship(entry.ship_id)
        old = await db.confirmed_log_for_crew(crew.id) if crew else None
        if old is not None and not can_change(interaction.user.id, old, crew, ship, _is_mod(interaction.user)):
            await interaction.response.send_message(voice.say("ledger_replace_denied"), ephemeral=True)
            return
        entry = await db.update_log(entry.id, status="confirmed", confirmed_at=iso(now_utc()))
        if old is not None:
            await self.remove(guild, old)
        message = getattr(interaction, "message", None)
        public = message is not None and not getattr(getattr(message, "flags", None), "ephemeral", True)
        channel_id = getattr(interaction.channel, "id", None)
        if public and (crew is None or crew.channel_id == channel_id):
            # Read from a screenshot posted in chat, right where the crew is: that post becomes the ledger entry.
            await interaction.response.edit_message(
                content=voice.say("ledger_logged", haul=haul_line(entry.gold, entry.doubloons)),
                embed=render_log(entry, ship=ship, crew=crew), view=None)
            await db.update_log(entry.id, channel_id=channel_id, message_id=message.id)
            crew_cog = self.bot.get_cog("CrewCall")
            if crew is not None and crew_cog is not None:
                await crew_cog.refresh_card(guild, await db.get_crew(crew.id))
            return
        await interaction.response.edit_message(content=voice.say("ledger_confirmed"),
                                                embed=render_log(entry, ship=ship, crew=crew), view=None)
        await self.announce(guild, entry, crew, ship, fallback=interaction.channel)

    async def announce(self, guild, entry, crew, ship, fallback=None) -> None:
        """Post the confirmed haul as a reply to the crew card (or where /ship log was used), and update the card."""
        channel = guild.get_channel(crew.channel_id) if crew is not None and guild is not None else None
        channel = channel or fallback
        if channel is None:
            return
        kw = {}
        if crew is not None and crew.message_id and channel.id == crew.channel_id:
            kw["reference"] = discord.MessageReference(message_id=crew.message_id, channel_id=crew.channel_id,
                                                       fail_if_not_exists=False)
        try:
            message = await channel.send(voice.say("ledger_logged", haul=haul_line(entry.gold, entry.doubloons)),
                                         embed=render_log(entry, ship=ship, crew=crew),
                                         allowed_mentions=discord.AllowedMentions.none(), **kw)
            await self.bot.db.update_log(entry.id, channel_id=channel.id, message_id=message.id)
        except discord.HTTPException as e:
            log.warning("Couldn't post ledger entry %s: %s", entry.id, e)
        crew_cog = self.bot.get_cog("CrewCall")
        if crew is not None and crew_cog is not None:
            await crew_cog.refresh_card(guild, await self.bot.db.get_crew(crew.id))

    async def remove(self, guild, entry) -> None:
        """Take a haul out of the ledger, and its post down."""
        await self.bot.db.delete_log(entry.id)
        if guild is not None and entry.channel_id and entry.message_id:
            channel = guild.get_channel(entry.channel_id)
            if channel is not None:
                try:
                    await channel.get_partial_message(entry.message_id).delete()
                except discord.HTTPException:
                    pass

    # ------------------------------------------------------------ reminders, from Crew Call
    async def on_crew_sailed(self, guild, crew) -> None:
        if crew.game_key != "sot":
            return
        s = await self.bot.db.get_settings(guild.id)
        if not s.ledger_reminders:
            return
        await self._nudge(guild, crew, "ledger_sail_reminder", reply=False)

    async def on_crew_ended(self, guild, crew) -> None:
        if not ask_at_end(crew, now_utc()):
            return
        s = await self.bot.db.get_settings(guild.id)
        if not s.ledger_reminders or await self.bot.db.confirmed_log_for_crew(crew.id):
            return
        await self._nudge(guild, crew, "ledger_end_ask", reply=True)

    async def _nudge(self, guild, crew, key: str, reply: bool) -> None:
        channel = guild.get_channel(crew.channel_id) if guild is not None else None
        if channel is None:
            return
        keeper = log_keeper(crew, await self.bot.db.get_ship(crew.ship_id))
        kw = {}
        if reply and crew.message_id:
            kw["reference"] = discord.MessageReference(message_id=crew.message_id, channel_id=crew.channel_id,
                                                       fail_if_not_exists=False)
        try:
            await channel.send(voice.say(key, captain=f"<@{keeper}>"),
                               allowed_mentions=discord.AllowedMentions(everyone=False, roles=False,
                                                                        users=[discord.Object(keeper)]), **kw)
        except discord.HTTPException as e:
            log.warning("Couldn't send the ledger reminder for crew %s: %s", crew.id, e)

    # ------------------------------------------------------------ /pirate
    @pirate.command(name="profile", description="A pirate's profile: crews, ships and plunder")
    @app_commands.describe(member="Whose profile (leave empty for your own)")
    async def pirate_profile(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        who = member or interaction.user
        embed = await self.pirate_embed(interaction.guild_id, who)
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    async def pirate_embed(self, guild_id: int, who) -> discord.Embed:
        db = self.bot.db
        gamertag, motto = await db.pirate_profile(guild_id, who.id)
        sailed, captained, per_game = await db.crew_history(guild_id, who.id)
        avatar = getattr(getattr(who, "display_avatar", None), "url", None)
        return render_pirate(user_id=who.id, name=who.display_name, avatar=avatar, gamertag=gamertag, motto=motto,
                             sailed=sailed, captained=captained, per_game=per_game,
                             ships=await db.ships(guild_id, who.id),
                             totals=await db.ledger_totals(guild_id, user_id=who.id),
                             recent=await db.recent_logs(guild_id, user_id=who.id, limit=3))

    @pirate.command(name="set", description="Your gamertag and motto for your pirate profile")
    @app_commands.describe(gamertag="Your in-game name, so crewmates can find you (a single dash clears it)",
                           motto="A line for your profile (a single dash clears it)")
    async def pirate_set(self, interaction: discord.Interaction,
                         gamertag: app_commands.Range[str, 1, 40] | None = None,
                         motto: app_commands.Range[str, 1, 150] | None = None) -> None:
        old_tag, old_motto = await self.bot.db.pirate_profile(interaction.guild_id, interaction.user.id)

        def pick(new, old, limit):
            if new is None:
                return old
            return None if new.strip() == "-" else _clean(new, limit)

        await self.bot.db.set_pirate_profile(interaction.guild_id, interaction.user.id,
                                             pick(gamertag, old_tag, 40), pick(motto, old_motto, 150))
        await interaction.response.send_message(voice.say("pirate_saved"), ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(ShipLedger(bot))
