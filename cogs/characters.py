import copy
import re
from typing import List, Dict, Set, Union, Optional
from datetime import timedelta, datetime
from collections import OrderedDict
import random
import asyncio

import psycopg2
from discord_slash import SlashContext
from discord_slash.cog_ext import cog_subcommand, cog_slash
from discord_slash.utils.manage_commands import create_option, create_permission
from discord_slash.model import SlashCommandOptionType, SlashCommandPermissionType

import events
from bot import *
import errors
from cogs import errorhandler
from utils import common
from utils.debounce import Debounce, DebounceException
from utils.event import Event


active_collection_names: Set[str] = set()
character_tiers: OrderedDict[int, float]  # num_stars to probability
hidden_tiers: List[int]
latest_rolls: Dict[int, datetime] = {}
character_claiming_event = Event()
character_claimed_event = Event()


def add_characters_from_str(collection: str, character_data: str):
    character_lines = character_data.split('\n')
    names = []
    pictures = []
    tiers = []
    quantities = []
    for line in character_lines:
        if len(line) < 2:
            continue
        match = re.match(fr"(?P<name>\S[a-zA-Z \-'()\d]*[a-zA-Z'.\d)])"
                         fr'( `(?P<picture>\S+)`)?'
                         fr'( (?P<rarity>{"|".join(map(str, character_tiers.keys()))}))?'
                         fr'( (?P<quantity>-?\d+))?$', line)
        if not match:
            raise errors.FormatError(line)
        name = match.group("name")
        if name in names:
            raise errors.FormatError(f"Duplicate name: {line}")
        names.append(name)
        pictures.append(match.group('picture'))
        tiers.append(match.group('rarity'))
        quantities.append(match.group('quantity'))
    args_str = ",".join(database.cursor.mogrify(f"('{collection}',%s,%s,%s,%s)",
                                                (name, picture, tier, quantity))
                        .decode("utf-8") for name, picture, tier, quantity in zip(names, pictures, tiers, quantities))
    try:
        database.update(
            f"""
            INSERT INTO character_collections (name) VALUES (%s)
            ON CONFLICT DO NOTHING;
            
            INSERT INTO character_data (collection, name, picture, rarity, quantity) VALUES {args_str}
            ON CONFLICT (collection, name) DO UPDATE SET picture = EXCLUDED.picture, rarity = EXCLUDED.rarity,
            quantity = EXCLUDED.quantity;
            """,
            (collection,)
        )
    except psycopg2.errors.CardinalityViolation:
        raise errors.FormatError(f"Duplicate name: Unknown line")
    return len(names)


async def prompt_character_add(ctx: SlashContext, collection_name):
    try:
        msg = (await lang.get('characters.add.enter_characters').send(ctx))[0]
        data = (await common.prompt(ctx.channel, ctx.author, msg)).content
    except errors.PromptError as e:
        await errorhandler.process(ctx, e)
        return

    try:
        count = add_characters_from_str(collection_name, data)  # Maybe try-except FormatError and put it in a loop
        await lang.get('characters.add.success').send(ctx, count=count, collection=collection_name)
    except errors.FormatError as e:
        await lang.get('characters.error.invalid_character_line').send(ctx, line=e.args[0])


@Debounce(timedelta(minutes=10), params=["user_id"])
def roll_character(user_id: int):
    n = random.random()
    n_total = 0
    last_pool = None
    row = None
    for tier, probability in character_tiers.items():
        pool = database.query(
            f"""
            SELECT character_data.id, collection, character_data.name, picture, quantity, color
            FROM character_data INNER JOIN character_rarity ON (character_rarity.num_stars = character_data.rarity)
            WHERE quantity != 0 AND character_data.rarity = {tier}
            AND collection in ({','.join(active_collection_names)})
            """
        ).fetchall()
        if len(pool) > 0:
            n_total += probability
            if n_total > n:
                row = (*random.choice(pool), tier)
                break
            last_pool = (pool, tier)
    if not row:
        if last_pool is None:
            return None
        row = (*random.choice(last_pool[0]), last_pool[1])
    now = datetime.utcnow()
    latest_rolls[user_id] = now

    member = rda.get_member(user_id)
    if member:
        asyncio.create_task(member.add_roles(roles['character_event'],
                                             reason="Character event participation: roll for character"))

    async def wait_for_claim():
        try:
            _, ctx = await character_claiming_event.wait(lambda claimer_id, _: claimer_id == user_id, timeout=90)
            if latest_rolls.get(user_id, None) == now:
                if row[4] != -1:
                    database.update(
                        """
                        UPDATE character_data
                        SET quantity = quantity - 1
                        WHERE id = %s AND quantity > 0
                        """,
                        (row[0],)
                    )
                    if database.cursor.rowcount == 0:  # Out of stock in those 90 seconds!
                        await lang.get('characters.error.character_already_claimed').send(ctx, character=row[2])
                        return
                asyncio.create_task(character_claimed_event.fire(user_id, *row, ctx))
                database.update(
                    """
                    INSERT INTO member_characters (member_id, collection, character_id)
                    VALUES (%s,%s,%s)
                    ON CONFLICT (member_id, collection) DO UPDATE SET character_id = EXCLUDED.character_id
                    """,
                    (user_id, row[1], row[0])
                )
        except asyncio.TimeoutError:
            pass
        finally:
            if latest_rolls.get(user_id, None) == now:
                latest_rolls.pop(user_id)
    asyncio.create_task(wait_for_claim())

    return row


async def character_page(ctx: Union[discord.Message, SlashContext], page_num: Optional[int], user: discord.User,
                         sender: discord.User):
    characters = database.query(
        """
        SELECT character_data.collection, name, picture, rarity
        FROM character_data INNER JOIN member_characters ON (character_data.id = member_characters.character_id)
        WHERE member_id = %s
        ORDER BY character_id DESC
        """,
        (user.id,)
    ).fetchall()
    last_page = len(characters)
    page_num = page_num or last_page
    try:
        collection, name, picture, tier = characters[page_num - 1]
    except IndexError:
        await lang.get('characters.error.user_has_no_characters').send(ctx, user=user.mention)
        return
    node = lang.get('characters.owned').replace(page=page_num, last=last_page, collection=collection, name=name,
                                                picture=picture, tier=tier, stars="★" * tier,
                                                sender=str(sender), user=user.mention)
    if isinstance(ctx, discord.Message):
        await node.nodes[0].edit(ctx)
    else:
        await node.send(ctx)


class Characters(commands.Cog):
    def __init__(self):
        global active_collection_names, character_tiers, hidden_tiers
        active_collection_names = {f"'{row[0]}'" for row in database.query(
            """
            SELECT name
            FROM character_collections
            WHERE is_active = true
            """
        ).fetchall()}
        character_tiers = OrderedDict([(tier, probability) for tier, probability in database.query(
            """
            SELECT num_stars, probability
            FROM character_rarity
            ORDER BY num_stars DESC
            """
        ).fetchall()])
        hidden_tiers = [name[0] for name in database.query(
            """
            SELECT num_stars
            FROM character_rarity
            WHERE hidden = true
            """
        ).fetchall()]

        @events.page_action
        async def page_character(page: int, title: str, user: discord.User, reaction: discord.Reaction):
            if title != lang.get('characters.owned').nodes[-1].args['embed'].title:
                return
            match = re.match(r'<@\d{17,}>', reaction.message.embeds[-1].description)
            ctx = commands.Context(bot=client, message=reaction.message, prefix=':P')
            await character_page(reaction.message, page, await commands.UserConverter().convert(ctx, match.group(0)),
                                 user)

    @cog_slash(name="characters", guild_ids=slash_guild(),
               description="View your claimed characters", default_permission=True,
               options=[
                   create_option(
                       name="user",
                       description="The user whose character collection you want to view if not your own",
                       option_type=SlashCommandOptionType.USER,
                       required=False
                   )
               ]
               )
    async def character_view(self, ctx: SlashContext, user: Optional[discord.User] = None):
        await character_page(ctx, 1, user or ctx.author, ctx.author)

    @cog_subcommand(base="character", name="roll", guild_ids=slash_guild(),
                    base_desc="Play as your favorite characters",
                    description="Roll for a character",
                    base_default_permission=True)
    async def character_roll(self, ctx: SlashContext):
        if len(active_collection_names) == 0:
            await lang.get('characters.error.no_active_collections').send(ctx)
            return
        if database.query(
            f"""
            SELECT character_id
            FROM member_characters
            WHERE member_id = %s AND collection in ({','.join(active_collection_names)})
            AND character_id IS NOT NULL
            """,
            (ctx.author.id,)
        ).fetchone():
            await lang.get('characters.error.max_characters_claimed').send(ctx)
            return

        try:
            char_id, collection, name, picture, quantity, color, num_stars = roll_character(ctx.author.id)
        except DebounceException as e:
            await lang.get('error.cooldown').send(ctx, interval=common.td_format(e.time_left))
            return
        except TypeError:
            await lang.get('characters.error.none_left').send(ctx)
            return
        star_str = "★" * num_stars
        quantity = quantity if quantity != -1 else '♾'
        node = lang.get('characters.rolled').replace(collection=collection, character=name, picture=picture,
                                                     quantity=quantity, color=color, stars=star_str)
        node.nodes[0].args['embed'].colour = discord.Colour(int(color, 16))
        msg: discord.Message = (await node.send(ctx))[0]
        try:
            claim = await character_claimed_event.wait(lambda claimer, *args: claimer == ctx.author.id, timeout=90)
            if claim[1] == char_id:
                claim_ctx = claim[-1]
                await lang.get('characters.claimed').send(claim_ctx, url=msg.jump_url, character=name,
                                                          collection=collection, num_left=quantity - 1
                                                          if quantity != -1 else "infinite")
                node.nodes[0].args['embed'].title += " (CLAIMED)"
                await node.edit(msg)
            else:
                raise asyncio.TimeoutError
        except asyncio.TimeoutError:
            embed = node.nodes[0].args['embed']
            embed.title += " (EXPIRED)"
            embed.description = node.nodes[0].options['expired']
            await node.edit(msg, collection=collection, stars=star_str)

    @cog_subcommand(base="character", name="claim", guild_ids=slash_guild(),
                    description="Claim the pending character - this cannot be undone",
                    base_default_permission=True)
    async def character_claim(self, ctx: SlashContext):
        if not latest_rolls.get(ctx.author.id):
            await lang.get('characters.error.no_pending_characters_to_claim').send(ctx)
            return
        await character_claiming_event.fire(ctx.author.id, ctx)

    @cog_subcommand(base="character", name="list", guild_ids=slash_guild(),
                    description="List the remaining characters you can roll for",
                    base_default_permission=True)
    async def character_list(self, ctx: SlashContext):
        if len(active_collection_names) == 0:
            await lang.get('characters.error.no_active_collections').send(ctx)
            return
        node = copy.deepcopy(lang.get('characters.list'))
        embed: discord.Embed = node.nodes[0].args['embed']
        for tier in character_tiers.keys():
            star_str = "★" * tier
            pool = database.query(
                f"""
                SELECT name, quantity
                FROM character_data
                WHERE quantity != 0 AND collection in ({','.join(active_collection_names)})
                AND rarity = %s
                """,
                (tier,)
            ).fetchall()
            if len(pool) > 0:
                embed.add_field(name=star_str, value="\n"
                                .join(f"{name if tier not in hidden_tiers else '???'} "
                                      f"x {quantity if quantity != -1 else '♾'}" for name, quantity in pool))
        await node.send(ctx)

    @cog_subcommand(base="collection", name="new", guild_ids=slash_guild(),
                    base_desc="Manage character collections",
                    description="Register a new collection of characters",
                    base_default_permission=False,
                    base_permissions={
                        rda.id: [
                            create_permission(roles['owner'].id, SlashCommandPermissionType.ROLE, True),
                            create_permission(roles['high_admin'].id, SlashCommandPermissionType.ROLE, True),
                            create_permission(roles['everyone'].id, SlashCommandPermissionType.ROLE, False)
                        ]
                    },
                    options=[
                        create_option(
                            name="collection_name",
                            description="An identifier for this new character collection",
                            option_type=SlashCommandOptionType.STRING,
                            required=True
                        )
                    ])
    async def character_collection_new(self, ctx: SlashContext, collection_name: str):
        collection_name = collection_name.lstrip().rstrip()
        if database.query(
            """
            SELECT name
            FROM character_collections
            WHERE name = %s
            """,
            (collection_name,)
        ).fetchone():
            await lang.get('characters.error.collection_already_exists').send(ctx, name=collection_name)
            return
        await prompt_character_add(ctx, collection_name)

    @cog_subcommand(base="collection", name="add", guild_ids=slash_guild(),
                    description="Add more characters to an existing collection",
                    options=[
                        create_option(
                            name="collection_name",
                            description="The name of the collection you're adding to",
                            option_type=SlashCommandOptionType.STRING,
                            required=True
                        )
                    ])
    async def character_collection_add(self, ctx: SlashContext, collection_name: str):
        if not database.query(
                """
                SELECT name
                FROM character_collections
                WHERE name = %s
                """,
                (collection_name,)
        ).fetchone():

            await lang.get('characters.error.collection_does_not_exist').send(ctx, name=collection_name)
            return
        await prompt_character_add(ctx, collection_name)

    @cog_subcommand(base="collection", name="rename", guild_ids=slash_guild(),
                    description="Rename an existing collection",
                    options=[
                        create_option(
                            name="current_collection_name",
                            description="The current name of the collection you're renaming",
                            option_type=SlashCommandOptionType.STRING,
                            required=True
                        ),
                        create_option(
                            name="new_collection_name",
                            description="The name you want to rename the collection to",
                            option_type=SlashCommandOptionType.STRING,
                            required=True
                        )
                    ])
    async def character_collection_rename(self, ctx: SlashContext, current_collection_name: str,
                                          new_collection_name: str):
        database.update(
            """
            UPDATE character_collections
            SET name = %s
            WHERE name = %s
            """,
            (new_collection_name, current_collection_name)
        )
        if database.cursor.rowcount == 0:
            await lang.get('characters.error.collection_does_not_exist').send(ctx, name=current_collection_name)
            return
        if f"'{current_collection_name}'" in active_collection_names:
            active_collection_names.discard(f"'{current_collection_name}'")
            active_collection_names.add(f"'{new_collection_name}'")
        await lang.get('characters.renamed').send(ctx, old_name=current_collection_name, new_name=new_collection_name)

    @cog_subcommand(base="collection", name="remove", guild_ids=slash_guild(),
                    description="Permanently remove a collection and its characters",
                    options=[
                        create_option(
                            name="collection_name",
                            description="The name of the collection you're removing",
                            option_type=SlashCommandOptionType.STRING,
                            required=True
                        )
                    ])
    async def character_collection_remove(self, ctx: SlashContext, collection_name: str):
        database.update("""
            DELETE FROM character_collections
            WHERE name = %s
        """, (collection_name,))
        if database.cursor.rowcount == 0:
            await lang.get('characters.error.collection_does_not_exist').send(ctx, name=collection_name)
            return
        active_collection_names.discard(f"'{collection_name}'")
        await lang.get('characters.removed').send(ctx, name=collection_name)

    @cog_subcommand(base="collection", name="activate", guild_ids=slash_guild(),
                    description="Allow players to roll for characters in the specified collection",
                    options=[
                        create_option(
                            name="collection_name",
                            description="The name of the collection you're activating",
                            option_type=SlashCommandOptionType.STRING,
                            required=True
                        ),
                        create_option(
                            name="activate",
                            description="Whether or not to activate the collection",
                            option_type=SlashCommandOptionType.BOOLEAN,
                            required=False
                        )
                    ])
    async def character_collection_activate(self, ctx: SlashContext, collection_name: str, activate: bool = True):
        try:
            collection_id = database.update(
                """
                UPDATE character_collections
                SET is_active = %s
                WHERE name = %s
                RETURNING name
                """,
                (activate, collection_name)
            ).fetchone()[0]
        except TypeError:
            await lang.get('characters.error.collection_does_not_exist').send(ctx, name=collection_name)
            return
        if activate:
            active_collection_names.add(f"'{collection_id}'")
        else:
            active_collection_names.discard(f"'{collection_id}'")
        await lang.get('characters.active_toggled').send(ctx, collection=collection_name, active=activate)

    @cog_subcommand(base="collection", name="list", guild_ids=slash_guild(),
                    description="View all registered collections")
    async def character_collection_list(self, ctx: SlashContext):
        data = database.query(
            """
            SELECT name, is_active
            FROM character_collections
            """
        ).fetchall()
        if not data:
            names = lang.get('characters.collection_list').nodes[0].options.get("no_collections", "No collections")
        else:
            names = "\n".join([f"**{row[0]}**" if row[1] else row[0] for row in data])
        node = lang.get('characters.collection_list').replace(names=names)
        await node.send(ctx)
