import common
from bot import *
import errors
from language import LangManager

"""
Assignment has an assigner (tutor), name (identifier), description (message ID), a solution (message ID).
It also has whether to tell the solution right after submission (in DM) or the date/time to tell the solution after
submission (after which it would be deleted).
Assignments will be created in DM and the assigner need only to edit the message directly to change them.
Assignments will be submitted based on tutor and name.
On submission, the student only need to use the assigner and the name and it will let the player know the description.
"""


async def __assign(ctx, name=None):
    dm = ctx.author.dm_channel

    await lang.get('assignment.create.start').send(ctx)

    if name is None:
        header = ""
        name = ""
        while True:
            name = (await common.prompt(dm, ctx.author, lang.get('assignment.create.1'), header=header)).content
            if 0 < len(name) < 32:
                break
            header = "**The name is too long! It cannot be longer than 31 characters!\n\n"

    description = await common.prompt(dm, ctx.author, lang.get('assignment.create.2'), timeout=900, name=name,
                                      time_display="15 minutes")
    description_id = description.id
    skipped = False
    solution = None
    try:
        solution = await common.prompt(dm, ctx.author, lang.get('assignment.create.3', timeout=900,
                                                                can_skip=True,
                                                                time_display="15 minutes",
                                                                url=description.jump_url))
        solution_id = solution.id
    except errors.PromptSkipped:
        skipped = True

    if not skipped:
        await lang.get('assignment.create.4', timeout=300, url=solution.jump_url).send(dm)
        # TODO - Complete homework creation prompt


async def __submit(ctx, assigner, name=None):
    pass


@commands.command(aliases=['hw', 'assignment', 'assignments'])
async def homework(ctx, sub=None, name=None, assigner: discord.Member = None):
    header = ''
    title = 'Assignments'
    color = ''
    if sub is not None:
        if sub.lower() in ("assign", "create", "start", "initiate", "make"):
            await __assign(ctx, name)
            return
        elif sub.lower() in ("remove", "delete", "unassign") and name is not None:
            database.update(
                """
                DELETE FROM assignments
                WHERE assigner = %s
                AND name = %s
                """,
                (ctx.author.id, name)
            )
            if database.cursor.rowcount != 0:
                header = f"**{name} was successfully deleted!\n\n"
                color = "%color.success%"
            else:
                header = f"**{name} does not exist!!\n\n"
                color = "%color.info%"
            # TODO - Also has to delete it from current scheduling process
        elif sub.lower() == "submit" and assigner is not None:
            pass
            return
        else:
            title = "Assignments - Unrecognized Command"
            color = "%color.error%"
    your_assignments = "\n".join(common.retrieve_assignments(ctx.author.id))
    node = lang.get('assignment.main').replace(title=title, header=header, assignments=your_assignments)
    node.args['embed'].color = discord.Color(int(LangManager.replace(color), 16))
    await node.send(ctx)


def setup(bot: commands.Bot):
    bot.add_command(homework)
