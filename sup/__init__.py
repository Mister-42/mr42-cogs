import discord
import json
from pathlib import Path
from redbot.core.bot import Red

from .sup import Sup

with open(Path(__file__).parent / "info.json") as fp:
	__red_end_user_data_statement__ = json.load(fp)["end_user_data_statement"]

async def setup(bot: Red) -> None:
	if discord.version_info.major == 2:
		await bot.add_cog(Sup(bot))
	else:
		bot.add_cog(Sup(bot))
