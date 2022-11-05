import asyncio
import datetime
import io
from typing import Optional

import discord
import yaml
from discord import option, slash_command
from discord.ext import commands, tasks

from . import database as db
from . import motionenforcement as ME
from . import quickinputs as qi
from . import timestamps as ts
from .news import broadcast

C = {}

writers_room = []  # no duplicate motion submissions

class Legislation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @slash_command(name='submotion', description='Submit a new motion.')
    # @commands.custom_check(is_legislator)
    async def submotion(self, ctx):
        if not await db.Elections.is_officer(ctx.author.id, "Legislator"):
            await ctx.respond("You are not a legislator.", ephemeral=True)
            return
        if ctx.author.id in writers_room:
            await ctx.respond("You are already writing a motion.", ephemeral=True)
            return
        writers_room.append(ctx.author.id)
        await ctx.respond("Upload the file containing the motion.")
        # TODO: timeout
        file = None
        try:
            file = await self.bot.wait_for("message", check=lambda m: m.author == ctx.author and m.channel == ctx.channel and m.attachments)
        except asyncio.TimeoutError:
            await ctx.respond("Motion submission timed out.", ephemeral=True)
            writers_room.remove(ctx.author.id)
            return
        file = file.attachments[0]
        contents = await file.read()
        motion = yaml.load(contents, Loader=yaml.SafeLoader)
        test = await ME.Motion(motion, self.bot, C["guild"], C).self_test()
        if test is not True:
            await ctx.respond(f"Motion is invalid: {test}")
            writers_room.remove(ctx.author.id)
            return
        writers_room.remove(ctx.author.id)
        new_id = await db.Motions.submit_new_motion(ctx.author.id, motion, contents)
        await ctx.respond(f"Motion submitted. ID: `{new_id}`")
        broadcast(self.bot, "motion", 1, f"New motion submitted: {new_id}")
    
    @slash_command(name='votmotion', description='Vote on a motion.')
    async def votmotion(self, ctx, motion_id: str):
        motion = await db.Motions.get_active_motion(motion_id)

        if not motion:
            await ctx.respond("Motion does not exist.", ephemeral=True)
            return

        if motion[
            "votetype"
        ] != "referendum" and not await db.Elections.is_officer(
            ctx.author.id, "Legislator"
        ):
            await ctx.respond("This motion is not a referendum.", ephemeral=True)
            return

        if motion["votetype"] in ["simple", "referendum"]:
            if ctx.author.id in motion["voters"]:
                await ctx.respond("You have already voted on this motion.", ephemeral=True)
                return
            await ctx.respond("Say 'yea' or 'nay' to vote.")
            vote = await self.bot.wait_for("message", check=lambda m: m.author == ctx.author and m.channel == ctx.channel and m.content.lower() in ["yea", "nay"])
            vote = vote.content.lower()
            vote = "Yea" if vote == "yea" else "Nay"
            if await db.Motions.cast_motion_vote_simple(ctx.author.id, motion_id, vote):
                await ctx.respond(f"Vote cast. `{vote.title()}`")
            else:  # they are trying to vote twice, look into reporting this in the future
                await ctx.respond("Vote failed to cast.", ephemeral=True)
    
    @slash_command(name='listmotions', description='List all active motions.')
    async def listmotions(self, ctx):
        motions = await db.Motions.get_active_motions()
        if not motions:
            await ctx.respond("There are no active motions.", ephemeral=True)
            return
        embed = discord.Embed(title="Active Motions")
        for motion in motions:
            embed.add_field(name=f"{motion['_id']}: {motion['title']}", value=f"Introduced: `{ts.short_text(motion['submitted'])}`\nExpires: `{ts.short_text(motion['expires'])}`\nIntroduced by: <@{motion['author']}>", inline=False)
        await ctx.respond(embed=embed, ephemeral=True)
    
    @slash_command(name='motioninfo', description='Get information about a motion.')
    @option(name='motion_id', description='The ID of the motion.', required=True)
    @option(name='include_copy', type=bool, description='Whether to include an file copy of the motion.', required=False)
    async def motioninfo(self, ctx, motion_id: str, include_copy: Optional[bool] = False):
        motion = await db.Motions.get_active_motion(motion_id)
        if not motion:
            motion = await db.Archives.get_archived_motion(motion_id)
        if not motion:
            await ctx.respond("Motion does not exist.", ephemeral=True)
            return
        if motion["votetype"] == "simple":
            yea, nay = len(motion['votes']['Yea']), len(motion['votes']['Nay'])
            embed = discord.Embed(title=f"{motion_id}: {motion['title']}")
            embed.add_field(name="Author", value=f"<@{motion['author']}>")
            embed.add_field(name="Introduced", value=ts.short_text(motion['submitted']))
            embed.add_field(name="Expires", value=ts.short_text(motion['expires']))
            embed.add_field(name="Description", value=motion["description"], inline=False)
            if await db.Constitution.get_key("MotionPublicVotes"):  # if votes are allowed to be made public
                embed.add_field(name="Ratio / Required", value=f"{db.Motions.passratio(yea, nay)} / {motion['passratio']}", inline=False)
                embed.add_field(name="Votes", value=f"**Yea**: {yea}\n**Nay**: {nay}", inline=False)
                embed.add_field(name="Yea", value="".join([f" - <@{x}>\n" for x in motion["votes"]["Yea"]]) if motion["votes"]["Yea"] else "None", inline=False)
                embed.add_field(name="Nay", value="".join([f" - <@{x}>\n" for x in motion["votes"]["Nay"]]) if motion["votes"]["Nay"] else "None", inline=False)
            await ctx.respond(embed=embed, ephemeral=True)

        if motion["votetype"] == "referendum":
            yea, nay = len(motion['votes']['Yea']), len(motion['votes']['Nay'])
            embed_ref = discord.Embed(title=f"{motion_id}: {motion['title']}")
            embed_ref.add_field(name="Author", value=f"<@{motion['author']}>")
            embed_ref.add_field(name="Introduced", value=ts.short_text(motion['submitted']))
            embed_ref.add_field(name="Expires", value=ts.short_text(motion['expires']))
            embed_ref.add_field(name="Description", value=motion["description"], inline=False)
            if await db.Constitution.get_key("ReferendumPublicVotes"):
                embed_ref.add_field(name="Ratio / Required", value=f"{db.Motions.passratio(yea, nay)} / {motion['passratio']}", inline=False)
                embed_ref.add_field(name="Votes", value=f"**Yea**: {yea}\n**Nay**: {nay}", inline=False)
            embeds = [embed_ref]
            if motion['original']['votetype'] == 'simple':
                original = motion['original']
                yea, nay = len(original['votes']['Yea']), len(original['votes']['Nay'])
                original_embed = discord.Embed(title=f"Original Motion: {motion['title']}")
                original_embed.add_field(name="Introduced", value=ts.short_text(original['submitted']))
                original_embed.add_field(name="Expires", value=ts.short_text(original['expires']))
                original_embed.add_field(name="Ratio / Required", value=f"{db.Motions.passratio(yea, nay)} / {original['passratio']}")
                original_embed.add_field(name="Votes", value=f"**Yea**: {yea}\n**Nay**: {nay}", inline=False)
                original_embed.add_field(name="Original Yea", value="".join([f" - <@{x}>\n" for x in original["votes"]["Yea"]]) if original["votes"]["Yea"] else "None", inline=False)
                original_embed.add_field(name="Original Nay", value="".join([f" - <@{x}>\n" for x in original["votes"]["Nay"]]) if original["votes"]["Nay"] else "None", inline=False)
                embeds.append(original_embed)
            await qi.PaginateEmbeds(ctx, embeds=embeds)


        if include_copy:  # holy fuck, holy fucking fuck, that transparency of yours is absurd
            await ctx.respond("Copy Attached", file=discord.File(io.BytesIO(motion["data_raw"]), filename=f"{motion_id}-{motion['title']}.yaml"), ephemeral=True)

    @tasks.loop(hours=1)
    async def motion_check_loop(self):
        for motion in await db.Motions.get_active_motions():
            motion_obj = ME.Motion(motion["data"], self.bot, C["guild"], C, motion["_id"])
            author = self.bot.get_user(int(motion["author"]))
            test = await motion_obj.self_test()
            if test is not True:
                await author.send(f"Your motion `{motion['_id']}` has been invalidated.\nError: {test}")
                await db.Archives.archive_motion(motion["_id"], "rejected")
                continue

            if motion["expires"] < datetime.datetime.now():

                if motion["votetype"] == "simple":
                    yea_int = len(motion["votes"]["Yea"])
                    nay_int = len(motion["votes"]["Nay"])
                    passratio = db.Motions.passratio(yea_int, nay_int)
                    needs_referendum = await db.Motions.motion_requires_referendum(motion_obj.data)
                    if passratio > motion["passratio"]:

                        if needs_referendum:
                            new_referendum = await db.Motions.motion_to_referendum(motion["_id"])
                            broadcast(self.bot, "motion", 4, f"Motion `{motion['_id']}` has passed and requires a referendum to be ratified.\nThe referendum is `{new_referendum['_id']}` and voting ends on {ts.long_text(new_referendum['expires'])}.")
                        else:
                            error = await motion_obj.execute()
                            if error:
                                await author.send(f"Your motion `{motion['_id']}` has encountered an error.\nError: {error}")
                                broadcast(self.bot, "motion", 2, f"Motion `{motion['_id']}` has passed with {yea_int} Yea to {nay_int} Nay.\nThere was an error executing the motion: {error}")
                            else:
                                broadcast(self.bot, "motion", 2, f"Motion `{motion['_id']}` has passed with {yea_int} Yea to {nay_int} Nay.")
                        await db.Archives.archive_motion(motion["_id"], "passed")
                    else:
                        broadcast(self.bot, "motion", 2, f"Motion `{motion['_id']}` has been defeated with {nay_int} Nay to {yea_int} Yea.")
                        await db.Archives.archive_motion(motion["_id"], "failed")

                if motion["votetype"] == "referendum":
                    yea_int = len(motion["votes"]["Yea"])
                    nay_int = len(motion["votes"]["Nay"])
                    passratio = db.Motions.passratio(yea_int, nay_int)

                    if passratio > motion["passratio"]:
                        error = await motion_obj.execute()

                        if error:
                            print(error)
                            await author.send(f"Your motion `{motion['_id']}` has encountered an error.\nError: {error}")
                            broadcast(self.bot, "motion", 2, f"Motion `{motion['_id']}` has passed with {yea_int} Yea to {nay_int} Nay.\nThere was an error executing the motion: {error}")
                        else:
                            broadcast(self.bot, "motion", 2, f"Motion `{motion['_id']}` has passed with {yea_int} Yea to {nay_int} Nay.")
                    else:
                        broadcast(self.bot, "motion", 2, f"Motion `{motion['_id']}` has been defeated with {nay_int} Nay to {yea_int} Yea.")
                        await db.Archives.archive_motion(motion["_id"], "failed")
        return
    
    @slash_command(name='debugadvancemotion', description='Manually trigger motion_check_loop')
    @commands.is_owner()
    async def debugadvancemotion(self, ctx):
        await ctx.interaction.response.defer()
        await self.motion_check_loop()
        await ctx.respond("Loop triggered.")

    @slash_command(name='debugexpiremotion', description='Force a motion to expire by changing its expiration date.')
    @commands.is_owner()
    @option('motion_id', str, description='The ID of the motion.')
    async def debugexpiremotion(self, ctx, motion_id: str):
        await db.Motions.force_expire_motion(motion_id)
        await ctx.respond("Motion expired, will be archived on next loop. Run `/debugadvancemotion` to force archive.")

def setup(bot, config):
    global C
    C = config
    bot.add_cog(Legislation(bot))
