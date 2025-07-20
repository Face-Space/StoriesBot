from aiogram.types import BotCommand

admin_commands = [
    BotCommand(command="start", description="запуск бота"),
    BotCommand(command="stop", description="остановка бота"),
    BotCommand(command="status", description="глянуть статус бота"),
    BotCommand(command="stories_days", description="дни недели размещения постов"),
    BotCommand(command="stories_time", description="время размещения постов")
]
