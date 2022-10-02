# -*- coding: utf-8 -*-
import contextlib
from datetime import datetime
import logging
import math
import re
import time

import discord
import aiohttp
import feedparser

from pytube import Channel, Playlist, YouTube
from typing import Optional
from discord.ext import tasks
from redbot.core import Config, bot, checks, commands
from redbot.core.utils.chat_formatting import escape, humanize_list, pagify
from redbot.core.utils.predicates import MessagePredicate

log = logging.getLogger("red.mr42-cogs.youtube")

class YouTube(commands.Cog):
    """A YouTube subscription cog"""
    def __init__(self, bot: bot.Red):
        self.bot = bot
        self.conf = Config.get_conf(self, identifier=823288853745238067, force_registration=True)
        self.conf.register_global(subs=[], interval=300)
        self.conf.register_guild(autodelete=True)
        self.background_get_new_videos.start()

    @commands.group(aliases=['yt'])
    async def youtube(self, ctx: commands.Context):
        """Post when new videos are published to a YouTube channel"""
        if not isinstance(ctx.channel, discord.DMChannel) and await self.conf.guild(ctx.guild).autodelete() and ctx.channel.permissions_for(ctx.guild.me).manage_messages:
            await ctx.message.delete()

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @youtube.command(aliases=['s', 'subscribe'])
    async def sub(self, ctx: commands.Context, channelYouTube, channelDiscord: Optional[discord.TextChannel] = None):
        """Subscribe a Discord channel to a YouTube channel

        If no discord channel is specified, the current channel will be subscribed.

        Channels can be added by channel ID, channel URL, video URL, or playlist URL.
        """
        yid = await self.get_youtube_channel(ctx, channelYouTube)
        if not yid:
            return

        subs = await self.conf.subs()
        channel = channelDiscord or ctx.channel
        feedTitle = False

        for sub in subs:
            if yid in sub.keys():
                # YouTube channel already exists in config
                if str(channel.id) in sub.get(yid).get('discord').keys():
                    # Already subsribed, do nothing!
                    await ctx.send("This subscription already exists!")
                    return

                # Adding Discord channel to existing YouTube subscription
                newChannel = {channel.id: {'publish': False}}
                sub.get(yid).get('discord').update(newChannel)
                feedTitle = sub.get(yid).get('name')
                break

        # YouTube channel does not exist in config
        if not feedTitle:
            try:
                feed = feedparser.parse(await self.get_feed(yid))
                feedTitle = feed['feed']['title']
            except:
                await ctx.send("Error getting channel feed. Make sure the input is correct.")
                return

            processed = []
            for entry in feed['entries'][:6]:
                processed.append(entry['yt_videoid'])

            try:
                updated = int(time.mktime(feed['entries'][0]['published_parsed']))
            except IndexError:
                # No videos are published on the YouTube channel
                updated = int(time.mktime(feed['feed']['published_parsed']))

            newChannel = {
                yid: {
                    'name': feedTitle,
                    'updated': updated,
                    'processed': processed,
                    'discord': {channel.id: {'publish': False}}
                }
            }
            subs.append(newChannel)

        if newChannel:
            await self.conf.subs.set(subs)
            if ctx.command.qualified_name != 'youtube migrate':
                await ctx.send(f"YouTube channel **{feedTitle}** will now be announced in <#{channel.id}> when new videos are published.")

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @youtube.command(aliases=['u', 'unsubscribe'])
    async def unsub(self, ctx: commands.Context, channelYouTube, channelDiscord: Optional[discord.TextChannel] = None):
        """Unsubscribe a Discord channel from a YouTube channel

        If no Discord channel is specified, the subscription will be removed from all channels"""
        yid = await self.get_youtube_channel(ctx, channelYouTube)
        if not yid:
            return

        updated = []
        subs = await self.conf.subs()
        for sub in subs:
            if yid in sub.keys():
                # YouTube channel exists in config
                feedTitle = sub.get(yid).get('name')
                if not channelDiscord:
                    for channel in ctx.guild.channels:
                        if str(channel.id) in sub.get(yid).get('discord').keys():
                            sub.get(yid).get('discord').pop(str(channel.id))
                            updated.append(channel.id)
                else:
                    if str(channelDiscord.id) in sub.get(yid).get('discord').keys():
                        sub.get(yid).get('discord').pop(str(channelDiscord.id))
                        updated.append(channelDiscord.id)
                # Remove from config if no Discord channels are left
                if not sub.get(yid).get('discord'):
                    sub.clear()

        if not updated:
            await ctx.send("Subscription not found.")
        else:
            deletedFrom = ""
            for update in updated:
                deletedFrom += f" <#{update}>"

            subs = self.remove_empty_elements(subs)
            await self.conf.subs.set(subs)
            await ctx.send(f"Unsubscribed from **{feedTitle}** on{deletedFrom}.")

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @youtube.command()
    async def list(self, ctx: commands.Context):
        """List current subscriptions"""
        guildSubs = []
        subsByChannel = {}
        for sub in await self.conf.subs():
            channelYouTube, sub = sub.popitem()
            for channel in ctx.guild.channels:
                subsByChannel[channel.id] = []
                dchan = str(channel.id)
                if dchan in sub.get('discord').keys():
                    d = {'message': '\u1d9c', 'mention': '\u1d50', 'publish': '\u1d56'}
                    tags = ''
                    for k, v in d.items():
                        if sub.get('discord').get(dchan).get(k, False):
                            tags += v
                    guildSubs.append({'name': sub.get('name'), 'id': channelYouTube, 'updated': sub.get('updated'), 'discord': channel, 'tags': tags})

        if not len(guildSubs):
            await ctx.send("No subscriptions yet - try adding some!")
            return

        for sub in sorted(guildSubs, key=lambda d: d['updated'], reverse=True):
            channel = sub['discord'].id
            line = f"`{sub['id']} {datetime.fromtimestamp(sub.get('updated'))}` {escape(sub.get('name')[:50], formatting=True)}"
            if sub['tags']:
                line += f" {sub['tags']}"
            subsByChannel[channel].append(line)
        subsByChannel = self.remove_empty_elements(subsByChannel)

        subs_string = ""
        subsByChannelSorted = dict(sorted(subsByChannel.items()))
        for sub, sub_ids in subsByChannelSorted.items():
            count = len(sub_ids)
            channel = self.bot.get_channel(sub)
            subs_string += f"\n\n**{count} YouTube {'subscription' if count == 1 else 'subscriptions'} for <#{channel.id}>**"
            for sub in sub_ids:
                subs_string += f"\n{sub}"

        for page in pagify(subs_string):
            await ctx.send(page)

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @youtube.command(aliases=['c', 'customize'])
    async def custom(self, ctx: commands.Context, channelYouTube, message: str = False, channelDiscord: Optional[discord.TextChannel] = None):
        """ Add a custom message for new videos from a YouTube channel

        You can use any keys available in the RSS object in your custom message
        by surrounding the key in perecent signs, e.g.:
        [p]youtube customize UCXuqSBlHAE6Xw-yeJA0Tunw "Linus from %author% is dropping things again!\\nCheck out their new video %title%" #video-updates

        You can also remove customization by not specifying any message.
        """
        await self.subscription_discord_options(ctx, 'message', channelYouTube, message, channelDiscord)

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @youtube.command(aliases=['m', 'rolemention'])
    async def mention(self, ctx: commands.Context, channelYouTube, mention: Optional[discord.Role], channelDiscord: Optional[discord.TextChannel] = None):
        """ Add a role @mention in front of the message

        Works for `@everyone` or any role. `@here` is not supported.

        You can also remove the mention by not specifying any role.
        """
        m = False
        if mention:
            m = mention.id
        await self.subscription_discord_options(ctx, 'mention', channelYouTube, m, channelDiscord)

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @youtube.command(aliases=['p'])
    async def publish(self, ctx: commands.Context, channelYouTube, channelDiscord: discord.TextChannel):
        """ Toggles publishing new messages to a Discord channel

        This feature is only available on Community Servers.
        """
        if 'COMMUNITY' not in ctx.guild.features:
            await ctx.send('This function is only available on Community Servers.')
            return

        if not channelDiscord.is_news():
            await ctx.send(f'The channel <#{channelDiscord}> is not an Announcement Channel.')
            return

        yid = await self.get_youtube_channel(ctx, channelYouTube)
        if not yid:
            return

        subs = await self.conf.subs()
        for sub in subs:
            if yid in sub.keys():
                channel = sub.get(yid).get('discord').get(str(channelDiscord.id))
                break

        if not channel:
            await ctx.send("Subscription not found.")
            return

        publish = False
        if not channel.get('publish'):
            publish = True

        await self.subscription_discord_options(ctx, 'publish', yid, publish, channelDiscord)

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @youtube.command()
    async def info(self, ctx: commands.Context, channelYouTube):
        """Provides information about a YouTube subscription"""
        yid = await self.get_youtube_channel(ctx, channelYouTube)
        if not yid:
            return

        for sub in await self.conf.subs():
            if yid in sub.keys():
                embed = discord.Embed()
                embed.title = f"Subscription information for {sub.get(yid).get('name')}"
                embed.url = f"https://www.youtube.com/channel/{yid}/"
                embed.set_footer(text=f"Latest video: {datetime.fromtimestamp(sub.get(yid).get('updated'))}")

                for channel in ctx.guild.channels:
                    dchan = str(channel.id)
                    if dchan in sub.get(yid).get('discord').keys():
                        info = []
                        message = sub.get(yid).get('discord').get(dchan).get('message', False)
                        if message:
                            info.append(f'Custom: "{escape(message, formatting=True)}"')

                        mention = sub.get(yid).get('discord').get(dchan).get('mention', False)
                        if mention:
                            if mention == ctx.guild.id:
                                mention = ctx.guild.default_role
                            else:
                                mention = f"<@&{mention}>"
                            info.append(f"Mention: {mention}")

                        if sub.get(yid).get('discord').get(dchan).get('publish'):
                            msg = "Yes"
                            if not channel.is_news():
                                msg += ", but not an Announcement Channel"
                            info.append(f'Publish: {msg}')

                        info = "\n".join(info)
                        if not info:
                            info = "\u200b"
                        embed.add_field(name=f"Posted to #{channel.name}", value=info, inline=False)
                await ctx.send(embed=embed)
                return
        await ctx.send("Subscription not found.")

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @youtube.command(hidden=True)
    async def autodelete(self, ctx: commands.Context):
        """Toggles auto deleting the commands given to the plugin"""
        autodelete = False
        if not await self.conf.guild(ctx.guild).autodelete():
            autodelete = True
            if ctx.channel.permissions_for(ctx.guild.me).manage_messages:
                await ctx.message.delete()
            else:
                await ctx.send("I don't have permission to do that. Please enable **Manage Messages** for me.")

        await self.conf.guild(ctx.guild).autodelete.set(autodelete)
        await ctx.send(f'Automatic deletion of your commands has now been {"enabled" if autodelete else "disabled" }!')

    @checks.is_owner()
    @youtube.command(name="setinterval", hidden=True)
    async def set_interval(self, ctx: commands.Context, interval: int):
        """Set the interval in seconds at which to check for updates

        Very low values will probably get you rate limited

        Default is 300 seconds (5 minutes)"""
        self.background_get_new_videos.change_interval(seconds=interval)
        await ctx.send(f"Interval set to {await self.conf.interval()}")

    @checks.is_owner()
    @youtube.command(hidden=True)
    async def migrate(self, ctx: commands.Context):
        """Import all subscriptions from the `Tube` cog"""
        TubeConfig = Config.get_conf(None, 0x547562756c6172, True, cog_name='Tube')
        TubeConfig.register_guild(subscriptions=[])
        channels = 0
        for g in self.bot.guilds:
            guild = self.bot.get_guild(g.id)
            for data in await TubeConfig.guild(guild).subscriptions():
                channels += 1

        if channels == 0:
            await ctx.send("No data found to import. Migration has been cancelled.")
            return

        prompt = await ctx.send(f"You are about to import **{channels} YouTube subscriptions**. Depending on the internet speed of the server, this might take a while. Do you want to continue?"
            + "\n(yes/no)"
        )
        response = await ctx.bot.wait_for("message", check=MessagePredicate.same_context(ctx))

        if response.content.lower().startswith("y"):
            with contextlib.suppress(discord.NotFound):
                await prompt.delete()
            with contextlib.suppress(discord.HTTPException):
                await response.delete()
                await ctx.send("Migration started…")
                async with ctx.typing():
                    for g in self.bot.guilds:
                        guild = self.bot.get_guild(g.id)
                        count = 0
                        for data in await TubeConfig.guild(guild).subscriptions():
                            yid = data.get('id')
                            channel = self.bot.get_channel(int(data.get('channel').get('id')))

                            await self.sub(ctx, yid, channel)

                            if data.get('custom'):
                                await self.subscription_discord_options(ctx, 'message', yid, data.get('custom'), channel)

                            if data.get('mention'):
                                await self.subscription_discord_options(ctx, 'mention', yid, data.get('mention'), channel)

                            if data.get('publish'):
                                await self.subscription_discord_options(ctx, 'publish', yid, channel)
                            count += 1
                        await ctx.send(f"Imported {count} {'subscription' if count == 1 else 'subscriptions'} for {g.name}")
                if 'Tube' in ctx.bot.extensions:
                    prompt = await ctx.send("Running the _Tube_ cog alongside this cog *will* get spammy. Do you want to unload Tube?\n(yes/no)")
                    response = await ctx.bot.wait_for("message", check=MessagePredicate.same_context(ctx))
                    if response.content.lower().startswith("y"):
                        with contextlib.suppress(discord.NotFound):
                            await prompt.delete()
                        with contextlib.suppress(discord.HTTPException):
                            await response.delete()
                        with contextlib.suppress(commands.ExtensionNotLoaded):
                            ctx.bot.unload_extension('Tube')
                await ctx.send(f"Migration completed!")
        else:
            await ctx.send("Migration has been cancelled.")

    @tasks.loop(seconds=1)
    async def background_get_new_videos(self):
        try:
            subs = await self.conf.subs()
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
                data.update({'updated': max(data.get('updated'), int(time.mktime(entry["published_parsed"])))})

                message = None
                if time.mktime(entry["updated_parsed"]) > updated and entry['yt_videoid'] not in sub.get(yid).get('processed'):
                    for dchan in data.get('discord').keys():
                        channel = self.bot.get_channel(int(dchan))
                        if not channel:
                            chan = str(channelDiscord.id)
                            data.get('discord').pop(chan)
                            if not data.get('discord'):
                                sub.clear()
                            log.warning(f"Invalid channel {channelDiscord.name} ({dchan}) for subscription {yid} removed")
                            continue

                        for g in self.bot.guilds:
                            for c in g.channels:
                                if int(dchan) == c.id:
                                    guild = g
                        if not channel.permissions_for(guild.me).send_messages:
                            log.warning(f"Not allowed to post subscription to: {dchan}")
                            continue

                        link = f"https://youtu.be/{entry['yt_videoid']}"

                        # Build custom message if one is set
                        custom = data.get('discord').get(dchan).get('message', False)
                        if custom:
                            TOKENIZER = re.compile(r'([^\s]+)')
                            for token in TOKENIZER.split(custom):
                                if token.startswith("%") and token.endswith("%"):
                                    custom = custom.replace(token, entry.get(token[1:-1]))
                            description = f"{custom} {link}"
                        # Default descriptions
                        else:
                            if channel.permissions_for(guild.me).embed_links:
                                # Let the embed provide necessary info
                                description = link
                            else:
                                description = (f"New video from *{entry['author']}*\n**{entry['title']}**\n{link}")

                        mention = data.get('discord').get(dchan).get('mention', False)
                        if mention:
                            if mention == guild.id:
                                description = f"{guild.default_role} {description}"
                                mentions = discord.AllowedMentions(everyone=True)
                            else:
                                description = f"<@&{mention}> {description}"
                                mentions = discord.AllowedMentions(roles=True)
                        else:
                            mentions = discord.AllowedMentions()

                        message = await channel.send(content=description, allowed_mentions=mentions)
                        if data.get('discord').get(dchan).get('publish'):
                            if channel.is_news():
                                with contextlib.suppress(discord.HTTPException):
                                    await message.publish()
                            else:
                                log.warning(f"Can't publish, this is not a news channel: {dchan}")
                if message:
                    processed = [entry['yt_videoid']] + processed
                    sub.get(yid).update({'processed': processed[:6]})

        subs = self.remove_empty_elements(subs)
        await self.conf.subs.set(subs)

    @background_get_new_videos.before_loop
    async def wait_for_red(self):
        await self.bot.wait_until_red_ready()
        interval = await self.conf.interval()
        self.background_get_new_videos.change_interval(seconds=interval)

    async def fetch(self, session, url):
        """Fetch data from a URL"""
        try:
            async with session.get(url) as response:
                return await response.read()
        except aiohttp.client_exceptions.ClientConnectionError as e:
            log.exception(f"Fetch failed for url {url}: ", exc_info=e)
            return None

    async def get_feed(self, channel):
        """Fetch data from a feed"""
        async with aiohttp.ClientSession() as session:
            res = await self.fetch(
                session,
                f"https://www.youtube.com/feeds/videos.xml?channel_id={channel}"
            )
        return res

    async def get_youtube_channel(self, ctx: commands.Context, channelYouTube):
        url = channelYouTube
        match = re.compile("^UC[-_A-Za-z0-9]{21}[AQgw]$").fullmatch(channelYouTube)
        if match:
            subs = await self.conf.subs()
            for sub in subs:
                for channel in sub:
                    if channelYouTube == channel:
                        return channelYouTube
            url = f"https://www.youtube.com/channel/{match.string}"

        # URL is a channel?
        try:
            cid = Channel(url)
            if cid:
                return cid.channel_id
        except:
            pass

        # URL is a video?
        try:
            cid = YouTube(url)
            if cid:
                return cid.channel_id
        except:
            pass

        # URL is a playlist?
        try:
            cid = Playlist(url)
            if cid:
                return cid.owner_id
        except:
            pass

        await ctx.send(f"Your input **{channelYouTube}** is not valid.")

    async def subscription_discord_options(self, ctx: commands.Context, action, channelYouTube, data: Optional, channelDiscord: Optional[discord.TextChannel] = None):
        yid = await self.get_youtube_channel(ctx, channelYouTube)
        if not yid:
            return

        if action == 'message':
            actionName = 'Custom message'
        elif action == 'mention':
            actionName = 'Role mention'
        elif action == 'publish':
            actionName = 'Publishing'
        else:
            await ctx.name(f"Unknown action: {action}")
            return

        updated = []
        subs = await self.conf.subs()
        for sub in subs:
            if yid in sub.keys():
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
                else:
                    if str(channelDiscord.id) in sub.get(yid).get('discord').keys():
                        updated.append(channelDiscord.id)
                        chan = str(channelDiscord.id)
                        if data:
                            sub.get(yid).get('discord').get(chan).update({action: data})
                        else:
                            sub.get(yid).get('discord').get(chan).pop(action)
                break

        if not updated:
            await ctx.send("Subscription not found.")
        else:
            channels = []
            for update in updated:
                channels.append(f"<#{update}>")
            await self.conf.subs.set(subs)
            if ctx.command.qualified_name != 'youtube migrate':
                await ctx.send(f"{actionName} for **{feedTitle}** {'added to' if data else 'removed from'} {humanize_list(channels)}")

    def remove_empty_elements(self, d):
        """recursively remove empty lists, empty dicts, or None elements from a dictionary"""
        def empty(x):
            return x is None or x == {} or x == []

        if not isinstance(d, (dict, list)):
            return d
        elif isinstance(d, list):
            return [v for v in (self.remove_empty_elements(v) for v in d) if not empty(v)]
        else:
            return {k: v for k, v in ((k, self.remove_empty_elements(v)) for k, v in d.items()) if not empty(v)}

    def cog_unload(self):
        self.background_get_new_videos.cancel()
