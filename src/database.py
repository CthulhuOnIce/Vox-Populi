import asyncio
import base64
import datetime
import pickle
from multiprocessing.sharedctypes import Value
from sys import api_version

import discord
import motor
import motor.motor_asyncio
import pymongo
import yaml
import os 

try:
    with open("config.yml", "r") as r:
        C = yaml.load(r.read(), Loader=yaml.FullLoader)
except FileNotFoundError:
    print("No config.yml, please copy and rename config-example.yml and fill in the appropriate values.")
    exit()

client = None
async def establish_server_connection():
    global client
    conn_str = f"mongodb+srv://{C['mongodb']['username']}:{C['mongodb']['password']}@{C['mongodb']['url']}/{C['mongodb']['name']}"
    client = motor.motor_asyncio.AsyncIOMotorClient(conn_str, serverSelectionTimeoutMS=5000)

loop = asyncio.get_event_loop()
loop.run_until_complete(establish_server_connection())
del loop  # :troll:


async def create_connection(table):
    db = client[C["mongodb"]["name"]]
    return db[table]

class Constitution_:

    # There is no queue here, any change made will be reflected in future motions immediately
    # Nothing here can be office-specific, do that in office["restriction_queue"] and office["restrictions"]

    default_constitution = {
        "MotionLife": 7,
        "ReferendumLife": 14,
        "MotionRequirement": 0.5,  # % of legislators required to pass a motion
        "ReferendumRequirement": 0.5,  # % of voters required to pass a referendum
        "PreReferendumRequirement": 0.5,  # % of legislators required to pass a motion that requires a referendum
        
        # note, voter eligibility requirements only work on new voters and cannot retroactively disqualify voters
        "VoterAccountAge": 0,  # 0 to 730: the minimum account age in days
        "VoterMinMessages": 0,  # 0 to 1000: the minimum number of messages

        # flags
        "RulesReferendum": False,  # whether or not a referendum is required to change the rules
        "ConstitutionReferendum": False,  # whether or not a referendum is required to change the constitution
        "MotionPublicVotes": True,  # whether or not to publicize vote totals before the end of the motion
        "ReferendumPublicVotes": True,  # whether or not to publicize vote totals before the end of the referendum
    }

    def is_valid_key(self, key):
        return key in self.default_constitution

    async def broad_update(self, arg:dict):
        db = await create_connection("Global")
        for key in arg:
            if not self.is_valid_key(key):
                return False
        db.update_one({"_id": "Constitution"}, {"$set": arg})
        return True

    async def get_constitution(self):
        db = await create_connection("Global")
        const = await db.find_one({"_id": "Constitution"})
        if not const:
            await db.insert_one({"_id": "Constitution", **self.default_constitution})
            return self.default_constitution
        for key in self.default_constitution:
            if key not in const:
                await db.update_one({"_id": "Constitution"}, {"$set": {key: self.default_constitution[key]}})
                const[key] = self.default_constitution[key]
        return const

    async def get_key(self, key):
        if not self.is_valid_key(key):
            return False
        const = await self.get_constitution()
        return const[key]

    async def set_key(self, key, value):
        db = await create_connection("Global")
        if not self.is_valid_key(key):
            return False
        await db.update_one({"_id": "Constitution"}, {"$set": {key: value}})
        return True

Constitution = Constitution_()

class Players_:

    async def find_player(self, player_id):
        player_id = int(player_id)
        db = await create_connection("Players")
        return await db.find_one({"_id": player_id})

    async def remove_player(self, player_id:int):
        db = await create_connection("Players")
        found = await self.find_player(player_id)
        if found is not None:
            await db.update_one({"_id": player_id}, {"$set": {"left": datetime.datetime.now()}})
    
    async def increment_stat(self, player_id:int, stat:str):
        db = await create_connection("Players")
        try:
            await db.update_one({"_id": player_id}, {"$inc": {stat: 1}})
        except Exception as e:
            print(e)
    
    async def get_officers(self, office:str):
        db = await create_connection("Players")
        return await db.find({f"office.{office}.left_office": None}).to_list(None)

Players = Players_()

class StatTracking_:

    # its kind of weird to have this in a dictionary instead of through variables
    # and it's inefficient to keep writing a file like this
    # but the script has to be able to be killed and restarted with no data loss
    # because the source module's update feature can kill the bot to apply updates at any time
    stats = {
        "start_timestamp": datetime.date.today(),
        "end_timestamp": datetime.date.today(),
        "messages": 0,
        "messages_by_user": {},
        "joins": 0,
        "leaves": 0,
        "players_start": 0,
        "players_end": 0,
    }

    default_stats = stats.copy()  # used to reload stats at cashout

    def __init__(self):
        if not os.path.exists("data/stats.p"):
            return
        with open("data/stats.p", "rb") as r:
            self.stats = pickle.load(r)
    
    def save(self):
        with open("data/stats.p", "wb") as w:
            pickle.dump(self.stats, w)
    
    def increment_joins(self):
        self.stats["joins"] += 1
        self.save()
    
    def increment_leaves(self):
        self.stats["leaves"] += 1
        self.save()

    def increment_daily_messages(self, author):
        key = author.id
        if key not in self.stats["messages_by_user"]:
            self.stats["messages_by_user"][key] = 0
        self.stats["messages"] += 1
        self.stats["messages_by_user"][key] += 1
        self.save()

    async def cash_out(self, guild) -> dict:
        """Clears the stat tracker and returns the complete stat dict

        Args:
            guild (discord.guild): The guild the server is attached to (C["guild"])

        Returns:
            dict: self.stats before it was cleared
        """        
        # cap off the old stats
        self.stats["players_end"] = guild.member_count
        self.stats["end_timestamp"] = datetime.datetime.now()

        # save them and reload new ones
        ret = self.stats.copy()
        db = await create_connection("DailyStats")
        await db.insert_one(self.stats)
        self.stats = self.default_stats.copy()
        
        # start the new stats
        self.stats["start_timestamp"] = datetime.datetime.now()
        self.stats["players_start"] = guild.member_count
        self.save()
        return ret

    # this is the module which handles the day-to-day statistical tracking of the bot.

    async def generate_daily_report(self):
        return

    async def generate_monthly_report(self):
        return

StatTracking = StatTracking_()

class Rules_:

    rules_example = {
        "_id": "221010-46923",  # this is actually the ID of the motion the rule was created under
        "rules": {
            "221010-46923-1": "This is a rule text, it will be identified as 221010-46923-1",
            "221010-46923-2": "This is another rule text, it will be identified as 221010-46923-2"
        }
    }

    async def motion_has_rules(self, motionid):
        db = await create_connection("Rules")
        motion = await db.find_one({"_id": motionid})
        return bool(motion)

    async def get_all_rules(self): # -> {}
        db = await create_connection("Rules")
        return await db.find({}).to_list(None)

    async def get_rule_by_id(self, ruleid):
        if len(ruleid.split("-")) != 3:
            return
        rootmotion = ruleid.split("-")[0] + "-" + ruleid.split("-")[1]
        db = await create_connection("Rules")
        motion = await db.find_one({"_id": rootmotion})
        if not motion:
            return
        if ruleid not in motion["rules"]:
            return        # TODO: add to daily message count
        return motion["rules"]

    async def edit_rule(self, ruleid, new_text):
        if len(ruleid.split("-")) != 3:
            return
        rootmotion = ruleid.split("-")[0] + "-" + ruleid.split("-")[1]
        db = await create_connection("Rules")
        motion = await db.find_one({"_id": rootmotion})
        if ruleid not in motion["rules"]:
            return
        await db.update_one({"_id": rootmotion}, {"$set": {f"rules.{ruleid}": new_text}})
    
    async def add_rule(self, motion_id, text):
        db = await create_connection("Rules")
        motion = await db.find_one({"_id": motion_id})
        if not motion:
            return
        await db.update_one({"_id": motion_id}, {"$set": {f"rules.{motion_id}-{len(motion['rules']) + 1}": text}})

    async def set_rules(self, motion_id, motion_title, rules:list):
        db = await create_connection("Rules")
        new_rule = {"_id": motion_id, "rules": {}, "motion_title": motion_title}
        for index, rule in enumerate(rules, start=1):
            new_rule["rules"][f"{motion_id}-{index}"] = rule
        await db.insert_one(new_rule)

    async def remove_rule(self, ruleid: str):
        if len(ruleid.split("-")) == 3:  # deleting the specific rule
            rootmotion = ruleid.split("-")[0] + "-" + ruleid.split("-")[1]
            db = await create_connection("Rules")
            motion = await db.find_one({"_id": rootmotion})
            if ruleid not in motion["rules"]:
                return
            if len(motion["rules"]) == 1:  # the last rule
                await db.delete_one({"_id": rootmotion})
                return
            await db.update_one({"_id": rootmotion}, {"$unset": {f"rules.{ruleid}": ""}})

            return
        elif len(ruleid.split("-")) == 2:  # deleting all rules from a motion
            db = await create_connection("Rules")
            await db.delete_one({"_id": ruleid})
            return

Rules = Rules_()

class Motions_:
    
    def passratio(self, yea:int, nay:int):
        if yea == 0 and nay == 0 or yea == 0:
            return 0.0
        elif nay == 0:
            1.0
        return yea / (yea + nay)

    async def motion_requires_referendum(self, motion_data:dict):
        if "Constitution" in motion_data and await Constitution.get_key("ConstitutionReferendum"):
            return True
        return bool(
            "Rules" in motion_data
            and await Constitution.get_key("RulesReferendum")
        )

    async def force_expire_motion(self, motion_id:str):
        db = await create_connection("Motions")
        await db.update_one({"_id": motion_id}, {"$set": {"expires": datetime.datetime.now()}})

    async def get_active_motion(self, motion_id:str):
        db = await create_connection("Motions")
        # return await db.find_one({"_id": motion_id, "expires": {"$gt": datetime.datetime.now()}})
        return await db.find_one({"_id": motion_id})  

    async def generate_motion_id(self):
        db = await create_connection("Motions")
        now = datetime.datetime.now()
        append = now.strftime("%f")[-3:]
        motionid = datetime.datetime.now().strftime(f"%y%m%d-{append}%S") # ex. 221010-46923 
        while await db.find_one({"_id": motionid}) is not None:
            motionid = datetime.datetime.now().strftime("%y%m%d-%L%S")
        return motionid

    # I do not like that this searches by motion_data instead of motion_id
    # it's probably slower, but motion objects don't know their own id
    # perhaps you should be able to pass a motion from the database to create a motion object
    # as opposed to just the body of the motion
    async def motion_to_referendum(self, motion_id:str):
        db = await create_connection("Motions")
        motion = await db.find_one({"_id": motion_id})
        new_motion = motion.copy()
        if motion:
            now = datetime.datetime.now()
            motion_id = motion["_id"]
            await db.delete_one({"_id": motion_id})
            new_motion["_id"] = f"{motion_id}R"
            new_motion["votetype"] = "referendum"
            new_motion["submitted"] = now
            new_motion["expires"] = now + datetime.timedelta(days=await Constitution.get_key("ReferendumLife"))
            new_motion["passratio"] = await Constitution.get_key("ReferendumRequirement")
            new_motion["votes"] = {"Yea": [], "Nay": []}
            new_motion["voters"] = []
            new_motion["original"] = {
                "_id": motion["_id"],
                "expires": motion["expires"],
                "votetype": motion["votetype"],
                "votes": motion["votes"],
                "voters": motion["voters"],
                "submitted": motion["submitted"],
                "passratio": motion["passratio"]
            }
            await db.insert_one(new_motion)
            return new_motion

    async def submit_new_motion(self, author:int, motion:dict, motion_raw:str):
        now = datetime.datetime.now()
        motion_id = await self.generate_motion_id()
        db = await create_connection("Motions")
        await Players.increment_stat(author, "motions_submitted")
        life = await Constitution.get_key("MotionLife")
        passratio = await Constitution.get_key("PreReferendumRequirement") if await self.motion_requires_referendum(motion) else await Constitution.get_key("MotionRequirement")
        insertme = {
            "_id": motion_id,
            "author": author,
            "data": motion,
            "data_raw": motion_raw,
            "title": motion["Heading"]["Title"],
            "description": motion["Heading"]["Description"],
            "votetype": "simple",
            "votes": {"Nay": [], "Yea": []},  # {vote: [voter_id, voter_id, ...], ...}
            "voters": [],
            "submitted": now,
            "passratio": passratio,
            "expires": now + datetime.timedelta(days=life),
            # there used to be an item called 'executed' that told whether or not the motion had been executed
            # but now executed motions are archived instead
        }
        await db.insert_one(insertme)
        return motion_id

    async def cast_motion_vote_simple(self, player_id, motion_id, vote): # returns False if already voted, casts vote if not already voted
        db = await create_connection("Motions")
        motion = await db.find_one({"_id": motion_id})
        if player_id in motion["voters"]:
            return False
        await db.update_one({"_id": motion_id}, {"$addToSet": {f"votes.{vote}": player_id, "voters": player_id}})
        return True

    async def get_active_motions(self):
        db = await create_connection("Motions")
        return await db.find().to_list(None)

Motions = Motions_()

## Electoral Functions
class Elections_:

    valid_flags = ["can_submit_motions", "can_vote_motions", "can_veto_motions"]

    insert =  {
        "_id": "Legislator",
        "roleid": C["officer-role"],
        "flags": ["can_submit_motions", "can_vote_motions"],
        "generations": 0,
        "seats": 1,
        "restrictions_queue": {  # gets copied into restrictions at the end of the next election
            "min_messages": 0,
            "min_age_days": 0,
            "total_term_limit": 0,
            "successive_term_limit": 0,
        },
        "restrictions": {  # 0 - disabled, anything else - enabled
            "min_messages": 0,
            "min_age_days": 0,
            "total_term_limit": 0,
            "successive_term_limit": 0
        },
        "regular_elections": {
            "type": "simple",
            "last_election": datetime.datetime.now() - datetime.timedelta(days=365),
            "next_stage": None,
            "term_length": 90,
            "stages": {  # must add up to less than term_length, if less, the rest is considered normal term time
                "nomination": 7,
                "campaigning": 7,
                "voting": 2,
                "lame_duck": 7 # time after voting ends before the new term starts
            },
            "stage": "none",

            # simple: {candidate_id: [voter_id, voter_id, ...], ...}
            # ranked {voter_id: [candidate_id, candidate_id, ...], ...}
            # approval {voter_id: [candidate_id, candidate_id, ...], ...}
            "candidates": {},

            "voters": [], # list of voter ids
        }
    }

    async def enable_vote(self, player_id):
        db = await create_connection("Players")
        await db.update_one({"_id": player_id}, {"$set": {"can_vote": True}})

    async def populate_offices(self):
        db = await create_connection("Offices")
        await db.insert_one(self.insert)
    
    async def remove_offices(self):
        db = await create_connection("Offices")
        await db.drop()

    async def apply_restriction_queue(self, office_id):
        db = await create_connection("Offices")
        office = await db.find_one({"_id": office_id})
        await db.update_one({"_id": office_id}, {"$set": {"restrictions": office["restrictions_queue"]}})
    
    async def reset_votes(self, office_id):
        db = await create_connection("Offices")
        await db.update_one({"_id": office_id}, {"$set": {"regular_elections.candidates": {}, "regular_elections.voters": []}})

    async def set_election_stage(self, office_id, next_stage, stage_id):
        db = await create_connection("Offices")
        office = await db.find_one({"_id": office_id})
        office["regular_elections"]["stage"] = stage_id
        office["regular_elections"]["next_stage"] = next_stage
        await db.update_one({"_id": office_id}, {"$set": {"regular_elections": office["regular_elections"]}})

    async def set_last_election(self, office_id, date):
        db = await create_connection("Offices")
        await db.update_one({"_id": office_id}, {"$set": {"regular_elections.last_election": date}})

    async def get_all_offices(self):
        db = await create_connection("Offices")
        found = db.find()
        return await found.to_list(None)

    async def set_office_requirement(self, office_id, requirement, value):
        db = await create_connection("Offices")
        office = await db.find_one({"_id": office_id})
        office["restrictions"][requirement] = value
        await db.update_one({"_id": office_id}, {"$set": {"restrictions": office["restrictions"]}})

    async def set_office_requirements(self, office:dict, requirements:dict):
        for requirement in requirements:
            if requirement in office["restrictions_queue"]:
                office["restrictions"][requirement] = requirements[requirement]
        db = await create_connection("Offices")
        await db.update_one({"_id": office["_id"]}, {"$set": {"restrictions": office["restrictions"]}})

    async def set_office_requirments_queue(self, office:dict, requirements:dict):
        for requirement in requirements:
            if requirement in office["restrictions"]:
                office["restrictions_queue"][requirement] = requirements[requirement]
        db = await create_connection("Offices")
        await db.update_one({"_id": office["_id"]}, {"$set": {"restrictions_queue": office["restrictions_queue"]}})

    async def set_flags(self, office_id, flags):
        db = await create_connection("Offices")
        write_flags = [flag for flag in flags if flag in self.valid_flags]
        await db.update_one({"_id": office_id}, {"$set": {"flags": write_flags}})

    async def add_flags(self, office_id, flags):
        db = await create_connection("Offices")
        write_flags = [flag for flag in flags if flag in self.valid_flags]
        await db.update_one({"_id": office_id}, {"$addToSet": {"flags": write_flags}})
    
    async def rem_flags(self, office_id, flags):
        db = await create_connection("Offices")
        write_flags = [flag for flag in flags if flag in self.valid_flags]
        await db.update_one({"_id": office_id}, {"$pullAll": {"flags": write_flags}})

    async def get_office(self, office_id):
        db = await create_connection("Offices")
        return await db.find_one({"_id": office_id})

    async def cast_vote_simple(self, player_id, office_id, candidate_id): # returns False if already voted, casts vote if not already voted
        db = await create_connection("Offices")
        office = await db.find_one({"_id": office_id})
        
    async def add_voter(self, player_id, office_id):
        db = await create_connection("Offices")
        await db.update_one({"_id": office_id}, {"$addToSet": {"regular_elections.voters": player_id}})

    async def remove_voter(self, player_id, office_id):  # called when a player leaves the server or cancels their vote
        db = await create_connection("Offices")
        office = await db.find_one({"_id": office_id})
        office["regular_elections"]["voters"].remove(player_id)
        await db.update_one({"_id": office_id}, {"$set": {"regular_elections": office["regular_elections"]}})

    async def increment_terms_missed(self, office_id):
        db = await create_connection("Players")
        await db.update_many({"offices": {"$in": [office_id]}}, {"$inc": {"terms_missed_successively": 1, "$set": {"terms_served_successively": 0}}})

Elections = Elections_()

## Listener functions
class Radio_:

    async def frequencies(self):
        return [i["_id"] for i in await create_connection("Radio").find().to_list(None)]

    async def get_targets_for_frequency(self, frequency, importance=1):
        db = await create_connection("Radio")
        # find all keys with a value of less than or equal to the importance
        freq = await db.find_one({"_id": frequency})
        if freq is None:
            frequency = {"_id": frequency, "channels": {}}
            await db.insert_one(frequency)
            return []
        return [
            int(key)
            for key in freq["channels"]
            if freq["channels"][key] <= importance
        ]

    async def add_listener(self, send_id, news_code, importance):
        db = await create_connection("Radio")
        freq = await db.find_one({"_id": news_code})
        if freq is None:
            freq = {"_id": news_code, "channels": {}}
            await db.insert_one(freq)
        await db.update_one({"_id": news_code}, {"$set": {f"channels.{send_id}": importance}})

    async def del_listener(self, send_id, news_code):
        db = await create_connection("Radio")
        await db.update_one({"_id": send_id}, {"$pull": {"channels": news_code}})

Radio = Radio_()

# Example player document, not to be confused with the scge
class Archives_:

    player_schema = {
        "_id": 0,
        "can_vote": False,
        "joined": [],             # [datetime.datetime, datetime.datetime],
        "left": [],               # [datetime.datetime, datetime.datetime],
        "name": [],               # [{"name": "Example", "date": datetime.datetime}],
        "display_name": [],       # [{"name": "Example", "date": datetime.datetime}],
        "nickname": [],           # [{"name": "Example", "date": datetime.datetime}],
        "discriminator": [],      # [{"discriminator": "Example", "date": datetime.datetime}],
        "offices": {},
        "stats": {}
    }

    async def get_player(self, player_id:int):
        db = await create_connection("Archives")
        return await db.find_one({"_id": player_id})

    async def link_github(self, user_id, api_response):
        name = api_response["login"]
        id = api_response["id"]
        db = await create_connection("Players")
        await db.update_one({"_id": user_id}, {"$set": {"github": {"id": id, "last_updated": datetime.datetime.now(), "login": name}}}, upsert=True)

    # update player in records, return message total, called in on_message, on_member_update, on_member_join, on_member_leave, etc
    async def update_player(self, player, increment_messages = False, is_in_server = True):
        db = await create_connection("Players")
        update = {}

        fetched = await db.find_one({"_id": player.id})
        if fetched is None:
            insert = self.player_schema.copy()
            insert["_id"] = player.id
            insert["name"] = [{"name": player.name, "date": datetime.datetime.now()}]
            insert["nickname"] = [{"name": player.nick, "date": datetime.datetime.now()}]
            insert["display_name"] = [{"name": player.display_name, "date": datetime.datetime.now()}]
            insert["discriminator"] = [{"name": player.discriminator, "date": datetime.datetime.now()}]
            if is_in_server:
                insert["joined"] = [datetime.datetime.now()]
                insert["last_seen"] = datetime.datetime.now()

            await db.insert_one(insert)
            return insert

        update = {
            key: self.player_schema[key]
            for key in self.player_schema
            if key not in fetched
        }


        if update:
            await db.update_one({"_id": player.id}, {"$set": update})

        name         = fetched["name"][-1]["name"]         if len(fetched["name"])         else None
        display_name = fetched["display_name"][-1]["name"] if len(fetched["display_name"]) else None
        discriminator= fetched["discriminator"][-1]["name"]if len(fetched["discriminator"])else None
        nickname     = fetched["nickname"][-1]["name"]     if len(fetched["nickname"])     else None

        if display_name != player.display_name:
            update["display_name"] = {"name": player.display_name, "date": datetime.datetime.now()}
            display_name = player.display_name

        if name != player.name:
            update["name"] = {"name": player.name, "date": datetime.datetime.now()}
            name = player.name

        if discriminator != player.discriminator:
            update["discriminator"] = {"name": player.discriminator, "date": datetime.datetime.now()}
            discriminator = player.discriminator

        if nickname != player.nick:
            update["nickname"] = {"name": player.nick, "date": datetime.datetime.now()}
            nickname = player.nick

        await db.update_one({"_id": player.id}, {
            "$push": update, 
            "$inc": {"messages": 1 if increment_messages else 0}, 
            "$set": {"last_seen": datetime.datetime.now() if increment_messages else fetched["last_seen"]},
            "$unset": {"left": 1} if is_in_server and "left" in fetched else {}
        })

        fetched["messages"] += 1 if increment_messages else 0

        return fetched


    async def archive_motion(self, motion_id, status):  # called after motion is killed, either after execution or withdrawal
        # withdrawn - they withdrew the motion voluntarily
        # rejected - the motion failed to validate and was nullified
        if status not in ["passed", "failed", "withdrawn", "rejected"]:
            raise ValueError("Invalid status")

        db_archive = await create_connection("Archive-Motions")
        db_live = await create_connection("Motions")

        motion = await db_live.find_one({"_id": motion_id})
        motion["status"] = status
        motion["archived"] = datetime.datetime.now()

        await db_archive.insert_one(motion)
        await db_live.delete_one({"_id": motion_id})

    async def get_archived_motion(self, motion_id):
        db = await create_connection("Archive-Motions")
        return await db.find_one({"_id": motion_id})
        
    async def archive_election(self, office_id, winners):  # called after election is finished but before data is cleared

        winners = [int(winner) for winner in winners]

        db_archive = await create_connection("Archive-Elections")
        db_live = await create_connection("Offices")

        ts = datetime.datetime.now().strftime("%y-%m-%d:%H%M")

        tss = ts.split("-")  # hyuck hyuck
        y = int(tss[0])
        m = int(tss[1])
        d = int(tss[2].split(":")[0])

        # get current hour as int
        h = int(tss[2].split(":")[1][:2])

        # get current minute as int
        m = int(tss[2].split(":")[1][2:4])

        election = await db_live.find_one({"_id": office_id})
        archive = {
            "_id": f"{ts}-{office_id}",
            "office_id": office_id,
            "roleid": election["roleid"],
            "year": y,
            "month": m,
            "day": d,
            "hour": h,
            "minute": m,
            "winners": winners,
            "generation": election["generations"],
            "restrictions": election["restrictions"],
            "regular_elections": election["regular_elections"]
        }

        await db_archive.insert_one(archive)

Archives = Archives_()

# This can reconstruct a player from any point in time given datetime
class ReconstructedPlayer:
    
    display_name            = None
    name                    = None
    id                      = None
    messages                = None
    last_seen               = None
    
    db = None
    guild = None

    is_in_guild = False

    # this can be used to create a discord.Member-like object as it 
    # existed in the past or in the current state
    # it also updates the database with the current state,
    # if out of date
    async def __init__(self, guild, player_id, time=None):
        self.guild = guild
        self.db = await create_connection("Players")

        recon_player = await self.db.find_one({"_id": player_id})
        if recon_player is None:
            raise ValueError("Player not found")

        if time is None:
            used_time = time or datetime.datetime.now()
        # trim the list of names to only those that are valid at the time
        # then get the last one, which is the most recent one as of the given date
        # then extract the value from that entry
        self.messages = recon_player["messages"]
        self.joined = [i for i in recon_player["joined"] if i["date"] <= used_time][-1]
        self.display_name = [i for i in recon_player["display_name"] if i["date"] <= used_time][-1]["name"]
        self.name = [i for i in recon_player["name"] if i["date"] <= used_time][-1]["name"]
        self.id = player_id
        self.last_seen = recon_player["last_seen"]

        if member := guild.get_member(player_id) and not time:
            self.is_in_guild = True
            await self.update_player(member)
