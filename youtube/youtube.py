import aiohttp
import asyncio
import discord
import feedparser
import logging
import pytube
import re

from contextlib import suppress
from datetime import datetime
from discord.ext import tasks
from typing import Literal, NoReturn, Optional, Union
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.data_manager import bundled_data_path
from redbot.core.i18n import Translator, cog_i18n
from redbot.core.utils.chat_formatting import bold, error, escape, humanize_list, humanize_timedelta, inline, pagify, question, success, text_to_file, warning
from redbot.core.utils.views import ConfirmView
from string import Formatter

_ = Translator("YouTube", __file__)
log = logging.getLogger("red.mr42-cogs.youtube")
RequestType = Literal["discord_deleted_user", "owner", "user", "user_strict"]
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
				if str(channel.id) in dchans.keys():
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
					for channel in ctx.guild.channels:
						if str(channel.id) in sorted(dchans.keys()):
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
						info += " \u2016 " + _("{count} errors").format(count=errorCount)

					if channel.id not in subsByChannel:
						subsByChannel[channel.id] = {}
					subsByChannel[channel.id].update({yid: {'updated': await self.config.custom('subscriptions', yid).updated(), 'info': info}})
					subsYt.append(yid)

		if not len(subsByChannel):
			return await ctx.send(warning(_("No subscriptions yet - try adding some!")))

		text = richText = ""
		subCount = len(set(subsYt))
		subCountYt = sum(len(v) for v in subsByChannel.values())
		if len(subsByChannel) > 1:
			text = _("{count} total subscriptions").format(count=subCount)
			if subCount != subCountYt:
				text = _("{count} total subscriptions over {yt} YouTube channels").format(count=subCount, yt=subCountYt)
			richText = bold(text)

		for sub, sub_ids in sorted(subsByChannel.items()):
			count = len(sub_ids)
			channel = self.bot.get_channel(sub)

			msg = "\n\n" + _("{count} YouTube subscriptions for {channel}") if subCount > 1 else _("1 YouTube subscription for {channel}")
			text += msg.format(count=count, channel=f"#{channel.name}")
			richText += msg.format(count=count, channel=channel.mention)
			if ctx.command.qualified_name == 'youtube listall':
				text += f" ({channel.guild.name})"
				richText += f" ({bold(channel.guild.name)})"

			for yid, data in sub_ids.items():
				ytinfo = f"{yid} {datetime.fromtimestamp(data['updated'])}"
				text += f"\n{ytinfo} {data['info']}"
				richText += f"\n{inline(ytinfo)} {escape(data['info'], formatting=True)}"

		pages = list(pagify(richText.strip()))
		if isinstance(ctx.channel, discord.DMChannel) or len(pages) > await self.config.guild(ctx.guild).maxpages():
			if not isinstance(ctx.channel, discord.DMChannel) and not ctx.channel.permissions_for(ctx.guild.me).attach_files:
				return await ctx.send(error("I do not have permission to attach files in this channel."))
			page = text_to_file(text.strip(), "subscriptions.txt")
			return await ctx.send(file=page)
		for page in pages:
			await ctx.send(page)

	@checks.admin_or_permissions(manage_guild=True)
	@commands.guild_only()
	@youtube.command(aliases=['c', 'customize'])
	async def custom(self, ctx: commands.Context, channelYouTube: str, message: str = "", channelDiscord: Optional[discord.TextChannel] = None) -> NoReturn:
		"""Add a custom message for new videos from a YouTube channel.

		You can use keys in your custom message, surrounded by curly braces.
		E.g. `[p]youtube customize UCXuqSBlHAE6Xw-yeJA0Tunw "Linus from **{author}** is dropping things again!\\nCheck out their new video {title}" #video-updates`

		Valid options are: {mention}, {author}, {title}, {published}, {updated} and {summary}.

		You can also remove customization by not specifying any message."""
		options = {'mention', 'author', 'title', 'published', 'updated', 'summary'}
		fail = []
		for x in [i[1] for i in Formatter().parse(message) if i[1] is not None and i[1] not in options]:
			fail.append(inline(x))
		if fail:
			return await ctx.send(error(_("You are not allowed to use {key} in the message.").format(key=humanize_list(fail))))
		msg = message.replace("\\n", "\n").strip()
		await self.subscription_discord_options(ctx, 'message', channelYouTube, msg, channelDiscord)

	@checks.admin_or_permissions(manage_guild=True)
	@commands.guild_only()
	@youtube.command(aliases=['m', 'rolemention'])
	async def mention(self, ctx: commands.Context, channelYouTube: str, mention: Optional[Union[discord.Role, str]], channelDiscord: Optional[discord.TextChannel] = None) -> NoReturn:
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
		if embed := await self.config.channel(channelDiscord).embed():
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
								mention = ctx.guild.default_role
							elif m == "here":
								mention = "@here"
							part += f"\n{spacer}- {bold(_('Mention'))}: {mention}"

						if dchans.get(dchan).get('publish'):
							publish = _("Yes")
							if not channel.is_news():
								publish = _("Yes, but not an Announcement Channel")
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
		"""Set the limit on amount of pages being sent.

		When the limit is reached, a text file will be sent instead, E.g. in `[p]youtube list`.

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
				for channel in channels:
					if str(channel.id) in dchans.keys():
						if not channel.is_news():
							notNews.append(channel.mention)
							continue
						dchan = str(channel.id)
						publish = not dchans.get(dchan).get('publish')
						await self.subscription_discord_options(ctx, 'publish', yid, publish, channel)

		if notNews:
			msg = _("The channels {list} are not Announcement Channels.")
			if len(notNews) == 1:
				msg = _("The channel {list} is not an Announcement Channel.")
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
	async def infoall(self, ctx: commands.Context, channelYouTube: str) -> None:
		"""Provides information about a YouTube subscription across servers."""
		await self.info(ctx, channelYouTube)

	@checks.is_owner()
	@youtube.command()
	async def listall(self, ctx: commands.Context) -> None:
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
			for x in await TubeConfig.guild(guild).subscriptions():
				channels += 1

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
						await self.subscription_discord_options(ctx, 'message', yid, message, channel)

					if data.get('mention'):
						await self.subscription_discord_options(ctx, 'mention', yid, data.get('mention'), channel)

					if data.get('publish'):
						await self.subscription_discord_options(ctx, 'publish', yid, channel)
					count += 1

				msg = _("Imported 1 subscription for {guild}.")
				if count > 1:
					msg = _("Imported {count} subscriptions for {guild}.")
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

	@tasks.loop(minutes=1)
	async def background_get_new_videos(self) -> None:
		for yid in await self.config.custom('subscriptions').get_raw():
			name = await self.config.custom('subscriptions', yid).name()

			for dchan in await self.config.custom('subscriptions', yid).discord():
				if not self.bot.get_channel(int(dchan)):
					await self.config.custom('subscriptions', yid, 'discord', dchan).clear()
					log.info(f"Removed invalid channel {dchan} for subscription {yid} ({name})")
					continue

			if not (dchans := await self.config.custom('subscriptions', yid).discord()):
				await self.config.custom('subscriptions', yid).clear()
				log.info(f"Removed subscription {yid} ({name}): no subscribed channels left")
				continue

			now = int(datetime.now().timestamp())
			if errorCount := await self.config.custom('subscriptions', yid).errorCount() or 0:
				lastTry = await self.config.custom('subscriptions', yid).lastTry()
				if errorCount in range(3, 9) and now - lastTry < 900 \
					or errorCount >= 9 and now - lastTry < 3600:
					continue

			try:
				feedData = await self.get_feed(yid)
			except ConnectionError:
				continue

			if isinstance(feedData, aiohttp.ClientResponse):
				if errorCount >= 14 and now - lastTry < 86400:
					continue
				errorCount += 1
				await self.config.custom('subscriptions', yid).lastTry.set(now)
				await self.config.custom('subscriptions', yid).errorCount.set(errorCount)

				if errorCount >= 42:
					for dchan in dchans:
						fullName = name
						if oldname := dchans.get(dchan).get('oldname'):
							fullName += f" \u27ea {oldname}"
						channel = self.bot.get_channel(int(dchan))

						message = _("Hello {owner}").format(owner=channel.guild.owner.mention) + "\n\n"
						message += _("I'm giving up…") + "\n"
						message += _("The YouTube channel {ytName} has been gone for a while now.").format(ytName=bold(fullName))
						message += " " + _("I'm deleting it from the configuration.") + "\n\n"
						message += _("Have a nice day!")
						with suppress(discord.Forbidden, discord.HTTPException):
							await channel.guild.owner.send(message)
					await self.config.custom('subscriptions', yid).clear()
					log.info(f"Removed subscription {yid} ({name})")
				elif errorCount >= 14 and errorCount%7 == 0 or errorCount == 41:
					for dchan in dchans:
						fullName = name
						if oldname := dchans.get(dchan).get('oldname'):
							fullName += f" \u27ea {oldname}"
						channel = self.bot.get_channel(int(dchan))
						prefixes = await self.bot.get_valid_prefixes(channel.guild)

						message = _("Hello {owner}").format(owner=channel.guild.owner.mention) + "\n\n"
						message += _("I'm messaging you, as you are the owner of {guild}.").format(guild=bold(channel.guild.name)) + "\n"
						message += _("You have previously subscribed to the YouTube channel {ytName} on your channel {channel}.").format(ytName=bold(fullName), channel=channel.mention)
						message += " " + _("Unfortunately this channel seems to have been removed from YouTube.")
						message += " " + _("Please feel free to verify this for yourself on {url}.").format(url=f"https://www.youtube.com/channel/{yid}") + "\n\n"
						message += _("To unsubscribe from this channel, please type `{prefix}youtube unsubscribe {yid}` somewhere __in your server__.").format(prefix=prefixes[0], yid=yid)
						deletionDays = _("1 day") if errorCount == 41 else _("{days} days").format(days=42 - errorCount)
						message += " " + _("It will be automatically removed from the configuration in {days}.").format(days=bold(deletionDays))
						message += " " + _("If you do not take any action, I will inform you later again.") + "\n\n"
						message += _("Have a nice day!")
						try:
							await channel.guild.owner.send(message)
						except (discord.Forbidden, discord.HTTPException):
							log.warning(f"Error {feedData.status} {feedData.reason} for channel {yid} ({name}), {channel.guild.owner.name} could not be notified")
				continue

			if errorCount > 30:
				for dchan in dchans:
					fullName = name
					if oldname := dchans.get(dchan).get('oldname'):
						fullName += f" \u27ea {oldname}"
					channel = self.bot.get_channel(int(dchan))
					prefixes = await self.bot.get_valid_prefixes(channel.guild)

					message = _("Hello {owner}").format(owner=channel.guild.owner.mention) + "\n\n"
					message += _("I'm messaging you, as you are the owner of {guild}.").format(guild=bold(channel.guild.name)) + "\n"
					message += _("Remember when I said the YouTube channel {ytName} was unavailable at the time? Well, it's back now!").format(ytName=bold(fullName))
					message += " "+ _("This means you can safely ignore my previous messages about this channel.") + "\n"
					message += _("Please feel free to verify this for yourself on {url}.").format(url=f"https://www.youtube.com/channel/{yid}") + "\n\n"
					message += _("Have a nice day!")
					with suppress(discord.Forbidden, discord.HTTPException):
						await channel.guild.owner.send(message)

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
						channel = self.bot.get_channel(int(dchan))
						if not channel.permissions_for(channel.guild.me).send_messages:
							log.warning(f"Not allowed to post messages to #{channel} ({channel.guild.name})")
							continue
						await self.send_message(entry, channel, dchans)

			if processed != processedOrig:
				await self.config.custom('subscriptions', yid).processed.set(processed[:6])
				await self.config.custom('subscriptions', yid).updated.set(int(published.timestamp()))

	async def send_message(self, entry: feedparser, channel: discord.TextChannel, dchans: dict) -> None:
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
			message = await channel.send(role, file=icon, embed=embed, allowed_mentions=mentions)
		else:
			description = custom or _("New video from {author}: {title}").format(author=bold(entry['author']), title=bold(entry['title']))
			if role and dchans.get(dchan).get('message', "").find("{mention}") == -1:
				description = f"{role} {description}"
			message = await channel.send(content=f"{description}\nhttps://youtu.be/{entry['yt_videoid']}", allowed_mentions=mentions)

		if dchans.get(dchan).get('publish'):
			if not channel.is_news():
				return log.warning(f"Can't publish, not a news channel: {channel.id} ({channel.guild.name})")
			with suppress(discord.HTTPException):
				await message.publish()

	@background_get_new_videos.before_loop
	async def background_get_new_videos_wait_for_red(self) -> NoReturn:
		await self.bot.wait_until_red_ready()
		interval = await self.config.interval()
		self.background_get_new_videos.change_interval(seconds=interval)

	@background_get_new_videos.error
	async def background_get_new_videos_error(self, error) -> NoReturn:
		log.error("FATAL ERROR!", exc_info=error)

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

		# URL is a channel?
		with suppress(Exception):
			return pytube.Channel(url).channel_id

		# URL is a video?
		with suppress(Exception):
			return pytube.YouTube(url).channel_id

		# URL is a playlist?
		with suppress(Exception):
			return pytube.Playlist(url).owner_id

		msg = _("Unable to retrieve channel id from {channel}.").format(channel=bold(channelYouTube)) + "\n"
		msg += _("If you're certain your input is correct, it might be a bug in {pytube}.").format(pytube=inline("pytube"))
		msg += " " + _("In that case, please visit {url} to file a bug report.").format(url="<https://github.com/pytube/pytube>")
		await ctx.send(error(msg))

	async def subscription_discord_options(self, ctx: commands.Context, action: str, channelYouTube: str, data: Optional[str], channelDiscord: Optional[discord.TextChannel] = None) -> None:
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
			for channel in channels:
				if str(channel.id) in sub.keys():
					updated.append(channel.mention)
					if data:
						obj = getattr(self.config.custom('subscriptions', yid, 'discord', channel.id), action)
						await obj.set(data)
					elif sub.get(str(channel.id)).get(action):
						await self.config.custom('subscriptions', yid, 'discord', channel.id, action).clear()

		if not updated:
			return await ctx.send(error(_("Subscription not found.")))

		if ctx.command.qualified_name != 'youtube migrate':
			msg = _("{action} for {title} removed from {list}.")
			if data:
				msg = _("{action} for {title} added to {list}.")
			feedTitle = await self.config.custom('subscriptions', yid).name()
			await ctx.send(success(msg.format(action=actionName, title=bold(feedTitle), list=humanize_list(updated))))

	async def red_delete_data_for_user(self, *, requester: RequestType, user_id: int) -> None:
		pass

	def cog_unload(self):
		self.background_get_new_videos.cancel()
