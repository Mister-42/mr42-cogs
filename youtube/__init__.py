# -*- coding: utf-8 -*-
from .youtube import YouTube

async def setup(bot):
    bot.add_cog(YouTube(bot))
