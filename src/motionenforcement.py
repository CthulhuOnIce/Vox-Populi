import base64
import time

import discord
import yaml
from discord.ext import commands

from . import database as db
from .news import broadcast

# just a template to copy and paste for use in developing cogs in the future


blacklisted_permissions = ["manage_permissions", "manage_channels", "manage_guild", "administrator", "manage_roles", "moderate_members", "kick_members", "ban_members"]

class Motion:

    motion_id = "0"
    referendum_created = False
    validated = False  # whether the motion passes a self-check and has done one

    data = None
    bot = None
    config = None
    guild = None

    new_text_channels = {}
    new_voice_channels = {}
    new_categories = {}
    new_roles = {}

    def __init__(self, data, bot, guild, config: dict, motion_id:str = None):
        self.data = data
        self.bot = bot
        self.guild = guild
        self.config = config
        if motion_id:
            self.motion_id = motion_id

    def get_channel(self, channel, preferred_type=discord.TextChannel):
        lst = None
        if preferred_type == discord.TextChannel:
            lst = self.new_text_channels
        elif preferred_type == discord.VoiceChannel:
            lst = self.new_voice_channels
        elif preferred_type == discord.CategoryChannel:
            lst = self.new_categories
        elif preferred_type == discord.abc.GuildChannel:
            lst = {**self.new_text_channels, **self.new_voice_channels, **self.new_categories}

        if isinstance(channel, int):
            for gchannel in self.guild.channels:
                if gchannel.id == channel and isinstance(gchannel, preferred_type):
                    return gchannel
        elif isinstance(channel, str):
            if channel in lst:
                return lst[channel]

        return None

    def get_role(self, role):
        if isinstance(role, int):
            for role in self.guild.roles:
                if role.id == role:
                    return role
        elif isinstance(role, str):
            if role == "everyone":
                return self.guild.default_role
            if role in self.new_roles:
                return self.new_roles[role]
        return None
    
    def find_channel_position(self, position, preferred_type = discord.TextChannel):
        if "Above" or "Below" in position:
            target = self.get_channel(position["Above"] if "Above" in position else position["Below"], preferred_type)
            if not target:
                return "The channel you are trying to move the channel to does not exist."
            return max(target.position - 1 if "Above" in position else target.position + 1, 0)
        elif "Absolute" in position:
            return position["Absolute"]

    def find_role_position(self, position):
        if "Above" or "Below" in position:
            target = self.get_role(position["Above"] if "Above" in position else position["Below"])
            if not target:
                return "The role you are trying to move the role to does not exist."
            return target.position + 1 if "Above" in position else target.position - 1
        elif "Absolute" in position:
            return position["Absolute"]
    
    def generate_channel_permissions(self, overwrite, channel):
        # 'Overwrites' = [{'Role': 'everyone', 'Overwrites': {'view_channel': False}}, {'Role': 'Secret Club Member', 'Overwrites': {'view_channel': True}}]
        target = None
        if "Role" in overwrite:
            target = self.get_role(overwrite["Role"])
            if not target:
                return "The role you are trying to edit overwrites for does not exist.", None

        elif "Member" in overwrite:
            if isinstance(overwrite["Member"], int):
                for member in self.guild.members:
                    if member.id == overwrite["Member"]:
                        target = member
                        break
            if not target:
                return "The member you are trying to edit overwrites for does not exist.", None
                
        for overwrite_ in overwrite["Overwrites"]:
            if overwrite_ in blacklisted_permissions:
                overwrite_["Overwrites"].pop(overwrite_)
                
        overwrites = overwrite["Overwrites"]

        overwrites_discord = channel.overwrites_for(target)

        overwrites_discord.update(**overwrites)
        return target, overwrites_discord

    async def create_text_channel(self, motion_data: dict):
        new_channel = None
        if "Clone" in motion_data:
            cloned_channel = None
            cloned_channel = self.get_channel(motion_data["Clone"])
            if not cloned_channel:
                return "The text channel you are trying to clone does not exist."
            new_channel = await cloned_channel.clone()
        else:
            new_channel = await self.guild.create_text_channel(motion_data["Name"])
        await new_channel.edit(name=motion_data["Name"])
        self.new_text_channels[motion_data["Name"]] = new_channel
        
    async def edit_text_channel(self, motion_data: dict):
        selected_channel = self.get_channel(motion_data["Channel"])
        if not selected_channel:
            return "The text channel you are trying to edit does not exist."
        if "Overwrites" in motion_data:
            for overwrites in motion_data["Overwrites"]:
                target, overwrites_discord = self.generate_channel_permissions(overwrites, selected_channel)
                if isinstance(target, str):
                    return target
                await selected_channel.set_permissions(target, overwrite=overwrites_discord)
        
        if "AddListeners" in motion_data:
            for channel in motion_data["AddListeners"]:
                threshold = motion_data["AddListeners"][channel]
                if channel not in await db.Radio.frequencies():
                    return "The radio frequency you are trying to add a listener to does not exist."
                await db.Radio.add_listener(selected_channel.id, channel, threshold)
                await selected_channel.send(f"📻 This channel is now listening to `{channel}` at a threshold of `{threshold}`.")
        if "DelListeners" in motion_data:
            for channel in motion_data["DelListeners"]:
                if channel not in await db.Radio.frequencies():
                    return "The radio frequency you are trying to remove a listener from does not exist."
                await db.Radio.del_listener(selected_channel.id, channel)
                await selected_channel.send(f"📻 This channel is no longer listening to {channel}.")
    
        payload = {}
        if "Name" in motion_data:
            payload["name"] = motion_data["Name"]
        if "Topic" in motion_data:
            payload["topic"] = motion_data["Topic"]
        if "SlowMode" in motion_data:
            payload["slowmode_delay"] = motion_data["SlowMode"]
        if "NSFW" in motion_data:
            payload["nsfw"] = motion_data["NSFW"]
        if "Category" in motion_data:
            payload["category"] = self.get_channel(motion_data["Category"], discord.CategoryChannel)
            if not payload["category"]:
                return "The category you are trying to move the channel to does not exist."
        if "Position" in motion_data:
            payload["position"] = self.find_channel_position(motion_data["Position"])
            if isinstance(payload["position"], str):
                return payload["position"]
        if "SyncPermissions" in motion_data:
            payload["sync_permissions"] = bool(motion_data["SyncPermissions"])

        await selected_channel.edit(**payload)
            
    
    async def create_voice_channel(self, motion_data: dict):
        new_channel = None
        if "Clone" in motion_data:
            cloned_channel = None
            cloned_channel = self.get_channel(motion_data["Clone"], discord.VoiceChannel)
            if not cloned_channel:
                return "The voice channel you are trying to clone does not exist."
            new_channel = await cloned_channel.clone()
        else:
            new_channel = await self.guild.create_voice_channel(motion_data["Name"])
        await new_channel.edit(name=motion_data["Name"])
        self.new_voice_channels[motion_data["Name"]] = new_channel
    
    async def edit_voice_channel(self, motion_data: dict):
        selected_channel = self.get_channel(motion_data["Channel"], discord.VoiceChannel)
        if not selected_channel:
            return "The voice channel you are trying to edit does not exist."
        if "Overwrites" in motion_data:
            for overwrites in motion_data["Overwrites"]:
                target, overwrites_discord = self.generate_channel_permissions(overwrites, selected_channel)
                if isinstance(target, str):
                    return target
                await selected_channel.set_permissions(target, overwrite=overwrites_discord)
    
        payload = {}
        if "Name" in motion_data:
            payload["name"] = motion_data["Name"]
        if "UserLimit" in motion_data:
            payload["user_limit"] = motion_data["UserLimit"]
        if "Category" in motion_data:
            payload["category"] = self.get_channel(motion_data["Category"], discord.CategoryChannel)
            if not payload["category"]:
                return "The category you are trying to move the channel to does not exist."
        if "Position" in motion_data:
            payload["position"] = self.find_channel_position(motion_data["Position"], discord.VoiceChannel)
            if isinstance(payload["position"], str):
                return payload["position"]
        if "SyncPermissions" in motion_data:
            payload["sync_permissions"] = bool(motion_data["SyncPermissions"])
        await selected_channel.edit(**payload)

    async def create_category(self, motion_data: dict):
        new_category = None
        if "Clone" in motion_data:
            cloned_category = None
            cloned_category = self.get_channel(motion_data["Clone"], discord.CategoryChannel)
            if not cloned_category:
                return "The category you are trying to clone does not exist."
            new_category = await cloned_category.clone()
        else:
            new_category = await self.guild.create_category(motion_data["Name"])
        await new_category.edit(name=motion_data["Name"])
        self.new_categories[motion_data["Name"]] = new_category
    
    async def edit_category(self, motion_data: dict):
        selected_category = self.get_channel(motion_data["Category"], discord.CategoryChannel)
        if not selected_category:
            return "The category you are trying to edit does not exist."

        if "Overwrites" in motion_data:
            for overwrites in motion_data["Overwrites"]:
                target, overwrites_discord = self.generate_channel_permissions(overwrites, selected_category)
                if isinstance(target, str):
                    return target
                await selected_category.set_permissions(target, overwrite=overwrites_discord)
    
        payload = {}
        if "Name" in motion_data:
            payload["name"] = motion_data["Name"]
        if "NSFW" in motion_data:
            payload["nsfw"] = motion_data["NSFW"]
        if "Position" in motion_data:
            payload["position"] = self.find_channel_position(motion_data["Position"], discord.CategoryChannel)
            if isinstance(payload["position"], str):
                return payload["position"]
        await selected_category.edit(**payload)
    
    async def delete_channel(self, motion_data: dict):
        selected_channel = self.get_channel(motion_data["ID"], discord.abc.GuildChannel)
        if not selected_channel:
            return "The channel you are trying to delete does not exist."
        if isinstance(selected_channel, discord.CategoryChannel):
            for channel in selected_channel.channels:
                await channel.delete()
        await selected_channel.delete()

    async def create_role(self, motion_data: dict, dry_run = False):  
        if not dry_run:
            new_role = await self.guild.create_role(name=motion_data["Name"])
            await new_role.edit(name=motion_data["Name"])
        self.new_roles[motion_data["Name"]] = new_role

    async def edit_role(self, motion_data: dict):
        selected_role = self.get_role(motion_data["Role"])
        if not selected_role:
            return "The role you are trying to edit does not exist."

        payload = {}
        if "Permissions" in motion_data:
            old_permissions = selected_role.permissions
            for permission in motion_data["Permissions"]:
                if permission in blacklisted_permissions:
                    motion_data["Permissions"].pop(permission)
            old_permissions.update(**motion_data["Permissions"])
            payload["permissions"] = old_permissions
        if "Name" in motion_data:
            payload["name"] = motion_data["Name"]
        if "Color" in motion_data:
            if not isinstance(motion_data["Color"], int):
                return "The color you are trying to set is not a valid color. Valid colors are hex integers, ex. 0xfff."
            payload["color"] = motion_data["Color"]
        if "Position" in motion_data:
            payload["position"] = self.find_role_position(motion_data["Position"])
            if isinstance(payload["position"], str):
                return payload["position"]
        if "Hoist" in motion_data:
            payload["hoist"] = bool(motion_data["Hoist"])
        if "Mentionable" in motion_data:
            payload["mentionable"] = bool(motion_data["Mentionable"])
        await selected_role.edit(**payload)

    async def give_role(self, motion_data: dict):
        selected_role = self.get_role(motion_data["Role"])
        if not selected_role:
            return "The role you are trying to give does not exist."
        for member in self.guild.members:
            if member.id in motion_data["Members"]:
                await member.add_roles(selected_role)
    
    async def take_role(self, motion_data: dict):
        selected_role = self.get_role(motion_data["Role"])
        if not selected_role:
            return "The role you are trying to take does not exist."
        for member in self.guild.members:
            if member.id in motion_data["Members"]:
                await member.remove_roles(selected_role)

    async def remove_role(self, motion_data: dict):
        selected_role = self.get_role(motion_data["Role"])
        if not selected_role:
            return "The role you are trying to remove does not exist."
        await selected_role.delete()

    async def ban_player(self, motion_data: dict):
        if not "Reason" in motion_data or len(motion_data["Reason"]) <= 30:
            return "The reason you are trying to ban someone for is too short or doesn't exist."
        for member in self.guild.members:
            if member.id in motion_data["ID"]:
                await self.guild.ban(member, delete_message_days=0, reason=motion_data["Reason"])
                return
    
    async def kick_player(self, motion_data: dict):
        for member in self.guild.members:
            if member.id in motion_data["ID"]:
                await member.kick(reason=motion_data["Reason"])
                return

    function_map = {
        "CreateTextChannel": create_text_channel,
        "EditTextChannel": edit_text_channel,
        "CreateVoiceChannel": create_voice_channel,
        "EditVoiceChannel": edit_voice_channel,
        "CreateCategory": create_category,
        "EditCategory": edit_category,
        "DeleteChannel": delete_channel,
        "CreateRole": create_role,
        "EditRole": edit_role,
        "GiveRole": give_role,
        "TakeRole": take_role,
        "RemoveRole": remove_role,
        "BanPlayer": ban_player,
    }

    async def self_test(self):
        
        def search_and_validate(dictionary, key, type, requires_presence = True):
            """Searches the dictionary and validates its type. If the key is not present, it will return True.
            If the presence isnt required and the key is not present, it will return False.
            Otherwise, it will return the error as a string"""
            if key in dictionary:
                if isinstance(dictionary[key], type):
                    return False
                else:
                    return f"The {key} you are trying to set is not a valid {key}. Valid {key}s are {type}s."
            else:
                if requires_presence:
                    return f"The {key} you are trying to set does not exist."
                else:
                    return False
        
        def str_within_threshold(string, maximum:int, minimum:int = 0):
            if len(string) >= minimum and len(string) <= maximum:
                return False
            else:
                return f"The string you are trying to set is not within the threshold of {minimum} and {maximum} characters."
        
        def num_within_threshold(integer, maximum, minimum = 0):
            if integer >= minimum and integer <= maximum:
                return False
            else:
                return f"The integer you are trying to set is not within the threshold of {minimum} and {maximum}."


        motion_data = self.data
        # validates the motion data, check references and types

        # validate the heading
        if error := search_and_validate(motion_data, "Heading", dict):
            return error

        if error := search_and_validate(motion_data["Heading"], "Title", str):
            return error

        if len(motion_data["Heading"]["Title"]) < 10:
            return "The motion data heading title is too short."

        if error := search_and_validate(motion_data["Heading"], "Description", str):
            return error
        
        if len(motion_data["Heading"]["Description"]) < 50:
            return "The motion data heading description is too short."

        
        # constitution
        if "Constitution" in motion_data:
            if error := search_and_validate(motion_data, "Constitution", dict):
                return error

            if "Guild" in motion_data["Constitution"]:  # TODO: implement guild editing
                pass

            if "General" in motion_data["Constitution"]:  # tests done
                if error := search_and_validate(motion_data["Constitution"], "General", dict):
                    return error
                general = motion_data["Constitution"]["General"]
                if "MotionLife" in general:
                    if error := search_and_validate(motion_data["Constitution"]["General"], "MotionLife", int):
                        return error
                    if error := num_within_threshold(motion_data["Constitution"]["General"]["MotionLife"], 60, 2):
                        return error
                if "ReferendumLife" in general:
                    if error := search_and_validate(motion_data["Constitution"]["General"], "ReferendumLife", int):
                        return error
                    if error := num_within_threshold(motion_data["Constitution"]["General"]["ReferendumLife"], 120, 2):
                        return error
                if "VoterAccountAge" in general:
                    if error := search_and_validate(motion_data["Constitution"]["General"], "VoterAccountAge", int):
                        return error
                    if error := num_within_threshold(motion_data["Constitution"]["General"]["VoterAccountAge"], 730, 0):
                        return error
                if "VoterMinMessages" in general:
                    if error := search_and_validate(motion_data["Constitution"]["General"], "VoterMinMessages", int):
                        return error
                    if error := num_within_threshold(motion_data["Constitution"]["General"]["VoterMinMessages"], 1000, 0):
                        return error
                if "ConstitutionReferendum" in general:
                    if error := search_and_validate(motion_data["Constitution"]["General"], "ConstitutionReferendum", bool):
                        return error
                if "MotionPublicVotes" in general:
                    if error := search_and_validate(motion_data["Constitution"]["General"], "MotionPublicVotes", bool):
                        return error
                if "ReferendumPublicVotes" in general:
                    if error := search_and_validate(motion_data["Constitution"]["General"], "ReferendumPublicVotes", bool):
                        return error
                for requirement in ["MotionRequirement", "ReferendumRequirement", "PrereferendumRequirement"]:
                    if requirement in general:
                        if error := search_and_validate(motion_data["Constitution"]["General"], requirement, float):
                            return error
                        if error := num_within_threshold(motion_data["Constitution"]["General"][requirement], 1, 0.5):
                            return error

            # TODO: check Offices

            """ 
            if "OfficeRequirements" in motion_data["Constitution"]:
                if error := search_and_validate(motion_data["Constitution"], "OfficeRequirements", dict):
                    return error
                for office in motion_data["Constitution"]["OfficeRequirements"]:
                    if not await db.Elections.get_office(office):
                        return f"The office {office} does not exist."
                    m_office = motion_data["Constitution"]["OfficeRequirements"][office]
                    if "MinimumMessages" in m_office:
                        if error := search_and_validate(m_office, "MinimumMessages", int):
                            return error
                        if error := num_within_threshold(m_office["MinimumMessages"], 10000, 0):
                            return error
            """

        
        self.validated = True
        return True

                   

    async def execute(self):
        if not self.validated:
            return "The motion data has not been validated."
        print(f"Executing motion {self.motion_id} {self.data['Heading']['Title']}")

        
        # if not self.is_referendum and await db.Motions.motion_requires_referendum(self.data):  # motion passed, but requires referendum, so convert to referendum and return
        #    ref = await db.Motions.motion_to_referendum(self.data)
        #    broadcast(self.bot, 'motion', 4, f"Motion {ref['original']['_id']}: {ref['title']} has passed and requires a referendum.\nReferendum ID: {ref['_id']}\nExpires: {ref['expires'].strftime('%Y-%m-%d %H:%M:%S')}")
        #    self.referendum_created = True
        #    return
    
        # Execute Constitution Changes
        if "Constitution" in self.data:

            if "Guild" in self.data["Constitution"]:
                guild = self.data["Constitution"]["Guild"]
                payload = {}
                if "Name" in guild:
                    payload["name"] = guild["Name"]
                if "Description" in guild:
                    payload["description"] = guild["Description"]
                if "Icon" in guild:
                    payload["icon"] = base64.b64decode(guild["Icon"])
                if "Banner" in guild:
                    payload["banner"] = base64.b64decode(guild["Banner"])
                if "VerificationLevel" in guild:
                    if guild["VerificationLevel"] in vars(discord.VerificationLevel):  # :troll:
                        payload["verification_level"] = vars(discord.VerificationLevel)[guild["VerificationLevel"]]
                if "AllowInvites" in guild:
                    payload["disable_invites"] = not guild["AllowInvites"]
                if "VanityCode" in guild:
                    payload["vanity_code"] = guild["VanityCode"]
                await self.guild.edit(**payload)

            if "General" in self.data["Constitution"]:
                general = self.data["Constitution"]["General"]
                for key in general.copy():
                    if key not in db.default_constitution:
                        del general[key]
                await db.Constitution.broad_update(general)

            if "Offices" in self.data["Constitution"]:
                for Office in self.data["Constitution"]["Offices"]:
                    office = self.data["Constitution"]["Offices"][Office]
                    OF = await db.Elections.get_office(Office)
                    if not OF: continue  # TODO: error

                    if "Name" in office or "Color" in office:  # role editing
                        payload = {}
                        role = await self.guild.get_role(office["roleid"])
                        # TODO: this means that someone deleted the role, so we should probably delete the office
                        if not role: continue
                        if "Name" in office:
                            payload["name"] = office["Name"]
                        if "Color" in office:
                            payload["color"] = office["Color"]
                        if payload:
                            await role.edit(**payload)
                    
                    if "Flags" in office:
                        await db.Elections.set_flags(Office, office["Flags"])

                    if "AddFlags" in office:
                        await db.Elections.add_flags(Office, office["AddFlags"])

                    if "RemFlags" in office:
                        await db.Elections.rem_flags(Office, office["RemFlags"])  

                    if "OfficeRequirements" in office:
                        await db.Elections.set_office_requirements_queue(OF, office["OfficeRequirements"])
            
            """
            if "OfficeRequirements" in self.data["Constitution"]:
                for Office in self.data["Constitution"]["OfficeRequirements"]:
                    if await db.Elections.get_office(Office):  # FIXME: Optimize this
                        OR = self.data["Constitution"]["OfficeRequirements"][Office]
                        if "MinimumMessages" in OR:
                            await db.Elections.set_office_requirement(Office, "min_messages", OR["MinimumMessages"])
                        if "MinimumAge" in OR:
                            await db.Elections.set_office_requirement(Office, "min_age_days", OR["MinimumAge"])
                        if "TotalTermLimit" in OR:
                            await db.Elections.set_office_requirement(Office, "total_term_limit", OR["TotalTermLimit"])
                        if "SuccessiveTermLimit" in OR:
                            await db.Elections.set_office_requirement(Office, "successive_term_limit", OR["SuccessiveTermLimit"])
                    else:
                        return "The office you are trying to edit does not exist."
            """

        if "Rules" in self.data:
            if "Add" in self.data["Rules"]:
                await db.Rules.set_rules(self.motion_id, self.data["Heading"]["Title"], self.data["Rules"]["Add"])
            if "Remove" in self.data["Rules"]:
                for remove in self.data["Rules"]["Remove"]:
                    await db.Rules.remove_rule(self.motion_id, remove)
            if "Amend" in self.data["Rules"]: # {motion: thing_to_add}
                for amend in self.data["Rules"]["Amend"]:
                    new_rule = self.data["Rules"]["Amend"][amend]
                    if await db.Rules.motion_has_rules(amend):
                        await db.Rules.amend_rule(amend, new_rule)
            if "Edit" in self.data["Rules"]:
                for edit in self.data["Rules"]["Edit"]:
                    if await db.Rules.get_rule_by_id(edit):
                        await db.Rules.edit_rule(edit, self.data["Rules"]["Edit"][edit])



        # Execute Motions
        if "Body" in self.data:
            item = 0
            for motion in self.data["Body"]:
                item += 1
                function = list(motion.keys())[0]
                motion_data = motion[function]
                if function in self.function_map:
                    result = await self.function_map[function](self, motion_data)
                    if result:
                        return f"{item}: {result}"
                time.sleep(0.25)
            


