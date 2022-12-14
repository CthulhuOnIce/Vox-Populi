# just a template to copy and paste for use in developing cogs in the future

from typing import Optional

import discord
import yaml
from discord import Embed, option, slash_command
from discord.ext import commands, tasks

from . import database as db
from . import motionenforcement as MM
from . import quickinputs as qi

C = {}

class Debug(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @slash_command(name='dpag', description='Test embed paginator')
    async def dpag(self, ctx):
        await qi.PaginateEmbeds(ctx, [Embed(title="Test 1"), Embed(title="Test 2"), Embed(title="Test 3")])
    
    @slash_command(name='flmo', description='Clear all motions.')
    async def flmo(self, ctx):
        if not await qi.quickConfirm(ctx, "Are you sure you want to clear all motions?"):
            return
        dbo = await db.create_connection("Motions")
        await dbo.drop()
        await ctx.respond("All motions cleared.", ephemeral=True)

    @slash_command(name='popo', description='Run db.populate_offices()')
    @commands.is_owner()
    async def popo(self, ctx):
        await db.Elections.populate_offices()
        await ctx.respond("Done!")

    @slash_command(name='roff', description='Delete all offices')
    @commands.is_owner()
    async def roff(self, ctx):
        await db.Elections.remove_offices()
        await ctx.respond("Done!")

    @slash_command(name='repopo', description='roff + popo')
    async def repopo(self, ctx):
        await db.Elections.remove_offices()
        await db.Elections.populate_offices()
        await ctx.respond("Done!")

    @slash_command(name='tmc', description='Test qi.quickBMC')
    @commands.is_owner()
    @option('num_options', int, description='Number of options in the list')
    @option('min_answers', int, description='Minimum number of answers')
    @option('max_answers', int, description='Maximum number of answers')
    async def tmc(self, ctx, num_options, min_answers, max_answers):
        candidates = [f"Test Option {i+1}" for i in range(10)]

        choices = await qi.quickBMC(ctx, f"Select options. Min: {min_answers} Max {max_answers}", candidates, max_answers=max_answers, min_answers=min_answers)

        msg_choices = [f"Choice #{i+1}: {choice}" for i, choice in enumerate(choices)]
        msg = "```"
        msg += "\n".join(msg_choices)
        msg += "```"

        await ctx.respond(msg, ephemeral=True)

    @slash_command(name='aleg', description='Instantly execute a yaml file as a motion.')
    @commands.is_owner()
    async def aleg(self, ctx):
        await ctx.respond("Upload a yaml file to execute a motion.")
        # wait for a yaml file to be uploaded
        res = await self.bot.wait_for('message', check=lambda m: m.author == ctx.author and m.channel == ctx.channel and m.attachments)
        # download yaml file and load as json with pyyaml safe load
        edit_me = await res.reply("Loading yaml file...")
        yaml_file = res.attachments[0]
        yaml_file = await yaml_file.read()
        yaml_file = yaml.load(yaml_file, Loader=yaml.SafeLoader)
        
        motion = MM.Motion(yaml_file, self.bot, C["guild"], C)

        x = await motion.self_test()
        if x:
            await edit_me.edit(content=x)
            return
        # replace edit_me with a message and a reaction menu to cancel or confirm the motion
        await edit_me.edit(content="Motion loaded. React to confirm or cancel.")
        await edit_me.add_reaction("???")
        await edit_me.add_reaction("???")
        # wait for a reaction
        res = await self.bot.wait_for('reaction_add', check=lambda r, u: u == ctx.author and r.message == edit_me)
        if res[0].emoji == "???":
            await edit_me.edit(content="Motion cancelled.")
            return
        # execute motion
        x = await motion.execute()
        if x:
            await edit_me.edit(content=x)
            return
        await edit_me.edit(content="Motion executed.")

    @commands.user_command(name="Make Legislator")  # create a user command for the supplied guilds
    @commands.is_owner()
    async def make_legislator(self, ctx, member: discord.Member):  # user commands return the member

        if not await db.Elections.is_officer(member.id, "Legislator"):
            await db.Elections.set_new_officer(member.id, "Legislator")
            await ctx.respond(f"Made {member.mention} a legislator.", ephemeral=True)
        else:
            await ctx.respond(f"{member.mention} is already a legislator.", ephemeral=True)
    
    @commands.user_command(name="Fire Legislator")  # create a user command for the supplied guilds
    @commands.is_owner()
    async def fire_legislator(self, ctx, member: discord.Member):  # user commands return the member
        if await db.Elections.is_officer(member.id, "Legislator"):
            await db.Elections.remove_officer(member.id, "Legislator")
            await ctx.respond(f"Fired {member.mention} from the legislature.", ephemeral=True)
        else:
            await ctx.respond(f"{member.mention} is not a legislator.", ephemeral=True)

def setup(bot, config):
    global C
    C = config
    bot.add_cog(Debug(bot))
