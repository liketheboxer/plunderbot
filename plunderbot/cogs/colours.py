"""Colours: role menus members pick from themselves (regions, platforms, games...).

Each menu's card has one button. Pressing it opens a private dropdown already ticked with the
roles the member wears; saving sets exactly those. Menus marked for onboarding are also offered
to newcomers the moment a Harbormaster lets them aboard. Picking a region role that spans several
time zones (Asia, South America) asks which zone is closest.
"""
from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from .. import voice
from ..db import RoleMenu
from ..discord_util import fetch_linked, self_serve_problem
from ..menu_logic import MAX_OPTIONS, parse_import, partial_emoji, plan, render_menu, slug
from ..region_logic import broad_zones_for

log = logging.getLogger("plunderbot.colours")


class MenuButton(discord.ui.DynamicItem[discord.ui.Button], template=r"colours:open:(?P<id>\d+)"):
    """The button on a menu's card (and on the welcome-aboard message). Survives restarts."""

    def __init__(self, menu_id: int, label: str = "Choose roles", emoji: str | None = None):
        super().__init__(discord.ui.Button(label=label[:80], style=discord.ButtonStyle.primary,
                                           custom_id=f"colours:open:{menu_id}", emoji=partial_emoji(emoji)))
        self.menu_id = menu_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str]):
        return cls(int(match["id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        cog = interaction.client.get_cog("Colours")
        if cog is None:
            await interaction.response.send_message(voice.say("error"), ephemeral=True)
            return
        await cog.open_picker(interaction, self.menu_id)


def menu_view(menu: RoleMenu) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(MenuButton(menu.id, f"Choose {menu.title}" if len(menu.title) < 60 else "Choose roles"))
    return view


class Picker(discord.ui.View):
    """The private dropdown a member sees after pressing a menu's button."""

    def __init__(self, cog: "Colours", menu: RoleMenu, options: list[discord.SelectOption]):
        super().__init__(timeout=600)
        self.cog, self.menu = cog, menu
        select = discord.ui.Select(placeholder=f"Choose {menu.title}"[:150], options=options, min_values=0,
                                   max_values=1 if menu.mode == "single" else len(options))
        select.callback = self.chosen
        self.select = select
        self.add_item(select)

    async def chosen(self, interaction: discord.Interaction) -> None:
        await self.cog.apply(interaction, self.menu.id, [int(v) for v in self.select.values])


class ZonePicker(discord.ui.View):
    """Which zone is closest, for a region that spans several."""

    def __init__(self, cog: "Colours", zones: list[tuple[str, str]]):
        super().__init__(timeout=600)
        self.cog = cog
        select = discord.ui.Select(placeholder="Which time zone is closest?",
                                   options=[discord.SelectOption(label=label[:100], value=zone, description=zone)
                                            for label, zone in zones[:25]])
        select.callback = self.chosen
        self.select = select
        self.add_item(select)

    async def chosen(self, interaction: discord.Interaction) -> None:
        await self.cog.save_zone(interaction, self.select.values[0])


async def _menu_ac(interaction: discord.Interaction, current: str):
    menus = await interaction.client.db.menus(interaction.guild_id)
    needle = current.lower()
    return [app_commands.Choice(name=f"{m.title} ({m.key})"[:100], value=m.key) for m in menus
            if needle in m.key or needle in m.title.lower()][:25]


@app_commands.guild_only()
@app_commands.default_permissions(manage_roles=True)
class Colours(commands.GroupCog, group_name="colours", group_description="Role menus members pick from (Quartermasters)"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(MenuButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(MenuButton)

    # ------------------------------------------------------------ members: picking roles
    async def open_picker(self, interaction: discord.Interaction, menu_id: int) -> None:
        menu = await self.bot.db.get_menu(menu_id)
        if menu is None or menu.guild_id != interaction.guild_id:
            await interaction.response.send_message(voice.say("colours_gone"), ephemeral=True)
            return
        options = self.select_options(interaction.guild, menu, interaction.user)
        if not options:
            await interaction.response.send_message(voice.say("colours_gone"), ephemeral=True)
            return
        await interaction.response.send_message(voice.say("colours_prompt", title=menu.title),
                                                view=Picker(self, menu, options), ephemeral=True)

    @staticmethod
    def select_options(guild: discord.Guild, menu: RoleMenu, member) -> list[discord.SelectOption]:
        wearing = {r.id for r in getattr(member, "roles", [])}
        out = []
        for o in menu.options[:MAX_OPTIONS]:
            role = guild.get_role(o.role_id)
            if role is None:
                continue
            out.append(discord.SelectOption(label=(o.label or role.name)[:100], value=str(role.id),
                                            description=(o.description or None) and o.description[:100],
                                            emoji=partial_emoji(o.emoji), default=role.id in wearing))
        return out

    async def apply(self, interaction: discord.Interaction, menu_id: int, chosen: list[int]) -> None:
        guild, member = interaction.guild, interaction.user
        menu = await self.bot.db.get_menu(menu_id)
        if menu is None:
            await interaction.response.edit_message(content=voice.say("colours_gone"), view=None)
            return
        live = [o.role_id for o in menu.options if guild.get_role(o.role_id) is not None]
        add, remove = plan({r.id for r in member.roles}, live, chosen, menu.mode)
        if not add and not remove:
            await interaction.response.edit_message(content=voice.say("colours_same"), view=None)
            return
        add_roles = [guild.get_role(r) for r in add]
        remove_roles = [guild.get_role(r) for r in remove]
        me = guild.me
        if any(self_serve_problem(r, me) for r in add_roles + remove_roles):
            await interaction.response.edit_message(content=voice.say("colours_cant"), view=None)
            return
        try:
            if remove_roles:
                await member.remove_roles(*remove_roles, reason=f"Colours: {menu.title}")
            if add_roles:
                await member.add_roles(*add_roles, reason=f"Colours: {menu.title}")
        except discord.HTTPException as e:
            log.warning("Couldn't change %s's roles from menu %s: %s", member.id, menu.id, e)
            await interaction.response.edit_message(content=voice.say("colours_cant"), view=None)
            return
        parts = []
        if add_roles:
            parts.append("Now wearing " + voice.join_names([r.mention for r in add_roles]) + ".")
        if remove_roles:
            parts.append("Took off " + voice.join_names([r.mention for r in remove_roles]) + ".")
        text = voice.say("colours_done", changes=" ".join(parts))
        zones = await self.broad_zones(guild, member, add_roles)
        if zones:
            await interaction.response.edit_message(content=text + "\n\n" + voice.say("colours_zone_prompt"),
                                                    view=ZonePicker(self, zones))
        else:
            await interaction.response.edit_message(content=text, view=None)

    async def broad_zones(self, guild: discord.Guild, member, added: list[discord.Role]) -> list[tuple[str, str]]:
        """If they just picked a region too broad for one zone (and haven't chosen a zone themselves),
        the zones to offer them."""
        mapping = await self.bot.db.region_zones(guild.id)
        for role in added:
            if role.id in mapping:
                continue
            zones = broad_zones_for(role.name)
            if zones:
                saved = await self.bot.db.member_timezone_source(member.id)
                if saved is None or saved[1] != "manual":
                    return zones
        return []

    async def save_zone(self, interaction: discord.Interaction, zone: str) -> None:
        from datetime import datetime, timezone
        from ..voyage_logic import zone_from_name, zone_label
        tz = zone_from_name(zone)
        if tz is None:
            await interaction.response.edit_message(content=voice.say("tz_unknown", zone=zone), view=None)
            return
        await self.bot.db.set_member_timezone(interaction.user.id, tz.key, "manual")
        now = datetime.now(timezone.utc)
        await interaction.response.edit_message(content=voice.say(
            "tz_saved", zone=zone_label(tz, now), local=now.astimezone(tz).strftime("%-I:%M %p")), view=None)

    async def onboarding_items(self, guild: discord.Guild) -> list[discord.ui.Item]:
        """Buttons for the menus newcomers are offered when they're let aboard."""
        return [MenuButton(m.id, f"Choose {m.title}" if len(m.title) < 60 else m.title[:80])
                for m in await self.bot.db.menus(guild.id) if m.onboarding and m.options][:10]

    # ------------------------------------------------------------ Quartermasters: building menus
    async def _get(self, interaction: discord.Interaction, key: str) -> RoleMenu | None:
        menu = await self.bot.db.menu_by_key(interaction.guild_id, key)
        if menu is None:
            await interaction.response.send_message(f"There's no menu called \"{key}\". See /colours list.",
                                                    ephemeral=True)
        return menu

    async def refresh(self, guild: discord.Guild, menu: RoleMenu) -> str:
        """Update a posted menu's card. Returns a note for the reply."""
        if not (menu.channel_id and menu.message_id):
            return "It isn't posted yet; use /colours post."
        channel = guild.get_channel(menu.channel_id)
        if channel is None:
            return "Its channel is gone; post it again with /colours post."
        try:
            await channel.get_partial_message(menu.message_id).edit(embed=render_menu(menu), view=menu_view(menu))
            return "The posted card is updated."
        except discord.NotFound:
            return "Its card was deleted; post it again with /colours post."
        except discord.HTTPException as e:
            return f"I couldn't update the posted card ({e.status})."

    @app_commands.command(name="create", description="Make a new role menu")
    @app_commands.describe(title="Shown on the card, e.g. Region Roles", mode="Pick one, or as many as they like",
                           description="Text above the list of roles")
    @app_commands.choices(mode=[app_commands.Choice(name="Pick as many as they like", value="multi"),
                                app_commands.Choice(name="Pick one", value="single")])
    async def create(self, interaction: discord.Interaction, title: app_commands.Range[str, 1, 100],
                     mode: app_commands.Choice[str], description: app_commands.Range[str, 1, 2000] | None = None) -> None:
        key = slug(title)
        if await self.bot.db.menu_by_key(interaction.guild_id, key):
            await interaction.response.send_message(f"There's already a menu called \"{key}\".", ephemeral=True)
            return
        await self.bot.db.create_menu(interaction.guild_id, key, title, description, mode.value)
        await interaction.response.send_message(
            f"Made the **{title}** menu (key `{key}`). Add roles with /colours add, then /colours post.",
            ephemeral=True)

    @app_commands.command(name="add", description="Add a role to a menu (or change its emoji and text)")
    @app_commands.describe(menu="Which menu", role="The role", emoji="Paste an emoji (optional)",
                           label="Name in the dropdown (default: the role's name)",
                           description="A short line under it (optional)")
    @app_commands.autocomplete(menu=_menu_ac)
    async def add(self, interaction: discord.Interaction, menu: str, role: discord.Role, emoji: str | None = None,
                  label: app_commands.Range[str, 1, 100] | None = None,
                  description: app_commands.Range[str, 1, 100] | None = None) -> None:
        m = await self._get(interaction, menu)
        if m is None:
            return
        problem = self_serve_problem(role, interaction.guild.me)
        if problem:
            await interaction.response.send_message(problem, ephemeral=True)
            return
        if emoji and partial_emoji(emoji.strip()) is None:
            await interaction.response.send_message(f"I can't use \"{emoji}\" as an emoji.", ephemeral=True)
            return
        if len(m.options) >= MAX_OPTIONS and all(o.role_id != role.id for o in m.options):
            await interaction.response.send_message(f"A menu can hold {MAX_OPTIONS} roles at most.", ephemeral=True)
            return
        await self.bot.db.set_menu_option(m.id, role.id, emoji.strip() if emoji else None, label, description)
        m = await self.bot.db.get_menu(m.id)
        note = await self.refresh(interaction.guild, m)
        await interaction.response.send_message(f"{role.mention} is on **{m.title}**. {note}", ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="remove", description="Take a role off a menu")
    @app_commands.autocomplete(menu=_menu_ac)
    async def remove(self, interaction: discord.Interaction, menu: str, role: discord.Role) -> None:
        m = await self._get(interaction, menu)
        if m is None:
            return
        gone = await self.bot.db.remove_menu_option(m.id, role.id)
        m = await self.bot.db.get_menu(m.id)
        note = await self.refresh(interaction.guild, m)
        text = f"Took {role.mention} off **{m.title}**." if gone else f"{role.mention} wasn't on **{m.title}**."
        await interaction.response.send_message(f"{text} {note}", ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="move", description="Move a role up or down a menu")
    @app_commands.describe(position="1 is the top")
    @app_commands.autocomplete(menu=_menu_ac)
    async def move(self, interaction: discord.Interaction, menu: str, role: discord.Role,
                   position: app_commands.Range[int, 1, 25]) -> None:
        m = await self._get(interaction, menu)
        if m is None:
            return
        if all(o.role_id != role.id for o in m.options):
            await interaction.response.send_message(f"{role.mention} isn't on **{m.title}**.", ephemeral=True,
                                                    allowed_mentions=discord.AllowedMentions.none())
            return
        await self.bot.db.move_menu_option(m.id, role.id, position)
        m = await self.bot.db.get_menu(m.id)
        note = await self.refresh(interaction.guild, m)
        await interaction.response.send_message(f"Moved. {note}", ephemeral=True)

    @app_commands.command(name="edit", description="Change a menu's title, text or mode")
    @app_commands.choices(mode=[app_commands.Choice(name="Pick as many as they like", value="multi"),
                                app_commands.Choice(name="Pick one", value="single")])
    @app_commands.autocomplete(menu=_menu_ac)
    async def edit(self, interaction: discord.Interaction, menu: str,
                   title: app_commands.Range[str, 1, 100] | None = None,
                   description: app_commands.Range[str, 1, 2000] | None = None,
                   mode: app_commands.Choice[str] | None = None) -> None:
        m = await self._get(interaction, menu)
        if m is None:
            return
        changes = {k: v for k, v in (("title", title), ("description", description),
                                     ("mode", mode.value if mode else None)) if v is not None}
        if not changes:
            await interaction.response.send_message("Nothing to change.", ephemeral=True)
            return
        m = await self.bot.db.update_menu(m.id, **changes)
        note = await self.refresh(interaction.guild, m)
        await interaction.response.send_message(f"Updated **{m.title}**. {note}", ephemeral=True)

    @app_commands.command(name="onboarding", description="Offer a menu to newcomers when they're let aboard")
    @app_commands.autocomplete(menu=_menu_ac)
    async def onboarding(self, interaction: discord.Interaction, menu: str, offer: bool) -> None:
        m = await self._get(interaction, menu)
        if m is None:
            return
        await self.bot.db.update_menu(m.id, onboarding=int(offer))
        text = (f"Newcomers will get a **{m.title}** button when they're let aboard." if offer
                else f"**{m.title}** is no longer offered to newcomers.")
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="post", description="Post a menu's card (or move it to another channel)")
    @app_commands.describe(channel="Where to post it (default: here)")
    @app_commands.autocomplete(menu=_menu_ac)
    async def post(self, interaction: discord.Interaction, menu: str,
                   channel: discord.TextChannel | None = None) -> None:
        m = await self._get(interaction, menu)
        if m is None:
            return
        channel = channel or interaction.channel
        perms = channel.permissions_for(interaction.guild.me)
        if not (perms.view_channel and perms.send_messages and perms.embed_links):
            await interaction.response.send_message(f"I can't post in {channel.mention}.", ephemeral=True)
            return
        if m.channel_id == channel.id and m.message_id:
            note = await self.refresh(interaction.guild, m)
            if note.startswith("The posted card"):
                await interaction.response.send_message(f"Already posted there. {note}", ephemeral=True)
                return
        old = (m.channel_id, m.message_id)
        message = await channel.send(embed=render_menu(m), view=menu_view(m))
        await self.bot.db.update_menu(m.id, channel_id=channel.id, message_id=message.id)
        if old[1] and old != (channel.id, message.id):
            old_channel = interaction.guild.get_channel(old[0])
            if old_channel is not None:
                try:
                    await old_channel.get_partial_message(old[1]).delete()
                except discord.HTTPException:
                    pass
        await interaction.response.send_message(f"Posted **{m.title}**: {message.jump_url}", ephemeral=True)

    @app_commands.command(name="import", description="Copy a reaction-role message (e.g. MEE6's) into a new menu")
    @app_commands.describe(message="Link to the message (right-click it › Copy Message Link)",
                           title="Menu title (default: the message's title)",
                           mode="Pick one, or as many as they like")
    @app_commands.choices(mode=[app_commands.Choice(name="Pick as many as they like", value="multi"),
                                app_commands.Choice(name="Pick one", value="single")])
    async def import_(self, interaction: discord.Interaction, message: str, mode: app_commands.Choice[str],
                      title: app_commands.Range[str, 1, 100] | None = None) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        msg = await fetch_linked(guild, message)
        if msg is None:
            await interaction.followup.send("I couldn't open that message. Check the link and that I can read "
                                            "that channel.", ephemeral=True)
            return
        text = "\n".join([msg.content or ""] + [e.description or "" for e in msg.embeds]
                         + [f.value for e in msg.embeds for f in e.fields])
        pairs = parse_import(text)
        if not pairs:
            hidden = "" if msg.author.id == guild.me.id else (
                " If another bot posted it, Discord may be hiding its text from me.")
            await interaction.followup.send(
                "I didn't find any role mentions in that message, so there's nothing to copy." + hidden +
                " Build it with /colours create and /colours add instead.", ephemeral=True)
            return
        title = title or next((e.title for e in msg.embeds if e.title), None) or "Roles"
        key, n = slug(title), 2
        while await self.bot.db.menu_by_key(guild.id, key):
            key, n = f"{slug(title)}-{n}", n + 1
        intro = next((e.description for e in msg.embeds if e.description), msg.content or "")
        intro = "\n".join(line for line in intro.splitlines() if "<@&" not in line).strip() or None
        m = await self.bot.db.create_menu(guild.id, key, title, intro[:2000] if intro else None, mode.value)
        added, skipped = [], []
        for emoji, role_id in pairs[:MAX_OPTIONS]:
            role = guild.get_role(role_id)
            problem = "it no longer exists" if role is None else self_serve_problem(role, guild.me)
            if problem:
                skipped.append(f"<@&{role_id}> ({problem})")
                continue
            await self.bot.db.set_menu_option(m.id, role_id, emoji, None, None)
            added.append(f"{emoji or ''} {role.mention}".strip())
        lines = [f"Made **{title}** (key `{key}`) with {len(added)} role(s): " + ", ".join(added)]
        if skipped:
            lines.append("Skipped: " + ", ".join(skipped))
        lines.append("Check it with /colours preview, then /colours post. The old message is untouched.")
        await interaction.followup.send("\n".join(lines)[:1990], ephemeral=True,
                                        allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="preview", description="See a menu's card privately")
    @app_commands.autocomplete(menu=_menu_ac)
    async def preview(self, interaction: discord.Interaction, menu: str) -> None:
        m = await self._get(interaction, menu)
        if m is None:
            return
        await interaction.response.send_message(embed=render_menu(m), ephemeral=True)

    @app_commands.command(name="list", description="All role menus")
    async def list_(self, interaction: discord.Interaction) -> None:
        menus = await self.bot.db.menus(interaction.guild_id)
        if not menus:
            await interaction.response.send_message("No menus yet. Start with /colours create or /colours import.",
                                                    ephemeral=True)
            return
        lines = []
        for m in menus:
            where = f"<#{m.channel_id}>" if m.message_id else "not posted"
            flags = " · offered at onboarding" if m.onboarding else ""
            lines.append(f"`{m.key}` **{m.title}**: {len(m.options)} role(s), "
                         f"{'pick one' if m.mode == 'single' else 'pick any'}, {where}{flags}")
        await interaction.response.send_message("\n".join(lines)[:1990], ephemeral=True)

    @app_commands.command(name="delete", description="Delete a menu (and its posted card)")
    @app_commands.autocomplete(menu=_menu_ac)
    async def delete(self, interaction: discord.Interaction, menu: str) -> None:
        m = await self._get(interaction, menu)
        if m is None:
            return
        if m.channel_id and m.message_id:
            channel = interaction.guild.get_channel(m.channel_id)
            if channel is not None:
                try:
                    await channel.get_partial_message(m.message_id).delete()
                except discord.HTTPException:
                    pass
        await self.bot.db.delete_menu(m.id)
        await interaction.response.send_message(f"Deleted **{m.title}**. Nobody's roles were changed.",
                                                ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(Colours(bot))
