import asyncio
import base64
import datetime
from multiprocessing.sharedctypes import Value
from sys import api_version

import discord
import motor
import motor.motor_asyncio
import pymongo
import yaml

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

class Constitution:

    is_valid_key = lambda key: key in default_constitution

    async def broad_update(arg:dict):
        db = await create_connection("Global")
        for key in arg:
            if not Constitution.is_valid_key(key):
                return False
        db.update_one({"_id": "Constitution"}, {"$set": arg})
        return True

    async def get_constitution():
        db = await create_connection("Global")
        const = await db.find_one({"_id": "Constitution"})
        if not const:
            await db.insert_one({"_id": "Constitution", **default_constitution})
            return default_constitution
        for key in default_constitution:
            if key not in const:
                await db.update_one({"_id": "Constitution"}, {"$set": {key: default_constitution[key]}})
                const[key] = default_constitution[key]
        return const

    async def get_key(key):
        if not Constitution.is_valid_key(key):
            return False
        const = await Constitution.get_constitution()
        return const[key]

    async def set_key(key, value):
        db = await create_connection("Global")
        if not Constitution.is_valid_key(key):
            return False
        await db.update_one({"_id": "Constitution"}, {"$set": {key: value}})
        return True

class StatTracking:

    async def find_player(player_id):
        player_id = int(player_id)
        db = await create_connection("Players")
        return await db.find_one({"_id": player_id})

    async def remove_player(player_id):
        db = await create_connection("Players")
        found = await StatTracking.find_player(player_id)
        if found is not None:
            await db.update_one({"_id": player_id}, {"$set": {"left": datetime.datetime.now()}})
    
    async def increment_daily_messages():
        db = await create_connection("Global")
        await db.update_one({"_id": "MonthlyStats"}, {"$inc": {f"{datetime.datetime.now().strftime('%m-%d')}.count": 1}})


rules_example = {
    "_id": "221010-46923",  # this is actually the ID of the motion the rule was created under
    "rules": {
        "221010-46923-1": "This is a rule text, it will be identified as 221010-46923-1",
        "221010-46923-2": "This is another rule text, it will be identified as 221010-46923-2"
    }
}

rules_new_example = {  # this is how the rules should be stored in the database (TODO)
    "_id": "221010-46923",  # this is actually the ID of the motion the rule was created under
    "rules": [
        "This is a rule text, it will be identified as 221010-46923-1",
        "This is another rule text, it will be identified as 221010-46923-2",
        "This is another rule text, it will be identified as 221010-46923-3"
    ],
}


class Rules:

    async def motion_has_rules(motionid):
        db = await create_connection("Rules")
        motion = await db.find_one({"_id": motionid})
        if not motion:
            return False
        return True

    async def get_all_rules(): # -> {}
        db = await create_connection("Rules")
        rules_from_db = await db.find({}).to_list(None)
        return rules_from_db

    async def get_rule_by_id(ruleid):
        if len(ruleid.split("-")) != 3:
            return
        rootmotion = ruleid.split("-")[0] + "-" + ruleid.split("-")[1]
        db = await create_connection("Rules")
        motion = await db.find_one({"_id": rootmotion})
        if not motion:
            return
        if not ruleid in motion["rules"]:
            return
        return motion["rules"][ruleid]
    
    async def get_rules_from_motion(motionid):
        db = await create_connection("Rules")
        motion = await db.find_one({"_id": motionid})
        if not motion:
            return
        return motion["rules"]

    async def edit_rule(ruleid, new_text):
        if len(ruleid.split("-")) != 3:
            return
        rootmotion = ruleid.split("-")[0] + "-" + ruleid.split("-")[1]
        db = await create_connection("Rules")
        motion = await db.find_one({"_id": rootmotion})
        if ruleid not in motion["rules"]:
            return
        await db.update_one({"_id": rootmotion}, {"$set": {f"rules.{ruleid}": new_text}})
    
    async def add_rule(motion_id, text):
        db = await create_connection("Rules")
        motion = await db.find_one({"_id": motion_id})
        if not motion:
            return
        await db.update_one({"_id": motion_id}, {"$set": {f"rules.{motion_id}-{len(motion['rules']) + 1}": text}})

    async def set_rules(motion_id, motion_title, rules:list):
        db = await create_connection("Rules")
        new_rule = {"_id": motion_id, "rules": {}, "motion_title": motion_title}
        index = 0
        for rule in rules:
            index += 1
            new_rule["rules"][f"{motion_id}-{index}"] = rule
        await db.insert_one(new_rule)

    async def remove_rule(ruleid: str):
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

class Motions:
    
    def passratio(yea:int, nay:int):
        if yea == 0 and nay == 0:
            return 0.0
        elif yea == 0:
            return 0.0
        elif nay == 0:
            1.0
        return yea / (yea + nay)

    async def motion_requires_referendum(motion_data:dict):
        if "Constitution" in motion_data and await Constitution.get_key("ConstitutionReferendum"):
            return True
        if "Rules" in motion_data and await Constitution.get_key("RulesReferendum"):
            return True
        return False

    async def force_expire_motion(motion_id:str):
        db = await create_connection("Motions")
        await db.update_one({"_id": motion_id}, {"$set": {"expires": datetime.datetime.now()}})

    async def get_active_motion(motion_id:str):
        db = await create_connection("Motions")
        # return await db.find_one({"_id": motion_id, "expires": {"$gt": datetime.datetime.now()}})
        return await db.find_one({"_id": motion_id})  

    async def generate_motion_id():
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
    async def motion_to_referendum(motion_id:str):
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

    async def submit_new_motion(author:int, motion:dict, motion_raw:str):
        now = datetime.datetime.now()
        motion_id = await Motions.generate_motion_id()
        db = await create_connection("Motions")
        dbo = await create_connection("Officers")
        await dbo.update_one({"_id": author}, {"$inc": {"stats.motions_submitted": 1}})
        life = await Constitution.get_key("MotionLife")
        passratio = await Constitution.get_key("PreReferendumRequirement") if await Motions.motion_requires_referendum(motion) else await Constitution.get_key("MotionRequirement")
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

    async def cast_motion_vote_simple(player_id, motion_id, vote): # returns False if already voted, casts vote if not already voted
        db = await create_connection("Motions")
        motion = await db.find_one({"_id": motion_id})
        if player_id in motion["voters"]:
            return False
        await db.update_one({"_id": motion_id}, {"$addToSet": {f"votes.{vote}": player_id, "voters": player_id}})
        return True

    async def get_active_motions():
        db = await create_connection("Motions")
        shid = await db.find().to_list(None)
        return shid


# The "officers" table lists every officer to have ever held office, and the appropriate 
# information, such as terms_served_successively, terms_served_total, to determine
# whether or not they are eligible for re-election or to run for a higher office.


officer_example = {
    "_id": 123456789012345678,  # player id
    "office_id": "Legislator",  # office id
    "terms_served_successively": 0,
    "terms_served_total": 0,
    "terms_missed_successively": 0,
    "last_term_start": datetime.datetime.now(),
    "last_term_end": None,  # set when they are no longer in office, used to determine if they are in office
    "stats": {
        "motions_submitted": 0,
        "motions_passed": 0,
        "motions_failed": 0,
        "vote_success": 0,  # whether or not they voted on the winning side of a motion, determines competence
        "vote_failure": 0,
    }
}

## Electoral Functions
class Elections:

    async def is_in_office(player_id, office_id):
        player_id = str(player_id)
        db = await create_connection("Officers")
        return await db.find_one({"_id": player_id, "office_id": office_id, "last_term_end": None}) is not None

    async def enable_vote(player_id):
        db = await create_connection("Players")
        await db.update_one({"_id": player_id}, {"$set": {"can_vote": True}})

    async def populate_offices():
        db = await create_connection("Offices")
        insert =  {
            "_id": "Legislator",
            "roleid": C["officer-role"],
            "flags": ["can_submit_motions", "can_vote_motions"],
            "generations": 0,
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
                "seats": 1,
                "stage": "none",
                "candidates": [],
                # simple: {candidate_id: [voter_id, voter_id, ...], ...}
                # ranked {voter_id: [candidate_id, candidate_id, ...], ...}
                # approval {voter_id: [candidate_id, candidate_id, ...], ...}
                "votes": {},

                "voters": [], # list of voter ids
            }
        }
        await db.insert_one(insert)

    async def player_has_flag(user_id, flag):
        db = await create_connection("Officers")
        db.find_one({"_id": user_id, "flags": flag})
        return await db.find_one({"_id": user_id, "flags": flag}) is not None

    async def remove_offices():
        db = await create_connection("Offices")
        await db.drop()

    async def apply_restriction_queue(office_id):
        db = await create_connection("Offices")
        office = await db.find_one({"_id": office_id})
        await db.update_one({"_id": office_id}, {"$set": {"restrictions": office["restrictions_queue"]}})

    async def get_election_winners(office_id):
        db = await create_connection("Offices")
        office = await db.find_one({"_id": office_id})
        if office["regular_elections"]["type"] == "simple":  # sort based on number of votes, then trim for top seats
            lst = sorted(office["regular_elections"]["votes"].items(), key=lambda x: len(x[1]), reverse=True)[:office["regular_elections"]["seats"]]
            lst = [x[0] for x in lst]
            return lst
        if office["regular_elections"]["type"] == "ranked":
            winners = []
            for voter in office["regular_elections"]["votes"]:
                for candidate in office["regular_elections"]["votes"][voter]:
                    if candidate not in winners:
                        winners.append(candidate)
                        break
            return winners[:office["regular_elections"]["seats"]]
        if office["regular_elections"]["type"] == "approval":
            winners = []
            for voter in office["regular_elections"]["votes"]:
                for candidate in office["regular_elections"]["votes"][voter]:
                    if candidate not in winners:
                        winners.append(candidate)
            return winners[:office["regular_elections"]["seats"]]

    async def reset_votes(office_id):
        db = await create_connection("Offices")
        await db.update_one({"_id": office_id}, {"$set": {"regular_elections.votes": {}, "regular_elections.candidates": [], "regular_elections.voters": []}})

    async def set_election_stage(office_id, next_stage, stage_id):
        db = await create_connection("Offices")
        office = await db.find_one({"_id": office_id})
        office["regular_elections"]["stage"] = stage_id
        office["regular_elections"]["next_stage"] = next_stage
        await db.update_one({"_id": office_id}, {"$set": {"regular_elections": office["regular_elections"]}})

    async def set_last_election(office_id, date):
        db = await create_connection("Offices")
        await db.update_one({"_id": office_id}, {"$set": {"regular_elections.last_election": date}})

    async def get_all_offices():
        db = await create_connection("Offices")
        found = db.find()
        return await found.to_list(None)

    async def set_office_requirement(office_id, requirement, value):
        db = await create_connection("Offices")
        office = await db.find_one({"_id": office_id})
        office["restrictions"][requirement] = value
        await db.update_one({"_id": office_id}, {"$set": {"restrictions": office["restrictions"]}})

    async def get_office(office_id):
        db = await create_connection("Offices")
        return await db.find_one({"_id": office_id})

    async def make_candidate(player_id, office):
        db = await create_connection("Offices")
        # add player id to regular_elections["candidates"] in office
        office = await db.find_one({"_id": office})
        if player_id not in office["regular_elections"]["candidates"]:
            office["regular_elections"]["candidates"].append(player_id)

            if office["regular_elections"]["type"] == "simple":
                office["regular_elections"]["votes"][str(player_id)] = []

            await db.update_one({"_id": office["_id"]}, {"$set": {"regular_elections": office["regular_elections"]}})
            return True
        return False

    async def drop_candidate(player_id, office):
        db = await create_connection("Offices")
        # remove player id from regular_elections["candidates"] in office
        office = await db.find_one({"_id": office})
        if player_id in office["regular_elections"]["candidates"]:
            await db.update_one({"_id": office}, {"$pull": {"regular_elections.candidates": player_id}})
            return True
        return False

    async def cast_vote_simple(player_id, office_id, candidate_id): # returns False if already voted, casts vote if not already voted
        db = await create_connection("Offices")
        office = await db.find_one({"_id": office_id})
        for candidate in office["regular_elections"]["candidates"]:
            if str(player_id) in office["regular_elections"]["votes"][str(candidate)]:  # i guess i have to use str() here because of the way mongodb stores the data
                return False
        office["regular_elections"]["votes"][str(candidate_id)].append(player_id)
        await db.update_one({"_id": office_id}, {"$set": {"regular_elections": office["regular_elections"]}})
        return True

    async def add_voter(player_id, office_id):
        db = await create_connection("Offices")
        await db.update_one({"_id": office_id}, {"$addToSet": {"regular_elections.voters": player_id}})


    async def remove_voter(player_id, office_id):  # called when a player leaves the server or cancels their vote
        db = await create_connection("Offices")
        office = await db.find_one({"_id": office_id})
        office["regular_elections"]["voters"].remove(player_id)
        await db.update_one({"_id": office_id}, {"$set": {"regular_elections": office["regular_elections"]}})

    async def increment_terms_missed(player_id):
        db = await create_connection("Officers")
        await db.update_one({"_id": player_id}, {"$inc": {"terms_missed_successively": 1}, "$set": {"terms_served_successively": 0}})

    async def is_officer(player_id, office_id):
        db = await create_connection("Officers")
        return await db.find_one({"_id": str(player_id), "last_term_end": None, "office_id": office_id})
    
    # check if a player is currently in an office which has this flag enabled
    async def player_has_flag(player_id, flag):
        db = await create_connection("Officers")
        officer = await db.find_one({"_id": str(player_id), "last_term_end": None})
        if officer:
            office = await Elections.get_office(officer["office_id"])
            if flag in office["flags"]:
                return True
        return False
        

    async def set_new_officer(officer:int, office_id:str):
        Elections.set_new_officers([officer], office_id, demote_others=False)

    async def set_new_officers(officers:list, office_id:str, demote_others = True):
        db = await create_connection("Officers")
        dbo = await create_connection("Offices")
        office = await dbo.find_one({"_id": office_id})
        for officer_id in officers:
            new = False
            officer = await db.find_one({"_id": officer_id})
            if not officer:
                new = True
                officer = officer_example.copy()
                officer["_id"] = officer_id
            officer["office_id"] = office_id
            officer["terms_served_successively"] += 1
            officer["terms_missed_successively"] = 0
            officer["terms_served_total"] += 1
            officer["last_term_start"] = datetime.datetime.now()
            officer["last_term_end"] = None
            if new:
                await db.insert_one(officer)
            else:
                await db.update_one({"_id": officer["_id"]}, {"$set": officer})

        if demote_others:
            for incombent in db.find({"last_term_end": None}):
                if incombent["_id"] not in officers:
                    await Elections.remove_officer(incombent["_id"], office_id)
            # reset terms_served_successively for all officers who have gone at least half a term without being in office
            # makes it so that you cant just drop out and run again to bypass term limits
            # and cyclically resets everyones terms_served_successively
            for officer in db.find({"last_term_end": {"$lt": datetime.datetime.now() - datetime.timedelta(days=office["regular_elections"]["term_length"]/2)}, "terms_served_successively": {"$gt": 0}}):
                await Elections.reset_terms_served_successfully(officer["_id"])
            await dbo.update_one({"_id": office_id}, {"$inc": {"generations": 1}})
        # dbo.update_one({"_id": office_id}, {"$set": {"regular_elections.stage": "none"}})

    async def remove_officer(player_id, office_id):
        db = await create_connection("Officers")
        await db.update_one({"_id": player_id, "office_id": office_id, "last_term_end": None}, {"$set": {"last_term_end": datetime.datetime.now()}})
    
    async def reset_terms_served_successfully(player_id):
        db = await create_connection("Officers")
        if await db.find_one({"_id": player_id}):
            await db.update_one({"_id": player_id}, {"$set": {"terms_served_successively": 0}})
    
    async def is_eligible_for_office(candidate_id, office_id):

        player = await  create_connection("Players")
        player = await player.find_one({"_id": candidate_id})

        past_officer = await create_connection("Officers")
        past_officer = await past_officer.find_one({"_id": candidate_id})

        office = await create_connection("Offices")
        office = await office.find_one({"_id": office_id})
        if office["restrictions"]["min_messages"]:
            if player["messages"] < office["restrictions"]["min_messages"]:
                return False
        if office["restrictions"]["min_age_days"]:
            if office["restrictions"]["min_age_days"] > (datetime.datetime.now() - player["joined"]).days:
                return False
        if past_officer is None:
            return True
        if office["restrictions"]["total_term_limit"]:
            if past_officer["terms_served_total"] >= office["restrictions"]["total_term_limit"]:
                return False
        if office["restrictions"]["successive_term_limit"]:
            if past_officer["terms_served_successively"] >= office["restrictions"]["successive_term_limit"]:
                return False
        return True

## Listener functions
class Radio:
    async def frequencies():
        return [i["_id"] for i in await create_connection("Radio").find().to_list(None)]

    async def get_targets_for_frequency(frequency, importance=1):
        db = await create_connection("Radio")
        # find all keys with a value of less than or equal to the importance
        freq = await db.find_one({"_id": frequency})
        if freq is None:
            frequency = {"_id": frequency, "channels": {}}
            await db.insert_one(frequency)
            return []
        ret = []
        for key in freq["channels"]:
            if freq["channels"][key] <= importance:
                ret.append(int(key))
        return ret

    async def add_listener(send_id, news_code, importance):
        db = await create_connection("Radio")
        freq = await db.find_one({"_id": news_code})
        if freq is None:
            freq = {"_id": news_code, "channels": {}}
            await db.insert_one(freq)
        await db.update_one({"_id": news_code}, {"$set": {f"channels.{send_id}": importance}})

    async def del_listener(send_id, news_code):
        db = await create_connection("Radio")
        await db.update_one({"_id": send_id}, {"$pull": {"channels": news_code}})


# Example player document
player_example = {
    "_id": 123456789012345679,
    "name": [{"name": "Example", "date": datetime.datetime}],
    "display_name": [{"name": "Example", "date": datetime.datetime}],
    "profile_picture": [{"data": bin, "date": datetime.datetime}],
    "messages": 0,
    "last_seen": datetime.datetime,
    "joined": [datetime.datetime, datetime.datetime],
    "can_vote": False

}       
 

class Archives:


    async def link_github(user_id, api_response):
        name = api_response["login"]
        id = api_response["id"]
        db = await create_connection("Players")
        await db.update_one({"_id": user_id}, {"$set": {"github": {"id": id, "last_updated": datetime.datetime.now(), "login": name}}}, upsert=True)

    # update player in records, return message total, called in on_message, on_member_update, on_member_join, on_member_leave, etc
    async def update_player(player, increment_messages = False):
        db = await create_connection("Players")
        update = {}

        fetched = await db.find_one({"_id": player.id})
        if fetched is None:
            insert = {}
            insert["_id"] = player.id
            insert["name"] = [{"name": player.name, "date": datetime.datetime.now()}]
            insert["nickname"] = [{"name": player.nick, "date": datetime.datetime.now()}]
            insert["display_name"] = [{"name": player.display_name, "date": datetime.datetime.now()}]
            insert["discriminator"] = [{"name": player.discriminator, "date": datetime.datetime.now()}]
            insert["messages"] = 1
            insert["last_seen"] = datetime.datetime.now()
            insert["joined"] = datetime.datetime.now()
            insert["can_vote"] = False
            await db.insert_one(insert)
            return insert["messages"]
        
        name = fetched["name"][-1]["name"]
        display_name = fetched["display_name"][-1]["name"]
        discriminator = fetched["discriminator"][-1]["name"]
        nickname = fetched["nickname"][-1]["name"]

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

        if update != {}:
            await db.update_one({"_id": player.id}, {
                "$push": update, 
                "$inc": {"messages": 1 if increment_messages else 0}, 
                "$set": {"last_seen": datetime.datetime.now() if increment_messages else fetched["last_seen"]},
                "$unset": {"left": 1}
            })
        return fetched["messages"] + 1 if increment_messages else fetched["messages"]


    async def archive_motion(motion_id, status):  # called after motion is killed, either after execution or withdrawal
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

    async def get_archived_motion(motion_id):
        db = await create_connection("Archive-Motions")
        return await db.find_one({"_id": motion_id})
        
    async def archive_election(office_id, winners):  # called after election is finished but before data is cleared

        winners = [int(winner) for winner in winners]

        db_archive = await create_connection("Archive-Elections")
        db_live = await create_connection("Offices")

        ts = datetime.datetime.now().strftime("%y-%m-%d:%H%M")

        tss = ts.split("-")  # hyuck hyuck
        y = int(tss[0])
        m = int(tss[1])
        d = int(tss[2].split(":")[0])

        # get current hour as int
        h = int(tss[2].split(":")[1][0:2])

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
            used_time = time if time else datetime.datetime.now()  # :troll:
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
            await Archives.update_player(member)
