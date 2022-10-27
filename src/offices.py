import asyncio
from datetime import datetime, timedelta

import discord

from . import database as db
from . import quickinputs as qi
from . import timestamps as ts

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

    async def make_candidate(self, member, make_check = False):
        if make_check:
            if not await self.is_eligible_candidate(member):
                return False
        return await db.Elections.make_candidate(member.id, self.office.name)

    async def drop_candidate(self, member):
        return await db.Elections.drop_candidate(member.id, self.office.name)

    async def get_winners(self):
        return await db.Elections.get_election_winners(self.office.name)
    
    async def appoint_winners(self):
        winners = await self.get_winners()
        return winners

    async def advance_stage(self):
        return

    async def stage_check(self):
        if self.next_stage >= datetime.now():
            self.advance_stage()

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
