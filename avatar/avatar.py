import discord

from discord import app_commands
from redbot.core import commands
from redbot.core.i18n import Translator, cog_i18n
from redbot.core.utils.chat_formatting import bold, error
from typing import Optional

_ = Translator("Avatar", __file__)

@cog_i18n(_)
class Avatar(commands.Cog):
	"""Get a user's avatar."""

	@commands.command()
	async def avatar(self, ctx: commands.Context, user: Optional[discord.Member] = None) -> None:
		"""Returns a user's avatar as attachment.

		User argument can be user mention, nickname, username, user ID.

		Defaults to requester when no argument is supplied."""
		user = user or ctx.author
		message = _("{author} requested the avatar of {name}.").format(author=ctx.author.mention, name=bold(user.display_name))
		if user == ctx.author:
			message = _("Here is your avatar, {author}.").format(author=ctx.author.mention)
		elif user == ctx.me:
			message = _("This is _my_ avatar, {author}!").format(author=ctx.author.mention)
		elif isinstance(ctx.channel, discord.DMChannel):
			message = _("You requested the avatar of {name}.").format(name=bold(user.global_name))

		if isinstance(ctx.channel, discord.channel.DMChannel) or ctx.channel.permissions_for(ctx.guild.me).attach_files:
			async with ctx.typing():
				pfp = await self.getPfp(ctx, user)
			return await ctx.send(message, file=pfp)
		elif ctx.channel.permissions_for(ctx.guild.me).embed_links:
			return await ctx.send(message + "\n" + user.display_avatar.url)

		await ctx.send(error(_("I do not have permission to attach files or embed links in this channel.")))

	async def getPfp(self, ctx: commands.Context, user: discord.Member) -> discord.File:
		pfp = user.avatar if isinstance(ctx.channel, discord.channel.DMChannel) else user.display_avatar
		fileExt = "gif" if pfp and pfp.is_animated() else "png"
		filename = f"pfp-{user.id}.{fileExt}"
		return await pfp.to_file(filename=filename)

	@app_commands.command(name="avatar", description="Get a user's avatar")
	@app_commands.describe(user="The user you wish to retrieve the avatar of.")
	@app_commands.guild_only()
	async def slash_avatar(self, interaction: discord.Interaction, user: discord.Member):
		message = _("{author} requested the avatar of {name}.").format(author=interaction.user.mention, name=bold(user.display_name))
		if user == interaction.user:
			message = _("Here is your avatar, {author}.").format(author=interaction.user.mention)
		elif user == interaction.guild.me:
			message = _("This is _my_ avatar, {author}!").format(author=interaction.user.mention)

		if interaction.channel.permissions_for(interaction.guild.me).attach_files:
			pfp = await self.getPfp(interaction, user)
			return await interaction.response.send_message(message, file=pfp)
		elif interaction.channel.permissions_for(interaction.guild.me).embed_links:
			return await interaction.response.send_message(message + "\n" + user.display_avatar.url)

		await interaction.response.send_message(error(_("I do not have permission to attach files or embed links in this channel.")), ephemeral=True)

	async def red_delete_data_for_user(self, **kwargs) -> None:
		pass
