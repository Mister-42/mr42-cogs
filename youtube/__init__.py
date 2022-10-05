# -*- coding: utf-8 -*-
import discord
from .youtube import YouTube

async def setup(bot):
    if discord.version_info.major == 2:
        await bot.add_cog(YouTube(bot))
    else:
        bot.add_cog(YouTube(bot))
