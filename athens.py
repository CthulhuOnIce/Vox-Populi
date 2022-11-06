import asyncio
from inspect import getargvalues
import os
import subprocess
import sys
import traceback
from datetime import datetime

import discord
import yaml
from discord.ext import commands

from src import debug, electionmanager, legislation, recordkeeping, source, timestamps, offices, testing

# from disputils import BotEmbedPaginator, BotConfirmation, BotMultipleChoice
CI = False
TOKEN_ENV = "vox-token"
GUILD_ENV = "vox-guild"

try:
    with open("config.yml", "r") as r:
        C = yaml.load(r.read(), Loader=yaml.FullLoader)
except FileNotFoundError:
    if "token" in os.environ:
        C = {"token": os.environ["token"]}
    print("No config.yml, please copy and rename config-example.yml and fill in the appropriate values.")
    exit()

C["started"] = datetime.now()

if "vox-token" in os.environ:
    C["token"] = os.environ["vox-token"]
    CI = True

feedbacktimeout = []

intents = discord.Intents.all()

bot = commands.Bot(intents=intents, owner_id=C["sudoers"][0])

# Setup cogs
recordkeeping.setup(bot, C)
debug.setup(bot, C)
electionmanager.setup(bot, C)
legislation.setup(bot, C)
source.setup(bot, C)


@bot.event
async def on_connect():
    # start subsystems
    await offices.populate(bot, C)

@bot.event
async def on_ready():  # I just like seeing basic info like this
    C["bot"] = bot
    C["guild"] = bot.get_guild(int(os.environ[GUILD_ENV]) if CI else C["guild_id"])
    if not C["guild"]:
        print(f"Guild not found, please check your config.yml (or {GUILD_ENV} env variable if running in CI)")
        exit()
    print("-----------------Info-----------------")
    print(f"Total Servers: {len(bot.guilds)}")
    # CI tests
    if "--test" in sys.argv or CI:
        await testing.test(bot, C)

@bot.event
async def on_application_command_error(ctx, error):  # share certain errors with the user
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.BadArgument):
        await ctx.send(f"Bad Argument: {error}")
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"Missing Argument: {error}")
        return
    if isinstance(error, commands.CommandInvokeError):
        original = error.original
        if isinstance(original, IndexError):
            await ctx.send(f"IndexError: {original}\n[This might mean your search found no results]")
            return
    await ctx.respond("That command caused an error. This has been reported to the developer.", ephemeral=True)
    
    error_log = "\n-----------------Error-----------------\n"
    error_log += f"Error: {type(error).__name__}: {error}\n"
    error_log += f"TimeStamp: {timestamps.short_text(datetime.now())}\n"
    if ctx:
        error_log += f"Cog: {ctx.command.cog.__class__.__name__}\n"
        error_log += f"Command: {ctx.command}\n"
        error_log += f"Author: {ctx.author}\n"
        error_log += f"Channel: {ctx.channel}\n"
        if getattr(ctx, "args", None):
            error_log += f"Args: {ctx.args}\n"
        if getattr(ctx, "kwargs", None):
            error_log += f"Kwargs: {ctx.kwargs}\n"
    else:
        error_log += "No Context\n"
    error_log += f"Traceback:\n{''.join(traceback.format_exception(type(error), error, error.__traceback__))}"
    # error_log += f"Args: {ctx.args}\n"
    with open("logs/errors.log", "a+") as a:
        a.write(error_log)
    print(error_log)

bot.run(C["token"])
