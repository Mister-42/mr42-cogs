import contextlib
import discord
import logging
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
log = logging.getLogger("red.mr42-cogs.ytdedup")
RequestType = Literal["discord_deleted_user", "owner", "user", "user_strict"]

@cog_i18n(_)
class YouTubeDeDup(commands.Cog):
    """Remove duplicate YouTube links"""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=823288853745238067)
        self.config.register_guild(history=7)
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
        if await self.config.channel(channel).messages():
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

        days = await self.config.guild(ctx.guild).history()
        async with ctx.typing():
            async for message in channel.history(after=datetime.now() - timedelta(days=days)):
                await self.process_message(message)
        await ctx.send(success(_("The channel {channel} will now be monitored for duplicate YouTube links.").format(channel=channel.mention)))

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @youtubededup.command(aliases=['u'])
    async def unwatch(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        """Remove a channel from the watchlist."""
        messages = await self.config.channel(channel).messages()
        if not messages:
            return await ctx.send(warning(_("The channel {channel} is not being watched.").format(channel=channel.mention)))

        await self.config.channel(channel).clear()
        await ctx.send(success(_("The channel {channel} will no longer be monitored for duplicate YouTube links.").format(channel=channel.mention)))

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @youtubededup.command(hidden=True)
    async def history(self, ctx: commands.Context, history: int) -> None:
        """Set the amount of days history is being kept and checked.

        Default is 7 days."""
        days = f"{history} days"
        if history == 1:
            days = "1 day"

        await self.config.guild(ctx.guild).history.set(history)
        await ctx.send(success(_("I will keep message history for {days}.").format(days=bold(days))))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if await self.config.channel(message.channel).messages():
            await self.process_message(message)

    @tasks.loop(minutes=30)
    async def background_clean(self) -> None:
        for chan in await self.config.all_channels():
            channel = self.bot.get_channel(chan)
            days = await self.config.guild(channel.guild).history()
            messages = await self.config.channel(channel).messages()
            messagesOrig = messages.copy()
            for message in messagesOrig:
                if messages.get(message).get('time') < int(datetime.timestamp(datetime.now() - timedelta(days=days))):
                    messages.pop(message)
            await self.config.channel(channel).messages.set(messages)

    async def red_delete_data_for_user(self, *, requester: RequestType, user_id: int) -> None:
        pass

    async def process_message(self, message: discord.Message) -> None:
        if embeds := message.embeds:
            for embed in embeds:
                await self.process_vid(embed.url, message)
        elif text := message.content:
            links = re.findall(r'(https?://\S+)', text)
            for link in links:
                await self.process_vid(link, message)

    async def process_vid(self, url: str, message: discord.Message) -> None:
        timestamp = int(datetime.timestamp(message.created_at))
        if vid := self.get_yid(url):
            channel = message.channel
            messages = await self.config.channel(channel).messages()

            if channel.permissions_for(message.guild.me).manage_messages and vid in [message for message in messages]:
                previous = False
                prevId = messages.get(vid).get('msg')
                with contextlib.suppress(discord.NotFound):
                    previous = await channel.fetch_message(prevId)
                if previous and message.author.bot:
                    log.info(f"Deleted previous https://youtu.be/{vid} by {previous.author.name} from #{channel.name} ({message.guild})")
                    await previous.delete()
                else:
                    log.info(f"Deleted new https://youtu.be/{vid} by {message.author.name} from #{channel.name} ({message.guild})")
                    return await message.delete()

            newVid = {
                'msg': message.id,
                'time': int(datetime.timestamp(message.created_at))
            }
            messages.update({vid: newVid})
            await self.config.channel(channel).messages.set(messages)

    def get_yid(self, url: str):
        query = urlparse(url)
        if query.hostname == 'youtu.be': return query.path[1:]
        if query.hostname in {'www.youtube.com', 'youtube.com', 'music.youtube.com'}:
            if query.path == '/watch': return parse_qs(query.query)['v'][0]
            if query.path[:7] == '/watch/': return query.path.split('/')[1]
            if query.path[:7] == '/embed/': return query.path.split('/')[2]
            if query.path[:3] == '/v/': return query.path.split('/')[2]
        return None

    def cog_unload(self):
        self.background_clean.cancel()
