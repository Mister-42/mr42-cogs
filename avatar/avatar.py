import discord
from io import BytesIO
from redbot.core import commands
from redbot.core.i18n import Translator, cog_i18n
from redbot.core.utils.chat_formatting import bold
from typing import Literal, Optional

_ = Translator("Avatar", __file__)
RequestType = Literal["discord_deleted_user", "owner", "user", "user_strict"]

@cog_i18n(_)
class Avatar(commands.Cog):
    """Get user's avatar."""

    @commands.command()
    async def avatar(self, ctx: commands.Context, user: Optional[discord.Member] = None) -> None:
        """Returns a user's avatar as attachment.

        User argument can be user mention, nickname, username, user ID.

        Defaults to requester when no argument is supplied.
        """
        if not user:
            user = ctx.author

        if isinstance(ctx.channel, discord.channel.DMChannel) or ctx.channel.permissions_for(ctx.guild.me).attach_files:
            async with ctx.typing():
                pfp = BytesIO()

                fileExt = "png"
                if isinstance(ctx.channel, discord.channel.DMChannel):
                    await user.avatar.save(pfp)
                    if user.avatar and user.avatar.is_animated():
                        fileExt = "gif"
                else:
                    await user.display_avatar.save(pfp)
                    if user.display_avatar and user.display_avatar.is_animated():
                        fileExt = "gif"

                if user == ctx.author:
                    message = _("Here is your avatar, {name}.").format(name=ctx.author.mention)
                elif user == ctx.me:
                    message = _("This is _my_ avatar, {name}!").format(name=ctx.author.mention)
                elif isinstance(ctx.channel, discord.DMChannel):
                    message = _("You requested the avatar of {name}.").format(name=bold(user.name))
                else:
                    message = _("{author} requested the avatar of {name}.").format(author=ctx.author.mention, name=bold(user.name))

                pfp.seek(0)
                filename = f"pfp-{user.id}.{fileExt}"
            return await ctx.send(message, file=discord.File(pfp, filename=filename))

        elif ctx.channel.permissions_for(ctx.guild.me).embed_links:
            async with ctx.typing():
                pfp = user.display_avatar.url
            return await ctx.send(pfp)

        await ctx.send(_("I do not have permission to attach files or embed links in this channel."))

    async def red_delete_data_for_user(self, *, requester: RequestType, user_id: int) -> None:
        pass
