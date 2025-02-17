import os
import logging
import traceback

import dotenv
import psycopg2

logger = logging.getLogger('discord')
logger.setLevel(logging.INFO)
handler = logging.FileHandler(filename='./discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

connection = None
cursor = None

dotenv.load_dotenv("./.env")
IS_DEBUG = os.environ['DEBUG'] == "1"


def connect(url=os.environ['DATABASE_URL'], sslmode='require', connect_timeout=-1, **kwargs):
    try:
        global connection, cursor
        connection = psycopg2.connect(url, sslmode=sslmode, connect_timeout=connect_timeout, **kwargs)
        cursor = connection.cursor()
    except (Exception, psycopg2.DatabaseError) as error:
        logger.fatal(error)


connect()


def update(*args, many: bool = False):
    """
    Executes a query and commits it.
    """
    try:
        if not many:
            cursor.execute(*args)
        else:
            cursor.executemany(*args)
        connection.commit()
        return cursor
    except psycopg2.errors.SyntaxError:
        logger.error(traceback.format_exc() + "\n" + args[0])
    except (psycopg2.DatabaseError, psycopg2.OperationalError):
        if IS_DEBUG:
            logger.error(traceback.format_exc())
            return
        connect()
        logger.debug("The update has failed! A new connection has been created.")
        return update(*args)


def query(*args):
    """
    Same as update() except it doesn't commit.
    """
    try:
        cursor.execute(*args)
        return cursor
    except psycopg2.DatabaseError:
        if IS_DEBUG:
            logger.error(traceback.format_exc())
            return
        connect()
        logger.debug("The query has failed! A new connection has been created.")
        return query(*args)
