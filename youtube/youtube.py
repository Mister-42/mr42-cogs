import aiohttp
import asyncio
import contextlib
import discord
import feedparser
import logging
import pytube
import re

from datetime import datetime
from discord.ext import tasks
from typing import Literal, NoReturn, Optional, Union
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.data_manager import bundled_data_path
from redbot.core.i18n import Translator, cog_i18n
from redbot.core.utils.chat_formatting import bold, error, escape, humanize_list, humanize_timedelta, inline, pagify, success, text_to_file, warning
from redbot.core.utils.menus import start_adding_reactions
from redbot.core.utils.predicates import ReactionPredicate

_ = Translator("YouTube", __file__)
log = logging.getLogger("red.mr42-cogs.youtube")
RequestType = Literal["discord_deleted_user", "owner", "user", "user_strict"]
YT_COLOR = discord.Colour.from_rgb(255, 0, 0)
YT_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

@cog_i18n(_)
class YouTube(commands.Cog):
    """Subscribe to channels on YouTube."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=823288853745238067)
        self.config.register_global(interval=300)
        self.config.register_guild(maxpages=2)
        self.config.init_custom('subscriptions', 1)
        self.config.register_custom('subscriptions')
        self.background_get_new_videos.start()

    @commands.group(aliases=['yt'])
    async def youtube(self, ctx: commands.Context) -> NoReturn:
        """Post when new videos are published to a YouTube channel."""

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @youtube.command(aliases=['s', 'subscribe'])
    async def sub(self, ctx: commands.Context, channelYouTube: str, channelDiscord: Optional[discord.TextChannel] = None) -> None:
        """Subscribe a Discord channel to a YouTube channel.

        If no discord channel is specified, the current channel will be subscribed.

        Channels can be added by channel ID, channel URL, video URL, or playlist URL."""
        async with ctx.typing():
            yid = await self.get_youtube_channel(ctx, channelYouTube)
            if not yid:
                return await ctx.send(error(_("Your input {channel} is not valid.").format(channel=bold(channelYouTube))))

            channel = channelDiscord or ctx.channel
            if dchans := await self.config.custom('subscriptions', yid).discord():
                feedTitle = await self.config.custom('subscriptions', yid).name()
                if str(channel.id) in dchans.keys():
                    return await ctx.send(warning(_("{title} is already being announced in {channel}.").format(title=bold(f"{feedTitle}"), channel=channel.mention)))
                dchans.update({channel.id: {}})
                await self.config.custom('subscriptions', yid).discord.set(dchans)
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
            await ctx.send(success(_("YouTube channel {title} will now be announced in {channel} when new videos are published.").format(title=bold(feedTitle), channel=channel.mention)))

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @youtube.command(aliases=['u', 'unsubscribe'])
    async def unsub(self, ctx: commands.Context, channelYouTube: str, channelDiscord: Optional[discord.TextChannel] = None) -> None:
        """Unsubscribe a Discord channel from a YouTube channel.

        If no Discord channel is specified, the subscription will be removed from all channels"""
        async with ctx.typing():
            yid = await self.get_youtube_channel(ctx, channelYouTube)
            if not yid:
                return await ctx.send(error(_("Your input {channel} is not valid.").format(channel=bold(channelYouTube))))

            updated = []
            if dchans := await self.config.custom('subscriptions', yid).discord():
                feedTitle = await self.config.custom('subscriptions', yid).name()
                if not channelDiscord:
                    for channel in ctx.guild.channels:
                        if str(channel.id) in sorted(dchans.keys()):
                            dchans.pop(str(channel.id))
                            updated.append(channel.mention)
                elif str(channelDiscord.id) in dchans.keys():
                    dchans.pop(str(channelDiscord.id))
                    updated.append(channelDiscord.mention)

            if not updated:
                return await ctx.send(error(_("Subscription not found.")))

            if dchans.keys():
                await self.config.custom('subscriptions', yid).discord.set(dchans)
            else:
                await self.config.custom('subscriptions', yid).clear()

            await ctx.send(success(_("Unsubscribed from {title} on {list}.").format(title=bold(feedTitle), list=humanize_list(updated))))

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @youtube.command()
    async def list(self, ctx: commands.Context, channelDiscord: Optional[discord.TextChannel] = None) -> None:
        """List current subscriptions."""
        guildSubs = []
        subsByChannel = {}
        subCount = subCountYt = 0

        for yid in await self.config.custom('subscriptions').get_raw():
            dchans = await self.config.custom('subscriptions', yid).discord()

            channels = [channelDiscord] if channelDiscord else ctx.guild.channels
            if ctx.command.qualified_name == 'youtube listall':
                channels = [self.bot.get_channel(int(channel)) for channel in dchans.keys()]

            guildSub = False
            for channel in channels:
                if not channel:
                    continue
                subsByChannel[channel.id] = {}
                dchan = str(channel.id)
                if dchan in dchans.keys():
                    guildSub = True
                    subCount += 1
                    d = {'message': '\u1d9c', 'mention': '\u1d50', 'publish': '\u1d56'}
                    sub = self.config.custom('subscriptions', yid)
                    tags = ''.join(v for k, v in d.items() if k in dchans.get(dchan))
                    guildSubs.append({'name': await sub.name(), 'id': yid, 'updated': await sub.updated(), 'discord': channel, 'tags': tags})
            if guildSub:
                subCountYt += 1

        if not len(guildSubs):
            return await ctx.send(warning(_("No subscriptions yet - try adding some!")))

        for sub in sorted(guildSubs, key=lambda d: d['updated'], reverse=True):
            name = sub['name']
            if sub['tags']:
                name += f" {sub['tags']}"
            channel = sub['discord'].id
            subsByChannel[channel].update({sub['id']: {'updated': sub['updated'], 'name': name}})
        subsByChannel = {k:v for k,v in subsByChannel.items() if v}

        text = richText = ""
        if len(subsByChannel) > 1:
            text = _("{count} total subscriptions").format(count=subCount)
            if subCount != subCountYt:
                text = _("{count} total subscriptions over {yt} YouTube channels").format(count=subCount, yt=subCountYt)
            richText = bold(text)

        for sub, sub_ids in sorted(subsByChannel.items()):
            count = len(sub_ids)
            channel = self.bot.get_channel(sub)

            msg = _("{count} YouTube subscriptions for {channel}") if subCount > 1 else _("1 YouTube subscription for {channel}")
            text += "\n\n" + msg.format(count=count, channel=f"#{channel.name}")
            richText += "\n\n" + bold(msg.format(count=count, channel=channel.mention))
            if ctx.command.qualified_name == 'youtube listall':
                text += f" ({channel.guild.name})"
                richText += f" ({bold(channel.guild.name)})"

            for yid, data in sub_ids.items():
                info = f"{yid} {datetime.fromtimestamp(data['updated'])}"
                text += f"\n{info} {data['name']}"
                richText += f"\n{inline(info)} {escape(data['name'], formatting=True)}"

        pages = list(pagify(richText.strip()))
        if len(pages) > await self.config.guild(ctx.guild).maxpages():
            page = text_to_file(text.strip(), "subscriptions.txt")
            return await ctx.send(file=page)
        for page in pages:
            await ctx.send(page)

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @youtube.command(aliases=['c', 'customize'])
    async def custom(self, ctx: commands.Context, channelYouTube: str, message: str = False, channelDiscord: Optional[discord.TextChannel] = None) -> NoReturn:
        """Add a custom message for new videos from a YouTube channel.

        You can use keys in your custom message, surrounded by curly braces.
        E.g. `[p]youtube customize UCXuqSBlHAE6Xw-yeJA0Tunw "Linus from **{author}** is dropping things again!\\nCheck out their new video {title}" #video-updates`

        Valid options are: {author}, {title}, {published}, {updated} and {summary}.

        You can also remove customization by not specifying any message."""
        msg = message.replace("\\n", "\n")
        await self.subscription_discord_options(ctx, 'message', channelYouTube, msg, channelDiscord)

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @youtube.command(aliases=['m', 'rolemention'])
    async def mention(self, ctx: commands.Context, channelYouTube: str, mention: Optional[Union[discord.Role, str]], channelDiscord: Optional[discord.TextChannel] = None) -> NoReturn:
        """Add a role @mention in front of the message.

        You can also remove the mention by not specifying any role."""
        m = False
        if isinstance(mention, discord.Role):
            m = mention.id
        elif mention == "@here":
            m = "here"
        await self.subscription_discord_options(ctx, 'mention', channelYouTube, m, channelDiscord)

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @youtube.command(aliases=['p'])
    async def publish(self, ctx: commands.Context, channelYouTube: str, channelDiscord: Optional[discord.TextChannel] = None) -> None:
        """ Toggles publishing new messages to a Discord channel.

        This feature is only available on Community Servers."""
        if 'COMMUNITY' not in ctx.guild.features:
            return await ctx.send(error(_("This feature is only available on Community Servers.")))

        async with ctx.typing():
            yid = await self.get_youtube_channel(ctx, channelYouTube)
            if not yid:
                return await ctx.send(error(_("Your input {channel} is not valid.").format(channel=bold(channelYouTube))))

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

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @youtube.command()
    async def info(self, ctx: commands.Context, channelYouTube: str) -> None:
        """Provides information about a YouTube subscription."""
        async with ctx.typing():
            yid = await self.get_youtube_channel(ctx, channelYouTube)
            if not yid:
                return await ctx.send(error(_("Your input {channel} is not valid.").format(channel=bold(channelYouTube))))

            if dchans := await self.config.custom('subscriptions', yid).discord():
                sub = self.config.custom('subscriptions', yid)
                channels = ctx.guild.channels
                if ctx.command.qualified_name == 'youtube infoall':
                    channels = [self.bot.get_channel(int(channel)) for channel in dchans.keys()]

                info = []
                for channel in channels:
                    dchan = str(channel.id)
                    if dchan in dchans.keys():
                        title = channel.mention
                        if ctx.command.qualified_name == 'youtube infoall':
                            title += f" ({channel.guild})"
                        part = bold(title)

                        if message := dchans.get(dchan).get('message'):
                            part += "\n" + _("Custom: {message}").format(message=escape(message, formatting=True))

                        if m := dchans.get(dchan).get('mention'):
                            mention = f"<@&{m}>"
                            if m == ctx.guild.id:
                                mention = ctx.guild.default_role
                            elif m == "here":
                                mention = "@here"
                            part += "\n" + _("Mention: {mention}").format(mention=mention)

                        if dchans.get(dchan).get('publish'):
                            msg = _("Yes")
                            if not channel.is_news():
                                msg = _("Yes, but not an Announcement Channel")
                            part += "\n" + _("Publish: {message}").format(message=msg)

                        info.append(part)

                if not info:
                    return await ctx.send(error(_("Subscription not found.")))

                if ctx.channel.permissions_for(ctx.guild.me).embed_links:
                    embed = discord.Embed()
                    embed.colour = YT_COLOR
                    embed.title = _("Subscription information for {name}").format(name=await sub.name())
                    embed.url = f"https://www.youtube.com/channel/{yid}/"
                    embed.description = "\n\n".join(info)
                    embed.timestamp = datetime.fromtimestamp(await sub.updated())
                    icon = discord.File(bundled_data_path(self) / "youtube_social_icon_red.png", filename="youtube.png")
                    embed.set_footer(text=_("Latest video"), icon_url="attachment://youtube.png")
                    return await ctx.send(file=icon, embed=embed)
                msg = _("Subscription information for {name}").format(name=await sub.name())
                msg += "\n\n" + "\n\n".join(info)
                await ctx.send(msg)

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @youtube.command()
    async def maxpages(self, ctx: commands.Context, limit: Optional[int]) -> None:
        """Set the limit on amount of pages being sent.

        When the limit is reached, a text file will be sent instead, E.g. in `[p]youtube list`.

        Default is a maximum of 2 pages."""
        maxPages = limit or await self.config.guild(ctx.guild).maxpages()
        pages = _("{pages} pages").format(pages=maxPages)
        if maxPages == 1:
            pages = _("1 page")

        if limit is None:
            return await ctx.send(_("I am currently sending a maximum of {limit} before sending a file instead.").format(limit=bold(pages)))

        await self.config.guild(ctx.guild).maxpages.set(limit)
        await ctx.send(success(_("I will now send a file after reaching {limit}.").format(limit=bold(pages))))

    @checks.is_owner()
    @youtube.command()
    async def delete(self, ctx: commands.Context, channelYouTube: str) -> None:
        """Delete a YouTube channel from the configuration.

        This cog does not detect if channels are removed or taken down, as this cannot be done reliably.

        If you see your logs being filled with entries like the one below, there is a good chance the channel is no longer around.
        `[WARNING] red.mr42-cogs.youtube: Error 404 Not Found for channel UCXuqSBlHAE6Xw-yeJA0Tunw (Linus Tech Tips)`

        You can delete such subscriptions with `[p]youtube delete UCXuqSBlHAE6Xw-yeJA0Tunw`."""
        yid = await self.get_youtube_channel(ctx, channelYouTube)
        if not yid:
            return await ctx.send(error(_("Your input {channel} is not valid.").format(channel=bold(channelYouTube))))

        channel = self.config.custom('subscriptions', yid)
        name = await channel.name()
        if not name:
            return await ctx.send(error(_("Subscription not found.")))

        dchans = []
        for g in await channel.discord():
            dchan = self.bot.get_channel(int(g))
            if not dchan:
                continue
            dchans.append(f"{dchan.mention} ({dchan.guild})")

        prompt = (_("You are about to remove {channel} from the configuration.").format(channel=bold(name))
            + " " + _("It is subsribed to by {channels}.").format(channels=humanize_list(dchans))
            + "\n" + _("Do you want to continue?")
        )
        query: discord.Message = await ctx.send(prompt)
        start_adding_reactions(query, ReactionPredicate.YES_OR_NO_EMOJIS)
        pred = ReactionPredicate.yes_or_no(query, ctx.author)

        try:
            await ctx.bot.wait_for("reaction_add", check=pred, timeout=30)
        except asyncio.TimeoutError:
            with contextlib.suppress(discord.NotFound):
                await query.delete()

        if not pred.result:
            with contextlib.suppress(discord.NotFound):
                await query.delete()
            return await ctx.send(_("{channel} has not been deleted.").format(channel=bold(name)))
        else:
            with contextlib.suppress(discord.Forbidden):
                await query.clear_reactions()
            await self.config.custom('subscriptions', yid).clear()
            await ctx.send(success(_("{channel} has been removed from the configuration.").format(channel=bold(name))))

    @checks.is_owner()
    @youtube.command()
    async def infoall(self, ctx: commands.Context, channelYouTube: str) -> None:
        """Provides information about a YouTube subscription across servers."""
        await self.info(ctx, channelYouTube)

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
    @youtube.command()
    async def listall(self, ctx: commands.Context) -> None:
        """List current subscriptions across servers."""
        await self.list(ctx)

    @checks.is_owner()
    @youtube.command()
    async def test(self, ctx: commands.Context, channelYouTube: Optional[str]) -> None:
        """Send a test message to the current channel."""
        yid = 'UCBR8-60-B28hp2BmDPdntcQ'
        if channelYouTube is not None:
            yid = await self.get_youtube_channel(ctx, channelYouTube)
            if not yid:
                return await ctx.send(error(_("Your input {channel} is not valid.").format(channel=bold(channelYouTube))))

        ytFeedData = await self.get_feed(yid)
        ytFeed = feedparser.parse(ytFeedData)
        dchans = {str(ctx.channel.id): {'mention': ctx.guild.id, 'message': f"This is a test message from the YouTube cog, as requested by <@{ctx.author.id}>.\n**Sorry for pinging @everyone.** I don't do this by default for normal new videos, just for this test. *Or* when explicitly requested."}}

        for entry in ytFeed['entries'][:1][::-1]:
            await self.send_message(entry, ctx.channel, dchans)

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

        prompt = (_("You are about to import **{channels} YouTube subscriptions**.").format(channels=channels)
            + " " + _("Depending on the internet speed of the server, this might take a while.")
            + "\n" + _("Do you want to continue?")
        )
        query: discord.Message = await ctx.send(prompt)
        start_adding_reactions(query, ReactionPredicate.YES_OR_NO_EMOJIS)
        pred = ReactionPredicate.yes_or_no(query, ctx.author)

        try:
            await ctx.bot.wait_for("reaction_add", check=pred, timeout=30)
        except asyncio.TimeoutError:
            with contextlib.suppress(discord.NotFound):
                await query.delete()

        if not pred.result:
            with contextlib.suppress(discord.NotFound):
                await query.delete()
            return await ctx.send(_("Migration has been cancelled."))
        else:
            with contextlib.suppress(discord.Forbidden):
                await query.clear_reactions()
            await ctx.send(_("Migration started…"))
            async with ctx.typing():
                for g in self.bot.guilds:
                    guild = self.bot.get_guild(g.id)
                    count = 0
                    for data in await TubeConfig.guild(guild).subscriptions():
                        yid = data.get('id')
                        channel = self.bot.get_channel(int(data.get('channel').get('id')))

                        await self.sub(ctx, yid, channel)

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

                    if count > 1:
                        await ctx.send(_("Imported {count} subscriptions for {guild}.").format(count=count, guild=g.name))
                    else:
                        await ctx.send(_("Imported 1 subscription for {guild}.").format(guild=g.name))
            if 'Tube' in ctx.bot.extensions:
                prompt = (_("Running the `Tube` cog alongside this cog *will* get spammy. Do you want to unload `Tube`?"))
                query: discord.Message = await ctx.send(prompt)
                start_adding_reactions(query, ReactionPredicate.YES_OR_NO_EMOJIS)
                pred = ReactionPredicate.yes_or_no(query, ctx.author)

                try:
                    await ctx.bot.wait_for("reaction_add", check=pred, timeout=30)
                except asyncio.TimeoutError:
                    with contextlib.suppress(discord.NotFound):
                        await query.delete()

                if not pred.result:
                    with contextlib.suppress(discord.NotFound):
                        await query.delete()
                else:
                    with contextlib.suppress(discord.Forbidden):
                        await query.clear_reactions()
                    ctx.bot.unload_extension('Tube')
            await ctx.send(success(_("Migration completed!")))

    @tasks.loop(minutes=1)
    async def background_get_new_videos(self) -> None:
        for yid in await self.config.custom('subscriptions').get_raw():
            sub = self.config.custom('subscriptions', yid)

            now = int(datetime.now().timestamp())
            errorCount = await sub.errorCount() or 0
            if errorCount := await sub.errorCount() or 0:
                lastTry = await sub.lastTry()
                if errorCount in range(3, 7) and now - lastTry < 900:
                    continue
                if errorCount in range(7, 29) and now - lastTry < 3600:
                    continue
                if errorCount >= 30 and now - lastTry < 86400:
                    continue

            try:
                feedData = await self.get_feed(yid)
            except ConnectionError:
                continue

            dchans = await sub.discord()
            if isinstance(feedData, aiohttp.ClientResponse):
                errorCount += 1
                await sub.errorCount.set(errorCount)
                await sub.lastTry.set(now)

                if errorCount >= 30:
                    for dchan in list(dchans):
                        channel = self.bot.get_channel(int(dchan))
                        prefixes = await self.bot.get_valid_prefixes(channel.guild)

                        message = _("Hello {name}").format(name=bold(channel.guild.owner.nick))
                        message += "\n\n"
                        message += _("I'm messaging you, as you are the owner of {guild}.").format(guild=bold(channel.guild.name))
                        message += "\n"
                        message += _("You have previously subscribed to the YouTube channel {ytName} on your channel {channel}.").format(ytName=bold(await sub.name()), channel=channel.mention)
                        message += " "
                        message += _("Unfortunately this channel seems to have been removed from YouTube.")
                        message += " "
                        message += _("Please feel free to verify this for yourself on https://www.youtube.com/channel/{yid}.").format(yid=yid)
                        message += "\n\n"
                        message += _("To unsubscribe from this channel, please type `{prefix}youtube unsubscribe {yid}` somewhere __in your server__.").format(prefix=prefixes[0], yid=yid)
                        message += " "
                        message += _("If you do not take any action and the YouTube channel remains unavailable, I will inform you later again.")
                        message += "\n\n"
                        message += _("Have a nice day!")
                        await channel.guild.owner.send(message)
                continue

            if errorCount:
                await sub.errorCount.clear()
                await sub.lastTry.clear()

            feed = feedparser.parse(feedData)
            name = feed['feed']['title']
            if name != await sub.name():
                await sub.name.set(name)

            processed = await sub.processed() or []
            processedOrig = processed.copy()
            upd = await sub.updated()
            for entry in feed['entries'][:4][::-1]:
                published = datetime.strptime(entry['published'], YT_FORMAT)
                updated = datetime.strptime(entry['updated'], YT_FORMAT)

                if updated.timestamp() > upd and entry['yt_videoid'] not in processed:
                    processed = [entry['yt_videoid']] + processed
                    for dchan in list(dchans):
                        channel = self.bot.get_channel(int(dchan))
                        if not channel:
                            dchans.pop(dchan)
                            await sub.discord.set(dchans)
                            log.warning(f"Removed invalid channel {dchan} for subscription {yid} ({name})")
                            continue

                        if not channel.permissions_for(channel.guild.me).send_messages:
                            log.warning(f"Not allowed to post messages to {channel} ({channel.guild.name})")
                            continue

                        await self.send_message(entry, channel, dchans)

            if processed != processedOrig:
                await sub.updated.set(int(published.timestamp()))
                await sub.processed.set(processed[:6])

            if not dchans.keys():
                await sub.clear()
                log.warning(f"Removed subscription {yid} ({name}): no subscribed channels left")

    async def send_message(self, entry: feedparser, channel: discord.TextChannel, dchans: dict) -> None:
        dchan = str(channel.id)
        if custom := dchans.get(dchan).get('message'):
            options = {
                'author': entry['author'],
                'title': entry['title'],
                'published': datetime.strptime(entry['published'], YT_FORMAT),
                'updated': datetime.strptime(entry['updated'], YT_FORMAT),
                'summary': entry['summary'],
            }
            custom = custom.format(**options)

        mentions = discord.AllowedMentions()
        if role := dchans.get(dchan).get('mention'):
            if role == channel.guild.id:
                role = channel.guild.default_role
                mentions = discord.AllowedMentions(everyone=True)
            elif role == "here":
                role = "@here"
                mentions = discord.AllowedMentions(everyone=True)
            else:
                role = f"<@&{role}>"
                mentions = discord.AllowedMentions(roles=True)

        if channel.permissions_for(channel.guild.me).embed_links:
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
            if role:
                description = f"{role} {description}"
            message = await channel.send(content=f"{description} https://youtu.be/{entry['yt_videoid']}", allowed_mentions=mentions)

        if dchans.get(dchan).get('publish'):
            if channel.is_news():
                with contextlib.suppress(discord.HTTPException):
                    await message.publish()
            else:
                log.warning(f"Can't publish, not a news channel: {channel.id} ({channel.guild.name})")

    @background_get_new_videos.before_loop
    async def wait_for_red(self) -> NoReturn:
        await self.bot.wait_until_red_ready()
        interval = await self.config.interval()
        self.background_get_new_videos.change_interval(seconds=interval)

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
        try:
            return pytube.Channel(url).channel_id
        except Exception:
            pass

        # URL is a video?
        try:
            return pytube.YouTube(url).channel_id
        except Exception:
            pass

        # URL is a playlist?
        try:
            return pytube.Playlist(url).owner_id
        except Exception:
            pass

    async def subscription_discord_options(self, ctx: commands.Context, action: str, channelYouTube: str, data: Optional, channelDiscord: Optional[discord.TextChannel] = None) -> None:
        """Store custom options for Discord channels."""
        yid = await self.get_youtube_channel(ctx, channelYouTube)
        if not yid:
            return await ctx.send(error(_("Your input {channel} is not valid.").format(channel=bold(channelYouTube))))

        if data == "":
            data = None

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
            feedTitle = await self.config.custom('subscriptions', yid).name()
            if not channelDiscord:
                for channel in ctx.guild.channels:
                    if str(channel.id) in sub.keys():
                        updated.append(channel)
                        dchan = str(channel.id)
                        if data:
                            sub.get(dchan).update({action: data})
                        elif sub.get(dchan).get(action):
                            sub.get(dchan).pop(action)
                        await self.config.custom('subscriptions', yid).discord.set(sub)
            elif str(channelDiscord.id) in sub.keys():
                updated.append(channelDiscord)
                dchan = str(channelDiscord.id)
                if data:
                    sub.get(dchan).update({action: data})
                elif sub.get(dchan).get(action):
                    sub.get(dchan).pop(action)
                await self.config.custom('subscriptions', yid).discord.set(sub)

        if not updated:
            return await ctx.send(error(_("Subscription not found.")))

        if ctx.command.qualified_name != 'youtube migrate':
            channels = [update.mention for update in updated]
            msg = _("{action} for {title} removed from {list}.")
            if data:
                msg = _("{action} for {title} added to {list}.")
            await ctx.send(success(msg.format(action=actionName, title=bold(feedTitle), list=humanize_list(channels))))

    async def red_delete_data_for_user(self, *, requester: RequestType, user_id: int) -> None:
        pass

    def cog_unload(self):
        self.background_get_new_videos.cancel()
