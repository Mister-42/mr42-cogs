# -*- coding: utf-8 -*-
from .avatar import Avatar

async def setup(bot):
    bot.add_cog(Avatar())
