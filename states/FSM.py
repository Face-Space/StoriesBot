from aiogram.fsm.state import State, StatesGroup


class StoriesDays(StatesGroup):
    stories_days = State()


class StoriesTime(StatesGroup):
    stories_time = State()


