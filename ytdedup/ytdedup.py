import contextlib
import discord
import re

from datetime import datetime, timedelta
from discord.ext import tasks
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.i18n import Translator, cog_i18n
from redbot.core.utils.chat_formatting import bold, error, humanize_list, success, underline, warning
from typing import Literal, NoReturn
from urllib.parse import urlparse, parse_qs

_ = Translator("YouTube", __file__)
RequestType = Literal["discord_deleted_user", "owner", "user", "user_strict"]

@cog_i18n(_)
class YouTubeDeDup(commands.Cog):
	"""Remove duplicate YouTube links"""

	def __init__(self, bot: Red) -> None:
		self.bot = bot
		self.config = Config.get_conf(self, identifier=823288853745238067)
		self.config.register_guild(history=7, notify=True)
		default_channel_settings = {"messages": {}}
		self.config.register_channel(**default_channel_settings)
		self.background_clean.start()

	@commands.group(aliases=['ytdd'])
	async def youtubededup(self, ctx: commands.Context) -> NoReturn:
		"""Remove duplicate YouTube links in specified channels."""

	@checks.admin_or_permissions(manage_guild=True)
	@commands.guild_only()
	@youtubededup.command(aliases=['w'])
	async def watch(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
		"""Add a channel to be watched."""
		if channel.id in await self.config.all_channels():
			return await ctx.send(warning(_("The channel {channel} is already being monitored.").format(channel=channel.mention)))

		perm = []
		if not channel.permissions_for(channel.guild.me).read_messages:
			perm.append(underline(_("View Channel")))
		if not channel.permissions_for(channel.guild.me).manage_messages:
			perm.append(underline(_("Manage Messages")))
		if not channel.permissions_for(channel.guild.me).read_message_history:
			perm.append(underline(_("Read Message History")))

		if perm:
			return await ctx.send(error(_("I don't have permission to {perm} in {channel}.").format(perm=humanize_list(perm), channel=channel.mention)))

		await self.get_message_history(ctx, channel)
		await ctx.send(success(_("The channel {channel} will now be monitored for duplicate YouTube links.").format(channel=channel.mention)))

	@checks.admin_or_permissions(manage_guild=True)
	@commands.guild_only()
	@youtubededup.command(aliases=['u'])
	async def unwatch(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
		"""Remove a channel from the watchlist."""
		if channel.id not in await self.config.all_channels():
			return await ctx.send(warning(_("The channel {channel} is not being watched.").format(channel=channel.mention)))

		await self.config.channel(channel).clear()
		await ctx.send(success(_("The channel {channel} will no longer be monitored for duplicate YouTube links.").format(channel=channel.mention)))

	@checks.admin_or_permissions(manage_guild=True)
	@commands.guild_only()
	@youtubededup.command()
	async def history(self, ctx: commands.Context, history: int) -> None:
		"""Set the amount of days history is being kept and checked.

		Default is 7 days."""
		history = abs(history)
		await self.config.guild(ctx.guild).history.set(history)

		for channel in ctx.guild.channels:
			if channel.id in await self.config.all_channels():
				await self.get_message_history(ctx, channel)

		days = _("1 day") if history == 1 else _("{history} days").format(history=history)
		await ctx.send(success(_("I will keep message history for {days}.").format(days=bold(days))))

	@checks.admin_or_permissions(manage_guild=True)
	@commands.guild_only()
	@youtubededup.command()
	async def notify(self, ctx: commands.Context) -> None:
		"""Toggle between informing the sender and complete silence."""
		notify = not await self.config.guild(ctx.guild).notify()
		await self.config.guild(ctx.guild).notify.set(notify)

		action = _("enabled") if notify else _("disabled")
		await ctx.send(success(_("User notification has been {action}.").format(action=action)))

	@commands.Cog.listener()
	async def on_message(self, message: discord.Message) -> None:
		if message.channel.id in await self.config.all_channels():
			await self.process_message(message)

	@tasks.loop(minutes=30)
	async def background_clean(self) -> None:
		for chan in await self.config.all_channels():
			if channel := self.bot.get_channel(chan):
				days = await self.config.guild(channel.guild).history()
				messages = await self.config.channel(channel).messages()
				for message in messages:
					if messages.get(message).get('time') < int(datetime.timestamp(datetime.now() - timedelta(days=days))):
						obj = getattr(self.config.channel(channel).messages, message)
						await obj.clear()
			else:
				await self.config.channel_from_id(chan).clear()

	@background_clean.before_loop
	async def background_clean_wait_for_red(self) -> NoReturn:
		await self.bot.wait_until_red_ready()

	async def red_delete_data_for_user(self, *, requester: RequestType, user_id: int) -> None:
		pass

	async def process_message(self, message: discord.Message) -> None:
		if embeds := message.embeds:
			for embed in embeds:
				await self.process_vid(embed.url, message)
		elif text := message.content:
			links = re.findall(r'(https?://\S+/\S+[a-zA-Z0-9])', text)
			for link in links:
				await self.process_vid(link, message)

	async def process_vid(self, url: str, message: discord.Message) -> None:
		if yid := self.get_yid(url):
			channel = message.channel
			messages = await self.config.channel(channel).messages()

			if channel.permissions_for(message.guild.me).manage_messages and yid in [message for message in messages]:
				rmmsg = message
				if message.author.bot:
					with contextlib.suppress(discord.NotFound):
						rmmsg = await channel.fetch_message(messages.get(yid).get('msg'))

				await rmmsg.delete()
				if rmmsg is message and not message.author.bot and await self.config.guild(channel.guild).notify():
					txt = _("Hello {name}. I have deleted your link, as it was already posted here recently.").format(name=message.author.mention)
					await channel.send(content=warning(txt), delete_after=10)

			newVid = {
				'msg': message.id,
				'time': int(message.created_at.timestamp())
			}
			obj = getattr(self.config.channel(channel).messages, yid)
			await obj.set(newVid)

	async def get_message_history(self, ctx: commands.Context, channel: discord.TextChannel):
		await self.config.channel(channel).messages.set({})
		days = await self.config.guild(ctx.guild).history()
		async with ctx.typing():
			async for message in channel.history(after=datetime.now() - timedelta(days=days), limit=None):
				await self.process_message(message)

	def get_yid(self, url: str):
		query = urlparse(url)
		if query.hostname == 'youtu.be': return query.path[1:]
		if query.hostname in {'www.youtube.com', 'youtube.com', 'music.youtube.com'}:
			if query.path == '/watch':
				return parse_qs(query.query)['v'][0]
			elif query.path.startswith(('/watch/', '/shorts/', '/live/', '/embed/', '/v/')):
				return query.path.split('/')[2]
		return None

	def cog_unload(self):
		self.background_clean.cancel()
