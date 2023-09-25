# rsync -av /home/pi/mr42-cogs/sup/ vm1:/usr/local/etc/redbot/DeepThought/cogs/CogManager/cogs/sup/

import discord
import logging
import os
import random
import time

from typing import Literal, NoReturn, Optional
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.data_manager import bundled_data_path
from redbot.core.i18n import Translator, cog_i18n
from redbot.core.utils.chat_formatting import humanize_timedelta

_ = Translator("Sup", __file__)
log = logging.getLogger("red.mr42-cogs.sup")
RequestType = Literal["discord_deleted_user", "owner", "user", "user_strict"]

@cog_i18n(_)
class Sup(commands.Cog):
	"""Shut Up, PeK!"""

	def __init__(self, bot: Red) -> None:
		self.bot = bot
		self.config = Config.get_conf(self, identifier=823288853745238067)
		self.config.register_guild(interval=2)

	@commands.group()
	async def sup(self, ctx: commands.Context) -> NoReturn:
		"""Shut Up, PeK!"""

	@checks.admin_or_permissions(manage_guild=True)
	@commands.guild_only()
	@sup.command()
	async def toggle(self, ctx: commands.Context, interval: Optional[int]) -> None:
		"""Toggle `Shut up, PeK!` on this server"""
		if await self.config.guild(ctx.guild).enabled():
			await self.config.guild(ctx.guild).clear()
			return await ctx.send("PeK will now be able to talk undisturbed.")
		await self.config.guild(ctx.guild).enabled.set(True)
		await ctx.send("Shut up, PeK!")

	@checks.admin_or_permissions(manage_guild=True)
	@commands.guild_only()
	@sup.command()
	async def interval(self, ctx: commands.Context, interval: Optional[int]) -> None:
		"""Set the minimum interval in hours at which to reply to PeK.

		Default is 2 hours."""
		if interval is None:
			interval = await self.config.guild(ctx.guild).interval()
			return await ctx.send(_("I am currently replying a maximum of once every {time} to <@190796445782245376>.").format(time=humanize_timedelta(seconds=interval * 3600)))
		elif interval < 1:
			return await ctx.send(error(_("You cannot set the interval to less than 1 hour")))

		await self.config.guild(ctx.guild).interval.set(interval)
		await ctx.send(success(_("I will now reply a maximum of once every {time} to <@190796445782245376>.").format(time=humanize_timedelta(seconds=interval * 3600))))

	@commands.Cog.listener()
	async def on_message(self, message):
		if message.author.id == 190796445782245376 and message.guild.id in await self.config.all_guilds():
			last = await self.config.guild(message.guild).last() or 0
			ts = int(time.time())
			if last + (await self.config.guild(message.guild).interval() * 3600) < ts:
				res = []
				for path in os.listdir(bundled_data_path(self)):
					if os.path.isfile(os.path.join(bundled_data_path(self), path)):
						res.append(path)

				img = random.choice(res)
				await message.reply(file=discord.File(f"{bundled_data_path(self)}/{img}", filename=f"{img}"))
				await self.config.guild(message.guild).last.set(ts)

	async def red_delete_data_for_user(self, *, requester: RequestType, user_id: int) -> None:
		pass
