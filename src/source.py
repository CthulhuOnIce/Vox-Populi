import os
import sys
from typing import Optional

import discord
import git
import requests
from discord import option, slash_command
from discord.ext import commands, tasks

from . import database as db
from .news import broadcast

C = {}

class Source(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @slash_command(name='info', description='Get currently running environment and version information.')
    async def info(self, ctx):
        embed = discord.Embed(title='Info', description='Currently running environment and version information.')
        embed.add_field(name='Python Version', value=f'`{sys.version}`')
        embed.add_field(name='Discord Module Version', value=f'`{discord.__version__}`')
        embed.add_field(name='Git Commit', value=f'`{git.Repo(search_parent_directories=True).head.object.hexsha}`')
        embed.add_field(name='Git Branch', value=f'`{git.Repo(search_parent_directories=True).active_branch}`')
        await ctx.respond(embed=embed, ephemeral=True)

    @slash_command(name='last10', description='Get the last 10 commits made to the codebase.')
    async def last10(self, ctx):
        repo = git.Repo(search_parent_directories=True)
        embed = discord.Embed(title='Last 10 Commits', description='The last 10 commits made to the codebase.')
        limit = 10
        count = 0
        for commit in repo.iter_commits():
            if count == limit:
                break
            embed.add_field(name=f"`{commit.hexsha[:6]}` by {commit.author}", value=f'`{commit.message}`', inline=False)
            count += 1
        await ctx.respond(embed=embed, ephemeral=True)

    @tasks.loop(hours=0.5)
    async def check_for_updates(self):
        if not C["auto-update"]:
            return
        # check if there are any updates
        repo = git.Repo(search_parent_directories=True)
        if repo.is_dirty() and C["no-dirty-repo"]:  # if there are uncommitted changes, don't update
            print("Did not update, repo is dirty.")
            return
        if not repo.remotes.origin.fetch()[0].commit == repo.head.commit:  # if there are updates, update
            print("No missed commits, not updating.")
            return
        # pull changes
        try:
            repo.remotes.origin.pull(kill_after_timeout=20)
            # restart bot
            broadcast(self.bot, "updates", 2, "Restarting bot to upply update...")
            print("Restarting bot to apply updates...")
            os.execv(sys.argv[0], sys.argv)
        except Exception as e:  # TODO: make this more specific
            print(e)
            return
    
    @commands.Cog.listener()
    async def on_ready(self):
        await self.check_for_updates()


def setup(bot, config):
    global C
    C = config
    bot.add_cog(Source(bot))
