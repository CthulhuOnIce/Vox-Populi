import asyncio
import datetime
import os
import random
import sys
from typing import Optional

import discord
import git
import requests
from discord import option, slash_command
from discord.ext import commands, tasks

from . import database as db
from . import quickinputs as qi
from . import timestamps as ts
from .news import broadcast

C = {}

class Source(commands.Cog):
    bot: commands.Bot
    def __init__(self, bot):
        self.bot = bot

    @slash_command(name='info', description='Get currently running environment and version information.')
    async def info(self, ctx):
        repo = git.Repo(search_parent_directories=True)
        latest = repo.head.object
        message = latest.message.strip("\n")
        embed = discord.Embed(title='Info', description='Currently running environment and version information.')
        embed.add_field(name='Python Version', value=f'`{sys.version}`', inline=False)
        embed.add_field(name='Discord Module', value=f'`{discord.__title__} v.{discord.__version__}`', inline=False)
        embed.add_field(name='Git Commit', value=f'`{latest.hexsha}`', inline=False)
        embed.add_field(name='Git Commit Author', value=f'`{latest.author}`', inline=False)
        embed.add_field(name='Git Commit Date', value=f'`{ts.long_text(latest.committed_datetime)}`', inline=False)
        embed.add_field(name='Git Commit Message', value=f'`{message}`', inline=False)
        embed.add_field(name='Git Branch', value=f'`{repo.active_branch}`', inline=False)
        uptime = datetime.datetime.now() - C['started']
        embed.add_field(name='Uptime', value=uptime, inline=False)
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

    @slash_command(name='commits', description='List all commits')
    async def commits(self, ctx):
        repo = git.Repo(search_parent_directories=True)
        embeds = []
        for commit in repo.iter_commits():
            embed = discord.Embed(title=f'Commit `{commit.hexsha}`', description=f'`{commit.message}`', color=0x00ff00)
            embed.add_field(name='Author', value=commit.author, inline=False)
            embed.add_field(name='Date', value=ts.long_text(commit.committed_datetime), inline=False)
            embeds.append(embed)
        await qi.PaginateEmbeds(ctx, embeds)

    @slash_command(name='linkgithub', description='Link your GitHub account to your Discord account.')
    async def linkgithub(self, ctx):
        alphabet ="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        key = ''.join(random.choice(alphabet) for _ in range(32))
        try:
            await ctx.author.send(f"Key: `{key}`\nPlease create a github gist with this key somewhere in the content.\nThen, send the **raw** link to the gist here. You have 5 minutes.")
            await ctx.interaction.response.send_message('Check your DMs!', ephemeral=True)
        except discord.Forbidden:
            await ctx.respond("I couldn't DM you. Please enable DMs from server members.", ephemeral=True)
            return

        msg = None

        try:
            msg = await self.bot.wait_for('message', check=lambda m: m.author == ctx.author and 'gist.githubusercontent.com' in m.clean_content, timeout=300)
        except asyncio.TimeoutError:
            await ctx.author.send("You took too long to respond.")
            return

        if msg is None:
            await ctx.author.send("You took too long to respond.")
            return

        gist_url = msg.clean_content

        # if the gist size is > 1KB, refuse
        gist_size = requests.head(gist_url).headers['Content-Length']
        if int(gist_size) > 1024:
            await ctx.author.send("Your gist is too large. Please make it smaller.")
            return 

        gist_text = requests.get(gist_url).text
        username = gist_url.strip("https://gist.githubusercontent.com/").split('/')[0]
        api_response = requests.get(f"https://api.github.com/users/{username}").json()

        if key not in gist_text:
            await ctx.author.send("Your gist does not contain the key. Please try again.")
            return

        await db.Archives.link_github(ctx.author.id, api_response)
        await ctx.author.send(f"Your GitHub account (`{username}`) has been linked to your Discord account.\nYou may renew or change this account at any time by running `/linkgithub` again.")

    @tasks.loop(hours=0.5)
    async def check_for_updates(self):
        if not C["auto-update"]:
            return
        # check if there are any updates
        repo = git.Repo(search_parent_directories=True)
        if repo.is_dirty() and C["no-dirty-repo"]:  # if there are uncommitted changes, don't update
            print("Did not update, repo is dirty.")
            return
        remote = repo.remotes.origin.fetch()[0]
        if remote.commit.hexsha == repo.head.commit.hexsha:  # if there are updates, update
            print("No missed commits, not updating.")
            return
        if remote.commit.committed_date < repo.head.commit.committed_date:  # if the remote is older than the local, don't update
            print("Local commit is newer than remote, not updating.")
            return
        # pull changes
        try:
            repo.remotes.origin.pull(kill_after_timeout=20)
            # restart bot
            broadcast(self.bot, "updates", 2, "Restarting bot to upply update...")
            print("Restarting bot to apply updates...")
            os.execv(sys.executable, [sys.executable] + sys.argv)
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
