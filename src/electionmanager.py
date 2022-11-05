import datetime
from typing import Optional

import discord
from discord import option, slash_command
from discord.ext import commands, tasks

from . import database as db
from . import quickinputs as qi
from . import timestamps as ts
from .news import broadcast

C = {}
def th(num:int):  # returns the ordinal of a number
    if num == 1:
        return f"{num}st"
    elif num == 2:
        return f"{num}nd"
    elif num == 3:
        return f"{num}rd"
    else:
        return f"{num}th"

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
        offices = await db.Elections.get_all_offices()
        embeds = []
        for office in offices:
            if "regular_elections" not in office:
                continue
            name = office["_id"]
            re = office["regular_elections"]
            embed = discord.Embed(title="Elections", description=name, color=0x00ff00)
            term_start = re["last_election"]
            term_end = term_start + datetime.timedelta(days=re["term_length"])
            election_season_length = re["stages"]["nomination"] + re["stages"]["campaigning"] + re["stages"]["voting"] + re["stages"]["lame_duck"]
            next_election_season_start = term_end - datetime.timedelta(days=election_season_length)
            term_end - datetime.timedelta(days=election_season_length)
            field_value = f"**Election Type:** {re['type']}\n**Term Start:** `{ts.simple_day(term_start)}`"
            field_value += f"\n**Key Dates:**\n"
            field_value += f" - **Nomination:**\n - - `{ts.simple_day(next_election_season_start)}`\n - - `{ts.simple_day(next_election_season_start + datetime.timedelta(days=re['stages']['nomination']))}`\n"
            field_value += f" - **Campaigning:**\n - - `{ts.simple_day(next_election_season_start + datetime.timedelta(days=re['stages']['nomination']))}` \n - - `{ts.simple_day(next_election_season_start + datetime.timedelta(days=re['stages']['nomination'] + re['stages']['campaigning']))}`\n"
            field_value += f" - **Voting:**\n - - `{ts.simple_day(next_election_season_start + datetime.timedelta(days=re['stages']['nomination'] + re['stages']['campaigning']))}`\n - - `{ts.simple_day(next_election_season_start + datetime.timedelta(days=re['stages']['nomination'] + re['stages']['campaigning'] + re['stages']['voting']))}`\n"
            if re["stages"]["lame_duck"] > 0:
                field_value += f" - **Lame Duck:**\n - - `{ts.simple_day(next_election_season_start + datetime.timedelta(days=re['stages']['nomination'] + re['stages']['campaigning'] + re['stages']['voting']))}`\n - - `{ts.simple_day(next_election_season_start + datetime.timedelta(days=election_season_length))}`"
            field_value += f"\n**Term End:** `{ts.simple_day(term_end)}`\n**Term Length:** `{re['term_length']} days`\n**Seats:** `{re['seats']}`"
            if re["next_stage"]:
                field_value += f"\n**Next Stage:** `{ts.simple_day(re['next_stage'])}`\nCurrent Stage: {re['stage']}"
            embed.add_field(name=office["_id"], value=field_value)
            embeds.append(embed)
        await qi.PaginateEmbeds(ctx, embeds)

    async def simple_vote(self, ctx, office:str):
        # check if user has already voted
        election = await db.Elections.get_office(office)
        re = election["regular_elections"]

        if ctx.author.id in re["voters"]:
            await ctx.respond("You have already voted in this election.")
            return
        await db.Elections.add_voter(ctx.author.id, election["_id"])

        candidates = re["candidates"]
        candidates_dict = {str(C["guild"].get_member(candidate)): str(candidate) for candidate in candidates}
        candidates_str = list(candidates_dict.keys())
        limit = re["seats"]

        choices = await qi.quickBMC(ctx, f"Select your preferred candidates. Max: {re['seats']}", candidates_dict, max_answers=re["seats"])
        choices = [int(choice) for choice in choices]

        msg_choices = [f"{th(i+1)} choice: {C['guild'].get_member(choice)}" for i, choice in enumerate(choices)]
        msg = "```" + "\n".join(msg_choices)
        msg += "```\n"
        msg += "Are you sure you want to vote for these candidates?"

        accept = await qi.quickConfirm(ctx, msg)
        if accept:
            for choice in choices:
                await db.Elections.cast_vote_simple(ctx.author.id, election["_id"], choice)
            await ctx.respond("Your vote has been cast.", ephemeral=True)
        else:
            await db.Elections.remove_voter(ctx.author.id, election["_id"])
            await ctx.respond("Vote cancelled.", ephemeral=True)

    @slash_command(name='vote', description='Vote in an election')
    async def vote(self, ctx, office:str):
        # check if election is open
        election = await db.Elections.get_office(office)
        if not election:
            await ctx.respond("No office found with that name.")
            return
        if "regular_elections" not in election:
            await ctx.respond("This office does not have regular elections.", ephemeral=True)
            return
        player_info = await db.StatTracking.find_player(ctx.author.id)
        if not player_info["can_vote"]:
            await ctx.respond("You are not allowed to vote.")
            return
        re = election["regular_elections"]
        if re["stage"] != "voting":
            await ctx.respond("Voting is not open for this office.", ephemeral=True)
            return
        if re["type"] == "simple":
            await self.simple_vote(ctx, office)

    @slash_command(name='reg', description='Register as a candidate for an office.')
    @option('office', str, description='The office you want to register for.')
    async def reg(self, ctx, office):
        # check if election is open
        election = await db.Elections.get_office(office)
        if not election:
            await ctx.respond("No office found with that name.")
            return
        if "regular_elections" not in election:
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
        if "regular_elections" not in election:
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
            if "regular_elections" not in office:
                continue
            term_end = office["regular_elections"]["last_election"] + datetime.timedelta(days=office["regular_elections"]["term_length"])

            nomination_days = office["regular_elections"]["stages"]["nomination"]
            campaigning_days = office["regular_elections"]["stages"]["campaigning"]
            voting_days = office["regular_elections"]["stages"]["voting"]
            lame_duck_days = office["regular_elections"]["stages"]["lame_duck"]

            nomination_day = term_end - datetime.timedelta(days=(nomination_days + campaigning_days + voting_days + lame_duck_days))  # official start of election period

            if office["regular_elections"]["next_stage"] is None:  # election is not running whatsoever
                if datetime.datetime.now() > nomination_day:  # starts election with nomination
                    self.bot.dispatch(event_name="election_start", office=office)
                    broadcast(self.bot, "election", 5, f"Election for {office['_id']} is opening soon! You can now nominate yourself for the position, if eligible.")
                    next_stage = datetime.datetime.now() + datetime.timedelta(days=nomination_days)
                    await db.Elections.set_election_stage(office["_id"], next_stage, "nomination")  # sets the current stage to nomination, expires in x days, end
            elif datetime.datetime.now() > office["regular_elections"]["next_stage"]:  # if the current stage has expired
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
                        if member.id not in winners:
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
                if "regular_elections" not in office:
                    continue
                if office["regular_elections"]["next_stage"] is None:
                    await db.Elections.set_last_election(office["_id"], datetime.datetime.now() - datetime.timedelta(days=office["regular_elections"]["term_length"]*3))
                else:
                    yesterday = datetime.datetime.now() - datetime.timedelta(days=1)
                    await db.Elections.set_election_stage(office["_id"], yesterday, office["regular_elections"]["stage"])
        await self.election_loop()
        

def setup(bot, config):
    global C
    C = config
    bot.add_cog(Elections(bot))
