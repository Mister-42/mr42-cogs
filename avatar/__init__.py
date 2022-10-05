# -*- coding: utf-8 -*-
import discord
from .avatar import Avatar

__red_end_user_data_statement__ = (
    "This cog does not persistently store data or metadata about users."
)

async def setup(bot):
    if discord.version_info.major == 2:
        await bot.add_cog(Avatar())
    else:
        bot.add_cog(Avatar())
