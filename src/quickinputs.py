import asyncio
import datetime
from typing import Optional

import discord
from discord import option, slash_command
from discord.ext import commands, tasks

from . import database as db
from . import quickinputs as qi


class quickBMCView(discord.ui.View):

    async def select_callback(self, interaction): # the function called when the user is done selecting options
        await interaction.response.defer()

    def __init__(self, ctx, question, options, min_answers=1, max_answers=1):
        super().__init__(timeout=300)
        self.ctx = ctx
        select_menus = []
        options_discord = []
        if isinstance(options, list):
            options_discord = [discord.SelectOption(label=option) for option in options]
        if isinstance(options, dict):
            options_discord = [discord.SelectOption(label=option, value=options[option]) for option in options]
        select_menu = discord.ui.Select(
            placeholder=question,
            min_values=min_answers,
            max_values=max_answers,
            options=options_discord,
        )
        select_menu.callback = self.select_callback
        self.select_menu = select_menu
        next_page = discord.ui.Button(label="Next", style=discord.ButtonStyle.blurple)
        prev_page = discord.ui.Button(label="Previous", style=discord.ButtonStyle.blurple)
        self.add_item(self.select_menu)


    async def interaction_check(self, interaction):
        return interaction.user == self.ctx.author
    
    async def on_timeout(self):
        await self.ctx.send("You took too long to respond, please try again later.")
        self.stop()
    
    @discord.ui.button(label="Submit", style=discord.ButtonStyle.green)
    async def submit(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.defer()
        self.values = self.select_menu.values
        self.stop()
    
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.defer()
        self.values = []
        self.stop()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await super().interaction_check(interaction) and interaction.user == self.ctx.author


async def quickBMC(ctx, question, options, min_answers=1, max_answers=1):  # return list of answers
    view = quickBMCView(ctx, question, options, min_answers, max_answers)
    await ctx.respond(question, view=view, ephemeral=True)
    await view.wait()
    return view.values

class quickBoolView(discord.ui.View):

    def __init__(self, ctx):
        super().__init__(timeout=60)
        self.ctx = ctx

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.green)
    async def yes(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.defer()
        self.value = True
        self.stop()
    
    @discord.ui.button(label="No", style=discord.ButtonStyle.red)
    async def no(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.defer()
        self.value = False
        self.stop()

    async def interaction_check(self, interaction):
        return interaction.user == self.ctx.author
    
    async def on_timeout(self):
        await self.ctx.send("You took too long to respond, please try again later.")
        self.stop()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await super().interaction_check(interaction) and interaction.user == self.ctx.author


async def quickConfirm(ctx, question, true="Yes", false="No", cancel=None):
    view = quickBoolView(ctx)
    await ctx.respond(question, view=view, ephemeral=True)
    await view.wait()
    return view.value

class EmbedPaginator(discord.ui.View):
    index = 0
    embeds = []
    cancelled = False
    message = None

    def __init__(self, ctx, embeds):
        super().__init__(timeout=60)
        self.ctx = ctx
        counter = 0
        for embed in embeds:
            counter += 1
            if embed.footer.text == discord.Embed.Empty:
                embed.set_footer(text=f"Page {counter}/{len(embeds)}")
        self.embeds = embeds
    
    async def redraw(self):
        if not self.message:    return
        jod = await self.message.original_response()
        await jod.edit(embed=self.embeds[self.index], view=self)

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.blurple)
    async def prev(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.defer()
        self.index = max(self.index - 1, 0)
        await self.redraw()

    @discord.ui.button(label="Next", style=discord.ButtonStyle.blurple)
    async def next(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.defer()
        self.index = min(self.index + 1, len(self.embeds) - 1)
        await self.redraw()

    @discord.ui.button(label="End", style=discord.ButtonStyle.red)
    async def end(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.defer()
        self.cancelled = True
        self.stop()

    async def on_timeout(self):
        self.cancelled = True
        self.stop()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await super().interaction_check(interaction) and interaction.user == self.ctx.author

async def PaginateEmbeds(ctx, embeds):
    if len(embeds) == 1:
        await ctx.respond(embed=embeds[0], ephemeral=True)
        return
    view = EmbedPaginator(ctx, embeds)
    msg = await ctx.respond(embed=embeds[0], view=view, ephemeral=True)
    view.message = msg
    await view.wait()
