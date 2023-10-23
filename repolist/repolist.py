from inspect import getfile
from redbot.core import checks, commands
from redbot.core.bot import Red
from redbot.core.i18n import Translator
from redbot.core.utils.chat_formatting import box, pagify

class RepoList(commands.Cog):
	"""List all installed repos and their available cogs in one command."""
	def __init__(self, bot: Red) -> None:
		self.bot = bot

	@checks.is_owner()
	@commands.command()
	async def repolist(self, ctx: commands.Context) -> None:
		"""List all installed repos and their available cogs."""
		cog = self.bot.get_cog("Downloader")
		_ = Translator("Downloader", getfile(cog.__class__))
		repos = cog._repo_manager.repos
		sorted_repos = sorted(repos, key=lambda r: str.lower(r.name))
		if len(repos) == 0:
			await ctx.send(box(_("There are no repos installed.")))
		else:
			for repo in sorted_repos:
				sort_function = lambda x: x.name.lower()
				all_installed_cogs = await cog.installed_cogs()
				installed_cogs_in_repo = [cog for cog in all_installed_cogs if cog.repo_name == repo.name]
				installed_str = "\n".join(
					"- {}{}".format(i.name, ": {}".format(i.short) if i.short else "")
					for i in sorted(installed_cogs_in_repo, key=sort_function)
				)

				if len(installed_cogs_in_repo) > 1:
					installed_str = _("# Installed Cogs\n{text}").format(text=installed_str)
				elif installed_cogs_in_repo:
					installed_str = _("# Installed Cog\n{text}").format(text=installed_str)

				available_cogs = [
					cog for cog in repo.available_cogs if not (cog.hidden or cog in installed_cogs_in_repo)
				]
				available_str = "\n".join(
					"+ {}{}".format(cog.name, ": {}".format(cog.short) if cog.short else "")
					for cog in sorted(available_cogs, key=sort_function)
				)

				if not available_str:
					cogs = _("> Available Cogs\nNo cogs are available.")
				elif len(available_cogs) > 1:
					cogs = _("> Available Cogs\n{text}").format(text=available_str)
				else:
					cogs = _("> Available Cog\n{text}").format(text=available_str)
				header = "{}: {}\n{}".format(repo.name, repo.short or "", repo.url)
				cogs = header + "\n\n" + cogs + "\n\n" + installed_str
				for page in pagify(cogs, ["\n"], shorten_by=16):
					await ctx.send(box(page.lstrip(" "), lang="markdown"))

	async def red_delete_data_for_user(self, **kwargs) -> None:
		pass
