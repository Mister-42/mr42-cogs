import aiohttp
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
from redbot.core.utils.chat_formatting import bold, error, escape, humanize_list, humanize_timedelta, inline, pagify, text_to_file, warning, success
from redbot.core.utils.predicates import MessagePredicate

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

        sub = {'yid': {"name": "YouTube", "updated": 0, "processed": [], "discord": {"dchan": {'message': None, "mention": None, "publish": False}}}}
        self.config.init_custom('subscriptions', 1)
        self.config.register_custom('subscriptions', **sub)
        self.background_get_new_videos.start()

    async def cog_load(self):
        await self.upgrade_db()

    @commands.group(aliases=['yt'])
    async def youtube(self, ctx: commands.Context) -> NoReturn:
        """Post when new videos are published to a YouTube channel."""

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @youtube.command(aliases=['s', 'subscribe'])
    async def sub(self, ctx: commands.Context, channelYouTube: str, channelDiscord: Optional[discord.TextChannel] = None) -> None:
        """Subscribe a Discord channel to a YouTube channel.

        If no discord channel is specified, the current channel will be subscribed.

        Channels can be added by channel ID, channel URL, video URL, or playlist URL.
        """
        async with ctx.typing():
            yid = await self.get_youtube_channel(ctx, channelYouTube)
            if not yid:
                return

            channel = channelDiscord or ctx.channel
            if dchans := await self.config.custom('subscriptions', yid).discord():
                # YouTube channel already exists in config
                if str(channel.id) in dchans.keys():
                    # Already subsribed, do nothing!
                    return await ctx.send(warning(_("This subscription already exists!")))

                # Adding Discord channel to existing YouTube subscription
                dchans.update({channel.id: {}})
                await self.config.custom('subscriptions', yid).discord.set(dchans)
                feedTitle = await self.config.custom('subscriptions', yid).name()
            else:
                # YouTube channel does not exist in config
                feed = feedparser.parse(await self.get_feed(yid))
                try:
                    feedTitle = feed['feed']['title']
                except KeyError:
                    return await ctx.send(error(_("Error getting channel feed. Make sure the input is correct.")))

                processed = [entry['yt_videoid'] for entry in feed['entries'][:6]]
                try:
                    updated = int(datetime.strptime(feed['entries'][0]['published'], YT_FORMAT).timestamp())
                except IndexError:
                    # No videos are published on the YouTube channel
                    updated = int(datetime.strptime(feed['feed']['published'], YT_FORMAT).timestamp())

                newChannel = {
                    'name': feedTitle,
                    'updated': updated,
                    'processed': processed,
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
                return

            updated = []
            if sub := await self.config.custom('subscriptions', yid).discord():
                # YouTube channel exists in config
                feedTitle = await self.config.custom('subscriptions', yid).name()
                if not channelDiscord:
                    for channel in ctx.guild.channels:
                        if str(channel.id) in sub.keys():
                            sub.pop(str(channel.id))
                            updated.append(channel.mention)
                elif str(channelDiscord.id) in sub.keys():
                    sub.pop(str(channelDiscord.id))
                    updated.append(channelDiscord.mention)

                if sub.keys():
                    await self.config.custom('subscriptions', yid).discord.set(sub)
                else:
                    await self.config.custom('subscriptions', yid).clear()

            if not updated:
                return await ctx.send(error(_("Subscription not found.")))
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
                subsByChannel[channel.id] = []
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
            channel = sub['discord'].id
            p1 = f"{sub['id']} {datetime.fromtimestamp(sub.get('updated'))}"
            p2 = escape(sub.get('name')[:50], formatting=True)
            if sub['tags']:
                p2 += f" {sub['tags']}"
            subsByChannel[channel].append(f"{p1} {p2}" if subCount > 50 else f"{inline(p1)} {p2}")
        subsByChannel = {k:v for k,v in subsByChannel.items() if v != []}

        text = richText = ""
        subsByChannelSorted = dict(sorted(subsByChannel.items()))
        if len(subsByChannel) > 1:
            text = _("{count} total subscriptions").format(count=subCount)
            if subCount != subCountYt:
                text = _("{count} total subscriptions over {yt} YouTube channels").format(count=subCount, yt=subCountYt)
            richText = bold(text)

        for sub, sub_ids in subsByChannelSorted.items():
            count = len(sub_ids)
            channel = self.bot.get_channel(sub)

            msg = _("{count} YouTube subscriptions for {channel}") if subCount > 1 else _("1 YouTube subscription for {channel}")
            title = msg.format(count=count, channel=f"#{channel.name}")
            richTitle = msg.format(count=count, channel=channel.mention)
            guild = f" ({channel.guild})" if ctx.command.qualified_name == 'youtube listall' else ""
            text += "\n\n" + title + guild
            richText += "\n\n" + bold(richTitle + guild)

            for s in sub_ids:
                text += f"\n{s}"
                richText += f"\n{s}"

        if subCount > 50:
            page = text_to_file(text.strip(), "subscriptions.txt")
            return await ctx.send(file=page)
        for page in pagify(richText):
            await ctx.send(page)

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @youtube.command(aliases=['c', 'customize'])
    async def custom(self, ctx: commands.Context, channelYouTube: str, message: str = False, channelDiscord: Optional[discord.TextChannel] = None) -> NoReturn:
        """ Add a custom message for new videos from a YouTube channel.

        You can use keys in your custom message, surrounded by curly braces, e.g.:
        [p]youtube customize UCXuqSBlHAE6Xw-yeJA0Tunw "Linus from {author} is dropping things again!\\nCheck out their new video {title}" #video-updates

        Valid options are: {author}, {title}, {published}, {updated} and {summary}.

        You can also remove customization by not specifying any message.
        """
        await self.subscription_discord_options(ctx, 'message', channelYouTube, message, channelDiscord)

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @youtube.command(aliases=['m', 'rolemention'])
    async def mention(self, ctx: commands.Context, channelYouTube: str, mention: Optional[discord.Role], channelDiscord: Optional[discord.TextChannel] = None) -> NoReturn:
        """ Add a role @mention in front of the message.

        Works for `@everyone` or any role. `@here` is not supported.

        You can also remove the mention by not specifying any role.
        """
        m = mention.id if mention else False
        await self.subscription_discord_options(ctx, 'mention', channelYouTube, m, channelDiscord)

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @youtube.command(aliases=['p'])
    async def publish(self, ctx: commands.Context, channelYouTube: str, channelDiscord: Optional[discord.TextChannel] = None) -> None:
        """ Toggles publishing new messages to a Discord channel.

        This feature is only available on Community Servers.
        """
        if 'COMMUNITY' not in ctx.guild.features:
            return await ctx.send(error(_("This function is only available on Community Servers.")))

        async with ctx.typing():
            yid = await self.get_youtube_channel(ctx, channelYouTube)
            if not yid:
                return

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
                return

            if dchans := await self.config.custom('subscriptions', yid).discord():
                sub = self.config.custom('subscriptions', channelYouTube)
                embed = discord.Embed()
                embed.colour = YT_COLOR
                embed.title = _("Subscription information for {name}").format(name=await sub.name())
                embed.url = f"https://www.youtube.com/channel/{yid}/"
                embed.timestamp = datetime.fromtimestamp(await sub.updated())

                channels = ctx.guild.channels
                if ctx.command.qualified_name == 'youtube infoall':
                    channels = [self.bot.get_channel(int(channel)) for channel in dchans.keys()]

                info = []
                for channel in channels:
                    dchan = str(channel.id)
                    if dchan in dchans.keys():
                        title = _("Posted to {channel}").format(channel=channel.mention)
                        if ctx.command.qualified_name == 'youtube infoall':
                            title += f" ({channel.guild})"
                        part = bold(title)

                        if message := dchans.get(dchan).get('message'):
                            part += "\n" + _("Custom: \"{message}\"").format(message=escape(message, formatting=True))

                        if mention := dchans.get(dchan).get('mention'):
                            mention = ctx.guild.default_role if mention == ctx.guild.id else f"<@&{mention}>"
                            part += "\n" + _("Mention: {mention}").format(mention=mention)

                        if dchans.get(dchan).get('publish'):
                            msg = _("Yes")
                            if not channel.is_news():
                                msg = _("Yes, but not an Announcement Channel")
                            part += "\n" + _("Publish: {message}").format(message=msg)

                        info.append(part + "\n")

                embed.description = "\n".join(info) if info else "\u200b"
                if not info:
                    return await ctx.send(error(_("Subscription not found.")))
                icon = discord.File(bundled_data_path(self) / "youtube_social_icon_red.png", filename="youtube.png")
                embed.set_footer(text=_("Latest video"), icon_url="attachment://youtube.png")
                await ctx.send(file=icon, embed=embed)

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

        prompt = await ctx.send(_("You are about to import **{channels} YouTube subscriptions**.").format(channels=channels)
            + " " + _("Depending on the internet speed of the server, this might take a while.")
            + " " + _("Do you want to continue?")
            + "\n(yes/no)"
        )
        response = await ctx.bot.wait_for("message", check=MessagePredicate.same_context(ctx))

        if not response.content.lower().startswith("y"):
            return await ctx.send(_("Migration has been cancelled."))

        with contextlib.suppress(discord.NotFound):
            await prompt.delete()
        with contextlib.suppress(discord.HTTPException):
            await response.delete()
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
                prompt = await ctx.send(_("Running the `Tube` cog alongside this cog *will* get spammy. Do you want to unload `Tube`?") + "\n(yes/no)")
                response = await ctx.bot.wait_for("message", check=MessagePredicate.same_context(ctx))
                if response.content.lower().startswith("y"):
                    with contextlib.suppress(discord.NotFound):
                        await prompt.delete()
                    with contextlib.suppress(discord.HTTPException):
                        await response.delete()
                    with contextlib.suppress(commands.ExtensionNotLoaded):
                        ctx.bot.unload_extension('Tube')
            await ctx.send(success(_("Migration completed!")))

    @tasks.loop(minutes=1)
    async def background_get_new_videos(self) -> None:
        if discord.version_info.major == 1:
            await self.upgrade_db()

        for yid in await self.config.custom('subscriptions').get_raw():
            sub = self.config.custom('subscriptions', yid)
            dchans = await self.config.custom('subscriptions', yid).discord()
            upd = await sub.updated()
            feed = feedparser.parse(await self.get_feed(yid))

            try:
                name = feed['feed']['title']
                if await sub.name() != name:
                    await self.config.custom('subscriptions', yid).name.set(name)
            except KeyError:
                # Skip current run
                log.warning(f"Unable to retrieve {yid} ({await sub.name()}), skipped")
                continue

            for entry in feed['entries'][:4][::-1]:
                processed = await sub.processed()
                published = datetime.strptime(entry['published'], YT_FORMAT)
                updated = datetime.strptime(entry['updated'], YT_FORMAT)

                message = None
                if updated.timestamp() > upd and entry['yt_videoid'] not in processed:
                    await self.config.custom('subscriptions', yid).updated.set(int(published.timestamp()))
                    for dchan in list(dchans):
                        channel = self.bot.get_channel(int(dchan))
                        if not channel:
                            dchans.pop(dchan)
                            await self.config.custom('subscriptions', yid).discord.set(dchans)
                            log.warning(f"Removed invalid channel {dchan} for subscription {yid} ({name})")
                            continue

                        if not channel.permissions_for(channel.guild.me).send_messages:
                            log.warning(f"Not allowed to post messages to {channel}")
                            continue

                        mentions = discord.AllowedMentions()
                        if role := dchans.get(dchan).get('mention'):
                            if role == channel.guild.id:
                                role = channel.guild.default_role
                                mentions = discord.AllowedMentions(everyone=True)
                            else:
                                role = f"<@&{role}>"
                                mentions = discord.AllowedMentions(roles=True)

                        # Build custom message if set
                        if custom := dchans.get(dchan).get('message'):
                            options = {
                                'author': entry['author'],
                                'title': entry['title'],
                                'published': published,
                                'updated': updated,
                                'summary': entry['summary'],
                            }
                            custom = custom.format(**options)

                        if channel.permissions_for(channel.guild.me).embed_links:
                            embed = discord.Embed()
                            embed.colour = YT_COLOR
                            embed.title = entry['title']
                            embed.url = entry['link']
                            # Check can be removed later, Dpy2 can handle None natively
                            if custom:
                                embed.description = custom
                            embed.set_author(name=entry['author'], url=entry['author_detail']['href'])
                            embed.set_image(url=entry['media_thumbnail'][0]['url'])
                            embed.timestamp = updated
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
                                log.warning(f"Can't publish, this is not a news channel: {dchan}")
                if message:
                    processed = [entry['yt_videoid']] + processed
                    await self.config.custom('subscriptions', yid).processed.set(processed[:6])
            if not dchans.keys():
                await self.config.custom('subscriptions', yid).clear()
                log.warning(f"Removed subscription {yid} ({name}): no subscribed channels left")

    @background_get_new_videos.before_loop
    async def wait_for_red(self) -> NoReturn:
        await self.bot.wait_until_red_ready()
        interval = await self.config.interval()
        self.background_get_new_videos.change_interval(seconds=interval)

    async def get_feed(self, channel: str) -> Union[aiohttp.StreamReader, None]:
        """Fetch data from a feed."""
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel}"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as response:
                    return await response.read()
            except aiohttp.client_exceptions.ClientConnectionError as e:
                log.exception(f"Fetch failed for url {url}: ", exc_info=e)
                return

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
        except:
            pass

        # URL is a video?
        try:
            return pytube.YouTube(url).channel_id
        except:
            pass

        # URL is a playlist?
        try:
            return pytube.Playlist(url).owner_id
        except:
            pass

        await ctx.send(error(_("Your input {channel} is not valid.").format(channel=bold(channelYouTube))))

    async def subscription_discord_options(self, ctx: commands.Context, action: str, channelYouTube: str, data: Optional, channelDiscord: Optional[discord.TextChannel] = None) -> None:
        """Store custom options for Discord channels."""
        yid = await self.get_youtube_channel(ctx, channelYouTube)
        if not yid:
            return

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
            await ctx.send(success(msg.format(action=actionName, title=feedTitle, list=humanize_list(channels))))

    async def upgrade_db(self):
        await self.config.custom('subscriptions').clear_all()
        if oldconfig := await self.config.subs():
            interval = await self.config.interval()
            for oldSub in oldconfig:
                yid, sub = oldSub.popitem()
                for dchan in sub.get('discord').keys():
                    if not sub.get('discord').get(dchan).get('publish'):
                        sub.get('discord').get(dchan).pop('publish')
                await self.config.custom('subscriptions', yid).set(sub)
            await self.config.clear_all_globals()
            if interval != 300:
                await self.config.interval.set(interval)

    async def red_delete_data_for_user(self, *, requester: RequestType, user_id: int) -> None:
        pass

    def cog_unload(self):
        self.background_get_new_videos.cancel()
