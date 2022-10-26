from . import database as db

C = None

Offices = []

class ElectionManager:
    enabled           = False
    current_stage     = None

    election_style    = None
    last_election     = None
    next_stage        = None
    term_length       = 0

    office            = None

    nomination_stage  = 0
    campaigning_stage = 0
    voting_stage      = 0
    lame_duck_stage   = 0

    voters = []

    # candidates = {}
    # votes = {}

    def __init__(self, office, reg_elections:dict):
        self.office = office
        if reg_elections:
            self.enabled            = True
            self.election_style     = reg_elections["type"]
            self.last_election      = reg_elections["last_election"]
            self.next_stage         = reg_elections["next_stage"]
            self.term_length        = reg_elections["term_length"]

            self.nomination_stage   = reg_elections["stages"]["nomination"]
            self.campaigning_stage  = reg_elections["stages"]["campaigning"]
            self.voting_stage       = reg_elections["stages"]["voting"]
            self.lame_duck_stage    = reg_elections["stages"]["lame_duck"]

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

    async def __init__(self, bot, config, office_id):
        self.name = office_id

        office = await db.Elections.get_office(office_id)

        self.election_manager = ElectionManager(self, office["regular_elections"])

        if not office:
            raise ValueError("Office not found")

        self.guild = bot.get_guild(config["guild_id"])
        self.role = self.guild.get_role(office["role_id"])
        self.generataion = office["generations"]


        for officer in await db.Elections.get_officers(office_id):
            user = self.guild.get_member(officer["user_id"])
            if not user:  pass # User left the server, TODO: remove from office
            self.members.append(user)

        Offices.append(self)
    
    async def database(self):
        return await db.get_office(self.name)

    async def set_future_limit(self, requirements:dict):
        database = self.database()
        db.Elections.set_office_requirments_queue(database, requirements)

    async def apply_restrictions_queue(self):
        database = self.database()
        self.min_age_days = database["requirements_queue"]["min_age_days"]
        self.min_messages = database["requirements_queue"]["min_messages"]
        self.total_term_limit = database["requirements_queue"]["total_term_limit"]
        self.successive_term_limit = database["requirements_queue"]["successive_term_limit"]
        await db.Elections.set_office_requirements(database, database["requirements_queue"])
    
    def is_officer(self, member):
        return member in self.members

def populate(bot, config):
    for office in config["offices"]:
        Office(bot, config, office)

