from aiogram import types
from dotenv import find_dotenv, load_dotenv

from common.bot_cmds_list import admin_commands
from filters.chat_types import admins_list
from handlers.bot_management import management_router
from bot_instance import bot, dp

load_dotenv(find_dotenv())
import asyncio
import logging

logging.basicConfig(level=logging.INFO, filename="bot.log", format='%(asctime)s %(levelname)s:%(message)s')

dp.include_router(management_router)


async def on_startup():
    await bot.send_message(admins_list[0], "Бот работает, можно запускать")
    print("Бот работает")

async def on_shutdown():
    await bot.send_message(admins_list[0], "Бот лёг")
    print("Бот лёг")


async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)


    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_my_commands(commands=admin_commands, scope=types.BotCommandScopeAllPrivateChats())
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())



if __name__ == "__main__":
    asyncio.run(main())
