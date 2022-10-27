import datetime
from typing import Optional

import discord
from discord import option, slash_command
from discord.ext import commands, tasks

from . import database as db
from . import quickinputs as qi
from . import timestamps as ts
from . import offices
from .news import broadcast

C = {}


class Elections(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @slash_command(name='is_in_office', description='Check if a User is in office.')
    @option('player', discord.Member, description='Target\'s User ID')
    @option('office', str, description='Office to check')
    async def is_in_office(self, ctx, player_id:discord.Member, office:str):
        player_id = player_id.id
        if await db.Elections.is_in_office(player_id, office):
            await ctx.respond("Yes", ephemeral=True)
        else:
            await ctx.respond("No", ephemeral=True)
        
    @slash_command(name='elections', description='Show upcoming elections.')
    async def show_elections(self, ctx):
        embeds = []
        for office in offices.Offices:
            if not office.election_manager:
                continue
            embed = await office.election_manager.generate_embed()
            embeds.append(embed)
        await qi.PaginateEmbeds(ctx, embeds)

    @slash_command(name='vote', description='Vote in an election')
    async def vote(self, ctx, office:str):
        office = offices.get_office(office)
        if not office:
            await ctx.respond("Invalid office.")
            return
        if not office.election_manager:
            await ctx.respond("This office does not have an election manager.")
            return
        player_info = await db.Players.find_player(ctx.author.id)
        if not player_info["can_vote"]:
            await ctx.respond("You are not allowed to vote.")
            return
        await office.election_manager.capture_vote(ctx)
    
    @slash_command(name='check_eligibility', description='Get information about a User or Player.')
    async def check_eligibility(self, ctx, office:str):
        office = offices.get_office(office)
        if not office:
            await ctx.respond("Office not found.")
            return
        answer = await office.is_eligible_candidate(ctx.author)
        await ctx.respond(answer)

    @slash_command(name='reg', description='Register as a candidate for an office.')
    @option('office', str, description='The office you want to register for.')
    async def reg(self, ctx, office):
        office = offices.get_office(office)
        if not office:
            await ctx.respond("Office not found.")
            return  
        if not office.election_manager:
            await ctx.respond("This office does not have regular elections.", ephemeral=True)
            return

        election_manager = office.election_manager
        await election_manager.register_candidate(ctx)

    @slash_command(name='drop', description='Drop out of an election, this can be used at any time.')
    @option('office', str, description='The office you want to drop out of running for.')
    async def drop(self, ctx, office):
        office = offices.get_office(office)
        if not office:
            await ctx.respond("Office not found.")
            return  
        if not office.election_manager:
            await ctx.respond("This office does not have regular elections.", ephemeral=True)
            return
        
        election_manager = office.election_manager
        await election_manager.drop_candidate(ctx)

    @tasks.loop(hours=1)
    async def election_loop(self):
        for office in offices.Offices:
            if not office.election_manager:
                continue
            await office.election_manager.tick()


    @slash_command(name='debugadvanceelection', description='Manually trigger election_loop')
    @option('force_next', bool, description='Force the election to advance to the next stage, even if it is not time yet.')
    @commands.is_owner()
    async def debugadvanceelection(self, ctx, force_next:bool):
        await ctx.respond("Election loop triggered.", ephemeral=True)
        for office in offices.Offices:
            if not office.election_manager:
                continue
            await office.election_manager.tick(force_next)
        

def setup(bot, config):
    global C
    C = config
    bot.add_cog(Elections(bot))
