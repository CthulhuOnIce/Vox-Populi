import asyncio
import base64
import datetime
import io
from re import S
from typing import Optional

import discord
import pytz
from discord import option, slash_command
from discord.ext import commands, tasks

from . import database as db
from . import quickinputs as qi
from . import timestamps as ts
from .news import broadcast

C = {}
class RecordKeeping(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    public_channels = ['election', 'nomination']  # dispatches with these news codes can be openly viewed

    @slash_command(name="rules", description="View the rules of the server")
    async def rules(self, ctx):
        rules = await db.Rules.get_all_rules()  # [{ruleid: rule_text}, ...]
        embeds = []
        for motion in rules:
            embed = discord.Embed(title=f"{motion['_id']}: {motion['motion_title']}", description="")
            for rule in motion["rules"]:
                embed.add_field(name=rule, value=motion["rules"]["rule"], inline=False)
            embeds.append(embed)
        await qi.PaginateEmbeds(ctx, embeds)

    @slash_command(name='b64', description='Generate the base64 for a given image.')
    async def b64(self, ctx):
        msg = None
        try:
            await ctx.respond('Please send the image you want to encode.')
            msg = await self.bot.wait_for('message', check=lambda m: m.author == ctx.author and m.channel == ctx.channel and m.attachments, timeout=120)
            try:
                data = await msg.attachments[0].read()
                txt = base64.b64encode(data).decode('utf-8')
                if len(txt) > 2000:
                    fileio = io.StringIO(txt)
                    await ctx.respond('B64 attached.', file=discord.File(fp=fileio, filename='b64.txt'))
                else:
                    await ctx.respond(base64.b64encode(data).decode('utf-8'))
            except Exception as e:
                await ctx.respond(f'Could not encode the image. {e}')
        except asyncio.TimeoutError:
            await ctx.reply('Timed out.')
            return

    # it is very important that every response to this command is ephermeral
    @slash_command(name='help', description='Get hints on various topics and bot functions.')
    @option('topic', str, description='The topic to get help on.')
    async def list_channels(self, ctx, topic: Optional[str] = None):
        help_topics = {
            "motions": "How to write motions, what motions do, how motions work.",
            "elections": "How elections work and how to run for office and vote.",
            "archives": "How to access individual archives",
            "aql": "How to use the AQL system to query archives.",
            "petition": "How to write a petition and how petitions work.",
        }

        if topic is None:
            embed = discord.Embed(title="Help Topics", description="Use `/help <topic>` to get help on a specific topic.")
            for topic in help_topics:
                embed.add_field(name=topic, value=help_topics[topic], inline=False)
            await ctx.respond(embed=embed, ephemeral=True)
        
        topic = topic.lower()
        if topic not in help_topics:
            await ctx.respond(f"Unknown topic: {topic}", ephemeral=True)
            return

    @slash_command(name='list_channels', description='List all channels available for news dispatches.')
    async def list_channels(self, ctx):
        channels = await db.Radio.frequencies()
        msg = "List of channels:\n"
        msg += "\n - ".join(channels)
        await ctx.respond(msg, ephemeral=True)

    @slash_command(name='listen', description='Listen to a channel for dispatches')
    @option('channel', str, description='Channel to listen to')
    @option('threshold', int, description='Importance level that must be met. 1-5.', optional=True)
    async def listen(self, ctx, channel: str, threshold: Optional[int] = 1):
        channels = await db.Radio.frequencies()
        if channel not in channels:
            await ctx.respond("Channel not found.", ephemeral=True)
            return
        await db.Radio.add_listener(ctx.author.id, channel, threshold)
        await ctx.respond(f"📻 Tuning to `{channel}`. With threshold `{threshold}`.", ephemeral=True)

    @slash_command(name='unlisten', description='Stop listening to a channel for dispatches')
    @option('channel', str, description='Channel to stop listening to', optional=True)
    async def unlisten(self, ctx, channel: str):
        channels = await db.Radio.frequencies()
        if channel not in channels:
            await ctx.respond("Channel not found.", ephemeral=True)
            return
        await db.Radio.del_listener(ctx.author.id, channel)
        await ctx.respond(f"🔇 Stopped listening to `{channel}`.", ephemeral=True)
    
    @slash_command(name='constitution', description='View the general constitution.')
    async def constitution(self, ctx):
        const = await db.Constitution.get_constitution()
        embed = discord.Embed(title="Constitution", description="The current general constitution.", color=0xffb452)
        for rule in const:
            if rule == "_id":   continue
            embed.add_field(name=rule, value=const[rule])
        await ctx.respond(embed=embed, ephemeral=True)

    @slash_command(name='player_info', description='Get information about a User or Player.')
    @option('player_id', str, description='Target\'s User ID')
    async def player_info(self, ctx, player_id:str):
        try:
            player_id = int(player_id)
        except ValueError:
            await ctx.respond('Invalid User ID', ephemeral=True)
            return
        player = C["guild"].get_member(player_id)
        if player is None:
            try:
                player = await self.bot.fetch_user(player_id)
            except discord.NotFound:
                await ctx.respond("User does not exist.", ephemeral=True)
                return
        
        embed = discord.Embed(title=f"Player Information for {player.display_name}", color=0x52be41)
        embed.add_field(name="Name", value=player.display_name, inline=False)
        embed.add_field(name="ID", value=player.id, inline=False)
        embed.add_field(name="Created", value=ts.simple_day(player.created_at), inline=False)
        if player.avatar:
            embed.set_thumbnail(url=player.avatar)
        player_info = await db.Players.find_player(player.id)
        if player_info:
            embed.add_field(name="Message Count", value=player_info["messages"], inline=False)
            embed.add_field(name="Last Seen", value=ts.simple_day(player_info["last_message"]), inline=False)
            if "left" in player_info:
                embed.add_field(name="left", value=player_info["left"], inline=False)
            status = "Active - Can Vote" if player_info["can_vote"] else "Active - Cannot Vote"
            if player not in C["guild"].members:
                status = "Inactive"
                embed.color = 0x75916e
                try:
                    ban = await C["guild"].fetch_ban(player)
                    status = "Banned"
                    embed.color = 0x916e6e
                    if ban.reason:
                        embed.add_field(name="Ban Reason", value=ban.reason, inline=False)
                except discord.NotFound:
                    pass
            embed.add_field(name="Status", value=status, inline=False)
        else:
            embed.add_field(name="Status", value="Not Registered", inline=False)
            embed.color = 0x808080
        await ctx.respond(embed=embed, ephemeral=True)


    @commands.user_command(name="Get Player Info")  # create a user command for the supplied guilds
    async def player_information_click(self, ctx, member: discord.Member):  # user commands return the member
        await self.player_info(ctx, member.id)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        return

    @commands.Cog.listener()
    async def on_broadcast(self, category, importance, message, embed=None):
        print(f"News: {category} - {importance} - {message}")
        targets = await db.Radio.get_targets_for_frequency(category, importance)
        for target in targets:
            # find if target is a user or a channel
            # send message to target
            target_obj = self.bot.get_user(target)
            if target_obj is None:
                target_obj = self.bot.get_channel(target)
            if target_obj is None:
                await db.Radio.del_listener(target, category)
            if not embed:
                embed = discord.Embed(title=f"News: {category}", description=message, color=0x52be41)
                embed.set_footer(text=f"Importance: {importance}")
            try:
                await target_obj.send(embed=embed)
            except Exception as e:  # if there's an error, remove the listener
                await db.unlisten(target, category)
        return
    
    @commands.Cog.listener()
    async def on_member_leave(self, member):
        if member.bot:
            return
        await db.StatTracking.increment_leaves()
        await db.Archives.update_player(member)
    
    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.bot:
            return
        await db.StatTracking.increment_joins()
        await db.Archives.update_player(member)
    
    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if after.bot:
            return
        await db.Archives.update_player(after)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        if message.guild is not C["guild"]:
            return
        await db.StatTracking.increment_daily_messages(message.author)
        messages = await db.Archives.update_player(message.author, True)
        player = await db.Players.find_player(message.author.id)
        if not player["can_vote"]:  # dont bother doing all the work if they can vote anyway
            const = await db.Constitution.get_constitution()
            if messages >= const["VoterMinMessages"] and message.author.created_at <= datetime.datetime.utcnow().replace(tzinfo=pytz.UTC) - datetime.timedelta(days=const["VoterAccountAge"]):
                await message.channel.send(f"Congratulations {message.author.mention}!\nYou have reached {const['VoterMinMessages']} messages and an account age of {const['VoterAccountAge']} days.\nYou can now vote in elections!")
                self.bot.dispatch(event_name="new_voter", member=message.author)
                await db.Elections.enable_vote(message.author.id)
    
    @tasks.loop(minutes=10)
    async def check_stat_cashout(self):
        if datetime.datetime.utcnow().hour == 0:
            if not datetime.datetime.utcnow().replace(tzinfo=pytz.UTC).date() == datetime.datetime.fromtimestamp(db.StatTracking["start_timestamp"]).replace(tzinfo=pytz.UTC).date():
                stats = await db.StatTracking.cash_out()


def setup(bot, config):
    global C
    C = config
    bot.add_cog(RecordKeeping(bot))
