"""The basics: who PlunderBot is."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from .. import voice


class Core(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="plunderbot", description="Meet PlunderBot, the Fortress's robot butler")
    async def about(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(voice.say("about", version=self.bot.version), ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(Core(bot))
