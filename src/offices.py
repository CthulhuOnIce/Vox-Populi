from . import database as db

C = None

Offices = []

class Office:
    name = None
    role = None
    guild = None
    members = []
    generataion = 0

    min_messages = 0
    min_age_days = 0
    total_term_limit = 0
    successive_term_limit = 0

    async def __init__(self, bot, config, office_id):
        self.name = office_id
        office = await db.Elections.get_office(office_id)
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
        db.Elections.set_office_requirements_queue(database, requirements)
    
    def is_officer(self, member):
        return member in self.members

def populate(bot, config):
    for office in config["offices"]:
        Office(bot, config, office)

