import aiohttp
import discord
import feedparser
import logging
import re
import yt_dlp

from contextlib import suppress
from datetime import datetime
from discord.ext import tasks
from typing import NoReturn, Optional, Union
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.data_manager import bundled_data_path
from redbot.core.i18n import Translator, cog_i18n
from redbot.core.utils.chat_formatting import bold, error, escape, humanize_list, humanize_timedelta, inline, pagify, question, success, text_to_file, warning
from redbot.core.utils.views import ConfirmView
from string import Formatter
from urllib.parse import urlparse

_ = Translator("YouTube", __file__)
log = logging.getLogger("red.mr42-cogs.youtube")
YT_COLOR = discord.Colour.from_rgb(255, 0, 0)
YT_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

def has_feature(feature: str):
	def predicate(ctx: commands.Context):
		return ctx.guild and feature.upper() in ctx.guild.features
	return commands.check(predicate)

@cog_i18n(_)
class YouTube(commands.Cog):
	"""Subscribe to channels on YouTube."""

	def __init__(self, bot: Red) -> None:
		self.bot = bot
		self.config = Config.get_conf(self, identifier=823288853745238067)
		self.config.register_global(interval=300)
		self.config.register_guild(maxpages=2)
		self.config.register_channel(embed=True)
		self.config.init_custom('subscriptions', 1)
		self.config.register_custom('subscriptions')
		self.background_get_new_videos.start()

	@commands.group(aliases=['yt'])
	async def youtube(self, ctx: commands.Context) -> NoReturn:
		"""Post when new videos are published to a YouTube channel."""

	@checks.admin_or_permissions(manage_guild=True)
	@commands.guild_only()
	@youtube.command(aliases=['s', 'sub'])
	async def subscribe(self, ctx: commands.Context, channelYouTube: str, channelDiscord: Optional[discord.TextChannel] = None) -> None:
		"""Subscribe a Discord channel to a YouTube channel.

		If no Discord channel is specified, the current channel will be subscribed.

		Channels can be added by channel ID, channel URL, video URL, or playlist URL."""
		async with ctx.typing():
			if not (yid := await self.get_youtube_channel(ctx, channelYouTube)):
				return

			channel = channelDiscord or ctx.channel
			if dchans := await self.config.custom('subscriptions', yid).discord():
				feedTitle = await self.config.custom('subscriptions', yid).name()
				if ctx.command.qualified_name != 'youtube migrate' and str(channel.id) in dchans.keys():
					return await ctx.send(warning(_("{title} is already being announced in {channel}.").format(title=bold(f"{feedTitle}"), channel=channel.mention)))
				await self.config.custom('subscriptions', yid, 'discord', channel.id).set({})
			else:
				try:
					feedData = await self.get_feed(yid)
				except ConnectionError:
					return await ctx.send(error(_("Unable to connect, please try again.")))

				if isinstance(feedData, aiohttp.ClientResponse):
					return await ctx.send(error(_("Error {error} for channel {channel}.").format(error=bold(f"{feedData.status} {feedData.reason}"), channel=bold(yid))))

				feed = feedparser.parse(feedData)
				feedTitle = feed['feed']['title']
				try:
					updated = datetime.strptime(feed['entries'][0]['published'], YT_FORMAT).timestamp()
				except IndexError:
					# No videos are published on the YouTube channel
					updated = datetime.strptime(feed['feed']['published'], YT_FORMAT).timestamp()

				newChannel = {
					'name': feedTitle,
					'updated': int(updated),
					'processed': [entry['yt_videoid'] for entry in feed['entries'][:6]],
					'discord': {channel.id: {}}
				}
				await self.config.custom('subscriptions', yid).set(newChannel)

		if ctx.command.qualified_name != 'youtube migrate':
			await ctx.send(success(_("The YouTube channel {title} will now be announced in {channel} when new videos are published.").format(title=bold(feedTitle), channel=channel.mention)))

	@checks.admin_or_permissions(manage_guild=True)
	@commands.guild_only()
	@youtube.command(aliases=['u', 'unsub'])
	async def unsubscribe(self, ctx: commands.Context, channelYouTube: str, channelDiscord: Optional[discord.TextChannel] = None) -> None:
		"""Unsubscribe a Discord channel from a YouTube channel.

		If no Discord channel is specified, the subscription will be removed from all channels."""
		async with ctx.typing():
			if not (yid := await self.get_youtube_channel(ctx, channelYouTube)):
				return

			updated = []
			if dchans := await self.config.custom('subscriptions', yid).discord():
				feedTitle = await self.config.custom('subscriptions', yid).name()
				if not channelDiscord:
					for channel in [x for x in ctx.guild.channels if str(x.id) in dchans.keys()]:
						await self.config.custom('subscriptions', yid, 'discord', channel.id).clear()
						updated.append(channel.mention)
				elif str(channelDiscord.id) in dchans.keys():
					await self.config.custom('subscriptions', yid, 'discord', channelDiscord.id).clear()
					updated.append(channelDiscord.mention)

			if not updated:
				return await ctx.send(error(_("Subscription not found.")))

			if not await self.config.custom('subscriptions', yid).discord():
				await self.config.custom('subscriptions', yid).clear()

			await ctx.send(success(_("Unsubscribed from {title} on {list}.").format(title=bold(feedTitle), list=humanize_list(updated))))

	@checks.admin_or_permissions(manage_guild=True)
	@commands.guild_only()
	@youtube.command()
	async def list(self, ctx: commands.Context, channelDiscord: Optional[discord.TextChannel] = None) -> None:
		"""List current subscriptions."""
		subsByChannel = {}
		subsYt = []

		data = await self.config.custom('subscriptions').get_raw()
		for yid in dict(sorted(data.items(), key=lambda d: d[1]['updated'], reverse=True)):
			dchans = await self.config.custom('subscriptions', yid).discord()

			channels = [self.bot.get_channel(int(channel)) for channel in dchans.keys()]
			if ctx.command.qualified_name != 'youtube listall':
				channels = [channelDiscord] if channelDiscord else ctx.guild.channels

			for channel in channels:
				if not channel:
					continue
				dchan = str(channel.id)
				if dchan in dchans.keys():
					info = await self.config.custom('subscriptions', yid).name()
					if oldname := dchans.get(dchan).get('oldname'):
						info += f" \u27ea {oldname}"

					d = {'message': '\u1d9c', 'mention': '\u1d50', 'publish': '\u1d56'}
					if tags := ''.join(v for k, v in d.items() if k in dchans.get(dchan)):
						info += f" {tags}"

					if (errorCount := await self.config.custom('subscriptions', yid).errorCount() or 0) > 6:
						info += " \u205D " + _("{count} errors").format(count=errorCount)

					if channel.guild.id not in subsByChannel:
						subsByChannel[channel.guild.id] = {}
					if channel.id not in subsByChannel[channel.guild.id]:
						subsByChannel[channel.guild.id][channel.id] = {}
					subsByChannel[channel.guild.id][channel.id].update({yid: {'updated': await self.config.custom('subscriptions', yid).updated(), 'info': info}})
					subsYt.append(yid)

		if not len(subsByChannel):
			return await ctx.send(warning(_("No subscriptions yet - try adding some!")))

		text = richText = ""
		subCount = len(subsYt)
		subCountYt = len(set(subsYt))
		if len(subsByChannel) > 1:
			text = _("{count} total subscriptions").format(count=subCount)
			if subCount != subCountYt:
				text = _("{count} total subscriptions over {yt} YouTube channels").format(count=subCount, yt=subCountYt)
			richText = bold(text)

		for guild in sorted(subsByChannel.keys()):
			for sub, sub_ids in sorted(subsByChannel[guild].items()):
				count = len(sub_ids)
				channel = self.bot.get_channel(sub)

				msg = "\n\n" + _("{count} YouTube subscriptions for {channel}") if subCount > 1 else _("1 YouTube subscription for {channel}")
				text += msg.format(count=count, channel=f"#{channel.name}")
				richText += msg.format(count=count, channel=channel.mention)
				if ctx.command.qualified_name == 'youtube listall':
					text += f" ({channel.guild.name})"
					richText += f" ({bold(channel.guild.name)})"

				for yid, data in sub_ids.items():
					text += f"\n{yid} {datetime.fromtimestamp(data['updated'])} {data['info']}"
					richText += f"\n{inline(yid)} <t:{data['updated']}:R> {escape(data['info'], formatting=True)}"

		pages = list(pagify(richText.strip()))
		if isinstance(ctx.channel, discord.DMChannel) or len(pages) > await self.config.guild(ctx.guild).maxpages():
			if not isinstance(ctx.channel, discord.DMChannel) and not ctx.channel.permissions_for(ctx.guild.me).attach_files:
				return await ctx.send(error("I do not have permission to attach files in this channel."))
			txt = text_to_file(text.strip(), "subscriptions.txt")
			return await ctx.send(file=txt)
		for page in pages:
			await ctx.send(page)

	@checks.admin_or_permissions(manage_guild=True)
	@commands.guild_only()
	@youtube.command(aliases=['c', 'customize'])
	async def custom(self, ctx: commands.Context, channelYouTube: str, message: str = "", channelDiscord: Optional[discord.TextChannel] = None) -> None:
		"""Add a custom message for new videos from a YouTube channel.

		You can use keys in your custom message, surrounded by curly braces.
		E.g. `[p]youtube customize UCXuqSBlHAE6Xw-yeJA0Tunw "Linus from **{author}** is dropping things again!\\nCheck out their new video {title}" #video-updates`

		Valid options are: {mention}, {author}, {title}, {published}, {updated} and {summary}.

		You can also remove customization by not specifying any message."""
		fail = []
		options = {'mention', 'author', 'title', 'published', 'updated', 'summary'}
		for x in [i[1] for i in Formatter().parse(message) if i[1] is not None and i[1] not in options]:
			fail.append(inline(x))

		if fail:
			msg = _("You are not allowed to use {key} in the message.").format(key=humanize_list(fail))
			if ctx.command.qualified_name == 'youtube migrate':
				msg += " " + _("Please fix this message later if you want to use a custom message: ")
				prefixes = await self.bot.get_valid_prefixes(channelDiscord.guild)
				msg += inline(f"{prefixes[0]}youtube custom {channelYouTube} {channelDiscord.mention} \"{message}\"")
			return await ctx.send(error(msg))
		msg = message.replace("\\n", "\n").strip()
		await self.subscription_discord_options(ctx, 'message', channelYouTube, msg, channelDiscord)

	@checks.admin_or_permissions(manage_guild=True)
	@commands.guild_only()
	@youtube.command(aliases=['m', 'rolemention'])
	async def mention(self, ctx: commands.Context, channelYouTube: str, mention: Optional[Union[discord.Role, str]], channelDiscord: Optional[discord.TextChannel] = None) -> None:
		"""Add a role @mention. Mentions will be placed in front of the message, or replacing {mention} in a custom message.

		You can also remove the mention by not specifying any role."""
		m = False
		if isinstance(mention, discord.Role):
			m = mention.id
		elif mention == "@here":
			m = "here"
		elif mention:
			return await ctx.send(error(_("You can't set {mention} as mention.").format(mention=mention)))
		await self.subscription_discord_options(ctx, 'mention', channelYouTube, m, channelDiscord)

	@checks.admin_or_permissions(manage_guild=True)
	@commands.guild_only()
	@youtube.command()
	async def embed(self, ctx: commands.Context, channelDiscord: discord.TextChannel) -> None:
		"""Toggles between embedded messages and linking videos

		Default is to embed messages, if the bot has the `embed_links` permission"""
		if await self.config.channel(channelDiscord).embed():
			await self.config.channel(channelDiscord).embed.set(False)
			return await ctx.send(success(_("From now on I will link to videos in {channel}.").format(channel=channelDiscord.mention)))

		await self.config.channel(channelDiscord).embed.clear()
		permcheck = []
		for perm in [i for i in ["attach_files", "embed_links"] if not getattr(channelDiscord.permissions_for(channelDiscord.guild.me), i)]:
			permcheck.append(inline(perm))

		if permcheck:
			return await ctx.send(warning(_("Embeds have now been enabled for {channel}, but it requires {permissions} to function.").format(channel=channelDiscord.mention, permissions=humanize_list(permcheck))))
		await ctx.send(success(_("Embeds have now been enabled for {channel}.").format(channel=channelDiscord.mention)))

	@checks.admin_or_permissions(manage_guild=True)
	@commands.guild_only()
	@youtube.command()
	async def info(self, ctx: commands.Context, channelYouTube: str) -> None:
		"""Provides information about a YouTube subscription."""
		if not (yid := await self.get_youtube_channel(ctx, channelYouTube)):
			return

		info = []
		async with ctx.typing():
			if dchans := await self.config.custom('subscriptions', yid).discord():
				sub = self.config.custom('subscriptions', yid)
				channels = [self.bot.get_channel(int(channel)) for channel in dchans.keys()]
				spacer = "  "
				if ctx.command.qualified_name != 'youtube infoall':
					channels = ctx.guild.channels
					spacer = ""

				for channel in channels:
					if not channel:
						continue

					dchan = str(channel.id)
					if dchan in dchans.keys():
						part = channel.mention
						if ctx.command.qualified_name == 'youtube infoall':
							part = "- " + channel.mention

						if oldname := dchans.get(dchan).get('oldname'):
							part += f"\n{spacer}- {bold(_('Subscribed as'))}: {oldname}"

						if message := dchans.get(dchan).get('message'):
							part += f"\n{spacer}- {bold(_('Custom'))}: {escape(message, formatting=True)}"

						if m := dchans.get(dchan).get('mention'):
							mention = f"<@&{m}>"
							if m == ctx.guild.id:
								mention = ctx.guild.default_role.name
							elif m == "here":
								mention = "@here"
							part += f"\n{spacer}- {bold(_('Mention'))}: {mention}"

						if dchans.get(dchan).get('publish'):
							publish = _("Yes") if channel.is_news() else _("Yes, but not an Announcement Channel")
							part += f"\n{spacer}- {bold(_('Publish'))}: {publish}"

						info.append(part)

		if not info:
			return await ctx.send(error(_("Subscription not found.")))

		if isinstance(ctx.channel, discord.DMChannel) or ctx.channel.permissions_for(ctx.guild.me).embed_links and ctx.channel.permissions_for(ctx.guild.me).attach_files:
			count = 0
			embeds = []
			msg = ''
			for v in info:
				count += 1
				if count <= 50 and len("\n\n" + msg + v + "\n") <= 4096:
					msg += v + "\n"
				elif info.index(v) == len(info) - 1:
					msg = v
				else:
					count = 1
					embeds.append(msg)
					msg = v + "\n"
			embeds.append(msg)

			for msg in embeds:
				embed = discord.Embed()
				embed.colour = YT_COLOR
				embed.title = _("Subscription information for {name}").format(name=await sub.name())
				embed.url = f"https://www.youtube.com/channel/{yid}/"
				embed.description = "\n\n" + msg
				embed.timestamp = datetime.fromtimestamp(await sub.updated())
				embed.set_footer(text=_("Latest video"), icon_url="attachment://youtube.png")
				icon = discord.File(bundled_data_path(self) / "youtube_social_icon_red.png", filename="youtube.png")
				await ctx.send(file=icon, embed=embed)
			return

		msg = _("Subscription information for {name}").format(name=await sub.name()) + "\n"
		msg += f"<https://www.youtube.com/channel/{yid}/>\n\n"
		msg += "\n\n".join(info)
		for page in list(pagify(msg.strip())):
			await ctx.send(page)

	@checks.admin_or_permissions(manage_guild=True)
	@commands.guild_only()
	@youtube.command()
	async def maxpages(self, ctx: commands.Context, limit: Optional[int]) -> None:
		"""Set a limit on amount of pages `list` will send.

		When the limit is reached, a text file will be sent instead.

		Default is a maximum of 2 pages."""
		maxPages = abs(limit) if limit is not None else await self.config.guild(ctx.guild).maxpages()
		pages = _("1 page") if maxPages == 1 else _("{pages} pages").format(pages=maxPages)

		if limit is None:
			return await ctx.send(_("I am currently sending a maximum of {limit} before sending a file instead.").format(limit=bold(pages)))

		await self.config.guild(ctx.guild).maxpages.set(maxPages)
		await ctx.send(success(_("I will now send a file after reaching {limit}.").format(limit=bold(pages))))

	@checks.admin_or_permissions(manage_guild=True)
	@commands.guild_only()
	@has_feature('news')
	@youtube.command(aliases=['p'])
	async def publish(self, ctx: commands.Context, channelYouTube: str, channelDiscord: Optional[discord.TextChannel] = None) -> None:
		""" Toggles publishing new messages to a Discord channel.

		This feature is only available on Community Servers."""
		if not (yid := await self.get_youtube_channel(ctx, channelYouTube)):
			return

		async with ctx.typing():
			dchan = False
			notNews = []
			channels = [channelDiscord] if channelDiscord else ctx.guild.channels
			if dchans := await self.config.custom('subscriptions', yid).discord():
				for channel in [x for x in channels if str(x.id) in dchans.keys()]:
					if not channel.is_news():
						notNews.append(channel.mention)
						continue
					dchan = str(channel.id)
					publish = not dchans.get(dchan).get('publish')
					await self.subscription_discord_options(ctx, 'publish', yid, publish, channel)

		if notNews:
			msg = _("The channel {list} is not an Announcement Channel.") if len(notNews) == 1 else _("The channels {list} are not Announcement Channels.")
			await ctx.send(warning(msg.format(list=humanize_list(notNews))))
		elif not dchan:
			await ctx.send(error(_("Subscription not found.")))

	@checks.is_owner()
	@commands.guild_only()
	@youtube.command(aliases=['test'])
	async def demo(self, ctx: commands.Context, channelYouTube: Optional[str]) -> None:
		"""Send a demo message to the current channel."""
		yid = 'UCBR8-60-B28hp2BmDPdntcQ'
		if channelYouTube and not (yid := await self.get_youtube_channel(ctx, channelYouTube)):
			return

		ytFeedData = await self.get_feed(yid)
		ytFeed = feedparser.parse(ytFeedData)
		dchans = {str(ctx.channel.id): {'mention': ctx.guild.id, 'message': f"This is a test message for **{{author}}** from the YouTube cog, as requested by {ctx.author.mention}.\n**Sorry for pinging {{mention}}.** I don't do this by default for normal new videos, just for this test. *Or* when explicitly requested."}}

		for entry in ytFeed['entries'][:1][::-1]:
			await self.send_message(entry, ctx.channel, dchans)

	@checks.is_owner()
	@youtube.command()
	async def infoall(self, ctx: commands.Context, channelYouTube: str) -> NoReturn:
		"""Provides information about a YouTube subscription across servers."""
		await self.info(ctx, channelYouTube)

	@checks.is_owner()
	@youtube.command()
	async def listall(self, ctx: commands.Context) -> NoReturn:
		"""List current subscriptions across servers."""
		await self.list(ctx)

	@checks.is_owner()
	@youtube.command()
	async def delete(self, ctx: commands.Context, channelYouTube: str) -> None:
		"""Delete a YouTube channel from the configuration. This will delete all data associated with this channel."""
		if not (yid := await self.get_youtube_channel(ctx, channelYouTube)):
			return

		if not (name := await self.config.custom('subscriptions', yid).name()):
			return await ctx.send(error(_("Subscription not found.")))

		dchans = []
		for g in await self.config.custom('subscriptions', yid).discord():
			if not (dchan := self.bot.get_channel(int(g))):
				continue
			dchans.append(dchan.mention)

		view = ConfirmView(ctx.author)
		prompt = (_("You are about to remove {channel} from the configuration.").format(channel=bold(name))
			+ " " + _("It is subscribed to by {channels}.").format(channels=humanize_list(dchans)) + "\n"
			+ _("Do you want to continue?")
		)
		view.message = await ctx.send(question(prompt), view=view)
		await view.wait()
		if view.result:
			await self.config.custom('subscriptions', yid).clear()
			return await ctx.send(success(_("{channel} has been removed from the configuration.").format(channel=bold(name))))
		return await ctx.send(warning(_("{channel} has not been deleted.").format(channel=bold(name))))

	@checks.is_owner()
	@youtube.command()
	async def interval(self, ctx: commands.Context, interval: Optional[int]) -> None:
		"""Set the interval in seconds at which to check for updates.

		Very low values will probably get you rate limited!

		Default is 300 seconds (5 minutes)."""
		if interval is None:
			interval = await self.config.interval()
			return await ctx.send(_("I am currently checking every {time} for new videos.").format(time=humanize_timedelta(seconds=interval)))
		elif interval < 60:
			return await ctx.send(error(_("You cannot set the interval to less than 60 seconds")))

		await self.config.interval.set(interval)
		self.background_get_new_videos.change_interval(seconds=interval)
		await ctx.send(success(_("I will now check every {time} for new videos.").format(time=humanize_timedelta(seconds=interval))))

	@checks.is_owner()
	@youtube.command(hidden=True)
	async def migrate(self, ctx: commands.Context) -> None:
		"""Import all subscriptions from the `Tube` cog."""
		TubeConfig = Config.get_conf(None, 0x547562756c6172, True, cog_name='Tube')
		TubeConfig.register_guild(subscriptions=[])
		channels = 0
		for g in self.bot.guilds:
			guild = self.bot.get_guild(g.id)
			channels += len(await TubeConfig.guild(guild).subscriptions())

		if channels == 0:
			return await ctx.send(error(_("No data found to import. Migration has been cancelled.")))

		view = ConfirmView(ctx.author)
		prompt = _("You are about to import **{channels} YouTube subscriptions**.").format(channels=channels)
		prompt += " " + _("Depending on the internet speed of the server, this might take a while.") + "\n"
		prompt += _("Do you want to continue?")
		view.message = await ctx.send(question(prompt), view=view)
		await view.wait()
		if not view.result:
			return await ctx.send(_("Migration has been cancelled."))

		await ctx.send(_("Migration started…"))
		async with ctx.typing():
			for g in self.bot.guilds:
				guild = self.bot.get_guild(g.id)
				count = 0
				for data in await TubeConfig.guild(guild).subscriptions():
					yid = data.get('id')
					channel = self.bot.get_channel(int(data.get('channel').get('id')))
					await self.subscribe(ctx, yid, channel)

					if message := data.get('custom'):
						TOKENIZER = re.compile(r'([^\s]+)')
						for token in TOKENIZER.split(message):
							if token.startswith("%") and token.endswith("%"):
								message = message.replace(token, f"{{{token[1:-1]}}}")
						await self.custom(ctx, yid, message, channel)

					if (mention := data.get('mention')) and (role := guild.get_role(mention)):
						await self.mention(ctx, yid, role, channel)

					if data.get('publish'):
						await self.subscription_discord_options(ctx, 'publish', yid, True, channel)
					count += 1

				if count > 0:
					msg = _("Imported 1 subscription for {guild}.") if count == 1 else _("Imported {count} subscriptions for {guild}.")
					await ctx.send(msg.format(count=count, guild=bold(g.name)))
		await ctx.send(success(_("Migration completed!")))

		if 'Tube' in ctx.bot.extensions:
			view = ConfirmView(ctx.author)
			prompt = _("Running the {tube} cog alongside this cog *will* get spammy. Do you want to unload {tube}?").format(tube=inline("Tube"))
			view.message = await ctx.send(question(prompt), view=view)
			await view.wait()
			with suppress(discord.NotFound):
				await view.message.delete()
			if view.result:
				await ctx.bot.unload_extension('Tube')

	@tasks.loop(minutes=5)
	async def background_get_new_videos(self) -> NoReturn:
		for yid in await self.config.custom('subscriptions').get_raw():
			name = await self.config.custom('subscriptions', yid).name()

			for dchan in await self.config.custom('subscriptions', yid).discord() or []:
				if not self.bot.get_channel(int(dchan)):
					await self.config.custom('subscriptions', yid, 'discord', dchan).clear()
					continue

			if not (dchans := await self.config.custom('subscriptions', yid).discord()):
				await self.config.custom('subscriptions', yid).clear()
				continue

			now = int(datetime.now().timestamp())
			if errorCount := await self.config.custom('subscriptions', yid).errorCount() or 0:
				lastTry = await self.config.custom('subscriptions', yid).lastTry()
				if errorCount in range(3, 9) and now - lastTry < 900 \
					or errorCount >= 9 and now - lastTry < 3600:
					continue

			bannediptime = await self.config.bannediptime() or 0
			if now - bannediptime < 900:
				continue

			try:
				feedData = await self.get_feed(yid)
			except ConnectionError:
				continue

			bannedipcount = await self.config.bannedipcount() or 0
			if isinstance(feedData, aiohttp.ClientResponse):
				if feedData.status == 403:
					bannedipcount += 1
					await self.config.bannedipcount.set(bannedipcount)
					await self.config.bannediptime.set(now)

					if bannedipcount == 1:
						await self.bot.send_to_owners("YouTube returned `403: Forbidden` error. Possible IP block, please review.")

					continue

				if errorCount >= 14 and now - lastTry < 86400:
					continue

				errorCount += 1
				await self.config.custom('subscriptions', yid).lastTry.set(now)
				await self.config.custom('subscriptions', yid).errorCount.set(errorCount)

				if errorCount >= 42:
					message = _("I'm giving up…") + "\n"
					message += _("The YouTube channel {ytName} has been gone for a while now.")
					message += " " + _("I'm deleting it from the configuration.")
					await self.send_guild_owner_messages(yid, message)
					await self.config.custom('subscriptions', yid).clear()
				elif errorCount >= 14 and errorCount%7 == 0 or errorCount == 41:
					message = _("I'm messaging you, as you are the owner of {guild}.") + "\n"
					message += _("You have previously subscribed to the YouTube channel {ytName} on your channel {channel}.")
					message += " " + _("Unfortunately this channel seems to have been removed from YouTube.")
					message += " " + _("Please feel free to verify this for yourself at {url}.") + "\n\n"
					message += _("To unsubscribe from this channel, please type `{prefix}youtube unsubscribe {yid}` somewhere __in your server__.")
					deletionDays = _("1 day") if errorCount == 41 else _("{days} days").format(days=42 - errorCount)
					message += " " + _("It will be automatically removed from the configuration in {days}.").format(days=bold(deletionDays))
					message += " " + _("If you do not take any action, I will inform you later again.")
					await self.send_guild_owner_messages(yid, message)
				continue

			if bannedipcount > 0:
				await self.config.bannediptime.clear()
				await self.config.bannedipcount.clear()
				await self.bot.send_to_owners("YouTube functionality restored: IP block has been lifted.")

			if errorCount >= 14:
				message = _("I'm messaging you, as you are the owner of {guild}.") + "\n"
				message += _("Remember when I said the YouTube channel {ytName} was unavailable at the time? Well, it's back now!")
				message += " "+ _("This means you can safely ignore my previous messages about this channel.") + "\n"
				message += _("Please feel free to verify this for yourself at {url}.")
				await self.send_guild_owner_messages(yid, message)

			if errorCount:
				await self.config.custom('subscriptions', yid).errorCount.clear()
				await self.config.custom('subscriptions', yid).lastTry.clear()

			feed = feedparser.parse(feedData)
			if name != feed['feed']['title']:
				for dchan in dchans:
					if not (oldname := await self.config.custom('subscriptions', yid, 'discord', dchan).oldname()):
						await self.config.custom('subscriptions', yid, 'discord', dchan).oldname.set(name)
					elif oldname == feed['feed']['title']:
						await self.config.custom('subscriptions', yid, 'discord', dchan).oldname.clear()
				await self.config.custom('subscriptions', yid).name.set(feed['feed']['title'])

			processed = await self.config.custom('subscriptions', yid).processed() or []
			processedOrig = processed.copy()
			upd = await self.config.custom('subscriptions', yid).updated()
			for entry in feed['entries'][:4][::-1]:
				published = datetime.strptime(entry['published'], YT_FORMAT)
				if published.timestamp() > upd and entry['yt_videoid'] not in processed:
					processed.insert(0, entry['yt_videoid'])
					for dchan in dchans:
						await self.send_message(entry, self.bot.get_channel(int(dchan)), dchans)

			if processed != processedOrig:
				await self.config.custom('subscriptions', yid).processed.set(processed[:6])
				await self.config.custom('subscriptions', yid).updated.set(int(published.timestamp()))

	async def send_guild_owner_messages(self, yid: str, message: str) -> NoReturn:
		for dchan in (dchans := await self.config.custom('subscriptions', yid).discord()):
			fullName = await self.config.custom('subscriptions', yid).name()
			if oldname := dchans.get(dchan).get('oldname'):
				fullName += f" \u27ea {oldname}"
			channel = self.bot.get_channel(int(dchan))
			prefixes = await self.bot.get_valid_prefixes(channel.guild)

			msg = _("Hello {owner}").format(owner=channel.guild.owner.mention) + "\n\n"
			msg += message.format(
					ytName = bold(fullName),
					guild = bold(channel.guild.name),
					channel = channel.mention,
					url = f"https://www.youtube.com/channel/{yid}",
					prefix = prefixes[0],
					yid = yid
				)
			msg += "\n\n" + _("Have a nice day!")
			with suppress(discord.Forbidden, discord.HTTPException):
				await channel.guild.owner.send(msg)

	async def send_message(self, entry: feedparser, channel: discord.TextChannel, dchans: dict) -> None:
		if not channel.permissions_for(channel.guild.me).send_messages:
			return

		dchan = str(channel.id)
		mentions = discord.AllowedMentions.none()
		if role := dchans.get(dchan).get('mention'):
			if role == channel.guild.id:
				role = channel.guild.default_role.name
				mentions = discord.AllowedMentions(everyone=True)
			elif role == "here":
				role = "@here"
				mentions = discord.AllowedMentions(everyone=True)
			else:
				role = f"<@&{role}>"
				mentions = discord.AllowedMentions(roles=True)

		if custom := dchans.get(dchan).get('message'):
			options = {
				'mention': role or bold(_("mention not set")),
				'author': entry['author'],
				'title': entry['title'],
				'published': datetime.strptime(entry['published'], YT_FORMAT),
				'updated': datetime.strptime(entry['updated'], YT_FORMAT),
				'summary': entry['summary']
			}
			custom = custom.format(**options)

		message = None
		if channel.permissions_for(channel.guild.me).embed_links and channel.permissions_for(channel.guild.me).attach_files and await self.config.channel(channel).embed():
			embed = discord.Embed()
			embed.colour = YT_COLOR
			embed.title = entry['title']
			embed.url = entry['link']
			embed.description = custom
			embed.set_author(name=entry['author'], url=entry['author_detail']['href'])
			embed.set_image(url=f"https://i.ytimg.com/vi/{entry['yt_videoid']}/hqdefault.jpg")
			embed.timestamp = datetime.strptime(entry['updated'], YT_FORMAT)
			icon = discord.File(bundled_data_path(self) / "youtube_social_icon_red.png", filename="youtube.png")
			embed.set_footer(text="YouTube", icon_url="attachment://youtube.png")
			with suppress(discord.DiscordServerError):
				message = await channel.send(role, file=icon, embed=embed, allowed_mentions=mentions)
		else:
			description = custom or _("New video from {author}: {title}").format(author=bold(entry['author']), title=bold(entry['title']))
			if role and dchans.get(dchan).get('message', "").find("{mention}") == -1:
				description = f"{role} {description}"
			with suppress(discord.DiscordServerError):
				message = await channel.send(content=f"{description}\nhttps://youtu.be/{entry['yt_videoid']}", allowed_mentions=mentions)

		if isinstance(message, discord.Message) and dchans.get(dchan).get('publish') and channel.is_news():
			with suppress(discord.HTTPException):
				await message.publish()

	@background_get_new_videos.before_loop
	async def background_get_new_videos_wait_for_red(self) -> NoReturn:
		await self.bot.wait_until_red_ready()
		interval = await self.config.interval()
		self.background_get_new_videos.change_interval(seconds=interval)

	@background_get_new_videos.error
	async def background_get_new_videos_error(self, error) -> NoReturn:
		log.error("Please report this error to https://github.com/Mister-42/mr42-cogs/issues", exc_info=error)

	async def get_feed(self, channel: str) -> Union[aiohttp.ClientResponse, bytes]:
		"""Fetch data from a feed."""
		async with aiohttp.ClientSession() as session:
			try:
				async with session.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel}") as response:
					if response.status == 200:
						return await response.read()
					return response
			except (aiohttp.ClientConnectorError, aiohttp.ClientConnectionError):
				raise ConnectionError

	async def get_youtube_channel(self, ctx: commands.Context, channelYouTube: str) -> Union[str, None]:
		"""Best effort to obtain YouTube Channel ID."""
		url = channelYouTube
		if match := re.compile("UC[-_A-Za-z0-9]{21}[AQgw]").fullmatch(channelYouTube):
			if await self.config.custom('subscriptions', match.string).discord():
				return match.string
			url = f"https://www.youtube.com/channel/{match.string}"

		if urlparse(url).hostname in {'youtu.be', 'youtube.com', 'www.youtube.com', 'music.youtube.com'}:
			options = {'extract_flat': False, 'playlist_items': '0'}
			with yt_dlp.YoutubeDL(options) as ydl, suppress(Exception):
				return ydl.extract_info(url, download=False).get('channel_id')

		await ctx.send(error(_("Unable to retrieve channel id from {channel}.").format(channel=bold(f"<{url}>"))))

	async def subscription_discord_options(self, ctx: discord.abc.Messageable, action: str, channelYouTube: str, data: Optional[str], channelDiscord: Optional[discord.TextChannel] = None) -> None:
		"""Store custom options for Discord channels."""
		if not (yid := await self.get_youtube_channel(ctx, channelYouTube)):
			return

		if action == 'message':
			actionName = _("Custom message")
		elif action == 'mention':
			actionName = _("Role mention")
		elif action == 'publish':
			actionName = _("Publishing")
		else:
			return await ctx.send(error(_("Unknown action: {action}").format(action=action)))

		updated = []
		if sub := await self.config.custom('subscriptions', yid).discord():
			channels = [channelDiscord] if channelDiscord else ctx.guild.channels
			for channel in [x for x in channels if str(x.id) in sub.keys()]:
				updated.append(channel.mention)
				if data:
					await getattr(self.config.custom('subscriptions', yid, 'discord', channel.id), action).set(data)
				elif sub.get(str(channel.id)).get(action):
					await self.config.custom('subscriptions', yid, 'discord', channel.id, action).clear()

		if not updated:
			return await ctx.send(error(_("Subscription not found.")))

		if ctx.command.qualified_name != 'youtube migrate':
			msg = _("{action} for {title} added to {list}.") if data else _("{action} for {title} removed from {list}.")
			feedTitle = await self.config.custom('subscriptions', yid).name()
			await ctx.send(success(msg.format(action=actionName, title=bold(feedTitle), list=humanize_list(updated))))

	async def red_delete_data_for_user(self, **kwargs) -> None:
		pass

	def cog_unload(self):
		self.background_get_new_videos.cancel()
