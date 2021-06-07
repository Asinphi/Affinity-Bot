import os as __os
import logging as __logging
import asyncio as __asyncio
import warnings as __warnings
from typing import Dict as __Dict, List as __List, Optional as __Optional
import functools as __functools

import discord
from discord.ext import commands
import discord_slash as __discord_slash

from utils import database
from utils.language import LangManager as __LangManager

from yaml import load, FullLoader

TOKEN = __os.environ['TOKEN']
WEB_URL = __os.environ['URL']

__warnings.filterwarnings("ignore", category=RuntimeWarning)

__logging.basicConfig(level=__logging.INFO)
logger = __logging.getLogger('discord')
logger.setLevel(__logging.INFO)
__handler = __logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
__handler.setFormatter(__logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(__handler)


def get_ignored_channels(guild_id):
    return database.query(
        """
        SELECT id
        FROM ignored_channels
        WHERE guild_id = %s
        """,
        (guild_id,)
    ).fetchall()


def get_prefix(guild_id):
    row = database.query(
        """
        SELECT prefix
        FROM guilds
        WHERE guilds.id = %s
        """,
        (guild_id,)
    ).fetchone()
    return lang.global_placeholders.get('default_prefix') if row is None else row[0]


def get_mention_or_prefix(_, message):
    if not message.guild:  # Sent in DMs
        return commands.when_mentioned_or(lang.global_placeholders.get('default_prefix'))(client, message)

    return commands.when_mentioned_or(get_prefix(message.guild.id))(client, message)


__intents = discord.Intents.all()
__intents.members = True
client = commands.Bot(command_prefix=get_mention_or_prefix, case_insensitive=True, help_command=None, intents=__intents)
slash = __discord_slash.SlashCommand(client, sync_commands=True)

# TODO - Make functions to get discord objects instead, refactor, and get rid of on_ready delay everywhere
rda: discord.Guild
channels: __Dict[str, discord.TextChannel]
roles: __Dict[str, discord.Role]


@__functools.cache
def slash_guild() -> __Optional[__List[int]]:
    #  return None if __os.environ['DEBUG'] == "0" else [rda.id]
    return [rda.id]


@client.listen('on_ready')
async def __on_ready():
    global rda, channels, roles
    with open("config.yml") as f:
        config = load(f, Loader=FullLoader)
        if __os.environ['DEBUG'] == '1':
            pre_text = 'test_'
            status = 'DEBUG'
        elif __os.environ['DEBUG'] == '0':
            pre_text = ''
            status = 'production'

        rda = client.get_guild(config[pre_text + 'servers']['rda'])
        channels = {name: rda.get_channel(channel_id) for name, channel_id in config[pre_text + "channels"].items()}
        roles = {name: rda.get_role(role_id) for name, role_id in config[pre_text + 'roles'].items()}

        logger.info("Created globals using {} set".format(status))
    logger.info(f"Logged in as {client.user}. I am in {len(client.guilds)} guilds.")
    await client.change_presence(activity=discord.Game("/character"))

__loop = __asyncio.get_event_loop()
__loop.create_task(client.start(TOKEN))

in_prompt = {}  # Dict of user IDs to their prompt message URLs; users in the middle of a prompt can't run commands

lang: __LangManager = __LangManager('messages.yml')
