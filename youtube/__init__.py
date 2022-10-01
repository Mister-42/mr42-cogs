# -*- coding: utf-8 -*-
from .youtube import youtube

async def setup(bot):
    bot.add_cog(youtube(bot))
