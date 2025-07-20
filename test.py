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
import asyncio

from filters.chat_types import IsAdmin, admins_list
from bot_instance import bot
from states.FSM import StoriesDays, StoriesTime


management_router = Router()
management_router.message.filter(IsAdmin())

# Используем class для хранения состояния бота вместо глобальных переменных
class BotState:
    def __init__(self):
        self.is_running = False
        self.stories_days = []
        self.stories_time = []
        self.sent_images = set()

bot_state = BotState()

channel_id = "-1002782899371"
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# Вынес создание драйвера в функцию с ленивой инициализацией, чтобы не стартовать сразу
def create_driver():
    service = Service(ChromeDriverManager().install())
    options = webdriver.ChromeOptions()
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36")
    options.add_argument("--headless")
    # Отключаем лишние логи selenium/google chrome
    options.add_argument("--log-level=3")
    options.add_argument("--disable-logging")
    return webdriver.Chrome(service=service, options=options)

driver = None  # Инициализируем позже при старте


available_days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]

# Сопоставляем русские дни с ключами cron (mon, tue...)
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
    global driver
    if driver is None:
        # Для надежности создаём драйвер, если вдруг он не инициализирован
        driver = create_driver()
    try:
        driver.refresh()
        await asyncio.sleep(2)  # Даем странице прогрузиться, без этого may fail
        await asyncio.sleep(0)  # Чтобы event loop не блокировать

        # Выполняем скролл (JS), чтобы подгрузить контент
        driver.execute_script("window.scrollBy(0, 1000)")

        src = driver.page_source
        soup = BeautifulSoup(src, "lxml")
        all_memes = soup.find_all(class_="infinite-item card")

        for mem in all_memes:
            # Проверяем наличие элементов и корректность структуры с защитой от исключений
            try:
                figure = mem.find("figure")
                if not figure:
                    continue
                a_tag = figure.find("a", attrs={"data-selector": ".meme-detail"})
                if not a_tag:
                    continue
                img_url = a_tag.get("href")
                if not img_url:
                    continue
            except Exception:
                continue

            if img_url not in bot_state.sent_images:
                bot_state.sent_images.add(img_url)
                await bot.send_photo(channel_id, photo=img_url, caption="Смотри что я нашёл!")
                await bot.send_message(chat_id=admins_list[0], text="Пост размещён")
                break
    except Exception as e:
        # Логируем ошибку чтобы не влияла на работу бота (можно настроить логирование)
        print(f"Error in get_content: {e}")

async def schedule_jobs():
    # Удаляем старые задания
    for job in scheduler.get_jobs():
        if job.id.startswith("get_content_job_"):
            scheduler.remove_job(job.id)

    if not bot_state.stories_days or not bot_state.stories_time:
        return

    if set(bot_state.stories_days) == set(available_days):
        day_of_week = "*"
    else:
        try:
            day_of_week = ",".join(day_map[day] for day in bot_state.stories_days)
        except KeyError:
            # В случае ошибки в днях - пропускаем расписание
            return

    for t in bot_state.stories_time:
        hour, minute = t.split(":")
        job_id = f"get_content_job_{hour}_{minute}"
        scheduler.add_job(
            get_content,
            trigger=CronTrigger(hour=hour, minute=minute, day_of_week=day_of_week),
            id=job_id,
            replace_existing=True
        )

    if not scheduler.running:
        scheduler.start()


@management_router.message(CommandStart())
async def start_cmd(message: types.Message):
    global driver
    if bot_state.is_running:
        await message.answer("Бот уже запущен.")
        return

    bot_state.is_running = True

    if not bot_state.stories_time:
        await message.answer(
            "Перед запуском бота установите время выкладывания постов с помощью команды /stories_time.\n"
            "Если вы установили время после запуска бота, перезапустите его"
        )
        return

    if not bot_state.stories_days:
        await message.answer(
            "Перед запуском бота установите дни недели выкладывания постов с помощью команды /stories_days.\n"
            "Если вы установили даты после запуска бота, перезапустите его"
        )
        return

    if driver is None:
        driver = create_driver()
    driver.get("https://www.memify.ru")
    await message.answer("Бот запущен, пожалуйста подождите...")
    await schedule_jobs()


@management_router.message(Command("stop"))
async def stop_cmd(message: types.Message):
    bot_state.is_running = False

    for job in scheduler.get_jobs():
        if job.id.startswith("get_content_job_"):
            scheduler.remove_job(job.id)

    # Можно корректно закрыть драйвер чтобы не держать процесс в фоне
    global driver
    if driver:
        try:
            driver.quit()
        except Exception:
            pass
        driver = None

    # Очистим уже отправленные ссылки, чтобы при новом старте не было "залипаний"
    bot_state.sent_images.clear()

    await message.answer("Бот остановлен")


@management_router.message(Command("status"))
async def status_cmd(message: types.Message):
    status = "Работает" if bot_state.is_running else "Остановлен"
    days = ', '.join(bot_state.stories_days) if bot_state.stories_days else "-"
    times = ', '.join(bot_state.stories_time) if bot_state.stories_time else "-"
    await message.answer(f"Статус бота: {status}")
    await message.answer(f"Дни недели, по которым выкладываются посты: {days}")
    await message.answer(f"Время выкладывания постов: {times}")


@management_router.message(Command("stories_days"))
async def set_days(message: types.Message, state: FSMContext):
    await message.answer(
        "Напишите через запятую c пробелом по каким дням недели размещать сторис, если все то *"
    )
    await state.set_state(StoriesDays.stories_days)


@management_router.message(StoriesDays.stories_days)
async def choose_days(message: types.Message, state: FSMContext):
    days = message.text.strip().lower()

    if days == "*":
        bot_state.stories_days = available_days
        await message.answer("Выбраны все дни недели.")
        await state.clear()
        return

    days_list = [d.strip() for d in days.split(",") if d.strip()]
    if all(day in available_days for day in days_list) and days_list:
        bot_state.stories_days = days_list
        await message.answer(f"Дни недели выбраны: {', '.join(bot_state.stories_days)}")
        await state.clear()
    else:
        await message.answer(
            "Введите корректные дни недели через запятую с пробелом, например: "
            "понедельник, вторник, среда, либо * чтобы выбрать все дни."
        )


@management_router.message(Command("stories_time"))
async def set_time(message: types.Message, state: FSMContext):
    await message.answer(
        "Укажите время размещения сторис через запятую, например: 07:01, 08:05, 09:05"
    )
    await state.set_state(StoriesTime.stories_time)


@management_router.message(StoriesTime.stories_time)
async def choose_time(message: types.Message, state: FSMContext):
    time = message.text.strip()
    times_list = [t.strip() for t in time.split(",") if t.strip()]

    time_pattern = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")

    if all(time_pattern.match(t) for t in times_list) and times_list:
        bot_state.stories_time = times_list
        await message.answer("Время для постов установлено.")
        await state.clear()
    else:
        await message.answer("Введите время в нужном формате, например: 23:59")


@management_router.message()
async def wtf(message: types.Message):
    # Для безопасности обрабатываем ошибочно присланные команды
    await message.delete()

'''Основные исправления и оптимизации:
1. Глобальные переменные заменены на класс BotState
Использование глобальных переменных плохо сказывается на читаемости и поддерживаемости кода. Заведён класс BotState, хранящий все состояния. Это также поможет в будущем сделать бота более объектно-ориентированным.

2. Создание Selenium драйвера вынесено в отдельную функцию с ленивой инициализацией
Драйвер создаётся только при необходимости, а не сразу при загрузке модуля. Это ускорит загрузку при перезапуске бота и позволит корректно закрывать драйвер.

3. Обработка ошибок при парсинге и при работе с Selenium
Добавлены try-except для предотвращения сбоев из-за неожиданного отсутствия элементов на странице или других ошибок.

4. Добавлен asyncio.sleep, чтобы дать странице время загрузиться после driver.refresh()
В асинхронном контексте без этого время ожидания, пока страница загрузится, может быть недостаточным.

5. Добавлен выход из функции start_cmd, если бот уже запущен
Не даёт запускать бота повторно иомного запусков драйвера.

6. Закрытие драйвера при остановке бота, очистка списка отправленных изображений
Это предотвращает утечку ресурсов и повторное отправление одних и тех же мемов.

7. Оптимизации в обработке списков: убраны лишние проверки, добавлена проверка на пустой список
8. Упрощения и улучшение читаемости
Например, аккуратный split с фильтрацией пустых строк (if t.strip()) для формирования списков.

9. Логика постановки задач APScheduler сделана более надёжной
Добавлена обработка ситуаций с ошибками в днях, а также упрощён код.

Комментарии по производительности
Основной "узкий" момент — Selenium. Вы используете headless Chrome + BeautifulSoup для парсинга. Так как загрузка страницы и её парсинг — это и есть наихудший по скорости участок.

Можно рассмотреть альтернативные подходы с использованием API/райдеров сайта (если таковые есть), или сократить логику парсинга так, чтобы не скроллировать бесконечно.

Также можно кешировать данные и проверять только новые посты, но текущая логика с множеством мелких улучшений в целом составляет хорошую основу.

Если хотите, могу помочь с более глубокими улучшениями, например, перейти на библиотеку вроде playwright или настроить асинхронный selenium!'''