import database
import discord
from datetime import timezone, datetime

from discord.ext import commands
from math import floor
from bot import lang, get_prefix
from yaml import load, FullLoader
from asyncio import TimeoutError
from copy import deepcopy
from language import MessageNode


def calculate(exp, is_profile=False):
    level_exp = 121
    exp_left = exp
    remainder = exp_left
    level = -1
    while exp_left >= 0:
        level += 1
        level_exp = 121 * (floor(level / 11) + 1) + (1331 if level >= 51 else 0) + (14641 if level >= 121 else 0)
        remainder = exp_left
        exp_left = exp_left - level_exp
    if is_profile:
        return level, remainder, level_exp
    return level


def add_exp(user_id, category_id, amount, multiplier_immune=False):
    if not multiplier_immune:
        pass
    database.update(
        """
        INSERT INTO levels (user_id, category_id, exp)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id, category_id) DO
        UPDATE SET exp = levels.exp + EXCLUDED.exp
        """,
        (user_id, category_id, amount)
    )


class Level(commands.Cog):
    """
    Solution emote: Add exp.
    Profile emote: DM profile and remove reaction.
    Profile command: Show exp and level.
    Average 11 exp.
    """

    def __init__(self, client):
        self.client = client
        with open("config.yml") as f:
            config = load(f, Loader=FullLoader)
            self.categories = config['categories']
            self.rda = config['servers']['rda']

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if reaction.emoji == lang.global_placeholders.get("emoji.solution") and reaction.message.author.id != user.id:
            category_name = None
            for category in self.categories:
                if reaction.message.channel.id in self.categories[category]:
                    category_name = category
                    break

            if category_name is None:
                return

            category_id, exp = database.query(
                """
                SELECT id, exp_rate
                FROM categories
                WHERE name = %s
                """,
                (category_name,)
            ).fetchone()

            add_exp(reaction.message.author.id, category_id, exp)
        elif reaction.emoji == lang.global_placeholders.get("emoji.profile"):
            await reaction.remove(user)
            await self.profile(user, (reaction.message.author,))

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction, user):
        if reaction.emoji == lang.global_placeholders.get("emoji.solution") and reaction.message.author.id != user.id:
            category_name = None
            for category in self.categories:
                if reaction.message.channel.id in self.categories[category]:
                    category_name = category
                    break

            if category_name is None:
                return

            category_id, exp = database.query(
                """
                SELECT id, exp_rate
                FROM categories
                WHERE name = %s
                """,
                (category_name,)
            ).fetchone()

            add_exp(reaction.message.author.id, category_id, -exp)

    @commands.command()
    async def profile(self, ctx, user: commands.Greedy[discord.Member] = None):
        if ctx.guild and ctx.guild.id == self.rda:
            user = user[0] if user else ctx.author
        else:
            user = self.client.get_guild(self.rda).get_member(user[0].id if user else ctx.author.id)

        ranks = database.query(
            """
            SELECT categories.name, levels.exp
            FROM levels JOIN categories
            ON category_id = categories.id AND user_id = %s
            """,
            (user.id,)
        ).fetchall()

        multipliers = database.query(
            """
            SELECT multiplier, end_time
            FROM multipliers
            WHERE user_id = %s
            """,
            (user.id,)
        ).fetchall()
        total_multiplier = 1
        for multiplier in multipliers:
            total_multiplier *= multiplier[0]

        rank_strings = [f"`{rank[0]}`\n**Level:** {calculate(rank[1])}    **Total Exp:** {rank[1]}\n**Exp Left Until Next Level:** {calculate(rank[1], True)[2] - calculate(rank[1], True)[1]}" for rank in ranks]
        multiplier_strings = "None." if not multipliers else [f"Multiplier: {multiplier[0]}x\nEnd Time: {multiplier[1] if multiplier[1] else 'Never.'}" for multiplier in multipliers]

        def strfdelta(timedelta):
            hours, remainder = divmod(timedelta.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            milliseconds, microseconds = divmod(timedelta.microseconds, 1000)
            return f"{timedelta.days} day{'s' if timedelta.days != 1 else ''}, {hours} hour{'s' if hours != 1 else ''}, {minutes} minute{'s' if minutes != 1 else ''}, {seconds} second{'s' if seconds != 1 else ''}, {milliseconds} millisecond{'s' if milliseconds != 1 else ''}, {microseconds} microsecond{'s' if microseconds != 1 else ''}"
        time = datetime.utcnow() - user.created_at
        print(time)
        print(str(time))
        print(strfdelta(time))

        await lang.get("profile").send(ctx, user_name=str(user), user_id=str(user.id), avatar_url=str(user.avatar_url), nickname='' if user.name == user.display_name else f"**Nickname:** {user.display_name}", levels='\n'.join(rank_strings) if rank_strings else "There are currently no levels to display.", multipliers=multiplier_strings if not multipliers else '\n'.join(multiplier_strings), join_server=user.joined_at.strftime('%A, %B %d, %Y; %I:%M %p UTC.'), join_discord=user.created_at.strftime('%A, %B %d, %Y; %I:%M %p UTC.'), server_duration=strfdelta(datetime.utcnow() - user.joined_at), discord_duration=strfdelta(datetime.utcnow() - user.created_at))

    @commands.command(aliases=("lb", "ranks", "ranking", "rankings", "levels", "leaderboards"))
    async def leaderboard(self, ctx, category=None):
        prefix = get_prefix(ctx.guild.id)

        shown_categories = []
        if category:
            category = category.upper() if category.upper() in ("GFX", "SFX") else category.capitalize()
            if category not in self.categories:
                await lang.get("error.invalid_category").send(ctx, category=category, prefix=prefix)
                return
            shown_categories.append(category)
        else:
            shown_categories = [category_name for category_name in self.categories]

        current_page = 1
        total_pages = 1
        rank_strings = {}
        lb_node = deepcopy(lang.get("leaderboard.main"))

        for category in shown_categories:
            ranks = database.query(
                """
                SELECT user_id, exp
                FROM levels JOIN categories
                ON category_id = categories.id AND categories.name = %s
                ORDER BY exp DESC
                """,
                (category,)
            ).fetchall()

            rank_strings[category] = []
            i = 0
            for row in ranks:
                i += 1
                formatting = '**' if row[0] != ctx.author.id else '`'
                index_string = formatting + "{}.)".format(i) + formatting
                rank_strings[category].append(f"{index_string} <@{row[0]}>  **Level:** {calculate(row[1])}    **Total Exp:** {row[1]}")

            category_total_pages = floor(len(rank_strings) / 10) + 1
            if category_total_pages > total_pages:
                total_pages = category_total_pages

            lb_node.nodes[0].args['embed'].add_field(name=category, value='\n\n'.join(rank_strings[category][(current_page - 1) * 10:current_page * 2]) if rank_strings[category] else "There are currently no rankings for this category.")
        lb_node.nodes[0].args['embed'].set_footer(text=f"{current_page}/{total_pages}")
        sent_message = (await lb_node.send(ctx, prefix=prefix))[0]

        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in (lang.global_placeholders.get("emoji.next"),
                                                                  lang.global_placeholders.get(
                                                                      "emoji.previous")) and reaction.message == sent_message

        while True:
            try:
                reaction, user = await self.client.wait_for('reaction_add', timeout=251, check=check)

                if reaction == lang.global_placeholders.get("emoji.next"):
                    current_page += 1
                else:
                    current_page -= 1
                if current_page > total_pages:
                    current_page = 1
                elif current_page < 1:
                    current_page = total_pages

                for category in shown_categories:
                    lb_node = lang.get("leaderboard.main")
                    page_rankings = '\n\n'.join(rank_strings[(current_page - 1) * 10:current_page * 2])
                    lb_node.nodes[0].args['embed'].add_field(name=category, value=page_rankings if page_rankings else "There are currently no rankings for this category on this page.")
                lb_node.nodes[0].args['embed'].set_footer(text=f"{current_page}/{total_pages}")
            except TimeoutError:
                inactive_embed = sent_message.embeds[0]
                inactive_embed.color = int(lang.global_placeholders.get("color.inactive"), 16)
                sent_message: discord.Message
                await sent_message.edit(content="This message is inactive. Please execute the command again to interact.", embed=inactive_embed)
                break

    @commands.command()
    async def categories(self, ctx):
        rows = database.query(
            """
            SELECT name, exp_rate
            FROM categories
            """
        ).fetchall()
        categories_node = deepcopy(lang.get("leaderboard.categories"))
        for row in rows:
            categories_node.nodes[0].args['embed'].add_field(name=row[0], value=f"Channels: <#{'><#'.join(str(channel) for channel in self.categories[row[0]])}>\nExp Rate: {row[1]}")
        await categories_node.send(ctx)
