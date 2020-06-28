import asyncio
import datetime
from collections import namedtuple

import pytz

from bot import *
from cogs.admin import Admin
from cogs.errorhandler import ErrorHandler


def generate_tables():
    statements = (
        f"""
        CREATE TABLE IF NOT EXISTS guilds(
            id BIGINT PRIMARY KEY UNIQUE NOT NULL,
            prefix TEXT DEFAULT '{DEFAULT_PREFIX}'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ignored_channels(
            id BIGINT PRIMARY KEY UNIQUE NOT NULL,
            guild_id BIGINT NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_channel_guild ON ignored_channels(guild_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS assignments(
            assigner BIGINT PRIMARY KEY NOT NULL,
            name TEXT NOT NULL,
            description BIGINT,
            solution BIGINT,
            use_time BOOLEAN,
            time TIMESTAMPTZ,
            interval INTERVAL
        )
        """,
    )
    for statement in statements:
        database.update(statement)


client.add_cog(ErrorHandler(client))
client.add_cog(Admin())


@client.event
async def on_ready():
    logger.info(f"Logged in as {client.user}. I am in {len(client.guilds)} guilds.")

    # Spam Nitrogen
    async def wait_for(dt):
        # sleep until the specified datetime
        while True:
            now = datetime.datetime.now(pytz.utc)
            remaining = (dt - now).total_seconds()
            if remaining < 86400:
                break
            # asyncio.sleep doesn't like long sleeps, so don't sleep more
            # than a day at a time
            await asyncio.sleep(86400)
        await asyncio.sleep(remaining)

    async def run_at(dt, coro):
        await wait_for(dt)
        return await coro

    async def spam():
        # JL: 260608867292020737
        # Nitrogen: 450375444450115585
        user_id = 450375444450115585
        user = client.get_user(user_id)
        await user.create_dm()
        dm = user.dm_channel
        while True:
            await dm.send("metable")
            await asyncio.sleep(2)

    # await run_at(datetime.datetime(2020, 4, 9, 17, 0, 0, 0, pytz.UTC), spam())


@client.event
async def on_message(msg):
    await client.process_commands(msg)
    pass


@client.check
async def globally_ignore_channels(ctx):
    if database.query(
            """
        SELECT id
        FROM ignored_channels
        WHERE id = %s
        """,
            (ctx.channel.id,)
    ).fetchone() is None:
        return True
    else:
        await ctx.message.delete()
        embed = discord.Embed(title=f"{EMOJIS['error']} You cannot use commands in this channel",
                              colour=EMBED_COLORS['error'],
                              description="This channel is ignored by the bot. Please use another channel to execute "
                                          "commands.")
        await ctx.send(embed=embed, delete_after=3)
        return False


@client.check
async def globally_ignore_banned(ctx):
    # TODO
    return True


# help is a default command - could be overridden if it looks ugly
@client.command(aliases=["help", "cmds", "commands"])
async def _help(ctx):
    await lang.get('help').send(ctx)


@client.command(name="reverse")
async def reverse_poem(ctx, msg: discord.Message):
    lines = msg.content.split("\n")
    await ctx.send("\n".join(reversed(lines)))


@client.command(name='command')
async def command(ctx):
    embed = discord.Embed(title=f"{EMOJIS['error']} Unrecognized Command", colour=EMBED_COLORS["error"],
                          description=f"That's not an actual command, silly! It was an example. For a list of real "
                                      f"commands, use `{ctx.prefix}commands`")

    await ctx.send(embed=embed)


Entry = namedtuple('Entry', 'client event')
entries = [
    Entry(client=client, event=asyncio.Event()),
    Entry(client=janitor, event=asyncio.Event())
]

loop = asyncio.get_event_loop()


async def login():
    await entries[0].client.login(TOKEN)
    await entries[1].client.login(JANITOR_TOKEN)


async def wrapped_connect(entry):
    try:
        await entry.client.connect()
    except Exception as e:
        await entry.client.close()
        logger.error('We got an exception: ', e.__class__.__name__, e)
        entry.event.set()


async def check_close():
    futures = [e.event.wait() for e in entries]
    await asyncio.wait(futures)


loop.run_until_complete(login())

for entry in entries:
    loop.create_task(wrapped_connect(entry))

loop.run_until_complete(check_close())

loop.close()
