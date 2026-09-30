"""Notice Board: polished pages (rules, the Pirate's Guide), the Game Index, and following games.

A page is a list of sections; each section is one embed with a heading, body, colour and optional
picture. Quartermasters write sections in a pop-up form (or import them from an existing message,
such as MEE6's rules post), then post the page. Posting again edits the same messages in place.

The Game Index is a page PlunderBot writes itself: every game with its forum thread and ping role,
and a Follow button. Following a game gives its ping role and adds you to its forum thread.
"""
from __future__ import annotations

import asyncio
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from .. import crew_emoji, games, images, voice
from ..db import Page, PageSection
from ..discord_util import fetch_linked, finish, self_serve_problem
from ..menu_logic import partial_emoji, plan, slug
from ..page_logic import (BODY_MAX, HEADING_MAX, chunk_lines, colour_text, game_index_lines, image_filename,
                          layout, parse_colour, plan_sections, render_section, split_parts)

log = logging.getLogger("plunderbot.noticeboard")

GUIDE_KEY = "pirates-guide"
STARTER_GUIDE = [
    ("Welcome aboard, pirate!",
     "Brimstone Hill Fortress is a crew of friendly pirates who sail the Sea of Thieves together, and plenty "
     "of other games besides. I'm PlunderBot, the Fortress's robot butler. I keep the calendar, muster crews and "
     "remember everyone's birthday. Here's how to find your way around."),
    ("Find a crew right now",
     "Type `/crew start`, pick the game and crew size, and I'll post a crew card in #looking-for-group and ping "
     "whoever follows that game. Press **Join** on someone else's card to hop aboard. When the crew fills (or the "
     "captain presses **Set Sail**) I open a voice channel for you, and tidy it away when everyone's gone.\n\n"
     "Just want company? Start a **1 Player Hangout** and play your own games together."),
    ("Plan a voyage",
     "`/voyage create` puts a voyage on the charts in #brimstone-events with **Aboard**, **Maybe** and "
     "**Can't make it** buttons, reminders before it starts, and a Discord Event. When it's time, it turns into "
     "a crew with its own voice channel. Anyone can plan one!"),
    ("Times in your own time zone",
     "Every time I show is in your own local time. When you type a time, I read it in your time zone: pick a "
     "region role in #new-pirate-orientation, or set it exactly with `/timezone set`."),
    ("Pick your roles",
     "The role menus in #new-pirate-orientation each have one button: press it, tick the roles you want and "
     "save. Follow the games you play with `/follow` so you hear when a crew is forming. You can change them "
     "whenever you like."),
    ("Your ship and the Ship's Ledger",
     "Sail Sea of Thieves? `/ship register` your ship, and after a session log the haul with `/ship log` and a "
     "screenshot of the Captain's Log. `/ship fleet` shows the richest ships and pirates."),
    ("Birthdays",
     "Tell me yours with `/birthday set` and the whole Fortress will raise a mug on the day."),
    ("Music",
     "Hop in a voice channel and `/play` a song name or a link, and I'll bring the band. The Now Playing card has "
     "buttons to pause, skip, stop, shuffle and repeat, and `/music queue` shows what's next. Or just @mention me "
     "and ask for something to play."),
    ("Need a hand?",
     "Ask a Harbormaster, or @mention me and ask. Fair winds!"),
]


class SectionModal(discord.ui.Modal):
    """The pop-up form for writing or editing a section."""

    def __init__(self, cog: "Noticeboard", page: Page, section: PageSection | None = None,
                 position: int | None = None):
        super().__init__(title=("Edit section" if section else "New section")[:45], timeout=900)
        self.cog, self.page, self.section, self.position = cog, page, section, position
        self.heading = discord.ui.TextInput(label="Heading", required=False, max_length=HEADING_MAX,
                                            default=section.heading if section else None)
        self.body = discord.ui.TextInput(label="Text (Markdown works)", style=discord.TextStyle.paragraph,
                                         required=False, max_length=4000, default=section.body if section else None)
        self.colour = discord.ui.TextInput(label="Colour (optional, e.g. #1f8b8b)", required=False, max_length=9,
                                           default=colour_text(section.colour) if section else None)
        for item in (self.heading, self.body, self.colour):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.save_section(interaction, self.page, self.section, self.position, self.heading.value,
                                    self.body.value, self.colour.value)


class FollowButton(discord.ui.DynamicItem[discord.ui.Button], template=r"noticeboard:follow"):
    def __init__(self):
        super().__init__(discord.ui.Button(label="Follow games", emoji="🔭", style=discord.ButtonStyle.primary,
                                           custom_id="noticeboard:follow"))

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str]):
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        cog = interaction.client.get_cog("Noticeboard")
        if cog is None:
            await interaction.response.send_message(voice.say("error"), ephemeral=True)
            return
        await cog.open_follow(interaction)


class FollowPicker(discord.ui.View):
    def __init__(self, cog: "Noticeboard", options: list[discord.SelectOption]):
        super().__init__(timeout=600)
        self.cog = cog
        select = discord.ui.Select(placeholder="Games to follow", options=options, min_values=0,
                                   max_values=len(options))
        select.callback = self.chosen
        self.select = select
        self.add_item(select)

    async def chosen(self, interaction: discord.Interaction) -> None:
        await self.cog.apply_follow(interaction, list(self.select.values))


def follow_view() -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(FollowButton())
    return view


async def _page_ac(interaction: discord.Interaction, current: str):
    pages = await interaction.client.db.pages(interaction.guild_id)
    needle = current.lower()
    return [app_commands.Choice(name=f"{p.title} ({p.key})"[:100], value=p.key) for p in pages
            if needle in p.key or needle in p.title.lower()][:25]


def thread_matches(game, thread_name: str) -> bool:
    """Is this forum thread about this game? Matches the name, short name or key, ignoring case and
    punctuation, or a thread name that starts with the game's name ("Sea of Thieves - LFG")."""
    name = games.normalise(thread_name)
    wanted = {games.normalise(game.name), games.normalise(game.short), game.key}
    return name in wanted or any(w and name.startswith(w) for w in wanted if len(w) >= 4)


@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
class Noticeboard(commands.GroupCog, group_name="noticeboard",
                  group_description="Pages like the rules and the Pirate's Guide (Quartermasters)"):
    section = app_commands.Group(name="section", description="Write a page's sections")

    def __init__(self, bot):
        self.bot = bot
        self._background: set = set()
        super().__init__()

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(FollowButton)
        self.bot.tree.add_command(follow_command, override=True)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(FollowButton)
        self.bot.tree.remove_command(follow_command.name)

    # ------------------------------------------------------------ helpers
    @property
    def data_dir(self):
        return self.bot.config.data_dir

    async def _get(self, interaction: discord.Interaction, key: str) -> Page | None:
        page = await self.bot.db.page_by_key(interaction.guild_id, key)
        if page is None:
            await interaction.response.send_message(f"There's no page called \"{key}\". See /noticeboard list.",
                                                    ephemeral=True)
        return page

    async def _section(self, interaction: discord.Interaction, page: Page, number: int) -> PageSection | None:
        if not 1 <= number <= len(page.sections):
            await interaction.response.send_message(
                f"**{page.title}** has {len(page.sections)} section(s); pick 1 to {len(page.sections)}.",
                ephemeral=True)
            return None
        return page.sections[number - 1]

    def render_group(self, sections: list[PageSection]) -> tuple[list[discord.Embed], list[discord.File]]:
        embeds, files = [], []
        for s in sections:
            path = images.path_of(s.image, self.data_dir)
            inside = path is not None and s.image_style != "banner"
            embeds.append(render_section(s, has_image=inside))
            if inside:
                files.append(discord.File(path, filename=image_filename(s.id, s.image)))
        return embeds, files

    # ------------------------------------------------------------ writing sections
    async def save_section(self, interaction: discord.Interaction, page: Page, section: PageSection | None,
                           position: int | None, heading: str, body: str, colour: str) -> None:
        try:
            colour_value = parse_colour(colour)
        except ValueError:
            await interaction.response.send_message(f"\"{colour}\" isn't a colour; use a hex code like #1f8b8b.",
                                                    ephemeral=True)
            return
        heading, body = heading.strip() or None, body.strip() or None
        if not heading and not body:
            await interaction.response.send_message("A section needs a heading or some text.", ephemeral=True)
            return
        if section is None:
            await self.bot.db.add_section(page.id, heading, body, colour_value, position=position)
            verb = "Added a section to"
        else:
            await self.bot.db.update_section(section.id, heading=heading, body=body, colour=colour_value)
            verb = "Updated a section on"
        await interaction.response.send_message(f"{verb} **{page.title}**. {self.post_hint(page)}", ephemeral=True)

    @staticmethod
    def post_hint(page: Page) -> str:
        return ("Run /noticeboard post to update the posted page." if page.message_ids
                else "Check it with /noticeboard preview, then /noticeboard post.")

    @app_commands.command(name="create", description="Start a new page")
    @app_commands.describe(title="e.g. Rules, Pirate's Guide")
    async def create(self, interaction: discord.Interaction, title: app_commands.Range[str, 1, 100]) -> None:
        key = slug(title)
        if await self.bot.db.page_by_key(interaction.guild_id, key):
            await interaction.response.send_message(f"There's already a page called \"{key}\".", ephemeral=True)
            return
        await self.bot.db.create_page(interaction.guild_id, key, title)
        await interaction.response.send_message(
            f"Made **{title}** (key `{key}`). Add sections with /noticeboard section add, or copy an existing "
            "message with /noticeboard import.", ephemeral=True)

    @section.command(name="add", description="Write a new section (opens a form)")
    @app_commands.describe(position="Where it goes: 1 is the top (default: the end)")
    @app_commands.autocomplete(page=_page_ac)
    async def section_add(self, interaction: discord.Interaction, page: str,
                          position: app_commands.Range[int, 1, 50] | None = None) -> None:
        p = await self._get(interaction, page)
        if p is None:
            return
        if p.kind != "custom":
            await interaction.response.send_message("The Game Index writes itself; no sections to add.",
                                                    ephemeral=True)
            return
        await interaction.response.send_modal(SectionModal(self, p, position=position))

    @section.command(name="edit", description="Edit a section (opens a form)")
    @app_commands.describe(number="Which section: 1 is the top")
    @app_commands.autocomplete(page=_page_ac)
    async def section_edit(self, interaction: discord.Interaction, page: str,
                           number: app_commands.Range[int, 1, 50]) -> None:
        p = await self._get(interaction, page)
        if p is None:
            return
        s = await self._section(interaction, p, number)
        if s is None:
            return
        if len(s.body or "") > 4000:
            await interaction.response.send_message(
                "That section is longer than Discord's form allows (4,000 characters), so editing it here would "
                "cut it short. Split it with /noticeboard section add first.", ephemeral=True)
            return
        await interaction.response.send_modal(SectionModal(self, p, section=s))

    @section.command(name="image", description="Put a picture on a section, or take it off")
    @app_commands.describe(number="Which section: 1 is the top", image="The picture (leave empty to remove it)",
                           style="Banner: on its own above the section. Inside: at the bottom of the section's box")
    @app_commands.choices(style=[app_commands.Choice(name="Banner above the section", value="banner"),
                                 app_commands.Choice(name="Inside the section", value="inside")])
    @app_commands.autocomplete(page=_page_ac)
    async def section_image(self, interaction: discord.Interaction, page: str,
                            number: app_commands.Range[int, 1, 50], image: discord.Attachment | None = None,
                            style: app_commands.Choice[str] | None = None) -> None:
        p = await self._get(interaction, page)
        if p is None:
            return
        s = await self._section(interaction, p, number)
        if s is None:
            return
        await interaction.response.defer(ephemeral=True)
        name = None
        if image is not None:
            try:
                name = await images.save(image, self.data_dir)
            except (images.ImageError, discord.HTTPException, OSError) as e:
                log.warning("Section picture refused (%s, %s, %s bytes): %r", image.filename, image.content_type,
                            image.size, e)
                await interaction.followup.send(f"I couldn't use that picture: {images.reason(e)}", ephemeral=True)
                return
        changes = {"image": name} if (image is not None or style is None) else {}
        if style is not None:
            changes["image_style"] = style.value
        await self.bot.db.update_section(s.id, **changes)
        if image is None and style is not None:
            await interaction.followup.send(f"Section {number}'s picture is now {style.name.lower()}. "
                                            f"{self.post_hint(p)}", ephemeral=True)
            return
        what = "Picture added to" if name else "Picture removed from"
        await interaction.followup.send(f"{what} section {number}. {self.post_hint(p)}", ephemeral=True)

    @section.command(name="remove", description="Delete a section")
    @app_commands.autocomplete(page=_page_ac)
    async def section_remove(self, interaction: discord.Interaction, page: str,
                             number: app_commands.Range[int, 1, 50]) -> None:
        p = await self._get(interaction, page)
        if p is None:
            return
        s = await self._section(interaction, p, number)
        if s is None:
            return
        await self.bot.db.remove_section(p.id, s.id)
        await interaction.response.send_message(
            f"Removed section {number} ({s.heading or 'untitled'}). {self.post_hint(p)}", ephemeral=True)

    @section.command(name="move", description="Move a section up or down")
    @app_commands.describe(number="Which section", position="Where it goes: 1 is the top")
    @app_commands.autocomplete(page=_page_ac)
    async def section_move(self, interaction: discord.Interaction, page: str,
                           number: app_commands.Range[int, 1, 50], position: app_commands.Range[int, 1, 50]) -> None:
        p = await self._get(interaction, page)
        if p is None:
            return
        s = await self._section(interaction, p, number)
        if s is None:
            return
        await self.bot.db.move_section(p.id, s.id, position)
        await interaction.response.send_message(f"Moved. {self.post_hint(p)}", ephemeral=True)

    @app_commands.command(name="import", description="Copy existing messages (e.g. MEE6's welcome and rules) into a page")
    @app_commands.describe(message="Link to the first message (hover it › ⋯ › Copy Message Link)",
                           through="Optional: link to the last message, to copy everything from first to last",
                           page="Leave empty to make a new page, or pick a page to add to")
    @app_commands.autocomplete(page=_page_ac)
    async def import_(self, interaction: discord.Interaction, message: str, through: str | None = None,
                      page: str | None = None) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        first = await fetch_linked(guild, message)
        if first is None:
            await interaction.followup.send("I couldn't open that message. Check the link and that I can read "
                                            "that channel.", ephemeral=True)
            return
        messages = [first]
        if through:
            last = await fetch_linked(guild, through)
            if last is None or last.channel.id != first.channel.id or last.id < first.id:
                await interaction.followup.send("The `through` link has to be a later message in the same channel.",
                                                ephemeral=True)
                return
            if last.id != first.id:
                between = [m async for m in first.channel.history(after=first, before=last, limit=48,
                                                                   oldest_first=True)]
                messages += between + [last]
        if page:
            p = await self.bot.db.page_by_key(guild.id, page)
            if p is None or p.kind != "custom":
                await interaction.followup.send(
                    f"There's no page called \"{page}\" to add to. Leave `page` empty to make a new one.",
                    ephemeral=True)
                return
        else:
            p = None
        blank = [m for m in messages if not (m.content or m.embeds or m.attachments)]
        if blank and not getattr(self.bot, "can_read_messages", True):
            await interaction.followup.send(
                f"{len(blank)} of those {len(messages)} message(s) look empty to me, because Discord hides other "
                "apps' messages unless **Message Content Intent** is on. Turn it on in the Discord Developer "
                "Portal (PlunderBot › Bot › Privileged Gateway Intents), refit PlunderBot, and import again.",
                ephemeral=True)
            return
        parts = split_parts(messages)
        plans = plan_sections(parts)
        if not plans:
            await interaction.followup.send("There was nothing I could copy there.", ephemeral=True)
            return
        if p is None:
            title = next((t["text"]["heading"] for t in plans if t["text"] and t["text"]["heading"]), None) \
                or "Imported page"
            key, n = slug(title), 2
            while await self.bot.db.page_by_key(guild.id, key):
                key, n = f"{slug(title)}-{n}", n + 1
            p = await self.bot.db.create_page(guild.id, key, title)
        added, missed = 0, []
        for plan in plans:
            banner, text = plan["banner"], plan["text"]
            picture, style = None, "inside"
            if banner is not None:
                picture = await self.copy_picture(banner)
                style = "banner"
                if picture is None:
                    missed.append(f"the picture above section {added + 1}")
            if text is not None and picture is None and text["urls"]:
                picture = await self.copy_picture(text)
                style = "inside"
                if picture is None:
                    missed.append(f"the picture in section {added + 1}")
            if text is None and picture is None:
                continue
            await self.bot.db.add_section(
                p.id, (text["heading"] or None) and text["heading"][:HEADING_MAX] if text else None,
                (text["body"] or None) and text["body"][:BODY_MAX] if text else None,
                text["colour"] if text else None, picture, image_style=style)
            added += 1
        lines = [f"Copied {len(messages)} message(s) into {added} section(s) on **{p.title}** (key `{p.key}`). "
                 "The old messages are untouched."]
        if blank:
            lines.append(f"{len(blank)} message(s) had nothing I could read.")
        if missed:
            lines.append("I couldn't copy " + ", ".join(missed) + ". Save the picture and add it with "
                         "/noticeboard section image.")
        lines.append("Check it with /noticeboard preview.")
        await interaction.followup.send(" ".join(lines)[:1990], ephemeral=True)

    async def copy_picture(self, part: dict) -> str | None:
        """Keep our own copy of an imported picture. Tries Discord's copy first, then the original link."""
        attachment = part.get("attachment")
        if attachment is not None:
            try:
                return await images.save(attachment, self.data_dir)
            except (images.ImageError, discord.HTTPException, OSError) as e:
                log.warning("Couldn't copy an attached picture: %s", e)
                return None
        for url in part.get("urls", []):
            try:
                data = await self.bot.http.get_from_cdn(url)
                return images.save_bytes(data, None, self.data_dir)
            except Exception as e:
                log.warning("Couldn't fetch a picture through Discord (%s): %s", url.split("?")[0][:120], e)
            try:
                return await images.download(url, self.data_dir)
            except Exception as e:
                log.warning("Couldn't download a picture (%s): %s", url.split("?")[0][:120], e)
        return None

    @app_commands.command(name="starter", description="Make a draft Pirate's Guide to edit")
    async def starter(self, interaction: discord.Interaction) -> None:
        if await self.bot.db.page_by_key(interaction.guild_id, GUIDE_KEY):
            await interaction.response.send_message("There's already a Pirate's Guide page (`pirates-guide`).",
                                                    ephemeral=True)
            return
        p = await self.bot.db.create_page(interaction.guild_id, GUIDE_KEY, "Pirate's Guide")
        for heading, body in STARTER_GUIDE:
            await self.bot.db.add_section(p.id, heading, body)
        await interaction.response.send_message(
            f"Drafted the **Pirate's Guide** with {len(STARTER_GUIDE)} sections (key `{GUIDE_KEY}`). Read it with "
            "/noticeboard preview, change anything with /noticeboard section edit, then post it.", ephemeral=True)

    # ------------------------------------------------------------ posting
    async def page_messages(self, guild: discord.Guild, page: Page) -> list[dict]:
        """What each message of the page should hold: {"embeds", "files", "view"}."""
        if page.kind == "game_index":
            return [await self.game_index_message(guild)]
        out = []
        for kind, chunk in layout(page.sections):
            if kind == "banner":
                s = chunk[0]
                path = images.path_of(s.image, self.data_dir)
                if path is not None:
                    out.append({"embeds": [], "files": [discord.File(path, filename=image_filename(s.id, s.image))],
                                "view": None})
                continue
            embeds, files = self.render_group(chunk)
            out.append({"embeds": embeds, "files": files, "view": None})
        return out

    async def publish(self, guild: discord.Guild, page: Page, channel, repost: bool = False) -> tuple[int, str]:
        """Post or update a page. Edits its messages in place when it can. Returns (message count, note)."""
        wanted = await self.page_messages(guild, page)
        if not wanted:
            return 0, "The page has no sections yet."
        existing = page.messages if (page.channel_id == channel.id and not repost) else []
        stale = [] if existing else list(page.messages)  # moving channel, or a repost
        ids: list[int] = []
        broken = False
        for i, m in enumerate(wanted):
            extra = {"view": m["view"]} if m["view"] is not None else {}
            if i < len(existing) and not broken:
                try:
                    await channel.get_partial_message(existing[i]).edit(
                        content=None, embeds=m["embeds"], attachments=m["files"], **extra)
                    ids.append(existing[i])
                    continue
                except discord.NotFound:
                    broken = True  # post the rest fresh so the page stays in order
                    stale.extend(existing[i + 1:])
            msg = await channel.send(embeds=m["embeds"], files=m["files"], **extra)
            ids.append(msg.id)
        if not broken:
            stale.extend(existing[len(wanted):])
        old_channel = (guild.get_channel(page.channel_id) if page.channel_id else None) or channel
        for mid in stale:
            try:
                await old_channel.get_partial_message(mid).delete()
            except discord.HTTPException:
                pass
        if not existing:
            note = "Posted."
        elif broken:
            note = "Part of it had been deleted, so the rest was posted again."
        elif len(wanted) > len(existing):
            note = ("It grew, so the new part went at the bottom of the channel. "
                    "Use repost:True to keep it together.")
        else:
            note = "Updated in place."
        await self.bot.db.update_page(page.id, channel_id=channel.id, message_ids=",".join(str(i) for i in ids))
        return len(ids), note

    @app_commands.command(name="post", description="Post a page, or update it where it's posted")
    @app_commands.describe(channel="Where (default: where it's posted now, or here)",
                           repost="Delete and post it again, e.g. to move it below something new")
    @app_commands.autocomplete(page=_page_ac)
    async def post(self, interaction: discord.Interaction, page: str, channel: discord.TextChannel | None = None,
                   repost: bool = False) -> None:
        p = await self._get(interaction, page)
        if p is None:
            return
        guild = interaction.guild
        channel = channel or (guild.get_channel(p.channel_id) if p.channel_id else None) or interaction.channel
        perms = channel.permissions_for(guild.me)
        if not (perms.view_channel and perms.send_messages and perms.embed_links and perms.attach_files):
            await interaction.response.send_message(
                f"I need View Channel, Send Messages, Embed Links and Attach Files in {channel.mention}.",
                ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            count, note = await self.publish(guild, p, channel, repost)
        except discord.HTTPException as e:
            await interaction.followup.send(f"Discord refused the page ({e.status}: {e.text or 'no reason'}).",
                                            ephemeral=True)
            return
        await interaction.followup.send(f"**{p.title}** in {channel.mention}: {count} message(s). {note}",
                                        ephemeral=True)

    @app_commands.command(name="preview", description="See a page privately before posting")
    @app_commands.autocomplete(page=_page_ac)
    async def preview(self, interaction: discord.Interaction, page: str) -> None:
        p = await self._get(interaction, page)
        if p is None:
            return
        messages = await self.page_messages(interaction.guild, p)
        if not messages:
            await interaction.response.send_message("The page has no sections yet.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        numbered = 0
        for m in messages:
            for e in m["embeds"]:
                numbered += 1
                if p.kind == "custom":
                    e.set_footer(text=f"Section {numbered}")
            await interaction.followup.send(embeds=m["embeds"], files=m["files"], ephemeral=True)

    @app_commands.command(name="list", description="All pages")
    async def list_(self, interaction: discord.Interaction) -> None:
        pages = await self.bot.db.pages(interaction.guild_id)
        if not pages:
            await interaction.response.send_message(
                "No pages yet. Try /noticeboard starter, /noticeboard import or /noticeboard create.", ephemeral=True)
            return
        lines = []
        for p in pages:
            where = f"<#{p.channel_id}>" if p.message_ids else "not posted"
            what = "Game Index" if p.kind == "game_index" else f"{len(p.sections)} section(s)"
            lines.append(f"`{p.key}` **{p.title}**: {what}, {where}")
        await interaction.response.send_message("\n".join(lines)[:1990], ephemeral=True)

    @app_commands.command(name="delete", description="Delete a page (and its posted messages)")
    @app_commands.autocomplete(page=_page_ac)
    async def delete(self, interaction: discord.Interaction, page: str) -> None:
        p = await self._get(interaction, page)
        if p is None:
            return
        channel = interaction.guild.get_channel(p.channel_id) if p.channel_id else None
        if channel is not None:
            for mid in p.messages:
                try:
                    await channel.get_partial_message(mid).delete()
                except discord.HTTPException:
                    pass
        await self.bot.db.delete_page(p.id)
        await interaction.response.send_message(f"Deleted **{p.title}**.", ephemeral=True)

    # ------------------------------------------------------------ Game Index and following games
    async def forum_threads(self, guild: discord.Guild) -> list:
        s = await self.bot.db.get_settings(guild.id)
        forum = guild.get_channel(s.forum_channel_id) if s.forum_channel_id else None
        if forum is None:
            return []
        threads = list(getattr(forum, "threads", []))
        try:
            async for t in forum.archived_threads(limit=100):
                threads.append(t)
        except (discord.HTTPException, AttributeError):
            pass
        return threads

    async def game_entries(self, guild: discord.Guild, with_threads: bool = True) -> list[dict]:
        threads = await self.forum_threads(guild) if with_threads else []
        roles = await self.bot.db.game_ping_roles(guild.id)
        overrides = await self.bot.db.crew_emoji(guild.id)
        out = []
        for g in games.GAMES:
            if not g.crew_call:
                continue
            thread = next((t for t in threads if thread_matches(g, t.name)), None)
            role_id = roles.get(g.key)
            if role_id and guild.get_role(role_id) is None:
                role_id = None
            _, card = crew_emoji.resolve(g, g.default_size.label, overrides)
            out.append({"key": g.key, "name": g.name, "emoji": card, "thread_id": thread.id if thread else None,
                        "role_id": role_id, "thread": thread})
        return out

    async def game_index_message(self, guild: discord.Guild) -> dict:
        entries = await self.game_entries(guild)
        s = await self.bot.db.get_settings(guild.id)
        intro = "Every game we sail, with its forum thread and the role that gets pinged when a crew forms."
        if s.forum_channel_id:
            intro += f" Chat about any of them in <#{s.forum_channel_id}>."
        intro += "\nPress **Follow games** to pick the ones you want to hear about."
        embeds = []
        for i, text in enumerate(chunk_lines(game_index_lines(entries, guild.id), 3800)):
            e = discord.Embed(colour=discord.Colour(0x1F8B8B), description=(intro + "\n\n" + text) if i == 0 else text)
            if i == 0:
                e.title = "Game Index"
            embeds.append(e)
        return {"embeds": embeds, "files": [], "view": follow_view()}

    @app_commands.command(name="gameindex", description="Post (or update) the Game Index with a Follow button")
    @app_commands.describe(forum="The forum with a thread per game (#game-discussion)",
                           channel="Where the index goes (default: where it's posted now, or here)")
    async def gameindex(self, interaction: discord.Interaction, forum: discord.ForumChannel | None = None,
                        channel: discord.TextChannel | None = None) -> None:
        guild = interaction.guild
        if forum is not None:
            await self.bot.db.update_settings(guild.id, forum_channel_id=forum.id)
        p = await self.bot.db.page_by_key(guild.id, "game-index")
        if p is None:
            p = await self.bot.db.create_page(guild.id, "game-index", "Game Index", kind="game_index")
        channel = channel or (guild.get_channel(p.channel_id) if p.channel_id else None) or interaction.channel
        perms = channel.permissions_for(guild.me)
        if not (perms.view_channel and perms.send_messages and perms.embed_links):
            await interaction.response.send_message(f"I can't post in {channel.mention}.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        count, note = await self.publish(guild, p, channel)
        entries = await self.game_entries(guild)
        no_thread = [e["name"] for e in entries if not e["thread_id"]]
        no_role = [e["name"] for e in entries if not e["role_id"]]
        lines = [f"Game Index in {channel.mention}. {note}"]
        if no_thread:
            lines.append("No forum thread found for: " + ", ".join(no_thread))
        if no_role:
            lines.append("No ping role (so they can't be followed): " + ", ".join(no_role)
                         + ". Set them with /admin crew autopings.")
        await interaction.followup.send("\n".join(lines)[:1990], ephemeral=True)

    async def open_follow(self, interaction: discord.Interaction) -> None:
        entries = [e for e in await self.game_entries(interaction.guild, with_threads=False) if e["role_id"]]
        if not entries:
            await interaction.response.send_message(voice.say("colours_gone"), ephemeral=True)
            return
        wearing = {r.id for r in interaction.user.roles}
        options = [discord.SelectOption(label=e["name"][:100], value=e["key"], emoji=partial_emoji(e["emoji"]),
                                        default=e["role_id"] in wearing) for e in entries[:25]]
        s = await self.bot.db.get_settings(interaction.guild_id)
        forum = f"<#{s.forum_channel_id}>" if s.forum_channel_id else "the game forum"
        await interaction.response.send_message(voice.say("follow_prompt", forum=forum),
                                                view=FollowPicker(self, options), ephemeral=True)

    async def apply_follow(self, interaction: discord.Interaction, chosen_keys: list[str]) -> None:
        guild, member = interaction.guild, interaction.user
        await interaction.response.defer()  # Discord allows 3 seconds; this can take longer
        entries = [e for e in await self.game_entries(guild, with_threads=False) if e["role_id"]]
        by_role = {e["role_id"]: e for e in entries}
        chosen = [e["role_id"] for e in entries if e["key"] in chosen_keys]
        add, remove = plan({r.id for r in member.roles}, list(by_role), chosen, "multi")
        if not add and not remove:
            await finish(interaction, content=voice.say("colours_same"), view=None)
            return
        add_roles = [guild.get_role(r) for r in add]
        remove_roles = [guild.get_role(r) for r in remove]
        gated = await self.bot.db.gated_roles(guild.id)
        if any(self_serve_problem(r, guild.me, gated) for r in add_roles + remove_roles):
            await finish(interaction, content=voice.say("colours_cant"), view=None)
            return
        try:
            if remove_roles:
                await member.remove_roles(*remove_roles, reason="Unfollowed a game")
            if add_roles:
                await member.add_roles(*add_roles, reason="Followed a game")
        except discord.HTTPException:
            await finish(interaction, content=voice.say("colours_cant"), view=None)
            return
        parts = []
        if add:
            parts.append("Following " + voice.join_names([by_role[r]["name"] for r in add]) + ".")
        if remove:
            parts.append("Stopped following " + voice.join_names([by_role[r]["name"] for r in remove]) + ".")
        await finish(interaction, content=voice.say("follow_done", changes=" ".join(parts)), view=None)
        # Threads are a bonus, and slow one at a time, so they're sorted after the reply.
        task = asyncio.create_task(self.update_threads(guild, member, add, remove))
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def update_threads(self, guild: discord.Guild, member, add: list[int], remove: list[int]) -> None:
        entries = {e["role_id"]: e for e in await self.game_entries(guild) if e["role_id"]}
        for rid in add + remove:
            thread = entries.get(rid, {}).get("thread")
            if thread is None:
                continue
            try:
                if rid in add:
                    await thread.add_user(member)
                else:
                    await thread.remove_user(member)
            except discord.HTTPException as e:
                log.info("Couldn't update %s in thread %s: %s", member.id, thread.id, e)

    async def onboarding_items(self, guild: discord.Guild) -> list[discord.ui.Item]:
        roles = await self.bot.db.game_ping_roles(guild.id)
        return [FollowButton()] if any(guild.get_role(r) for r in roles.values()) else []


@app_commands.command(name="follow", description="Pick the games you want to hear about")
@app_commands.guild_only()
async def follow_command(interaction: discord.Interaction) -> None:
    cog = interaction.client.get_cog("Noticeboard")
    if cog is None:
        await interaction.response.send_message(voice.say("error"), ephemeral=True)
        return
    await cog.open_follow(interaction)


async def setup(bot) -> None:
    await bot.add_cog(Noticeboard(bot))
