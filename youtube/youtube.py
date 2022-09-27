import aiohttp
import contextlib
import discord
import feedparser
import logging
import math
import pytube
import re

from datetime import datetime
from discord.ext import tasks
from typing import Literal, NoReturn, Optional, Union
from redbot.core import Config, bot, checks, commands
from redbot.core.bot import Red
from redbot.core.data_manager import bundled_data_path
from redbot.core.i18n import Translator, cog_i18n, get_regional_format
from redbot.core.utils.chat_formatting import bold, escape, humanize_list, humanize_timedelta, pagify
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
        self.config = Config.get_conf(self, identifier=823288853745238067, force_registration=True)
        self.config.register_global(subs=[], interval=300)
        self.background_get_new_videos.start()

    @commands.group(aliases=['yt'])
    async def youtube(self, ctx: commands.Context) -> NoReturn:
        """Post when new videos are published to a YouTube channel."""
        pass

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

            subs = await self.config.subs()
            channel = channelDiscord or ctx.channel
            if sub := next((sub for sub in subs if sub.get(yid)), None):
                # YouTube channel already exists in config
                if str(channel.id) in sub.get(yid).get('discord').keys():
                    # Already subsribed, do nothing!
                    return await ctx.send(_("This subscription already exists!"))

                # Adding Discord channel to existing YouTube subscription
                newChannel = {channel.id: {'publish': False}}
                sub.get(yid).get('discord').update(newChannel)
                feedTitle = sub.get(yid).get('name')
            else:
                # YouTube channel does not exist in config
                try:
                    feed = feedparser.parse(await self.get_feed(yid))
                    feedTitle = feed['feed']['title']
                except:
                    return await ctx.send(_("Error getting channel feed. Make sure the input is correct."))

                processed = [entry['yt_videoid'] for entry in feed['entries'][:6]]
                try:
                    updated = int(datetime.strptime(feed['entries'][0]['published'], YT_FORMAT).timestamp())
                except IndexError:
                    # No videos are published on the YouTube channel
                    updated = int(datetime.strptime(feed['feed']['published'], YT_FORMAT).timestamp())

                newChannel = {
                    yid: {
                        'name': feedTitle,
                        'updated': updated,
                        'processed': processed,
                        'discord': {channel.id: {'publish': False}}
                    }
                }
                subs.append(newChannel)

        await self.config.subs.set(subs)
        if ctx.command.qualified_name != 'youtube migrate':
            await ctx.send(_("YouTube channel {title} will now be announced in {channel} when new videos are published.").format(title=bold(feedTitle), channel=f"<#{channel.id}>"))

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
            subs = await self.config.subs()
            if sub := next((sub for sub in subs if sub.get(yid)), None):
                # YouTube channel exists in config
                feedTitle = sub.get(yid).get('name')
                if not channelDiscord:
                    for channel in ctx.guild.channels:
                        if str(channel.id) in sub.get(yid).get('discord').keys():
                            sub.get(yid).get('discord').pop(str(channel.id))
                            updated.append(f"<#{channel.id}>")
                elif str(channelDiscord.id) in sub.get(yid).get('discord').keys():
                    sub.get(yid).get('discord').pop(str(channelDiscord.id))
                    updated.append(f"<#{channelDiscord.id}>")
                # Remove from config if no Discord channels are left
                if not sub.get(yid).get('discord'):
                    sub.clear()

            if updated:
                subs = list(filter(None, subs))
                await self.config.subs.set(subs)
                await ctx.send(_("Unsubscribed from {title} on {list}.").format(title=bold(feedTitle), list=humanize_list(updated)))
            else:
                await ctx.send(_("Subscription not found."))

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @youtube.command()
    async def list(self, ctx: commands.Context, channelDiscord: Optional[discord.TextChannel] = None) -> None:
        """List current subscriptions."""
        guildSubs = []
        subsByChannel = {}

        channels = [channelDiscord] if channelDiscord else ctx.guild.channels
        for sub in await self.config.subs():
            channelYouTube, sub = sub.popitem()
            for channel in channels:
                subsByChannel[channel.id] = []
                dchan = str(channel.id)
                if dchan in sub.get('discord').keys():
                    d = {'message': '\u1d9c', 'mention': '\u1d50', 'publish': '\u1d56'}
                    tags = ''.join(v for k, v in d.items() if sub.get('discord').get(dchan).get(k, False))
                    guildSubs.append({'name': sub.get('name'), 'id': channelYouTube, 'updated': sub.get('updated'), 'discord': channel, 'tags': tags})

        if not len(guildSubs):
            return await ctx.send(_("No subscriptions yet - try adding some!"))

        for sub in sorted(guildSubs, key=lambda d: d['updated'], reverse=True):
            channel = sub['discord'].id
            line = f"`{sub['id']} {datetime.fromtimestamp(sub.get('updated'))}` {escape(sub.get('name')[:50], formatting=True)}"
            if sub['tags']:
                line += f" {sub['tags']}"
            subsByChannel[channel].append(line)
        subsByChannel = {k:v for k,v in subsByChannel.items() if v != []}

        subs_string = ""
        subsByChannelSorted = dict(sorted(subsByChannel.items()))
        for sub, sub_ids in subsByChannelSorted.items():
            count = len(sub_ids)
            channel = self.bot.get_channel(sub)

            if count > 1:
                subs_title = _("{count} YouTube subscriptions for {channel}").format(count=count, channel=f"<#{channel.id}>")
            else:
                subs_title = _("1 YouTube subscription for {channel}").format(channel=f"<#{channel.id}>")
            subs_string += "\n\n" + bold(subs_title)

            for sub in sub_ids:
                subs_string += f"\n{sub}"

        for page in pagify(subs_string):
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
            return await ctx.send(_("This function is only available on Community Servers."))

        async with ctx.typing():
            yid = await self.get_youtube_channel(ctx, channelYouTube)
            if not yid:
                return

            dchan = False
            notNews = []
            channels = [channelDiscord] if channelDiscord else ctx.guild.channels
            if sub := next((sub for sub in await self.config.subs() if sub.get(yid)), None):
                dchannels = sub.get(yid).get('discord')
                for channel in channels:
                    if str(channel.id) in dchannels.keys():
                        if not channel.is_news():
                            notNews.append(f"<#{channel.id}>")
                            continue
                        dchan = str(channel.id)
                        publish = not dchannels.get(dchan).get('publish')
                        await self.subscription_discord_options(ctx, 'publish', yid, publish, channel)

            if notNews:
                if len(notNews) == 1:
                    await ctx.send(_("The channel {list} is not an Announcement Channel.").format(list=humanize_list(notNews)))
                else:
                    await ctx.send(_("The channels {list} are not Announcement Channels.").format(list=humanize_list(notNews)))
            elif not dchan:
                await ctx.send(_("Subscription not found."))

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @youtube.command()
    async def info(self, ctx: commands.Context, channelYouTube: str) -> None:
        """Provides information about a YouTube subscription."""
        async with ctx.typing():
            yid = await self.get_youtube_channel(ctx, channelYouTube)
            if not yid:
                return

            if sub := next((sub for sub in await self.config.subs() if sub.get(yid)), None):
                embed = discord.Embed()
                embed.colour = YT_COLOR
                embed.title = f"Subscription information for {sub.get(yid).get('name')}"
                embed.url = f"https://www.youtube.com/channel/{yid}/"
                embed.timestamp = datetime.fromtimestamp(sub.get(yid).get('updated'))
                embed.set_footer(text=_("Latest video"), icon_url="attachment://youtube_social_icon_red.png")

                dchan = None
                for channel in ctx.guild.channels:
                    dchan = str(channel.id)
                    if dchan in sub.get(yid).get('discord').keys():
                        info = []
                        if message := sub.get(yid).get('discord').get(dchan).get('message'):
                            info.append(_("Custom: \"{message}\"").format(message=escape(message, formatting=True)))

                        if mention := sub.get(yid).get('discord').get(dchan).get('mention'):
                            mention = ctx.guild.default_role if mention == ctx.guild.id else f"<@&{mention}>"
                            info.append(_("Mention: {mention}").format(mention=mention))

                        if sub.get(yid).get('discord').get(dchan).get('publish'):
                            msg = _("Yes")
                            if not channel.is_news():
                                msg = _("Yes, but not an Announcement Channel")
                            info.append(_("Publish: {message}").format(message=msg))

                        info = "\n".join(info) if info else "\u200b"
                        embed.add_field(name=_("Posted to {channel}").format(channel=f"#{channel.name}"), value=info, inline=False)
                if not dchan:
                    return await ctx.send(_("Subscription not found."))
                icon = discord.File(bundled_data_path(self) / "youtube_social_icon_red.png", filename="youtube_social_icon_red.png")
                await ctx.send(file=icon, embed=embed)

    @checks.is_owner()
    @youtube.command(hidden=True)
    async def interval(self, ctx: commands.Context, interval: Optional[int]) -> None:
        """Set the interval in seconds at which to check for updates.

        Very low values will probably get you rate limited!

        Default is 300 seconds (5 minutes)."""
        if interval is None:
            interval = await self.config.interval()
            return await ctx.send(_("I am currently checking every {time} for new videos.").format(time=humanize_timedelta(seconds=interval)))
        elif interval < 60:
            return await ctx.send(_("You cannot set the interval to less than 60 seconds"))

        await self.config.interval.set(interval)
        self.background_get_new_videos.change_interval(seconds=interval)
        await ctx.send(_("I will now check every {time} for new videos.").format(time=humanize_timedelta(seconds=interval)))

    @checks.is_owner()
    @youtube.command(hidden=True)
    async def migrate(self, ctx: commands.Context) -> None:
        """Import all subscriptions from the `Tube` cog."""
        TubeConfig = Config.get_conf(None, 0x547562756c6172, True, cog_name='Tube')
        TubeConfig.register_guild(subscriptions=[])
        channels = 0
        for g in self.bot.guilds:
            guild = self.bot.get_guild(g.id)
            for _ in await TubeConfig.guild(guild).subscriptions():
                channels += 1

        if channels == 0:
            return await ctx.send(_("No data found to import. Migration has been cancelled."))

        prompt = await ctx.send(_("You are about to import **{channels} YouTube subscriptions**.").format(channels=channels)
            + " " + _("Depending on the internet speed of the server, this might take a while.")
            + " " + _("Do you want to continue?")
            + "\n(yes/no)"
        )
        response = await ctx.bot.wait_for("message", check=MessagePredicate.same_context(ctx))

        if response.content.lower().startswith("y"):
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
                await ctx.send(_("Migration completed!"))
        else:
            await ctx.send(_("Migration has been cancelled."))

    @tasks.loop(minutes=1)
    async def background_get_new_videos(self) -> None:
        try:
            subs = await self.config.subs()
        except:
            return

        for sub in subs:
            yid, data = next(iter(sub.items()))
            updated = data.get('updated')

            # Always update the YouTube channel name
            try:
                feed = feedparser.parse(await self.get_feed(yid))
                sub.get(yid).update({'name': feed['feed']['title']})
            except:
                # Skip current run
                log.warning(f"Unable to retrieve {yid}, skipped")
                continue

            for entry in feed['entries'][:4][::-1]:
                processed = sub.get(yid).get('processed')
                data.update({'updated': max(data.get('updated'), int(datetime.strptime(entry['published'], YT_FORMAT).timestamp()))})

                message = None
                if datetime.strptime(entry['updated'], YT_FORMAT).timestamp() > updated and entry['yt_videoid'] not in sub.get(yid).get('processed'):
                    for dchan in data.get('discord').keys():
                        channel = self.bot.get_channel(int(dchan))
                        if not channel:
                            data.get('discord').pop(dchan)
                            if not data.get('discord'):
                                sub.clear()
                            log.warning(f"Removed invalid channel {dchan} for subscription {yid}")
                            continue

                        for g in self.bot.guilds:
                            for c in g.channels:
                                if int(dchan) == c.id:
                                    guild = g
                        if not channel.permissions_for(guild.me).send_messages:
                            log.warning(f"Not allowed to post messages to {channel}")
                            continue

                        mentions = discord.AllowedMentions()
                        if role := data.get('discord').get(dchan).get('mention'):
                            if role == guild.id:
                                role = guild.default_role
                                mentions = discord.AllowedMentions(everyone=True)
                            else:
                                role = f"<@&{role}>"
                                mentions = discord.AllowedMentions(roles=True)

                        # Build custom message if set
                        if custom := data.get('discord').get(dchan).get('message'):
                            options = {
                                'author': entry['author'],
                                'title': entry['title'],
                                'published': datetime.strptime(entry['published'], YT_FORMAT),
                                'updated': datetime.strptime(entry['updated'], YT_FORMAT),
                                'summary': entry['summary'],
                            }
                            custom = custom.format(**options)

                        if channel.permissions_for(guild.me).embed_links:
                            embed = discord.Embed()
                            embed.colour = YT_COLOR
                            embed.title = entry['title']
                            embed.url = entry['link']
                            # Check can be removed later, Dpy2 can handle None natively
                            if custom:
                                embed.description = custom
                            embed.set_author(name=entry['author'], url=entry['author_detail']['href'])
                            embed.set_image(url=entry['media_thumbnail'][0]['url'])
                            embed.timestamp = datetime.strptime(entry['updated'], YT_FORMAT)
                            icon = discord.File(bundled_data_path(self) / "youtube_social_icon_red.png", filename="youtube_social_icon_red.png")
                            embed.set_footer(text="YouTube", icon_url="attachment://youtube_social_icon_red.png")
                            message = await channel.send(role, file=icon, embed=embed, allowed_mentions=mentions)
                        else:
                            description = custom or _("New video from {author}: {title}").format(author=bold(entry['author']), title=bold(entry['title']))
                            if role:
                                description = f"{role} {description}"
                            message = await channel.send(content=description + f" https://youtu.be/{entry['yt_videoid']}", allowed_mentions=mentions)

                        if data.get('discord').get(dchan).get('publish'):
                            if channel.is_news():
                                with contextlib.suppress(discord.HTTPException):
                                    await message.publish()
                            else:
                                log.warning(f"Can't publish, this is not a news channel: {dchan}")
                if message:
                    processed = [entry['yt_videoid']] + processed
                    sub.get(yid).update({'processed': processed[:6]})

        subs = list(filter(None, subs))
        await self.config.subs.set(subs)

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
        if match := re.compile("^UC[-_A-Za-z0-9]{21}[AQgw]$").fullmatch(channelYouTube):
            if next((sub for sub in await self.config.subs() if sub.get(channelYouTube)), None):
                return channelYouTube
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

        await ctx.send(_("Your input {channel} is not valid.").format(channel=bold(channelYouTube)))

    async def subscription_discord_options(self, ctx: commands.Context, action: str, channelYouTube: str, data: Optional, channelDiscord: Optional[discord.TextChannel] = None) -> None:
        """Store custom options for Discord channels."""
        yid = await self.get_youtube_channel(ctx, channelYouTube)
        if not yid:
            return

        if action == 'message':
            actionName = _("Custom message")
        elif action == 'mention':
            actionName = _("Role mention")
        elif action == 'publish':
            actionName = _("Publishing")
        else:
            return await ctx.send(_("Unknown action: {action}").format(action=action))

        updated = []
        subs = await self.config.subs()
        if sub := next((sub for sub in subs if sub.get(yid)), None):
            feedTitle = sub.get(yid).get('name')
            if not channelDiscord:
                for channel in ctx.guild.channels:
                    if str(channel.id) in sub.get(yid).get('discord').keys():
                        updated.append(channel.id)
                        chan = str(channel.id)
                        if data:
                            sub.get(yid).get('discord').get(chan).update({action: data})
                        elif sub.get(yid).get('discord').get(chan).get(action):
                            sub.get(yid).get('discord').get(chan).pop(action)
            elif str(channelDiscord.id) in sub.get(yid).get('discord').keys():
                updated.append(channelDiscord.id)
                chan = str(channelDiscord.id)
                if data:
                    sub.get(yid).get('discord').get(chan).update({action: data})
                else:
                    sub.get(yid).get('discord').get(chan).pop(action)

        if updated:
            await self.config.subs.set(subs)
            if ctx.command.qualified_name != 'youtube migrate':
                channels = [f"<#{update}>" for update in updated]
                if data:
                    await ctx.send(_("{action} for {title} added to {list}.").format(action=actionName, title=feedTitle, list=humanize_list(channels)))
                else:
                    await ctx.send(_("{action} for {title} removed from {list}.").format(action=actionName, title=feedTitle, list=humanize_list(channels)))
        else:
            await ctx.send(_("Subscription not found."))

    async def red_delete_data_for_user(self, *, requester: RequestType, user_id: int) -> None:
        pass

    def cog_unload(self):
        self.background_get_new_videos.cancel()
