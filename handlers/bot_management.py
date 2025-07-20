from aiogram import Router, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import re

from filters.chat_types import IsAdmin, admins_list
from bot_instance import bot
from states.FSM import StoriesDays, StoriesTime


management_router = Router()
management_router.message.filter(IsAdmin())

channel_id = "-1002782899371"
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
available_days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]



service = Service(ChromeDriverManager().install())
options = webdriver.ChromeOptions()
options.add_argument(
    "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36")
options.add_argument("--headless")
driver = webdriver.Chrome(service=service, options=options)



class BotState:
    def __init__(self):
        self.is_running = False
        self.stories_days = []
        self.stories_time = []
        self.sent_images = set()

bot_state = BotState()

# Сопоставляем русские дни с цифрами для cron (понедельник=0 ... воскресенье=6)
day_map = {
    "понедельник": "mon",
    "вторник":    "tue",
    "среда":      "wed",
    "четверг":    "thu",
    "пятница":    "fri",
    "суббота":    "sat",
    "воскресенье":"sun"
}


async def get_content():
    driver.refresh()
    driver.execute_script(f"window.scrollBy(0, 1000)")

    src = str(driver.page_source)
    soup = BeautifulSoup(src, "lxml")
    all_memes = soup.find_all(class_="infinite-item card")

    for mem in all_memes:
        img_url = mem.find("figure").find("a", attrs={"data-selector":".meme-detail"}).get("href")
        if img_url not in bot_state.sent_images:
            bot_state.sent_images.add(img_url)
            await bot.send_photo(channel_id, photo=img_url, caption="Смотри что я нашёл!")
            await bot.send_message(chat_id=admins_list[0], text="Пост размещён")
            break


async def schedule_jobs():
    # Удаляем старые задания с таким id
    for job in scheduler.get_jobs():
        if job.id.startswith("get_content_job_"):
            scheduler.remove_job(job.id)

    # Если нет выбранных дней или времени — ничего не планируем
    if not bot_state.stories_days or not bot_state.stories_time:
        return

    # Формируем строку дней для cron: mon,tue,...
    if set(bot_state.stories_days) == set(available_days):
        day_of_week = "*"
    else:
        # создаёт генератор, который по каждому дню из stories_days берёт соответствующее сокращение из словаря day_map
        day_of_week = ",".join(day_map[day] for day in bot_state.stories_days)

    # Добавляем задачи на каждый указанный час и минуту
    try:
        for t in bot_state.stories_time:
            hour, minute = t.split(":")
            job_id = f"get_content_job_{hour}_{minute}"
            scheduler.add_job(
                get_content,
                trigger=CronTrigger(hour=hour, minute=minute, day_of_week=day_of_week),
                id=job_id,
                replace_existing=True
            )
            # replace_existing=True если задача с таким id уже есть, она перезаписывается

        if not scheduler.running:
            scheduler.start()
    except Exception as e:
        await bot.send_message(chat_id=admins_list[0], text=f"В боте произошла ошибка: {e}. Проверьте логи")


@management_router.message(CommandStart())
async def start_cmd(message: types.Message):
    if bot_state.is_running:
        await message.answer("Бот уже запущен.")

    elif not bot_state.stories_time:
        await message.answer("Перед запуском бота установите время выкладывания постов с помощью команды /stories_time.\n"
                             "Если вы установили время после запуска бота, перезапустите его")

    elif not bot_state.stories_days:
        await message.answer("Перед запуском бота установите дни недели выкладывания постов с помощью команды /stories_days.\n"
                             "Если вы установили даты после запуска бота, перезапустите его")

    else:
        driver.get("https://www.memify.ru")
        await message.answer("Бот запущен, пожалуйста подождите...")
        bot_state.is_running = True
        # Запускаем планировщик с текущими stories_days и stories_time, если они заданы
        await schedule_jobs()


@management_router.message(Command("stop"))
async def stop_cmd(message: types.Message):
    bot_state.is_running = False

    for job in scheduler.get_jobs():
        if job.id.startswith("get_content_job_"):
            scheduler.remove_job(job.id)

    bot_state.sent_images.clear()
    await message.answer("Бот остановлен")


@management_router.message(Command("status"))
async def status_cmd(message: types.Message):
    status = "Работает" if bot_state.is_running else "Остановлен"
    await message.answer(f"Статус бота: {status}")
    await message.answer(f"Дни недели, по которым выкладываются посты: {', '.join(bot_state.stories_days)}")
    await message.answer(f"Время выкладывания постов: {', '.join(bot_state.stories_time)}")


@management_router.message(Command("stories_days"))
async def set_days(message: types.Message, state: FSMContext):
    await message.answer("Напишите через запятую c пробелом по каким дням недели размещать сторис, если все то *")
    await state.set_state(StoriesDays.stories_days)


@management_router.message(StoriesDays.stories_days)
async def choose_days(message: types.Message, state: FSMContext):
    days = message.text.strip().lower()

    days_list = [d.strip() for d in days.split(",")]
    if all(day in available_days for day in days_list):
        bot_state.stories_days = days_list
        await message.answer(f"Дни недели выбраны: {', '.join(bot_state.stories_days)}")
        await state.clear()

    elif days == "*":
        bot_state.stories_days = available_days
        await message.answer("Выбраны все дни недели.")
        await state.clear()

    else:
        await message.answer("Введите корректные дни недели через запятую с пробелом, например: "
                             "понедельник, вторник, среда, либо * чтобы выбрать все дни.")


@management_router.message(Command("stories_time"))
async def set_time(message: types.Message, state: FSMContext):
    await message.answer("Укажите время размещения сторис через запятую, например: 07:01, 08:05, 09:05")
    await state.set_state(StoriesTime.stories_time)


@management_router.message(StoriesTime.stories_time)
async def choose_time(message: types.Message, state: FSMContext):
    time = message.text.strip()
    times_list = [t.strip() for t in time.split(",")]

    # Регулярка для проверки времени 00:00 - 23:59
    time_pattern = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")

    # проверка, соответствует ли строка t заданному регулярному выражению time_pattern
    if all(time_pattern.match(t) for t in times_list):
        bot_state.stories_time = times_list
        await message.answer("Время для постов установлено.")
        await state.clear()
    else:
        await message.answer("Введите время в нужном формате, например: 23:59")


@management_router.message()
async def wtf(message: types.Message):
    await message.delete()

