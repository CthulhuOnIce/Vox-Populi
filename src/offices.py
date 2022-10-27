import asyncio
from datetime import datetime, timedelta

import discord

from . import database as db
from . import quickinputs as qi
from . import timestamps as ts
from .news import broadcast

C = None

Offices = []

def th(num:int):  # returns the ordinal of a number
    if num == 1:
        return f"{num}st"
    elif num == 2:
        return f"{num}nd"
    elif num == 3:
        return f"{num}rd"
    else:
        return f"{num}th"

# used for simple elections, use as a prototype for more advanced election styles
class ElectionManager:
    enabled           = False
    current_stage     = None

    election_style    = None
    last_election     = None
    next_stage        = None
    term_length       = 0

    office            = None
    guild             = None

    stage             = None
    nomination_stage  = 0
    campaigning_stage = 0
    voting_stage      = 0
    lame_duck_stage   = 0

    voters            = []

    # appointers = []  # list of office IDs that can appoint candidates / officers

    candidates = {}
    # votes = {}

    def __init__(self, office, reg_elections:dict):
        self.office = office
        self.guild = office.guild
        if reg_elections:
            self.enabled            = True

            self.stage              = reg_elections["stage"]

            self.election_style     = reg_elections["type"]
            self.last_election      = reg_elections["last_election"]
            self.next_stage         = reg_elections["next_stage"]
            self.term_length        = reg_elections["term_length"]

            self.nomination_stage   = reg_elections["stages"]["nomination"]
            self.campaigning_stage  = reg_elections["stages"]["campaigning"]
            self.voting_stage       = reg_elections["stages"]["voting"]
            self.lame_duck_stage    = reg_elections["stages"]["lame_duck"]

            self.voters             = [ self.guild.get_member(voter) for voter in reg_elections["voters"] ]
            for candidate in reg_elections["candidates"]:
                self.candidates[self.guild.get_member(candidate)] = reg_elections["candidates"][candidate]

            self.votes              = reg_elections["votes"]

    async def register_candidate(self, ctx):
        if not self.stage == "nomination":
            await ctx.respond("The nominations for this election have already closed.", ephemeral=True)
            return
        if not await self.office.is_eligible_candidate(ctx.author):
            await ctx.respond("You are not eligible for this office.", ephemeral=True)
            return
        if ctx.author in self.candidates:
            await ctx.respond("You have already registered for this election, use /drop to withdraw.", ephemeral=True)
            return
        self.candidates[ctx.author] = []
        await db.Elections.make_candidate(ctx.author.id, self.office.name)
        await ctx.respond("You have been registered as a candidate.", ephemeral=True)
        broadcast(self.bot, "nomination", 2, f"{ctx.author.mention} has registered as a candidate for {office}!")

    async def drop_candidate(self, member):
        return await db.Elections.drop_candidate(member.id, self.office.name)

    async def get_winners(self):
        return await db.Elections.get_election_winners(self.office.name)
    
    async def appoint_winners(self):
        winners = await self.get_winners()
        return winners

    async def advance_stage(self):
        term_end = self.last_election + datetime.timedelta(days=self.term_length)

        nomination_day = term_end - datetime.timedelta(days=(self.nomination_stage + self.campaigning_stage + self.voting_stage + self.lame_duck_stage))  # official start of election period

        if self.next_stage == None:  # election is not running whatsoever
            if datetime.datetime.now() > nomination_day:  # starts election with nomination
                self.bot.dispatch(event_name="election_start", office=self.office.name)
                broadcast(self.bot, "election", 5, f"Election for {self.office.name} is opening soon! You can now nominate yourself for the position, if eligible.")
                next_stage = datetime.datetime.now() + datetime.timedelta(days=self.nomination_stage)
                await db.Elections.set_election_stage(self.office.name, next_stage, "nomination")  # sets the current stage to nomination, expires in x days, end
                return
        else:
            if datetime.datetime.now() > self.next_stage:  # if the current stage has expired
                if self.stage == "nomination":  # nomination -> campaigning
                    # TODO: check if there are enough candidates, if not, extend the nomination period or concede the election by default
                    await db.Elections.increment_terms_missed(self.office.name)
                    broadcast(self.bot, "election", 5, f"Nomination for {self.office.name} has ended! You can now campaign for the position, if you were nominated.")
                    self.next_stage = datetime.datetime.now() + datetime.timedelta(days=self.campaigning_stage)
                    self.stage = "campaigning"

                if self.stage == "campaigning": # campaigning -> voting
                    broadcast(self.bot, "election", 5, f"The voting period for {self.office.name} has started! You have {self.voting_stage} days to vote!")
                    self.next_stage = datetime.datetime.now() + datetime.timedelta(days=self.voting_stage)
                    self.stage = "voting"

                if self.stage == "voting":  # voting -> lame duck
                    winners = await self.get_winners()
                    broadcast(self.bot, "election", 5, f"The voting period for {self.office.name} has ended! The winners are {', '.join([winner.mention for winner in winners])}!\nThey will take office in {self.lame_duck_stage} days.")
                    self.next_stage = datetime.datetime.now() + datetime.timedelta(days=self.lame_duck_stage)
                    self.stage = "lame_duck"

                if self.stage == "lame_duck":  # lame duck -> election end
                    broadcast(self.bot, "election", 5, f"The term for {self.office.name} has ended! The next election will start in {self.term_length} days.")
                    winners = await db.Elections.get_election_winners(self.office.name)
                    await db.Elections.set_new_officers(winners, self.office.name)
                    role = self.office.role
                    # demote everyone who lost
                    for member in role.members:
                        if not member.id in winners:
                            await member.remove_roles(role)
                    # promote everyone who won
                    for winner in winners:
                        winner = int(winner)
                        member = C["guild"].get_member(winner)
                        await member.add_roles(role)

                    broadcast(self.bot, "election", 5, f"The new term for {self.office.name} has started! Congratulations to the new officers!")

                    self.next_stage = None
                    self.stage = None

                    await db.Elections.set_last_election(self.office.name, datetime.datetime.now())
                    await db.Elections.reset_votes(self.office.name)
                    await db.Elections.apply_restriction_queue(self.office.name)
                
                await db.Elections.set_election_stage(self.office.name, self.next_stage, self.stage)

    async def tick(self):
        if self.next_stage >= datetime.now():
            await self.advance_stage()

    async def register_candidate(self, player):
        if not await self.is_eligible_candidate(player):
            return False

    async def generate_embed(self):
        name = self.office.name
        embed = discord.Embed(title="Elections", description=name, color=0x00ff00)
        term_start = self.last_election
        term_end = term_start + timedelta(days=self.term_length)
        election_season_length = self.nomination_stage + self.campaigning_stage + self.voting_stage + self.lame_duck_stage
        next_election_season_start = term_end - timedelta(days=election_season_length)
        term_end - timedelta(days=election_season_length)
        field_value = f"**Election Type:** {self.election_style}\n**Term Start:** `{ts.simple_day(term_start)}`"
        field_value += f"\n**Key Dates:**\n"
        field_value += f" - **Nomination:**\n - - `{ts.simple_day(next_election_season_start)}`\n - - `{ts.simple_day(next_election_season_start + timedelta(days=self.nomination_stage))}`\n"
        field_value += f" - **Campaigning:**\n - - `{ts.simple_day(next_election_season_start + timedelta(days=self.nomination_stage))}` \n - - `{ts.simple_day(next_election_season_start + timedelta(days=self.nomination_stage + self.campaigning_stage))}`\n"
        field_value += f" - **Voting:**\n - - `{ts.simple_day(next_election_season_start + timedelta(days=self.nomination_stage + self.campaigning_stage))}`\n - - `{ts.simple_day(next_election_season_start + timedelta(days=self.nomination_stage + self.campaigning_stage + self.voting_stage))}`\n"
        if self.lame_duck_stage > 0:
            field_value += f" - **Lame Duck:**\n - - `{ts.simple_day(next_election_season_start + timedelta(days=self.nomination_stage + self.campaigning_stage + self.voting_stage))}`\n - - `{ts.simple_day(next_election_season_start + timedelta(days=election_season_length))}`"
        field_value += f"\n**Term End:** `{ts.simple_day(term_end)}`\n**Term Length:** `{self.term_length} days`\n**Seats:** `{self.office.seats}`"
        if self.next_stage:
            field_value += f"\n**Next Stage:** `{ts.simple_day(self.next_stage)}`\nCurrent Stage: {self.stage}"
        embed.add_field(name=self.office.name, value=field_value)
        return embed
    
    async def capture_vote(self, ctx):
        # already done voted
        if ctx.author in self.voters:
            await ctx.respond("You have already voted in this election.")
            return

        self.voters.append(ctx.author)
        await db.Elections.add_voter(ctx.author.id, self.office.name)

        candidates_dict = {str(candidate): candidate for candidate in self.candidates}
        limit = self.office.seats

        choices = await qi.quickBMC(ctx, f"Select your preferred candidates. Max: {limit}", candidates_dict, max_answers=limit)

        msg_choices = [f"{th(i+1)} choice: {choice}" for i, choice in enumerate(choices)]
        msg = "```"
        msg += "\n".join(msg_choices)
        msg += "```\n"
        msg += "Are you sure you want to vote for these candidates?"

        accept = await qi.quickConfirm(ctx, msg)
        if accept:
            for choice in choices:
                self.votes[choice].append(ctx.author)
                await db.Elections.cast_vote_simple(ctx.author.id, self.office.name, choice)
            await ctx.respond("Your vote has been cast.", ephemeral=True)
        else:
            self.voters.remove(ctx.author)
            await db.Elections.remove_voter(ctx.author.id, self.office.name)
            await ctx.respond("Vote cancelled.", ephemeral=True)

class RankedChoice(ElectionManager):
    def __init__(self, office, reg_elections:dict):
        super().__init__(office, reg_elections)

class Office:
    name         = None
    role         = None
    guild        = None
    members      = []
    flags        = []
    generataion  = 0
    seats        = 0

    min_messages          = 0
    min_age_days          = 0
    total_term_limit      = 0
    successive_term_limit = 0

    # regualar election handline
    election_manager:ElectionManager = None

    async def New(self, bot, config, office):
        self.name = office["_id"]
        self.seats = office["seats"]

        if "regular_elections" in office:
            if office["regular_elections"]["type"] == "simple":
                self.election_manager = ElectionManager(self, office["regular_elections"])
            elif office["regular_elections"]["type"] == "ranked_choice":
                self.election_manager = RankedChoice(self, office["regular_elections"])
            elif office["regular_elections"]["type"] == "challenger":  # TODO: implement challenger elections
                pass
            elif office["regular_elections"]["type"] == "approval":  # TODO: implement approval elections
                pass
            else:
                raise Exception("Unknown election style: " + office["regular_elections"]["type"])

        if not office:
            raise ValueError("Office not found")

        self.guild = bot.get_guild(config['guild_id'])
        self.role = self.guild.get_role(office["roleid"])
        self.generataion = office["generations"]

        for officer in await db.Elections.get_officers(office["_id"]):
            user = self.guild.get_member(officer["_id"])
            if not user:  pass # User left the server, TODO: remove from office
            self.members.append(user)
        
        Offices.append(self)
    
    async def database(self):
        return await db.get_office(self.name)

    async def set_future_limit(self, requirements:dict):
        database = self.database()
        db.Elections.set_office_requirments_queue(database, requirements)

    async def is_eligible_candidate(self, member):
        player = await db.Archives.get_player(member.id)
        officer = await db.Elections.get_officer(member.id)
        if self.min_messages:
            if player.messages < self.min_messages:
                return False
        if self.min_age_days:
            joined = player["joined"]
            if joined:
                if (datetime.now() - joined).days < self.min_age_days:
                    return False
        if officer:
            if self.total_term_limit:
                if officer["terms_served_total"] >= self.total_term_limit:
                    return False
            if self.successive_term_limit:
                if officer["terms_served_successively"] >= self.successive_term_limit:
                    return False
        return True

    async def apply_restrictions_queue(self):
        database = self.database()
        self.min_age_days = database["requirements_queue"]["min_age_days"]
        self.min_messages = database["requirements_queue"]["min_messages"]
        self.total_term_limit = database["requirements_queue"]["total_term_limit"]
        self.successive_term_limit = database["requirements_queue"]["successive_term_limit"]
        await db.Elections.set_office_requirements(database, database["requirements_queue"])
    
    def is_officer(self, member):
        return member in self.members

def get_office(name:str) -> Office:
    for office in Offices:
        if office.name == name:
            return office
    return None

async def populate(bot, config):
    offices = await db.Elections.get_all_offices()
    for office in offices:
        await Office().New(bot, config, office)
