import asyncio
import re
import traceback

import uvicorn

import bot
from bot import *
from web.app import app


async def run():
    await client.wait_until_ready()
    await asyncio.sleep(1)
    from cogs.admin import Admin
    from cogs.characters import Characters
    from cogs.errorhandler import ErrorHandler
    from cogs import errorhandler
    import conditions

    def generate_tables():
        statements = (
            f"""
            CREATE TABLE IF NOT EXISTS guilds (
                id BIGINT PRIMARY KEY UNIQUE NOT NULL,
                prefix TEXT DEFAULT '{lang.global_placeholders.get('default_prefix')}'
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS ignored_channels (
                id BIGINT PRIMARY KEY UNIQUE NOT NULL,
                guild_id BIGINT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_channel_guild
            ON ignored_channels(guild_id)
            """,
            """
            CREATE TABLE IF NOT EXISTS character_collections (
                name TEXT PRIMARY KEY UNIQUE NOT NULL,
                is_active BOOLEAN DEFAULT FALSE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS character_modules (
                collection TEXT NOT NULL,
                module TEXT NOT NULL,
                submodule TEXT NOT NULL DEFAULT 'core',
                PRIMARY KEY (collection, module, submodule),
                FOREIGN KEY (collection) REFERENCES character_collections (name)
                    ON DELETE CASCADE
                    ON UPDATE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS character_rarity (
                id SMALLINT PRIMARY KEY UNIQUE NOT NULL,
                name TEXT UNIQUE NOT NULL,
                probability REAL NOT NULL, -- Probability for the entire group to be selected
                default_quantity SMALLINT DEFAULT -1,
                color TEXT DEFAULT '0x9e33f3',
                hidden BOOLEAN NOT NULL DEFAULT false
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS character_data (
                collection TEXT NOT NULL,
                id SERIAL UNIQUE NOT NULL,
                name TEXT NOT NULL,
                picture TEXT,
                rarity SMALLINT DEFAULT 1,
                quantity SMALLINT,
                PRIMARY KEY (collection, id),
                FOREIGN KEY (collection) REFERENCES character_collections (name)
                    ON DELETE CASCADE
                    ON UPDATE CASCADE
            );
            
            CREATE UNIQUE INDEX IF NOT EXISTS uniq_character_name ON character_data (collection, name);
            
            CREATE OR REPLACE FUNCTION trg_character_data_quantity_default()
                RETURNS trigger
                LANGUAGE plpgsql AS
            $func$
            BEGIN
                IF NEW.rarity IS NULL THEN
                    NEW.rarity := 1;
                END IF;
            
                SELECT INTO NEW.quantity  character_rarity.default_quantity
                FROM   character_rarity
                WHERE  character_rarity.id = NEW.rarity;
                RETURN NEW;
            END
            $func$;
            
            DROP TRIGGER IF EXISTS character_data_quantity_default ON character_data;
            
            CREATE TRIGGER character_data_quantity_default
            BEFORE INSERT ON character_data
            FOR EACH ROW
            WHEN (NEW.quantity IS NULL)
            EXECUTE PROCEDURE trg_character_data_quantity_default();
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_character_name
            ON character_data(name)
            """,
            """
            CREATE TABLE IF NOT EXISTS member_characters (
                member_id BIGINT NOT NULL,
                collection TEXT NOT NULL,
                character_id INTEGER,
                PRIMARY KEY (member_id, collection),
                FOREIGN KEY (collection, character_id) REFERENCES character_data(collection, id)
                    ON DELETE CASCADE
                    ON UPDATE CASCADE
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_character_id
            ON member_characters(character_id)
            """,
            """
            INSERT INTO character_rarity (id, name, probability, default_quantity, color, hidden)
            VALUES
                (0, 'Trash', 1.0, -1, '0xd9d9d9', false),
                (1, 'Common', 0.3, 2, '0x19e320', false),
                (2, 'Uncommon', 0.3, 2, '0x1ae5e8', false),
                (3, 'Rare', 0.2, 2, '0x139ded', false),
                (4, 'Legendary', 0.05, 1, '0xe6c50e', false),
                (5, 'Mythical', 0.01, 1, '0xed201c', true)
            ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, probability=EXCLUDED.probability,
            default_quantity=EXCLUDED.default_quantity, color=EXCLUDED.color, hidden=EXCLUDED.hidden
            """
        )
        for statement in statements:
            database.update(statement)

    generate_tables()

    client.add_cog(ErrorHandler())
    client.add_cog(Admin())
    client.add_cog(Characters())

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
            await lang.get('error.ignored_channel').send(ctx)
            return False

    @client.check
    async def globally_ignore_banned(ctx):
        # TODO
        return True

    @client.check
    async def ignore_in_prompt(ctx):
        prompt = in_prompt.get(ctx.message.author.id)
        if prompt:
            try:
                await ctx.message.delete()
            except discord.errors.Forbidden:
                pass
            await lang.get('error.in_prompt').send(ctx, prompt=prompt)
            return False
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
        await lang.get('error.command').send(ctx, prefix=get_prefix(ctx.guild.id))

    @client.command(aliases=('reminder',))
    @commands.cooldown(1, 60*5, type=commands.BucketType.user)
    async def remind(ctx):
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass
        await lang.get('remind').send(ctx)

    @remind.error
    async def remind_error(ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            try:
                await ctx.message.delete()
            except discord.Forbidden:
                pass
            await lang.get('error.cooldown').send(ctx.author,
                                                  seconds_left=round(remind.get_cooldown_retry_after(ctx), 2))
        else:
            await errorhandler.process(ctx, error)

    @client.command(aliases=('exec',))
    @conditions.manager_only()
    async def execute(ctx: commands.Context):
        content = ctx.message.content
        matcher = re.compile(r'(-s)?\s*```\w+$(.+)```', re.MULTILINE | re.DOTALL)
        code = matcher.search(content)
        if code:
            try:
                exec(f"async def __ex(ctx):\n  " + '\n  '.join(code.group(2).split('\n')),
                     {**globals(), **locals()}, locals())
                result = await locals()['__ex'](ctx)
                await ctx.message.add_reaction(lang.global_placeholders['emoji.gotcha'])
            except Exception as e:
                await ctx.send(f"```{traceback.format_exc()}```" if code.group(1) else str(e))
                await ctx.message.add_reaction(lang.global_placeholders['emoji.error'])
        else:
            await ctx.message.add_reaction(lang.global_placeholders['emoji.no'])

    await slash.sync_all_commands()


loop = asyncio.get_event_loop()
loop.create_task(run())

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=9000)
