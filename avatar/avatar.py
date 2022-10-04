# -*- coding: utf-8 -*-
import discord
from io import BytesIO
from typing import Optional
from redbot.core import commands

BaseCog = getattr(commands, "Cog", object)

class Avatar(BaseCog):
    """Get user avatar as attachment"""

    @commands.command()
    async def avatar(self, ctx, user: Optional[discord.Member] = None):
        """Returns a user's avatar as attachment

        User argument can be user mention, nickname, username, user ID.

        Defaults to yourself when no argument is supplied.
        """
        if not isinstance(ctx.channel, discord.DMChannel) and ctx.channel.permissions_for(ctx.guild.me).manage_messages:
            await ctx.message.delete()

        if not user:
            user = ctx.author

        pfp = BytesIO()
        await user.avatar_url.save(pfp)
        pfp.seek(0)

        if user.is_avatar_animated():
            filename = f"pfp-{user.id}.gif"
        else:
            filename = f"pfp-{user.id}.png"

        reqName = f"**<@{ctx.author.id}>**"
        if isinstance(ctx.channel, discord.DMChannel):
            reqName = 'You'

        message = f"{reqName} requested the avatar of **{user.name}**."
        if user == ctx.author:
            message = f"Here is your avatar, <@{user.id}>."

        await ctx.send(message, file=discord.File(pfp, filename=filename))
