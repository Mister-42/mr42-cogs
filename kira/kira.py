import discord
import logging
import re

from contextlib import suppress
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.i18n import Translator, cog_i18n
from redbot.core.utils.chat_formatting import bold, error, humanize_list, success, underline, warning
from redbot.core.utils.views import ConfirmView
from typing import Optional, NoReturn
from urllib.parse import urlparse

_ = Translator("KirA", __file__)
log = logging.getLogger("red.mr42-cogs.kira")

@cog_i18n(_)
class KirA(commands.Cog):
	"""Keep It Relevant, Asshole!"""

	def __init__(self, bot: Red) -> None:
		self.bot = bot
		self.config = Config.get_conf(self, identifier=823288853745238067)
		default_channel_settings = {
			'domains': ['youtu.be', 'youtube.com', 'www.youtube.com', 'music.youtube.com'],
			'question': _('Are you sure this video is relevant to the topic?'),
			'timeout': 10
		}
		self.config.register_channel(**default_channel_settings)

	@commands.group()
	async def kira(self, ctx: commands.Context) -> NoReturn:
		"""Remind people to only post relevant links."""

	@checks.admin_or_permissions(manage_guild=True)
	@commands.guild_only()
	@kira.command(aliases=['w'])
	async def watch(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
		"""Add a channel to be monitored."""
		if channel.id in await self.config.all_channels():
			return await ctx.send(warning(_("The channel {channel} is already being monitored.").format(channel=channel.mention)))

		perm = []
		if not channel.permissions_for(channel.guild.me).read_messages:
			perm.append(underline(_("View Channel")))
		if not channel.permissions_for(channel.guild.me).send_messages:
			perm.append(underline(_("Send Messages")))
		if not channel.permissions_for(channel.guild.me).manage_messages:
			perm.append(underline(_("Manage Messages")))

		if perm:
			return await ctx.send(error(_("I don't have permission to {perm} in {channel}.").format(perm=humanize_list(perm), channel=channel.mention)))

		await self.config.channel(channel).set({})
		await ctx.send(success(_("The channel {channel} will now be monitored for links.").format(channel=channel.mention)))

	@checks.admin_or_permissions(manage_guild=True)
	@commands.guild_only()
	@kira.command(aliases=['u'])
	async def unwatch(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
		"""Remove a channel from the watchlist."""
		if channel.id not in await self.config.all_channels():
			return await ctx.send(warning(_("The channel {channel} is not being monitored.").format(channel=channel.mention)))

		await self.config.channel(channel).clear()
		await ctx.send(success(_("The channel {channel} will no longer be monitored for links.").format(channel=channel.mention)))

	@checks.admin_or_permissions(manage_guild=True)
	@commands.guild_only()
	@kira.command()
	async def question(self, ctx: commands.Context, channel: discord.TextChannel, question: str) -> None:
		"""Change the question the sender will be required to answer."""
		if channel.id not in await self.config.all_channels():
			return await ctx.send(warning(_("The channel {channel} is not being monitored.").format(channel=channel.mention)))

		await self.config.channel(channel).question.set(question)
		await ctx.send(success(_("The question has been updated:") + "\n" + question))

	@checks.admin_or_permissions(manage_guild=True)
	@commands.guild_only()
	@kira.command()
	async def timeout(self, ctx: commands.Context, channel: discord.TextChannel, timeout: Optional[int]) -> None:
		"""Set the timeout for questioning the sender. 0 will disable the questioning and deletes the message immediately.

		Default is 10 seconds."""
		if channel.id not in await self.config.all_channels():
			return await ctx.send(warning(_("The channel {channel} is not being monitored.").format(channel=channel.mention)))

		t = 0 if timeout == 0 else abs(timeout or await self.config.channel(channel).timeout())
		text = _("1 second") if t == 1 else _("{time} seconds").format(time=t)

		if timeout is None:
			return await ctx.send(_("The current question timeout is {time}.").format(time=bold(text)))

		await self.config.channel(channel).timeout.set(t)
		await ctx.send(success(_("I will question the sender of links for {time}.").format(time=bold(text))))

	@checks.admin_or_permissions(manage_guild=True)
	@commands.guild_only()
	@kira.command()
	async def domain(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
		"""Configure which domains to look out for.

		This function doesn't do anything at the moment, but will be expanded later."""
		if channel.id not in await self.config.all_channels():
			return await ctx.send(warning(_("The channel {channel} is not being monitored.").format(channel=channel.mention)))

		domains = await self.config.channel(channel).domains()
		await ctx.send(_("Current configured domains: {domains}").format(domains=humanize_list(domains)))

	@commands.Cog.listener()
	async def on_message(self, message: discord.Message) -> None:
		if not message.author.bot and message.channel.id in await self.config.all_channels() and message.author != message.guild.owner:
			for link in re.findall(r'(https?://\S+/)', message.content):
				if urlparse(link).hostname in await self.config.channel(message.channel).domains():
					timeout = await self.config.channel(message.channel).timeout()
					if timeout and message.channel.permissions_for(message.guild.me).manage_messages:
						prompt = await self.config.channel(message.channel).question()
						view = ConfirmView(message.author, timeout=timeout)
						view.message = await message.reply(prompt, view=view)
						await view.wait()
						with suppress(discord.NotFound):
							await view.message.delete()

						if view.result:
							return
					with suppress(discord.NotFound):
						return await message.delete()

	async def red_delete_data_for_user(self, **kwargs) -> None:
		pass
