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
        # check if election is open
        election = await db.Elections.get_office(office)
        if not election:
            await ctx.respond("No office found with that name.")
            return
        if not "regular_elections" in election:
            await ctx.respond("This office does not have regular elections.", ephemeral=True)
            return
        re = election["regular_elections"]
        if not await db.Elections.is_eligible_for_office(ctx.author.id, office):
            await ctx.respond("You are not eligible for this office.", ephemeral=True)
            return
        if re["stage"] != "nomination":
            await ctx.respond("Nominations are not open for this office.", ephemeral=True)
            return
        if ctx.author.id in re["candidates"]:
            await ctx.respond("You are already a candidate for this office. Use /drop to drop out of the running.", ephemeral=True)
            return
        broadcast(self.bot, "nomination", 2, f"{ctx.author.mention} has registered as a candidate for {office}!")
        await db.Elections.make_candidate(ctx.author.id, election["_id"])
        await ctx.respond("You have been registered as a candidate for this office.", ephemeral=True)
    
    @slash_command(name='drop', description='Drop out of an election, this can be used at any time.')
    @option('office', str, description='The office you want to drop out of running for.')
    async def drop(self, ctx, office):
        election = await db.Elections.get_office(office)
        if not election:
            await ctx.respond("No office found with that name.")
            return
        if not "regular_elections" in election:
            await ctx.respond("This office does not have regular elections.", ephemeral=True)
            return
        re = election["regular_elections"]
        if ctx.author.id not in re["candidates"]:
            await ctx.respond("You are not a candidate for this office.", ephemeral=True)
            return
        if re["stage"] == "voting":
            await ctx.respond("You cannot drop out of an election after voting has started.", ephemeral=True)
            return
        if re["stage"] == "campaigning":
            broadcast(self.bot, "nomination", 2, f"{ctx.author.mention} has dropped out of the running for {office}!")
            return
        await db.Elections.drop_candidate(ctx.author.id, election["_id"])
        await ctx.respond("You have dropped out of the running for this office.", ephemeral=True)

    @tasks.loop(hours=1)
    async def election_loop(self):
        for office in await db.Elections.get_all_offices():
            if not "regular_elections" in office:
                continue
            term_end = office["regular_elections"]["last_election"] + datetime.timedelta(days=office["regular_elections"]["term_length"])

            nomination_days = office["regular_elections"]["stages"]["nomination"]
            campaigning_days = office["regular_elections"]["stages"]["campaigning"]
            voting_days = office["regular_elections"]["stages"]["voting"]
            lame_duck_days = office["regular_elections"]["stages"]["lame_duck"]

            nomination_day = term_end - datetime.timedelta(days=(nomination_days + campaigning_days + voting_days + lame_duck_days))  # official start of election period

            if office["regular_elections"]["next_stage"] == None:  # election is not running whatsoever
                if datetime.datetime.now() > nomination_day:  # starts election with nomination
                    self.bot.dispatch(event_name="election_start", office=office)
                    broadcast(self.bot, "election", 5, f"Election for {office['_id']} is opening soon! You can now nominate yourself for the position, if eligible.")
                    next_stage = datetime.datetime.now() + datetime.timedelta(days=nomination_days)
                    await db.Elections.set_election_stage(office["_id"], next_stage, "nomination")  # sets the current stage to nomination, expires in x days, end
                    continue
            else:
                if datetime.datetime.now() > office["regular_elections"]["next_stage"]:  # if the current stage has expired
                    if office["regular_elections"]["stage"] == "nomination":  # nomination -> campaigning
                        # TODO: check if there are enough candidates, if not, extend the nomination period or concede the election by default
                        await db.Elections.increment_terms_missed(office["_id"])
                        broadcast(self.bot, "election", 5, f"Nomination for {office['_id']} has ended! You can now campaign for the position, if you were nominated.")
                        next_stage = datetime.datetime.now() + datetime.timedelta(days=campaigning_days)
                        await db.Elections.set_election_stage(office["_id"], next_stage, "campaigning")

                    if office["regular_elections"]["stage"] == "campaigning": # campaigning -> voting
                        broadcast(self.bot, "election", 5, f"The voting period for {office['_id']} has started! You have {voting_days} days to vote!")
                        next_stage = datetime.datetime.now() + datetime.timedelta(days=voting_days)
                        await db.Elections.set_election_stage(office["_id"], next_stage, "voting")

                    if office["regular_elections"]["stage"] == "voting":  # voting -> lame duck
                        winners = [self.bot.get_user(int(user)) for user in await db.Elections.get_election_winners(office["_id"])]
                        broadcast(self.bot, "election", 5, f"The voting period for {office['_id']} has ended! The winners are {', '.join([winner.mention for winner in winners])}!\nThey will take office in {lame_duck_days} days.")
                        next_stage = datetime.datetime.now() + datetime.timedelta(days=lame_duck_days)
                        await db.Elections.set_election_stage(office["_id"], next_stage, "lame_duck")

                    if office["regular_elections"]["stage"] == "lame_duck":  # lame duck -> election end
                        broadcast(self.bot, "election", 5, f"The term for {office['_id']} has ended! The next election will start in {office['regular_elections']['term_length']} days.")
                        winners = await db.Elections.get_election_winners(office["_id"])
                        await db.Elections.set_new_officers(winners, office["_id"])
                        role = C["guild"].get_role(office["roleid"])
                        # demote everyone who lost
                        for member in role.members:
                            if not member.id in winners:
                                await member.remove_roles(role)
                        # promote everyone who won
                        for winner in winners:
                            winner = int(winner)
                            member = C["guild"].get_member(winner)
                            await member.add_roles(role)

                        broadcast(self.bot, "election", 5, f"The new term for {office['_id']} has started! Congratulations to the new officers!")

                        await db.Elections.set_election_stage(office["_id"], None, None)
                        await db.Elections.set_last_election(office["_id"], datetime.datetime.now())
                        await db.Elections.reset_votes(office["_id"])
                        await db.Elections.apply_restriction_queue(office["_id"])  # look into the possibility of doing this before nomination starts
        return


    @slash_command(name='debugadvanceelection', description='Manually trigger election_loop')
    @option('force_next', bool, description='Force the election to advance to the next stage, even if it is not time yet.')
    @commands.is_owner()
    async def debugadvanceelection(self, ctx, force_next):
        await ctx.interaction.response.defer()
        await ctx.respond("Election loop triggered.", ephemeral=True)
        if force_next:
            for office in await db.Elections.get_all_offices():
                if not "regular_elections" in office:
                    continue
                if office["regular_elections"]["next_stage"] == None:
                    await db.Elections.set_last_election(office["_id"], datetime.datetime.now() - datetime.timedelta(days=office["regular_elections"]["term_length"]*3))
                else:
                    yesterday = datetime.datetime.now() - datetime.timedelta(days=1)
                    await db.Elections.set_election_stage(office["_id"], yesterday, office["regular_elections"]["stage"])
        await self.election_loop()
        

def setup(bot, config):
    global C
    C = config
    bot.add_cog(Elections(bot))
