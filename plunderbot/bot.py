"""The PlunderBot client: wiring for the database, cogs, telemetry and health check."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from . import __version__, voice
from .config import Config
from .db import Database

log = logging.getLogger("plunderbot")

COGS = [
    "plunderbot.cogs.core",
    "plunderbot.cogs.admin",
    "plunderbot.cogs.birthdays",
    "plunderbot.cogs.crew",
    "plunderbot.cogs.voyages",
    "plunderbot.cogs.regions",
    "plunderbot.cogs.gangplank",
]


class PlunderTree(app_commands.CommandTree):
    async def on_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.NoPrivateMessage):
            text = voice.say("guild_only")
        elif isinstance(error, (app_commands.MissingPermissions, app_commands.CheckFailure)):
            text = voice.say("no_permission")
        else:
            cmd = interaction.command.qualified_name if interaction.command else "unknown"
            log.error("Error in /%s", cmd, exc_info=error)
            text = voice.say("error")
        try:
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
        except discord.HTTPException:
            pass


class PlunderBot(commands.Bot):
    def __init__(self, config: Config, telemetry=None):
        intents = discord.Intents.default()
        intents.members = True  # welcomes, birthday roles; needs "Server Members Intent" in the portal
        super().__init__(
            command_prefix=commands.when_mentioned,  # slash commands only; no prefix commands
            intents=intents,
            tree_cls=PlunderTree,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
            help_command=None,
        )
        self.config = config
        self.db = Database(config.db_path)
        self.telemetry = telemetry
        self.version = __version__

    async def setup_hook(self) -> None:
        await self.db.connect()
        for cog in COGS:
            await self.load_extension(cog)
        if self.config.dev_guild_id:
            guild = discord.Object(id=self.config.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d commands to guild %s", len(synced), self.config.dev_guild_id)
            # Clear the app's global commands so nothing shows twice, including any left behind
            # by whatever used this application before (e.g. MEE6's Bot Personalizer).
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global commands", len(synced))

    async def on_ready(self) -> None:
        log.info("PlunderBot %s aboard as %s in %d server(s)", self.version, self.user, len(self.guilds))
        try:
            self.config.ready_file.touch()  # the Docker HEALTHCHECK watches this
        except OSError as e:
            log.warning("Couldn't write the ready file %s: %s", self.config.ready_file, e)

    async def close(self) -> None:
        await super().close()
        await self.db.close()

    def gauge(self, name: str, value: float) -> None:
        if self.telemetry is not None:
            self.telemetry.gauge(name, value)
