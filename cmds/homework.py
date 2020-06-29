import common
from bot import *
import helpers

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

    lang.get('assignment.create').send(ctx)

    if name is None:
        header = ""
        desc = "**What is the name of the assignment?**\n\nThis is a unique identifier that " \
               "students use to submit the assignment. It cannot be longer than 31 " \
               "characters and cannot be shorter than 1. Using an existing name will " \
               "replace the assignment." + helpers.message['cancel_prompt']
        name = ""
        while True:
            embed = discord.Embed(title="Create Assignment", colour=EMBED_COLORS['wizard'],
                                  description=header + desc)
            embed.set_footer(text=helpers.message['respond_prompt'])
            name = (await common.prompt(dm, ctx.author, embed=embed)).content
            length = len(name)
            if 0 < length < 32:
                break
            header = "**The name is too long! It cannot be longer than 31 characters!\n\n"

    embed = discord.Embed(title="Create Assignment", colour=EMBED_COLORS['wizard'],
                          description=f"**The name of the assignment is `{name}`\n\n"
                                      "**Write the description to your assignment.**\n\nThis will be shown to any "
                                      "student looking for assignment information. You can attach files and edit your "
                                      "description message freely." + helpers.message['cancel_prompt'])
    embed.set_footer(text=helpers.message['respond_prompt'])
    description_id = (await common.prompt(dm, ctx.author, embed=embed)).id

    embed = discord.Embed(title="Create Assignment", colour=EMBED_COLORS['wizard'],
                          description="**Write the solution to your assignment.**\n\nThis will be shown to any student "
                                      "looking for assignment information. You can attach files and edit your "
                                      "description message freely." + helpers.message['cancel_prompt'])
    embed.set_footer(text=helpers.message['respond_prompt'])
    solution_id = (await common.prompt(dm, ctx.author, embed=embed)).id

    embed = discord.Embed(title="Create Assignment", colour=EMBED_COLORS['wizard'],
                          description="**When do you want the answer to be shown to submitters?**\n\nThe solution "
                                      "would only be shown to those who have submitted the assignment. You will be "
                                      "able to see all submissions." + helpers.message['cancel_prompt'])
    embed.set_footer(text=helpers.message['respond_prompt'])


async def __submit(ctx, assigner, name=None):
    pass


@commands.command(aliases=['hw', 'assignment', 'assignments'])
async def homework(ctx, sub=None, name=None, assigner: discord.Member = None):
    header = ''
    title = 'Assignments'
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
            color = EMBED_COLORS['error']
    your_assignments = "\n".join(helpers.retrieve_assignments(ctx.author.id))
    node = lang.get('assignment.main').replace(title=title, header=header, assignments=your_assignments)
    node.args['embed'].color = discord.Color(int(LangManager.replace(color), 16))
    await node.send(ctx)


def setup(bot: discord.Client):
    bot.add_command(homework)
