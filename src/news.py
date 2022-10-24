import discord

def broadcast(bot, category:str, severity:int, message:str, embed:discord.Embed = None):
    bot.dispatch("broadcast", category, severity, message, embed)