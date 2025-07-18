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
import datetime

from filters.chat_types import IsAdmin
from bot_instance import bot
from states.FSM import StoriesDays, StoriesTime

management_router = Router()
management_router.message.filter(IsAdmin())
is_running = False

channel_id = "-1002782899371"
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service)

sent_images = set()
available_days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
stories_days = []
stories_time = []

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
    global sent_images
    driver.execute_script(f"window.scrollBy(0, 1000)")

    src = str(driver.page_source)
    soup = BeautifulSoup(src, "lxml")
    all_memes = soup.find_all(class_="infinite-item card")

    for mem in all_memes:
        img_url = mem.find("figure").find("a", attrs={"data-selector":".meme-detail"}).get("href")
        if img_url not in sent_images:
            sent_images.add(img_url)
            await bot.send_photo(channel_id, photo=img_url, caption="Смотри что я нашёл!")
            break


def schedule_jobs(message: types.Message):
    # Удаляем старые задания с таким id
    for job in scheduler.get_jobs():
        if job.id.startswith("get_content_job_"):
            scheduler.remove_job(job.id)

    # Если нет выбранных дней или времени — ничего не планируем
    if not stories_days or not stories_time:
        return

    # Формируем строку дней для cron: mon,tue,...
    if set(stories_days) == set(available_days):  # все дни
        day_of_week = "*"
    else:
        day_of_week = ",".join(day_map[day] for day in stories_days)

    # Добавляем задачи на каждый указанный час и минуту
    for t in stories_time:
        hour, minute = t.split(":")
        job_id = f"get_content_job_{hour}_{minute}"
        scheduler.add_job(
            lambda: get_content(),
            trigger=CronTrigger(hour=hour, minute=minute, day_of_week=day_of_week),
            id=job_id,
            replace_existing=True
        )

    if not scheduler.running:
        scheduler.start()


@management_router.message(CommandStart())
async def start_cmd(message: types.Message):
    global is_running
    is_running = True
    await message.answer("Бот запущен, пожалуйста подождите...")
    driver.get("https://www.memify.ru")

    # Запускаем планировщик с текущими stories_days и stories_time, если они заданы
    schedule_jobs(message)


@management_router.message(Command("stop"))
async def stop_cmd(message: types.Message):
    global is_running
    is_running = False

    for job in scheduler.get_jobs():
        if job.id.startswith("get_content_job_"):
            scheduler.remove_job(job.id)

    await message.answer("Бот остановлен")


@management_router.message(Command("status"))
async def status_cmd(message: types.Message):
    status = "Работает" if is_running else "Остановлен"
    await message.answer(f"Статус бота: {status}")


@management_router.message(Command("stories_days"))
async def set_days(message: types.Message, state: FSMContext):
    await message.answer("Напишите через запятую с пробелом по каким дням недели размещать сторис, если все то *")
    await state.set_state(StoriesDays.stories_days)


@management_router.message(StoriesDays.stories_days)
async def choose_days(message: types.Message, state: FSMContext):
    global stories_days
    days = message.text.strip().lower()

    if days == "*":
        stories_days = available_days
        await message.answer("Выбраны все дни недели.")
        await state.clear()
        schedule_jobs(message)
        return

    days_list = [d.strip() for d in days.split(",")]
    if all(day in available_days for day in days_list):
        stories_days = days_list
        await message.answer(f"Дни недели выбраны: {', '.join(stories_days)}")
        await state.clear()
        schedule_jobs(message)
    else:
        await message.answer("Введите корректные дни недели через запятую с пробелом, например: "
                             "понедельник, вторник, среда, либо * чтобы выбрать все дни.")


@management_router.message(Command("stories_time"))
async def set_time(message: types.Message, state: FSMContext):
    await message.answer("Укажите время размещения сторис через запятую, например: 07:01, 08:05, 09:05")
    await state.set_state(StoriesTime.stories_time)


@management_router.message(StoriesTime.stories_time)
async def choose_time(message: types.Message, state: FSMContext):
    global stories_time
    times_input = message.text.strip()
    times_list = [t.strip() for t in times_input.split(",")]

    # Регулярка для проверки времени 00:00 - 23:59
    time_pattern = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")

    # Проверяем, все ли времена корректны
    if all(time_pattern.match(t) for t in times_list):
        stories_time = times_list
        await message.answer(f"Время для постов установлено: {', '.join(stories_time)}")
        await state.clear()
        schedule_jobs(message)
    else:
        await message.answer("Введите время в нужном формате, например: 23:59, 07:01, 09:05")


@management_router.message()
async def wtf(message: types.Message):
    await message.delete()


'''Что изменено и добавлено
stories_days и stories_time теперь — списки, а не строки.

Добавлена функция schedule_jobs(message), которая очищает все старые задания с меткой get_content_job_ и добавляет новые по выбранным времени и дням.

Сопоставление русских дней и англ. обозначений cron-расписаний.

При вводе дней и времени всегда запускается schedule_jobs — обновляются расписания.

Проверка, что все дни и времена корректны.

Для каждого времени создаётся отдельная задача с уникальным ID.

В самой задаче get_content не надо фильтровать по дню — это сделает cron.

Убраны запуски с интервалом (10 секунд) — чтобы не мешать расписанию.

Время планируется через CronTrigger по часам и минутам и дню недели.

Теперь при запуске бота и установке дней и времени, посты будут отправляться только в эти дни, в указанное время.'''