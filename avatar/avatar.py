import discord

from redbot.core import app_commands, commands
from redbot.core.i18n import Translator, cog_i18n
from redbot.core.utils.chat_formatting import bold, error
from typing import Optional

_ = Translator("Avatar", __file__)

@cog_i18n(_)
class Avatar(commands.Cog):
	"""Get a user's avatar."""

	@commands.hybrid_command(name="avatar", description="Get a user's avatar")
	@app_commands.describe(user="The user you wish to retrieve the avatar of")
	@app_commands.guild_only()
	async def avatar(self, ctx: commands.Context, user: discord.Member) -> None:
		"""Returns a user's avatar as attachment.

		User argument can be user mention, nickname, username, user ID.

		Defaults to requester when no argument is supplied."""
		message = _("{author} requested the avatar of {name}.").format(author=ctx.author.mention, name=bold(user.display_name))
		if user == ctx.author:
			message = _("Here is your avatar, {author}.").format(author=ctx.author.mention)
		elif user == ctx.me:
			message = _("This is _my_ avatar, {author}!").format(author=ctx.author.mention)
		elif isinstance(ctx.channel, discord.DMChannel):
			message = _("You requested the avatar of {name}.").format(name=bold(user.global_name))

		if isinstance(ctx.channel, discord.channel.DMChannel) or ctx.channel.permissions_for(ctx.guild.me).attach_files:
			async with ctx.typing():
				pfp = user.avatar if isinstance(ctx.channel, discord.channel.DMChannel) else user.display_avatar
				fileExt = "gif" if pfp and pfp.is_animated() else "png"
			return await ctx.send(message, file=await pfp.to_file(filename=f"pfp-{user.id}.{fileExt}"))
		elif ctx.channel.permissions_for(ctx.guild.me).embed_links:
			return await ctx.send(message + "\n" + user.display_avatar.url)

		await ctx.send(error(_("I do not have permission to attach files or embed links in this channel.")), ephemeral=True)

	async def red_delete_data_for_user(self, **kwargs) -> None:
		pass
