# -*- coding: utf-8 -*-
import discord
from .avatar import Avatar

async def setup(bot):
    if discord.version_info.major == 2:
        await bot.add_cog(Avatar())
    else:
        bot.add_cog(Avatar())
