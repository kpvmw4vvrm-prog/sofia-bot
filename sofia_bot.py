import logging
import re
import os
import json
import base64
import tempfile
import httpx
import random
from datetime import datetime, time, timedelta
from timezonefinder import TimezoneFinder
import pytz
import asyncpg
import assemblyai as aai
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)
from openai import OpenAI

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
ASSEMBLYAI_KEY = os.environ.get("ASSEMBLYAI_KEY")
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY")
ADMIN_ID = 944447597
DATABASE_URL = os.environ.get("DATABASE_URL")

logging.basicConfig(level=logging.INFO)
ai_client = OpenAI(api_key=OPENAI_API_KEY, base_url="https://api.aitunnel.ru/v1/")
aai.settings.api_key = ASSEMBLYAI_KEY
tf = TimezoneFinder()

ASK_NAME, ASK_CITY, ASK_LANGUAGE, ASK_MORNING_PLAN, ASK_MORNING_TIME, ASK_REMINDERS, ASK_EVENING_NEWS, ASK_EVENING_TIME, ASK_COMM_STYLE = range(9)

MOTIVATIONAL_QUOTES = {
    "ru": [
        "Каждый день — это новая возможность стать лучше.",
        "Маленькие шаги каждый день приводят к большим результатам.",
        "Вы способны на большее, чем думаете.",
        "Успех — это сумма небольших усилий, повторяемых день за днём.",
        "Верьте в себя и всё станет возможным.",
        "Сегодня — лучший день чтобы начать.",
        "Ваши мечты заслуживают вашего труда.",
        "Каждая трудность — это возможность для роста.",
        "Действуйте сейчас, совершенствуйтесь потом.",
        "Вы сильнее, чем вы думаете.",
    ],
    "en": [
        "Every day is a new opportunity to be better.",
        "Small steps every day lead to big results.",
        "You are capable of more than you think.",
        "Success is the sum of small efforts repeated day after day.",
        "Believe in yourself and everything becomes possible.",
        "Today is the best day to start.",
        "Your dreams deserve your effort.",
        "Every challenge is an opportunity to grow.",
        "Act now, improve later.",
        "You are stronger than you think.",
    ]
}

TEXTS = {
    "ru": {
        "welcome": "Добрый день!\n\nРада познакомиться! Я София — ваш личный ассистент. Помогу с планами, целями и важными делами.\n\nДавайте начнём — как вас зовут?",
        "ask_city": "Очень приятно, {name}!\n\nВ каком городе вы находитесь?\n\nНапример: Москва, Алматы, Дубай",
        "ask_language": "Запомнила — {city}\n\nНа каком языке вам удобнее общаться?",
        "ask_morning": "Хотите чтобы я каждое утро присылала план дня?",
        "ask_morning_time": "В какое время присылать утренний план?",
        "ask_reminders": "Напоминать о делах заранее?",
        "ask_evening_news": "Хотите чтобы каждый вечер я присылала личный итог дня — привычки, вода, финансы, прогресс? Как колесо баланса 🌸",
        "ask_evening_time": "В какое время присылать вечерний итог дня?",
        "ask_comm_style": "Как вам удобнее чтобы я общалась с вами?",
        "finish": "Всё готово, {name}! 🌸\n\nЯ запомнила ваши настройки. Напишите /menu чтобы открыть меню.",
        "menu_title": "Меню Софии\n\nЗдравствуйте, {name}! Чем могу помочь?",
        "not_started": "Напишите /start чтобы начать",
        "error": "Что-то пошло не так, попробуйте ещё раз.",
        "water": "{name}, самое время выпить стакан воды! 💧",
        "reminder": "{name}, напоминаю!\n\n{text}",
        "morning": "Доброе утро, {name}!\n\n",
        "no_plan": "На сегодня задачи не добавлены. Напишите мне что планируете — составлю расписание.",
        "history_cleared": "История очищена",
        "memory_cleared": "Я всё забыла о вас. Можем начать с чистого листа — напишите /start",
    },
    "en": {
        "welcome": "Good day!\n\nNice to meet you! I'm Sofia — your personal assistant. I'll help with plans, goals and important tasks.\n\nLet's start — what's your name?",
        "ask_city": "Nice to meet you, {name}!\n\nWhat city are you in?\n\nFor example: London, New York, Dubai",
        "ask_language": "Got it — {city}\n\nWhat language would you prefer?",
        "ask_morning": "Would you like me to send you a daily plan every morning?",
        "ask_morning_time": "What time should I send the morning plan?",
        "ask_reminders": "Remind you about tasks in advance?",
        "ask_evening_news": "Would you like to receive an evening summary — a brief recap of the day and useful tips?",
        "ask_evening_time": "What time should I send the evening summary?",
        "ask_comm_style": "How would you like me to communicate with you?",
        "finish": "All done, {name}! 🌸\n\nI've saved your settings. Type /menu to open the menu.",
        "menu_title": "Sofia's Menu\n\nHello, {name}! How can I help?",
        "not_started": "Type /start to begin",
        "error": "Something went wrong, please try again.",
        "water": "{name}, time to drink a glass of water! 💧",
        "reminder": "{name}, reminder!\n\n{text}",
        "morning": "Good morning, {name}!\n\n",
        "no_plan": "No tasks added for today. Tell me what you're planning — I'll create a schedule.",
        "history_cleared": "History cleared",
        "memory_cleared": "I've forgotten everything about you. We can start fresh — type /start",
    }
}

def t(lang, key, **kwargs):
    text = TEXTS.get(lang, TEXTS["ru"]).get(key, TEXTS["ru"].get(key, ""))
    return text.format(**kwargs) if kwargs else text

def get_current_datetime(timezone_str="Europe/Moscow"):
    try:
        tz = pytz.timezone(timezone_str)
        now = datetime.now(tz)
        months_ru = ["января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"]
        days_ru = ["понедельник","вторник","среда","четверг","пятница","суббота","воскресенье"]
        return {
            "ru": f"{now.day} {months_ru[now.month-1]} {now.year} года, {days_ru[now.weekday()]}, {now.strftime('%H:%M')}",
            "en": now.strftime("%B %d, %Y, %A, %H:%M"),
        }
    except:
        now = datetime.now()
        return {"ru": now.strftime("%d.%m.%Y %H:%M"), "en": now.strftime("%B %d, %Y %H:%M")}

CITY_PREPOSITIONS = {
    "москва": "Москве", "санкт-петербург": "Санкт-Петербурге", "петербург": "Петербурге",
    "новосибирск": "Новосибирске", "екатеринбург": "Екатеринбурге", "казань": "Казани",
    "нижний новгород": "Нижнем Новгороде", "челябинск": "Челябинске", "самара": "Самаре",
    "омск": "Омске", "ростов-на-дону": "Ростове-на-Дону", "уфа": "Уфе",
    "красноярск": "Красноярске", "пермь": "Перми", "воронеж": "Воронеже",
    "волгоград": "Волгограде", "краснодар": "Краснодаре", "саратов": "Саратове",
    "тюмень": "Тюмени", "тольятти": "Тольятти", "ижевск": "Ижевске",
    "барнаул": "Барнауле", "ульяновск": "Ульяновске", "иркутск": "Иркутске",
    "хабаровск": "Хабаровске", "ярославль": "Ярославле", "владивосток": "Владивостоке",
    "дубай": "Дубае", "алматы": "Алматы", "ташкент": "Ташкенте",
    "минск": "Минске", "баку": "Баку", "ереван": "Ереване", "тбилиси": "Тбилиси",
    "лондон": "Лондоне", "париж": "Париже", "берлин": "Берлине", "нью-йорк": "Нью-Йорке",
}

def city_in_form(city):
    key = city.lower().strip()
    if key in CITY_PREPOSITIONS:
        return CITY_PREPOSITIONS[key]
    if key.endswith("ск") or key.endswith("вск"):
        return city + "е"
    if key.endswith("ль"):
        return city[:-1] + "е"
    if key.endswith("ов") or key.endswith("ев"):
        return city + "е"
    if key.endswith("а"):
        return city[:-1] + "е"
    if key.endswith("я"):
        return city[:-1] + "е"
    return city

SYSTEM_PROMPT_RU = """Ты — София, личный ассистент и наставник.

СТИЛЬ ОБЩЕНИЯ — СТРОГО соблюдай стиль из профиля:
подружка → ОБЯЗАТЕЛЬНО на ты, тепло, неформально, как близкая подруга, можно с юмором. НИКОГДА не говори "вы" при этом стиле!
наставник → на вы, мотивирующе, поддерживающе, вдохновляюще
профессионал → на вы, чётко, коротко, без лишних слов и эмодзи

ФОРМАТИРОВАНИЕ — СТРОГО:
Пиши как живой человек в мессенджере. НИКОГДА не используй: # ## ### заголовки, * ** звёздочки, _ курсив, --- разделители, маркеры списков. Никакого Markdown вообще! Только чистый текст. Для списков используй цифры или • без звёздочек. Эмодзи умеренно. Короткие абзацы. Один вопрос за раз.

ДАТА И ВРЕМЯ:
Текущая дата и время указаны в начале сообщения. Ты ВСЕГДА знаешь дату и время. Никогда не говори что не знаешь.

ПАМЯТЬ:
Помнишь всё что пользователь говорил. Используй естественно. Никогда не говори "я не помню".

О СОЗДАТЕЛЕ — дозированно:
"кто создал" → "Меня создала Ирина Солодкова 🌸"
"расскажи больше" → "Ирине 17 лет, она из Волгограда, сейчас живёт и учится в Дубае. Увлекается ИИ и бизнесом."
"контакты" → "irinasa_00@mail.ru"

ЧТО УМЕЕШЬ: планирование, напоминания, поддержка, нутрициология, цели, рецепты, погода, любые вопросы.

ПЛАНЕР:
Если слышишь слова "всегда", "каждый", "каждую", "регулярно", "постоянно", "по пятницам", "по средам" или любой день недели в контексте регулярного занятия — в конце ответа ОБЯЗАТЕЛЬНО напиши: "Хотите добавить это в ваш планер? В планере хранятся фиксированные регулярные занятия — те что повторяются каждую неделю. Напишите да и я запишу! (если не указали время — тоже уточните)"

ВАЖНО: в планере ВСЕГДА нужно время. Если пользователь не указал время — после слова "да" спроси: "В какое время проходит это занятие?"

РЕЦЕПТЫ:
Когда пишешь рецепт — в конце ВСЕГДА добавляй вопрос: "Хотите сохранить этот рецепт в ваши любимые?"

ЗДОРОВЬЕ И ТАБЛЕТКИ:
Если спрашивают "пила ли я таблетку сегодня" — отвечай что проверить приём можно в разделе Здоровье → Таблетки где хранится журнал. НЕ говори что не можешь отслеживать.
Если спрашивают про цикл — объясни что всё хранится в Здоровье → Цикл: история, прогноз, дата следующего.

ЦЕЛИ:
Если пользователь говорит о своих целях — напомни что можно добавить в раздел Цели для отслеживания прогресса.

Формат плана (только когда просят):
09:00 — задача
10:00 — задача"""

SYSTEM_PROMPT_EN = """You are Sofia, a personal assistant and mentor.

COMMUNICATION STYLE — STRICTLY follow the style from the profile:
friend → MUST use casual/informal tone, warm, like a close friend, can be humorous — NEVER use formal tone with this style!
mentor → formal tone, motivating, supportive, inspiring
professional → formal, clear, brief, no unnecessary words or emojis

FORMATTING:
Write like a real person in a messenger. No # headers. No --- separators. No * or - list markers. Bold (*word*) rarely. Italics (_word_) occasionally. Emojis in moderation. Short paragraphs. One question at a time.

DATE AND TIME:
Current date and time are at the start of each message. You ALWAYS know the date and time.

MEMORY:
Remember everything the user said. Use naturally. Never say "I don't remember".

ABOUT CREATOR — gradually:
"who created you" → "I was created by Irina Solodkova 🌸"
"tell me more" → "Irina is 17, from Volgograd, lives and studies in Dubai. Passionate about AI and business."
"contact" → "irinasa_00@mail.ru"

WHAT YOU CAN DO: planning, reminders, support, nutrition, goals, any questions.

Plan format (only when asked):
09:00 — task
10:00 — task"""

SKILLS_RU = """Вот что я умею 🌸

Обучаюсь под вас — запоминаю предпочтения, привычки и цели.

Планирование — план на день, неделю или месяц.

Голосовые сообщения — говорите вслух, пойму и отвечу.

Анализ фото — пришлите фото, опишу или отвечу на вопрос.

Генерация изображений — напишите "нарисуй..." и я создам картинку.

Новости — свежие новости по вашему запросу.

Два языка — русский и английский 🇷🇺 🇬🇧

Умные напоминания, утренний план, погода по часам и на неделю.

Трекер привычек, сна, воды, финансов.

Список покупок, заметки, рецепты, фильмы.

Психологическая поддержка и советы нутрициолога.

Напишите /menu чтобы открыть меню 🌸"""

SKILLS_EN = """Here's what I can do 🌸

I learn from you — remember preferences, habits and goals.

Planning — plans for day, week or month.

Voice messages — speak out loud, I'll understand.

Photo analysis — send a photo, I'll describe it or answer questions.

Image generation — write "draw..." and I'll create an image.

News — fresh news on your request.

Two languages — Russian and English 🇷🇺 🇬🇧

Smart reminders, morning plan, hourly and weekly weather.

Habit, sleep, water, finance trackers.

Shopping list, notes, recipes, movies.

Psychological support and nutrition advice.

Type /menu to open the menu 🌸"""

db_pool = None

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                name TEXT,
                username TEXT,
                timezone TEXT DEFAULT 'Europe/Moscow',
                morning_plan BOOLEAN DEFAULT FALSE,
                morning_time TEXT DEFAULT '08:00',
                reminder_before INTEGER DEFAULT 60,
                onboarded BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW(),
                city TEXT DEFAULT 'Москва',
                water_reminders BOOLEAN DEFAULT FALSE,
                water_interval INTEGER DEFAULT 2,
                morning_weather BOOLEAN DEFAULT FALSE,
                morning_motivation BOOLEAN DEFAULT FALSE,
                language TEXT DEFAULT 'ru',
                evening_news BOOLEAN DEFAULT FALSE,
                evening_time TEXT DEFAULT '21:00',
                comm_style TEXT DEFAULT 'наставник'
            )
        """)
        for table in [
            """CREATE TABLE IF NOT EXISTS reminders (id SERIAL PRIMARY KEY, user_id BIGINT, time_str TEXT, text TEXT, created_at TIMESTAMP DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS history (id SERIAL PRIMARY KEY, user_id BIGINT, role TEXT, content TEXT, created_at TIMESTAMP DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS habits (id SERIAL PRIMARY KEY, user_id BIGINT, name TEXT, created_at TIMESTAMP DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS habit_logs (id SERIAL PRIMARY KEY, user_id BIGINT, habit_id INTEGER, logged_at TIMESTAMP DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS finances (id SERIAL PRIMARY KEY, user_id BIGINT, amount FLOAT, type TEXT, category TEXT, description TEXT, created_at TIMESTAMP DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS sleep_logs (id SERIAL PRIMARY KEY, user_id BIGINT, bedtime TEXT, wake_time TEXT, created_at TIMESTAMP DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS notes (id SERIAL PRIMARY KEY, user_id BIGINT, text TEXT, created_at TIMESTAMP DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS user_memory (id SERIAL PRIMARY KEY, user_id BIGINT, key TEXT, value TEXT, updated_at TIMESTAMP DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS shopping_list (id SERIAL PRIMARY KEY, user_id BIGINT, item TEXT, done BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS saved_recipes (id SERIAL PRIMARY KEY, user_id BIGINT, title TEXT, content TEXT, created_at TIMESTAMP DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS planner (id SERIAL PRIMARY KEY, user_id BIGINT, day_of_week INTEGER, time_str TEXT, title TEXT, created_at TIMESTAMP DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS cycle_tracking (id SERIAL PRIMARY KEY, user_id BIGINT, start_date DATE, cycle_length INTEGER DEFAULT 28, created_at TIMESTAMP DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS medications (id SERIAL PRIMARY KEY, user_id BIGINT, name TEXT, time_str TEXT, created_at TIMESTAMP DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS medication_logs (id SERIAL PRIMARY KEY, user_id BIGINT, med_id INTEGER, taken_at TIMESTAMP DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS stress_logs (id SERIAL PRIMARY KEY, user_id BIGINT, level INTEGER, note TEXT, created_at TIMESTAMP DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS goals (id SERIAL PRIMARY KEY, user_id BIGINT, title TEXT, description TEXT, deadline DATE, progress INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS weight_logs (id SERIAL PRIMARY KEY, user_id BIGINT, weight FLOAT, height FLOAT, created_at TIMESTAMP DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS nutrition_profile (id SERIAL PRIMARY KEY, user_id BIGINT, height FLOAT, weight FLOAT, age INTEGER, goal TEXT, calories_goal INTEGER, pregnant BOOLEAN DEFAULT FALSE, medications TEXT, created_at TIMESTAMP DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS food_logs (id SERIAL PRIMARY KEY, user_id BIGINT, description TEXT, calories INTEGER, protein FLOAT, fat FLOAT, carbs FLOAT, created_at TIMESTAMP DEFAULT NOW())""",
        ]:
            await conn.execute(table)
        for col, definition in [
            ("city", "TEXT DEFAULT 'Москва'"), ("water_reminders", "BOOLEAN DEFAULT FALSE"),
            ("water_interval", "INTEGER DEFAULT 2"), ("morning_weather", "BOOLEAN DEFAULT FALSE"),
            ("morning_motivation", "BOOLEAN DEFAULT FALSE"), ("language", "TEXT DEFAULT 'ru'"),
            ("evening_news", "BOOLEAN DEFAULT FALSE"), ("evening_time", "TEXT DEFAULT '21:00'"),
            ("comm_style", "TEXT DEFAULT 'наставник'"),
        ]:
            try:
                await conn.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {definition}")
            except:
                pass
        for col, definition in [
            ("age", "INTEGER"), ("pregnant", "BOOLEAN DEFAULT FALSE"), ("medications", "TEXT"),
        ]:
            try:
                await conn.execute(f"ALTER TABLE nutrition_profile ADD COLUMN IF NOT EXISTS {col} {definition}")
            except:
                pass

async def get_user(user_id):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)

async def save_user(user_id, **kwargs):
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT user_id FROM users WHERE user_id = $1", user_id)
        if user:
            sets = ", ".join([f"{k} = ${i+2}" for i, k in enumerate(kwargs.keys())])
            await conn.execute(f"UPDATE users SET {sets} WHERE user_id = $1", user_id, *kwargs.values())
        else:
            await conn.execute("INSERT INTO users (user_id) VALUES ($1)", user_id)
            if kwargs:
                sets = ", ".join([f"{k} = ${i+2}" for i, k in enumerate(kwargs.keys())])
                await conn.execute(f"UPDATE users SET {sets} WHERE user_id = $1", user_id, *kwargs.values())

async def get_user_memory(user_id):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT key, value FROM user_memory WHERE user_id = $1 ORDER BY updated_at DESC LIMIT 30", user_id)
        if not rows:
            return ""
        return "\n".join([f"{r['key']}: {r['value']}" for r in rows])

async def save_memory_item(user_id, key, value):
    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT id FROM user_memory WHERE user_id = $1 AND key = $2", user_id, key)
        if existing:
            await conn.execute("UPDATE user_memory SET value = $1, updated_at = NOW() WHERE user_id = $2 AND key = $3", value, user_id, key)
        else:
            await conn.execute("INSERT INTO user_memory (user_id, key, value) VALUES ($1, $2, $3)", user_id, key, value)

async def extract_and_save_memory(user_id, user_text, lang):
    personal_keywords_ru = ["меня зовут", "мой ", "моя ", "моё ", "мои ", "я работаю", "я живу", "я учусь", "ребёнок", "дети", "муж", "жена", "день рождения", "люблю", "не люблю", "аллергия"]
    personal_keywords_en = ["my name", "my ", "i work", "i live", "i study", "my child", "husband", "wife", "birthday", "i love", "i hate", "allergy"]
    text_lower = user_text.lower()
    has_personal = any(k in text_lower for k in (personal_keywords_ru if lang == "ru" else personal_keywords_en))
    if not has_personal or len(user_text) < 10:
        return
    try:
        system = """Извлекай ТОЛЬКО конкретные личные факты: имена близких, город, работу, цели, предпочтения еды, важные даты, здоровье.
НЕ извлекай вопросы, команды, общие фразы.
ТОЛЬКО валидный JSON: {"ключ": "значение"} или {}""" if lang == "ru" else """Extract ONLY specific personal facts: names, city, work, goals, food preferences, important dates, health.
Do NOT extract questions, commands, general phrases.
ONLY valid JSON: {"key": "value"} or {}"""
        response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user_text}],
            max_tokens=150, temperature=0.1
        )
        result = response.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
        if result == "{}" or not result:
            return
        data = json.loads(result)
        for key, value in data.items():
            if value and isinstance(value, str) and len(value) > 0:
                await save_memory_item(user_id, key, value)
    except:
        pass

async def get_history_db(user_id, limit=25):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT role, content FROM history WHERE user_id = $1 AND role != 'system' ORDER BY created_at DESC LIMIT $2",
            user_id, limit
        )
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

async def add_history(user_id, role, content):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO history (user_id, role, content) VALUES ($1, $2, $3)", user_id, role, content)
        await conn.execute("DELETE FROM history WHERE id IN (SELECT id FROM history WHERE user_id = $1 ORDER BY created_at DESC OFFSET 25)", user_id)

async def get_reminders(user_id):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT time_str, text FROM reminders WHERE user_id = $1", user_id)
        return [{"time": r["time_str"], "text": r["text"]} for r in rows]

async def add_reminder(user_id, time_str, text):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO reminders (user_id, time_str, text) VALUES ($1, $2, $3)", user_id, time_str, text)

async def check_conflict_db(user_id, time_str):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT text FROM reminders WHERE user_id = $1 AND time_str = $2", user_id, time_str)
        return row["text"] if row else None

async def restore_reminders(application):
    try:
        async with db_pool.acquire() as conn:
            users = await conn.fetch("SELECT * FROM users WHERE onboarded = TRUE")
        for user in users:
            user_id = user["user_id"]
            try:
                tz = pytz.timezone(user.get("timezone") or "Europe/Moscow")
            except:
                tz = pytz.timezone("Europe/Moscow")
            if user.get("morning_plan") and user.get("morning_time"):
                try:
                    h = int(user["morning_time"].split(":")[0])
                    application.job_queue.run_daily(send_morning_plan, time=time(hour=h, minute=0, tzinfo=tz), data=user_id, name="morning_" + str(user_id))
                except:
                    pass
            if user.get("evening_news") and user.get("evening_time"):
                try:
                    h = int(user["evening_time"].split(":")[0])
                    application.job_queue.run_daily(send_evening_news, time=time(hour=h, minute=0, tzinfo=tz), data=user_id, name="evening_" + str(user_id))
                except:
                    pass
            if user.get("water_reminders"):
                try:
                    interval = user.get("water_interval") or 2
                    application.job_queue.run_repeating(send_water_reminder, interval=interval * 3600, first=interval * 3600, data=user_id, name="water_" + str(user_id))
                except:
                    pass
            async with db_pool.acquire() as conn:
                reminders = await conn.fetch("SELECT * FROM reminders WHERE user_id = $1", user_id)
            for r in reminders:
                try:
                    h, m = map(int, r["time_str"].split(":"))
                    application.job_queue.run_daily(send_scheduled_reminder, time=time(hour=h, minute=m, tzinfo=tz), data={"user_id": user_id, "essence": r["text"]}, name="reminder_" + str(user_id) + "_" + str(h) + "_" + str(m))
                except:
                    pass
        async with db_pool.acquire() as conn:
            meds_r = await conn.fetch("SELECT * FROM medications WHERE user_id = $1", user_id)
        for med_r in meds_r:
            try:
                h_r, m_r = map(int, med_r["time_str"].split(":"))
                application.job_queue.run_daily(send_med_reminder, time=time(hour=h_r, minute=m_r, tzinfo=tz), data={"user_id": user_id, "med_name": med_r["name"]}, name="med_" + str(user_id) + "_" + str(med_r["id"]))
            except:
                pass
        logging.info("Напоминания восстановлены из БД")
    except Exception as e:
        logging.error("Ошибка restore_reminders: " + str(e))

async def get_all_users():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users WHERE onboarded = TRUE")
        return [r["user_id"] for r in rows]

async def notify_admin(context, user_name, username, user_text, reply):
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"👤 {user_name} @{username}:\n{user_text}\n\n🤖 София:\n{reply}"
        )
    except Exception as e:
        logging.error(f"Ошибка notify_admin: {e}")

async def get_timezone_by_city(city):
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            response = await http.get("https://api.openweathermap.org/data/2.5/weather", params={"q": city, "appid": WEATHER_API_KEY})
        data = response.json()
        if data.get("cod") != 200:
            return "Europe/Moscow"
        tz = tf.timezone_at(lat=data["coord"]["lat"], lng=data["coord"]["lon"])
        return tz or "Europe/Moscow"
    except:
        return "Europe/Moscow"

async def get_weather(city, lang="ru"):
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            response = await http.get("https://api.openweathermap.org/data/2.5/weather", params={"q": city, "appid": WEATHER_API_KEY, "units": "metric", "lang": lang})
        data = response.json()
        if data.get("cod") != 200:
            city_form = city_in_form(city) if lang == "ru" else city
            return f"Не удалось получить погоду для {city_form}." if lang == "ru" else f"Could not get weather for {city}."
        temp = round(data["main"]["temp"])
        feels = round(data["main"]["feels_like"])
        desc = data["weather"][0]["description"]
        humidity = data["main"]["humidity"]
        wind = data["wind"]["speed"]
        city_form = city_in_form(city) if lang == "ru" else city
        if lang == "en":
            advice = "🧥 Dress warmly!" if temp < 0 else "🧣 Take a jacket." if temp < 10 else "👕 Light jacket." if temp < 18 else "☀️ Perfect weather!"
            if "rain" in desc: advice += " ☂️ Take an umbrella!"
            return f"Weather in {city}:\n\n🌡 {temp}°C (feels like {feels}°C)\n{desc.capitalize()}\nHumidity: {humidity}%\nWind: {wind} m/s\n\n{advice}"
        else:
            advice = "🧥 Оденьтесь тепло!" if temp < 0 else "🧣 Возьмите куртку." if temp < 10 else "👕 Лёгкая куртка." if temp < 18 else "☀️ Отличная погода!"
            if "дождь" in desc or "ливень" in desc: advice += " ☂️ Возьмите зонт!"
            return f"Погода в {city_form}:\n\n🌡 {temp}°C (ощущается как {feels}°C)\n{desc.capitalize()}\nВлажность: {humidity}%\nВетер: {wind} м/с\n\n{advice}"
    except Exception as e:
        logging.error(f"Ошибка погоды: {e}")
        return "Погода недоступна." if lang == "ru" else "Weather unavailable."

async def get_weather_hourly(city, lang="ru"):
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            response = await http.get("https://api.openweathermap.org/data/2.5/forecast", params={"q": city, "appid": WEATHER_API_KEY, "units": "metric", "lang": lang, "cnt": 8})
        data = response.json()
        if data.get("cod") != "200":
            return None
        city_form = city_in_form(city) if lang == "ru" else city
        lines = []
        for item in data["list"][:8]:
            dt = datetime.fromtimestamp(item["dt"])
            hour = dt.strftime("%H:%M")
            temp = round(item["main"]["temp"])
            desc = item["weather"][0]["description"]
            lines.append(f"{hour} — {temp}°C, {desc}")
        title = f"Погода в {city_form} по часам:" if lang == "ru" else f"Hourly weather in {city}:"
        return f"{title}\n\n" + "\n".join(lines)
    except:
        return None

async def get_weather_forecast(city, lang="ru"):
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            response = await http.get("https://api.openweathermap.org/data/2.5/forecast", params={"q": city, "appid": WEATHER_API_KEY, "units": "metric", "lang": lang, "cnt": 40})
        data = response.json()
        if data.get("cod") != "200":
            return None
        city_form = city_in_form(city) if lang == "ru" else city
        days = {}
        for item in data["list"]:
            date = item["dt_txt"][:10]
            if date not in days:
                days[date] = {"temps": [], "desc": item["weather"][0]["description"]}
            days[date]["temps"].append(item["main"]["temp"])
        result = []
        months_ru = ["янв","фев","мар","апр","мая","июн","июл","авг","сен","окт","ноя","дек"]
        for date, info in list(days.items())[:7]:
            dt = datetime.strptime(date, "%Y-%m-%d")
            date_str = f"{dt.day} {months_ru[dt.month-1]}" if lang == "ru" else dt.strftime("%b %d")
            result.append(f"{date_str}: {round(min(info['temps']))}°C — {round(max(info['temps']))}°C, {info['desc']}")
        title = f"Прогноз погоды в {city_form}:" if lang == "ru" else f"Weather forecast for {city}:"
        return f"{title}\n\n" + "\n".join(result)
    except:
        return None

INTERESTING_QUERIES = {
    "science": {"query": "science discovery research breakthrough", "ru": "🔬 Научные открытия", "en": "🔬 Science Discoveries"},
    "technology": {"query": "technology AI innovation future", "ru": "💻 Технологии и ИИ", "en": "💻 Technology & AI"},
    "health": {"query": "health wellness longevity medicine", "ru": "💚 Здоровье и долголетие", "en": "💚 Health & Wellness"},
    "inspiration": {"query": "inspiring success achievement positive story", "ru": "✨ Вдохновляющие истории", "en": "✨ Inspiring Stories"},
}

async def fetch_articles(query, count=10, page=1):
    if not NEWS_API_KEY:
        return []
    try:
        params = {"apiKey": NEWS_API_KEY, "q": query, "language": "en", "pageSize": count, "sortBy": "publishedAt", "page": page}
        async with httpx.AsyncClient(timeout=10) as http:
            response = await http.get("https://newsapi.org/v2/everything", params=params)
        data = response.json()
        if data.get("status") != "ok" or not data.get("articles"):
            return []
        articles = []
        for a in data["articles"]:
            title = a.get("title", "").split(" - ")[0].strip()
            desc = a.get("description") or ""
            url = a.get("url") or ""
            if title and title != "[Removed]" and len(title) > 10:
                articles.append({"title": title, "description": desc, "url": url})
        return articles[:count]
    except Exception as e:
        logging.error(f"Ошибка fetch_articles: {e}")
        return []

async def translate_titles(titles, lang="ru"):
    if lang != "ru":
        return titles
    try:
        text = "\n".join([f"{i+1}. {t}" for i, t in enumerate(titles)])
        resp = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Переведи заголовки на русский. Отвечай ТОЛЬКО строками вида: 1. Заголовок"},
                {"role": "user", "content": text}
            ],
            max_tokens=800, temperature=0.1
        )
        result = resp.choices[0].message.content.strip()
        translated = []
        for line in result.split("\n"):
            line = line.strip()
            if line and line[0].isdigit() and ". " in line:
                translated.append(line.split(". ", 1)[1].strip())
        return translated if len(translated) == len(titles) else titles
    except:
        return titles

async def get_article_details(article, lang="ru"):
    try:
        title = article.get("title", "")
        desc = article.get("description", "")
        url = article.get("url", "")
        prompt = f"Расскажи подробнее об этой теме: {title}. {desc}\n\nНапиши интересный рассказ на 3-4 абзаца по-человечески, без форматирования." if lang == "ru" else f"Tell more about: {title}. {desc}\n\nWrite 3-4 interesting paragraphs, conversational."
        resp = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600, temperature=0.7
        )
        summary = resp.choices[0].message.content.strip()
        if url:
            link = "Читать оригинал" if lang == "ru" else "Read original"
            return f"{summary}\n\n🔗 {link}: {url}"
        return summary
    except:
        return article.get("description") or ("Описание недоступно." if lang == "ru" else "Unavailable.")

async def get_news(query=None, lang="ru"):
    articles = await fetch_articles(query or "positive world news", 5)
    if not articles:
        return None
    titles = [a["title"] for a in articles]
    translated = await translate_titles(titles, lang)
    return "\n".join([f"{i+1}. {t}" for i, t in enumerate(translated)])

async def generate_image(prompt):
    try:
        response = ai_client.images.generate(model="gpt-image-1-mini", prompt=prompt, size="1024x1024", n=1)
        item = response.data[0]
        if hasattr(item, 'url') and item.url:
            return item.url
        elif hasattr(item, 'b64_json') and item.b64_json:
            return f"data:image/png;base64,{item.b64_json}"
        return None
    except Exception as e:
        logging.error(f"Ошибка генерации изображения: {e}")
        return None

def calculate_sleep_times(wake_hour, wake_minute):
    total_minutes = wake_hour * 60 + wake_minute
    times = []
    for cycles in [6, 5, 4]:
        sleep_minutes = total_minutes - cycles * 90 - 15
        if sleep_minutes < 0:
            sleep_minutes += 24 * 60
        h = sleep_minutes // 60
        m = sleep_minutes % 60
        times.append(f"{h:02d}:{m:02d} ({cycles} цикла = {cycles * 1.5:.0f}ч)")
    return times

async def get_ai_recipe(lang="ru"):
    try:
        prompt = "Suggest one simple recipe. Name, ingredients and brief method. Conversational." if lang == "en" else "Предложи один простой рецепт. Название, ингредиенты и краткий способ. По-человечески."
        response = ai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "system", "content": prompt}, {"role": "user", "content": "Рецепт" if lang == "ru" else "Recipe"}], max_tokens=400, temperature=0.9)
        return response.choices[0].message.content
    except:
        return "Рецепт недоступен." if lang == "ru" else "Recipe unavailable."

async def get_ai_movie(lang="ru"):
    try:
        prompt = "Recommend one movie or series. Title, genre, brief description, why to watch. Conversational." if lang == "en" else "Посоветуй один фильм или сериал. Название, жанр, описание, почему стоит. По-человечески."
        response = ai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "system", "content": prompt}, {"role": "user", "content": "Что посмотреть?" if lang == "ru" else "What to watch?"}], max_tokens=250, temperature=0.9)
        return response.choices[0].message.content
    except:
        return "Рекомендация недоступна." if lang == "ru" else "Recommendation unavailable."

RECIPE_CATEGORIES = {
    "soups": "супы и первые блюда",
    "main": "вторые блюда из мяса рыбы или овощей",
    "salads": "салаты и закуски",
    "desserts": "десерты торты и выпечка",
    "trends": "модные и трендовые блюда 2025",
}
DAYS_RU = {"понедельник": 0, "понедельникам": 0, "вторник": 1, "вторникам": 1, "среду": 2, "средам": 2, "среда": 2, "четверг": 3, "четвергам": 3, "пятницу": 4, "пятницам": 4, "пятница": 4, "субботу": 5, "субботам": 5, "суббота": 5, "воскресенье": 6, "воскресеньям": 6}
DAYS_RU_NAMES = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

async def get_recipe_list(cat_key, lang="ru"):
    topic = RECIPE_CATEGORIES.get(cat_key, "блюда")
    prompt = "Предложи 5 разных названий блюд на тему: " + topic + ". Напиши ТОЛЬКО пронумерованный список 1-5, только названия без описаний."
    try:
        resp = ai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], max_tokens=150, temperature=0.9)
        return resp.choices[0].message.content.strip()
    except:
        return None

async def get_full_recipe(dish_name, lang="ru"):
    prompt = "Напиши подробный рецепт: " + dish_name + ". Включи ингредиенты и пошаговое приготовление. Пиши по-человечески, без звёздочек."
    try:
        resp = ai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], max_tokens=600, temperature=0.7)
        return resp.choices[0].message.content.strip()
    except:
        return None

async def rephrase_reminder(text, lang="ru"):
    try:
        system = "Rephrase as a reminder — brief, no 'me', no 'remind', no time. Just essence." if lang == "en" else "Перефразируй как напоминание — коротко, без 'мне', без 'напомни', без времени. Только суть."
        response = ai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "system", "content": system}, {"role": "user", "content": text}], max_tokens=80, temperature=0.3)
        result = response.choices[0].message.content.strip()
        return result[0].upper() + result[1:] if result else text
    except:
        return text

async def analyze_image(image_data, user_question, lang="ru"):
    try:
        prompt = user_question if user_question else ("Опиши что на этом фото подробно" if lang == "ru" else "Describe what's in this photo in detail")
        response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}}]}],
            max_tokens=600
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"Ошибка анализа фото: {e}")
        return "Не удалось проанализировать фото." if lang == "ru" else "Could not analyze the photo."

async def transcribe_voice(file_path):
    try:
        transcriber = aai.Transcriber()
        config = aai.TranscriptionConfig(language_code="ru")
        transcript = transcriber.transcribe(file_path, config=config)
        if transcript.status == aai.TranscriptStatus.error:
            raise Exception(f"Transcription error: {transcript.error}")
        return transcript.text
    except Exception as e:
        logging.error(f"Transcription failed: {e}")
        raise

def extract_exact_time(text):
    m = re.search(r'(\d{1,2})[:\.](\d{2})', text)
    if m:
        h, min_ = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= min_ <= 59:
            return h, min_
    return None, None

def extract_relative_time(text):
    m = re.search(r'через\s+(\d+)\s*(минут|мин|минуты|минуту)|in\s+(\d+)\s*(minutes|mins|minute)', text, re.IGNORECASE)
    if m:
        return int(m.group(1) or m.group(3)), 'minutes'
    m = re.search(r'через\s+(\d+)\s*(час|часа|часов)|in\s+(\d+)\s*(hours|hour)', text, re.IGNORECASE)
    if m:
        return int(m.group(1) or m.group(3)), 'hours'
    return None, None

def is_reminder_request(text):
    kw_ru = ["напомни", "напоминание", "пришли напоминание"]
    kw_en = ["remind me", "set a reminder", "reminder"]
    has_time = re.search(r'\d{1,2}[:.]\d{2}', text) or re.search(r'через\s+\d+|in\s+\d+', text, re.IGNORECASE)
    return has_time and (any(k in text.lower() for k in kw_ru) or any(k in text.lower() for k in kw_en))

def is_news_request(text):
    kw_ru = ["новост", "что случилось", "что происходит", "последние события", "в мире сейчас", "расскажи новости"]
    kw_en = ["news", "what happened", "latest events", "current events"]
    return any(k in text.lower() for k in kw_ru) or any(k in text.lower() for k in kw_en)

def is_image_gen_request(text):
    kw_ru = ["нарисуй", "сгенерируй картинку", "создай изображение", "сделай картинку"]
    kw_en = ["draw", "generate image", "create image", "make a picture"]
    return any(k in text.lower() for k in kw_ru) or any(k in text.lower() for k in kw_en)

def is_weather_request(text):
    kw_ru = ["погода", "какая погода", "погоду", "погодой", "температура", "тепло ли", "холодно ли", "дождь", "зонт"]
    kw_en = ["weather", "temperature", "rain", "sunny", "cold outside", "warm outside"]
    return any(k in text.lower() for k in kw_ru) or any(k in text.lower() for k in kw_en)

def is_change_style_request(text):
    kw_ru = ["измени стиль", "смени стиль", "общайся как", "хочу чтобы ты общалась", "перейди на", "говори со мной как"]
    kw_en = ["change style", "communicate as", "talk to me as", "switch to style"]
    return any(k in text.lower() for k in kw_ru) or any(k in text.lower() for k in kw_en)

async def send_scheduled_reminder(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    user_id = job_data["user_id"]
    essence = job_data["essence"]
    user = await get_user(user_id)
    name = user["name"] if user else ""
    lang = user.get("language", "ru") if user else "ru"
    await context.bot.send_message(chat_id=user_id, text=t(lang, "reminder", name=name, text=essence))

async def send_med_reminder(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    user_id = job_data["user_id"]
    med_name = job_data["med_name"]
    user = await get_user(user_id)
    name = user["name"] if user else ""
    await context.bot.send_message(chat_id=user_id, text="💊 " + name + ", не забудьте принять " + med_name + "!")

async def send_water_reminder(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    user = await get_user(user_id)
    name = user["name"] if user else ""
    lang = user.get("language", "ru") if user else "ru"
    await context.bot.send_message(chat_id=user_id, text=t(lang, "water", name=name))

async def send_morning_plan(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    user = await get_user(user_id)
    if not user:
        return
    name = user["name"]
    city = user.get("city") or "Москва"
    lang = user.get("language", "ru")
    reminders = await get_reminders(user_id)
    text = t(lang, "morning", name=name)
    if user.get("morning_motivation"):
        text += f"{random.choice(MOTIVATIONAL_QUOTES[lang])}\n\n"
    if user.get("morning_weather"):
        weather = await get_weather(city, lang)
        text += f"{weather}\n\n"
    if reminders:
        plan_text = "\n".join([f"{r['time']} — {r['text']}" for r in sorted(reminders, key=lambda x: x["time"])])
        title = "Ваш план на сегодня:" if lang == "ru" else "Your plan for today:"
        text += f"{title}\n\n{plan_text}"
    else:
        text += t(lang, "no_plan")
    await context.bot.send_message(chat_id=user_id, text=text)

async def send_evening_news(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    user = await get_user(user_id)
    if not user:
        return
    name = user["name"]
    lang = user.get("language", "ru")
    dt = get_current_datetime(user.get("timezone", "Europe/Moscow"))
    try:
        async with db_pool.acquire() as conn:
            habits = await conn.fetch("SELECT id, name FROM habits WHERE user_id = $1", user_id)
            habit_lines = []
            for h in habits:
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM habit_logs WHERE habit_id = $1 AND logged_at >= NOW() - INTERVAL '1 day'",
                    h["id"]
                )
                status = "выполнена" if count > 0 else "не отмечена"
                habit_lines.append(h["name"] + ": " + status)
            income = await conn.fetchval(
                "SELECT SUM(amount) FROM finances WHERE user_id = $1 AND type = 'income' AND created_at >= NOW() - INTERVAL '1 day'",
                user_id
            ) or 0
            expense = await conn.fetchval(
                "SELECT SUM(amount) FROM finances WHERE user_id = $1 AND type = 'expense' AND created_at >= NOW() - INTERVAL '1 day'",
                user_id
            ) or 0
        habits_text = ", ".join(habit_lines) if habit_lines else "привычки не добавлены"
        date_str = dt["ru"] if lang == "ru" else dt["en"]
        if lang == "ru":
            data_block = "Привычки за сегодня: " + habits_text + "\nФинансы: доходы " + str(int(income)) + ", расходы " + str(int(expense))
            prompt = "Составь тёплый вечерний итог дня для " + name + ". Сегодня " + date_str + ".\n\n" + data_block + "\n\nНапиши как личное колесо баланса — отметь что хорошо получилось сегодня, что можно улучшить завтра, добавь мотивацию и тёплые слова. По-человечески, 3-4 абзаца, без звёздочек и форматирования."
        else:
            data_block = "Habits today: " + habits_text + "\nFinances: income " + str(int(income)) + ", expenses " + str(int(expense))
            prompt = "Create a warm evening day summary for " + name + ". Today is " + date_str + ".\n\n" + data_block + "\n\nWrite like a personal balance wheel — note what went well today, what to improve tomorrow, add motivation and warm words. Natural, 3-4 paragraphs, no asterisks."
        response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600, temperature=0.8
        )
        await context.bot.send_message(chat_id=user_id, text=response.choices[0].message.content)
    except Exception as e:
        logging.error(f"Ошибка вечерней сводки: {e}")

def get_main_menu(lang="ru"):
    ru = lang == "ru"
    keyboard = [
        [InlineKeyboardButton("🌅 Утро" if ru else "🌅 Morning", callback_data="menu_morning"), InlineKeyboardButton("📒 Дневник" if ru else "📒 Diary", callback_data="menu_diary")],
        [InlineKeyboardButton("🏥 Здоровье" if ru else "🏥 Health", callback_data="menu_health"), InlineKeyboardButton("🎯 Цели" if ru else "🎯 Goals", callback_data="menu_goals")],
        [InlineKeyboardButton("✨ Интересное" if ru else "✨ Interesting", callback_data="menu_interesting"), InlineKeyboardButton("⚙️ Настройки" if ru else "⚙️ Settings", callback_data="menu_settings")],
        [InlineKeyboardButton("✖️ Закрыть меню" if ru else "✖️ Close menu", callback_data="close_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    if not user or not user["onboarded"]:
        await update.message.reply_text(t("ru", "not_started"))
        return
    lang = user.get("language", "ru")
    await update.message.reply_text("🌸", reply_markup=get_main_menu(lang))

async def skills_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    lang = user.get("language", "ru") if user else "ru"
    await update.message.reply_text(SKILLS_EN if lang == "en" else SKILLS_RU)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = await get_user(user_id)
    if not user:
        return
    name = user["name"]
    city = user.get("city") or "Москва"
    lang = user.get("language", "ru")
    ru = lang == "ru"

    if query.data == "menu_morning":
        keyboard = [
            [InlineKeyboardButton("📋 План на день" if ru else "📋 Day plan", callback_data="morning_plan")],
            [InlineKeyboardButton("🌤 Погода сейчас" if ru else "🌤 Weather now", callback_data="morning_weather_btn")],
            [InlineKeyboardButton("🕐 Почасовой прогноз" if ru else "🕐 Hourly forecast", callback_data="morning_hourly")],
            [InlineKeyboardButton("🌦 Прогноз на неделю" if ru else "🌦 Weekly forecast", callback_data="morning_forecast")],
            [InlineKeyboardButton("🧘 Мотивация" if ru else "🧘 Motivation", callback_data="morning_motivation")],
            [InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="back_main")],
        ]
        await query.edit_message_text("Утреннее меню" if ru else "Morning menu", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "morning_plan":
        reminders = await get_reminders(user_id)
        back = InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_morning")
        if reminders:
            plan = "\n".join([f"{r['time']} — {r['text']}" for r in sorted(reminders, key=lambda x: x["time"])])
            text = f"{'Ваш план на сегодня' if ru else 'Your plan for today'}:\n\n{plan}"
        else:
            text = t(lang, "no_plan")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "morning_weather_btn":
        await query.edit_message_text("Получаю погоду..." if ru else "Getting weather...")
        weather = await get_weather(city, lang)
        back = InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_morning")
        await query.edit_message_text(weather, reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "morning_hourly":
        await query.edit_message_text("Получаю почасовой прогноз..." if ru else "Getting hourly forecast...")
        hourly = await get_weather_hourly(city, lang)
        back = InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_morning")
        text = hourly if hourly else ("Прогноз недоступен." if ru else "Forecast unavailable.")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "morning_forecast":
        await query.edit_message_text("Получаю прогноз на неделю..." if ru else "Getting weekly forecast...")
        forecast = await get_weather_forecast(city, lang)
        back = InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_morning")
        text = forecast if forecast else ("Прогноз недоступен." if ru else "Forecast unavailable.")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "morning_motivation":
        quote = random.choice(MOTIVATIONAL_QUOTES[lang])
        keyboard = [[InlineKeyboardButton("🔄 Ещё" if ru else "🔄 Another", callback_data="morning_motivation")], [InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_morning")]]
        await query.edit_message_text(f"{'Мотивация дня' if ru else 'Motivation'}:\n\n{quote}", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "menu_interesting":
        keyboard = [
            [InlineKeyboardButton("🔬 Научные открытия" if ru else "🔬 Science Discoveries", callback_data="interesting_science")],
            [InlineKeyboardButton("💻 Технологии и ИИ" if ru else "💻 Technology & AI", callback_data="interesting_technology")],
            [InlineKeyboardButton("💚 Здоровье и долголетие" if ru else "💚 Health & Wellness", callback_data="interesting_health")],
            [InlineKeyboardButton("✨ Вдохновляющие истории" if ru else "✨ Inspiring Stories", callback_data="interesting_inspiration")],
            [InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="back_main")],
        ]
        await query.edit_message_text("Интересное — выберите тему:" if ru else "Interesting — choose a topic:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("interesting_"):
        category = query.data.replace("interesting_", "")
        cat_info = INTERESTING_QUERIES.get(category, {})
        title = cat_info.get("ru" if ru else "en", "Интересное")
        await query.edit_message_text(f"Загружаю {title}..." if ru else f"Loading {title}...")
        # Очищаем кэш для свежей загрузки
        context.user_data.pop(f"interesting_articles_{category}", None)
        context.user_data.pop(f"interesting_translated_{category}", None)
        page = random.randint(1, 3)
        articles = await fetch_articles(cat_info.get("query", "interesting news"), 10, page=page)
        if not articles:
            articles = await fetch_articles(cat_info.get("query", "interesting news"), 10, page=1)
        if not articles:
            back = InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_interesting")
            await query.edit_message_text("Материалы временно недоступны." if ru else "Content temporarily unavailable.", reply_markup=InlineKeyboardMarkup([[back]]))
            return
        titles = [a["title"] for a in articles]
        translated = await translate_titles(titles, lang)
        context.user_data[f"interesting_articles_{category}"] = articles
        context.user_data[f"interesting_translated_{category}"] = translated
        lines = [f"{i+1}. {t}" for i, t in enumerate(translated)]
        text = f"{title}\n\n" + "\n".join(lines)
        text += "\n\nНапишите цифру чтобы узнать подробнее" if ru else "\n\nType a number to read more"
        context.user_data["waiting_interesting"] = category
        keyboard = [
            [InlineKeyboardButton("🔄 Обновить" if ru else "🔄 Refresh", callback_data=f"interesting_{category}")],
            [InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_interesting")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "menu_shopping":
        async with db_pool.acquire() as conn:
            items = await conn.fetch("SELECT id, item, done FROM shopping_list WHERE user_id = $1 ORDER BY created_at", user_id)
        if items:
            lines = [f"{'✅' if i['done'] else '⬜'} {i['item']}" for i in items]
            text = ("Список покупок:\n\n" if ru else "Shopping list:\n\n") + "\n".join(lines)
        else:
            text = "Список покупок пуст.\n\nНапишите что добавить!" if ru else "Shopping list is empty.\n\nWrite what to add!"
        context.user_data["waiting_shopping"] = True
        keyboard = [
            [InlineKeyboardButton("🗑 Очистить" if ru else "🗑 Clear", callback_data="shopping_clear")],
            [InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="back_main")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "shopping_clear":
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM shopping_list WHERE user_id = $1", user_id)
        back = InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_shopping")
        await query.edit_message_text("Список покупок очищен!" if ru else "Shopping list cleared!", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "menu_habits":
        async with db_pool.acquire() as conn:
            habits = await conn.fetch("SELECT id, name FROM habits WHERE user_id = $1", user_id)
        text = ("Ваши привычки:\n\n" if ru else "Your habits:\n\n") + "\n".join([f"✅ {h['name']}" for h in habits]) if habits else ("Привычек пока нет." if ru else "No habits yet.")
        keyboard = [
            [InlineKeyboardButton("➕ Добавить" if ru else "➕ Add", callback_data="habit_add")],
            [InlineKeyboardButton("✅ Отметить" if ru else "✅ Mark done", callback_data="habit_log")],
            [InlineKeyboardButton("📊 Статистика" if ru else "📊 Statistics", callback_data="habit_stats")],
            [InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="back_main")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "habit_add":
        context.user_data["waiting_habit"] = True
        back = InlineKeyboardButton("◀️ Отмена" if ru else "◀️ Cancel", callback_data="menu_habits")
        await query.edit_message_text("Напишите название привычки\n\nНапример: Медитация, Чтение, Зарядка" if ru else "Write the habit name", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "habit_log":
        async with db_pool.acquire() as conn:
            habits = await conn.fetch("SELECT id, name FROM habits WHERE user_id = $1", user_id)
        if not habits:
            back = InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_habits")
            await query.edit_message_text("Сначала добавьте привычку!" if ru else "Add a habit first!", reply_markup=InlineKeyboardMarkup([[back]]))
            return
        keyboard = [[InlineKeyboardButton(f"✅ {h['name']}", callback_data=f"log_habit_{h['id']}")] for h in habits]
        keyboard.append([InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_habits")])
        await query.edit_message_text("Какую привычку отмечаем?" if ru else "Which habit to mark?", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("log_habit_"):
        habit_id = int(query.data.split("_")[-1])
        async with db_pool.acquire() as conn:
            habit = await conn.fetchrow("SELECT name FROM habits WHERE id = $1", habit_id)
            await conn.execute("INSERT INTO habit_logs (user_id, habit_id) VALUES ($1, $2)", user_id, habit_id)
        back = InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_habits")
        await query.edit_message_text(f"Привычка {habit['name']} отмечена! 💪" if ru else f"Habit {habit['name']} marked! 💪", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "habit_stats":
        async with db_pool.acquire() as conn:
            habits = await conn.fetch("SELECT id, name FROM habits WHERE user_id = $1", user_id)
            lines = []
            for h in habits:
                count = await conn.fetchval("SELECT COUNT(*) FROM habit_logs WHERE habit_id = $1 AND logged_at >= NOW() - INTERVAL '7 days'", h["id"])
                lines.append(f"{h['name']}: {count}/7 {'дней' if ru else 'days'}")
        text = ("Статистика за 7 дней:\n\n" if ru else "Stats for 7 days:\n\n") + "\n".join(lines) if lines else ("Нет данных." if ru else "No data.")
        back = InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_habits")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "menu_water":
        water_on = user.get("water_reminders", False)
        interval = user.get("water_interval", 2)
        status = ("✅ Включены" if water_on else "❌ Выключены") if ru else ("✅ On" if water_on else "❌ Off")
        keyboard = [
            [InlineKeyboardButton("💧 Выпила воду!" if ru else "💧 Drank water!", callback_data="water_drink")],
            [InlineKeyboardButton(("🔔 Выключить" if water_on else "🔔 Включить") if ru else ("🔔 Turn off" if water_on else "🔔 Turn on"), callback_data="water_toggle")],
            [InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="back_main")],
        ]
        text = f"Трекер воды\n\nНапоминания: {status}\nКаждые {interval} часа\nНорма: 8 стаканов 💧" if ru else f"Water tracker\n\nReminders: {status}\nEvery {interval} hours\nNorm: 8 glasses 💧"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "water_drink":
        back = InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_water")
        await query.edit_message_text("Стакан воды засчитан! 💧" if ru else "Glass of water counted! 💧", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "water_toggle":
        water_on = user.get("water_reminders", False)
        new_state = not water_on
        await save_user(user_id, water_reminders=new_state)
        if new_state:
            interval = user.get("water_interval", 2)
            context.application.job_queue.run_repeating(send_water_reminder, interval=interval * 3600, first=interval * 3600, data=user_id, name=f"water_{user_id}")
            text = f"Напоминания включены! Каждые {interval} часа 💧" if ru else f"Water reminders on! Every {interval} hours 💧"
        else:
            for job in context.application.job_queue.get_jobs_by_name(f"water_{user_id}"):
                job.schedule_removal()
            text = "Напоминания выключены." if ru else "Water reminders off."
        back = InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_water")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "menu_diary":
        keyboard = [
            [InlineKeyboardButton("💰 Финансы", callback_data="diary_finances"), InlineKeyboardButton("😴 Сон", callback_data="diary_sleep")],
            [InlineKeyboardButton("💧 Вода", callback_data="diary_water"), InlineKeyboardButton("💪 Привычки", callback_data="diary_habits")],
            [InlineKeyboardButton("📝 Заметки", callback_data="diary_notes"), InlineKeyboardButton("🍳 Рецепты", callback_data="diary_recipe")],
            [InlineKeyboardButton("🎬 Что посмотреть", callback_data="diary_movie"), InlineKeyboardButton("🛒 Покупки", callback_data="diary_shopping")],
            [InlineKeyboardButton("📅 Планер", callback_data="diary_planner")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
        ]
        await query.edit_message_text("Дневник:" if ru else "Diary:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "diary_water":
        water_on = user.get("water_reminders", False)
        interval = user.get("water_interval", 2)
        status = "Включены" if water_on else "Выключены"
        toggle_text = "Выключить" if water_on else "Включить"
        keyboard = [
            [InlineKeyboardButton("💧 Выпила воду!", callback_data="water_drink")],
            [InlineKeyboardButton(toggle_text, callback_data="water_toggle")],
            [InlineKeyboardButton("Назад", callback_data="menu_diary")],
        ]
        text = "Трекер воды\n\nНапоминания: " + status + "\nКаждые " + str(interval) + " часа\nНорма: 8 стаканов"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "diary_habits":
        async with db_pool.acquire() as conn:
            habits = await conn.fetch("SELECT id, name FROM habits WHERE user_id = $1", user_id)
        text = "Ваши привычки:\n\n" + "\n".join(["+ " + h["name"] for h in habits]) if habits else "Привычек пока нет."
        keyboard = [
            [InlineKeyboardButton("➕ Добавить", callback_data="habit_add")],
            [InlineKeyboardButton("✅ Отметить", callback_data="habit_log")],
            [InlineKeyboardButton("📊 Статистика", callback_data="habit_stats")],
            [InlineKeyboardButton("Назад", callback_data="menu_diary")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "diary_shopping":
        async with db_pool.acquire() as conn:
            items = await conn.fetch("SELECT id, item, done FROM shopping_list WHERE user_id = $1 ORDER BY created_at", user_id)
        if items:
            lines = [("+ " if i["done"] else "- ") + i["item"] for i in items]
            text = "Список покупок:\n\n" + "\n".join(lines)
        else:
            text = "Список покупок пуст. Напишите что добавить!"
        context.user_data["waiting_shopping"] = True
        keyboard = [
            [InlineKeyboardButton("Очистить", callback_data="shopping_clear")],
            [InlineKeyboardButton("Назад", callback_data="menu_diary")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "diary_planner":
        async with db_pool.acquire() as conn:
            events = await conn.fetch("SELECT id, day_of_week, time_str, title FROM planner WHERE user_id = $1 ORDER BY day_of_week, time_str", user_id)
        if events:
            lines = [DAYS_RU_NAMES[e["day_of_week"]] + " " + e["time_str"] + " — " + e["title"] for e in events]
            text = "Ваш планер:\n\n" + "\n".join(lines)
        else:
            text = "Планер пуст.\n\nЗдесь хранятся только фиксированные регулярные занятия которые повторяются каждую неделю.\n\nНапример: каждую среду в 17:00 тренировка"
        keyboard = [
            [InlineKeyboardButton("➕ Добавить", callback_data="planner_add")],
            [InlineKeyboardButton("🗑 Очистить", callback_data="planner_clear")],
            [InlineKeyboardButton("◀️ Назад", callback_data="menu_diary")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "planner_add":
        context.user_data["waiting_planner"] = True
        back = InlineKeyboardButton("◀️ Назад", callback_data="diary_planner")
        await query.edit_message_text("Напишите занятие:\nкаждую ДЕНЬ в ЧЧ:ММ название\n\nНапример: каждую среду в 17:00 танцы", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "planner_clear":
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM planner WHERE user_id = $1", user_id)
        back = InlineKeyboardButton("◀️ Назад", callback_data="diary_planner")
        await query.edit_message_text("Планер очищен.", reply_markup=InlineKeyboardMarkup([[back]]))
    elif query.data in ["diary_health", "menu_health"]:
        back_cb = "back_main" if query.data == "menu_health" else "menu_diary"
        keyboard = [
            [InlineKeyboardButton("🩸 Цикл", callback_data="health_cycle"), InlineKeyboardButton("💊 Таблетки", callback_data="health_meds")],
            [InlineKeyboardButton("😰 Стресс", callback_data="health_stress"), InlineKeyboardButton("⚖️ Вес и рост", callback_data="health_weight")],
            [InlineKeyboardButton("🥗 Нутрициология", callback_data="health_nutrition")],
            [InlineKeyboardButton("◀️ Назад", callback_data=back_cb)],
        ]
        await query.edit_message_text("Здоровье:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "health_cycle":
        async with db_pool.acquire() as conn:
            last = await conn.fetchrow("SELECT start_date, cycle_length FROM cycle_tracking WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1", user_id)
        if last and last["start_date"]:
            from datetime import date as _date, timedelta as _td
            start = last["start_date"]
            length = last["cycle_length"] or 28
            today = _date.today()
            days_since = (today - start).days
            day_of_cycle = (days_since % length) + 1
            next_start = start
            while (next_start - today).days <= 0:
                next_start = next_start + _td(days=length)
            days_to_next = (next_start - today).days
            cycle_end = start + _td(days=5)
            text = "Цикл:\n\nПоследнее начало: " + str(start) + "\nПримерное окончание: " + str(cycle_end) + "\nДлина: " + str(length) + " дней\nДень цикла: " + str(day_of_cycle) + "\nСледующий через: " + str(days_to_next) + " дней"
        else:
            text = "Цикл ещё не отслеживается.\n\nОтметьте начало цикла чтобы я вела историю и прогнозировала следующие."
        keyboard = [
            [InlineKeyboardButton("📝 Отметить начало цикла", callback_data="cycle_start")],
            [InlineKeyboardButton("📋 История циклов", callback_data="cycle_history")],
            [InlineKeyboardButton("⚙️ Длина цикла", callback_data="cycle_set_length")],
            [InlineKeyboardButton("◀️ Назад", callback_data="menu_health")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "cycle_history":
        async with db_pool.acquire() as conn:
            cycles = await conn.fetch("SELECT start_date, cycle_length FROM cycle_tracking WHERE user_id = $1 ORDER BY start_date DESC LIMIT 12", user_id)
        if cycles:
            from datetime import timedelta as _td2
            lines = [str(c["start_date"]) + " — примерно до " + str(c["start_date"] + _td2(days=5)) for c in cycles]
            text = "История циклов (можно показать врачу):\n\n" + "\n".join(lines)
        else:
            text = "История циклов пуста."
        back = InlineKeyboardButton("◀️ Назад", callback_data="health_cycle")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "cycle_set_length":
        context.user_data["waiting_cycle_length"] = True
        back = InlineKeyboardButton("◀️ Назад", callback_data="health_cycle")
        await query.edit_message_text("Напишите длину вашего цикла в днях (обычно 28):", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "cycle_start":
        context.user_data["waiting_cycle_date"] = True
        back = InlineKeyboardButton("◀️ Назад", callback_data="health_cycle")
        await query.edit_message_text("Напишите дату начала цикла в формате ДД.ММ.ГГГГ\n\nНапример: 01.06.2025", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "health_meds":
        async with db_pool.acquire() as conn:
            meds = await conn.fetch("SELECT id, name, time_str FROM medications WHERE user_id = $1 ORDER BY time_str", user_id)
            lines = []
            for med in meds:
                taken = await conn.fetchval("SELECT COUNT(*) FROM medication_logs WHERE med_id = $1 AND taken_at >= NOW() - INTERVAL '1 day'", med["id"])
                lines.append(("✅" if taken > 0 else "⬜") + " " + med["time_str"] + " — " + med["name"])
        text = "Таблетки:\n\n" + "\n".join(lines) if lines else "Таблетки не добавлены."
        keyboard = []
        if meds:
            keyboard.append([InlineKeyboardButton("✅ Отметить приём", callback_data="med_take")])
        keyboard.append([InlineKeyboardButton("➕ Добавить таблетку", callback_data="med_add")])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="diary_health")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "med_add":
        context.user_data["waiting_med_name"] = True
        back = InlineKeyboardButton("◀️ Назад", callback_data="health_meds")
        await query.edit_message_text("Напишите название и время через пробел\n\nНапример: Витамин D 08:00", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "med_take":
        async with db_pool.acquire() as conn:
            meds = await conn.fetch("SELECT id, name FROM medications WHERE user_id = $1", user_id)
        keyboard = [[InlineKeyboardButton("💊 " + m["name"], callback_data="take_med_" + str(m["id"]))] for m in meds]
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="health_meds")])
        await query.edit_message_text("Какую таблетку принимали?", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("take_med_"):
        med_id = int(query.data.split("_")[-1])
        async with db_pool.acquire() as conn:
            med = await conn.fetchrow("SELECT name FROM medications WHERE id = $1", med_id)
            await conn.execute("INSERT INTO medication_logs (user_id, med_id) VALUES ($1, $2)", user_id, med_id)
        back = InlineKeyboardButton("◀️ Назад", callback_data="health_meds")
        await query.edit_message_text("Приём " + med["name"] + " отмечен! 💊", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "health_stress":
        keyboard = [
            [InlineKeyboardButton("1", callback_data="stress_1"), InlineKeyboardButton("2", callback_data="stress_2"), InlineKeyboardButton("3", callback_data="stress_3")],
            [InlineKeyboardButton("4", callback_data="stress_4"), InlineKeyboardButton("5", callback_data="stress_5"), InlineKeyboardButton("6", callback_data="stress_6")],
            [InlineKeyboardButton("7", callback_data="stress_7"), InlineKeyboardButton("8", callback_data="stress_8"), InlineKeyboardButton("9", callback_data="stress_9")],
            [InlineKeyboardButton("10", callback_data="stress_10")],
            [InlineKeyboardButton("📊 История за неделю", callback_data="stress_history")],
            [InlineKeyboardButton("◀️ Назад", callback_data="menu_health")],
        ]
        await query.edit_message_text("Оцените уровень стресса:\n\n1 — всё спокойно\n10 — очень высокий стресс", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("stress_") and query.data not in ["stress_logs", "stress_history"]:
        level = int(query.data.replace("stress_", ""))
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO stress_logs (user_id, level) VALUES ($1, $2)", user_id, level)
        if level <= 3:
            advice = "Отличное состояние! Продолжайте в том же духе 🌸"
        elif level <= 6:
            advice = "Умеренный стресс. Попробуйте 5 минут глубокого дыхания или небольшую прогулку."
        elif level <= 8:
            advice = "Высокий стресс. Сделайте перерыв, выпейте воды, отдохните."
        else:
            advice = "Очень высокий стресс! Остановитесь, сделайте 10 глубоких вдохов. Вы справитесь 💙"
        back = InlineKeyboardButton("◀️ Назад", callback_data="diary_health")
        await query.edit_message_text("Уровень стресса " + str(level) + "/10 отмечен.\n\n" + advice, reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "health_weight":
        async with db_pool.acquire() as conn:
            logs = await conn.fetch("SELECT weight, height, created_at FROM weight_logs WHERE user_id = $1 ORDER BY created_at DESC LIMIT 8", user_id)
        if logs:
            lines = [l["created_at"].strftime("%d.%m.%Y") + ": " + str(l["weight"]) + " кг" + (" / " + str(l["height"]) + " см" if l["height"] else "") for l in logs]
            diff = round(logs[0]["weight"] - logs[-1]["weight"], 1)
            diff_str = ("+" if diff > 0 else "") + str(diff) + " кг за период"
            text = "Вес и рост:\n\n" + "\n".join(lines) + "\n\nДинамика: " + diff_str
        else:
            text = "Записей пока нет.\n\nЗаписывайте вес раз в неделю чтобы отслеживать динамику!"
        keyboard = [
            [InlineKeyboardButton("➕ Записать вес", callback_data="weight_add")],
            [InlineKeyboardButton("◀️ Назад", callback_data="menu_health")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "weight_add":
        context.user_data["waiting_weight"] = True
        back = InlineKeyboardButton("◀️ Назад", callback_data="health_weight")
        await query.edit_message_text("Напишите вес в кг (или вес и рост через пробел):\n\nНапример: 65 или 65 170", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "health_nutrition":
        async with db_pool.acquire() as conn:
            profile = await conn.fetchrow("SELECT * FROM nutrition_profile WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1", user_id)
            today_cal = await conn.fetchval("SELECT SUM(calories) FROM food_logs WHERE user_id = $1 AND created_at >= CURRENT_DATE", user_id) or 0
        if profile:
            age_txt = ("\nВозраст: " + str(profile["age"]) + " лет") if profile.get("age") else ""
            preg_txt = " (беременность)" if profile.get("pregnant") else ""
            meds_txt = ("\nПрепараты: " + str(profile["medications"])) if profile.get("medications") else ""
            norm = profile["calories_goal"] or 0
            remaining = norm - today_cal
            text = ("Нутрициология 🥗\n\nРост: " + str(int(profile["height"])) + " см\nВес: " + str(int(profile["weight"])) + " кг" + age_txt + "\nЦель: " + str(profile["goal"]) + preg_txt + meds_txt + "\nНорма калорий: " + str(norm) + " ккал\nСегодня съели: " + str(today_cal) + " ккал\nОсталось: " + str(max(0, remaining)) + " ккал\n\nЧто умею:\n• Отправьте фото еды — посчитаю КБЖУ и запишу\n• Напишите что ели — тоже посчитаю\n• Смотрите журнал питания за день")
            keyboard = [
                [InlineKeyboardButton("📋 Журнал питания", callback_data="food_log_view")],
                [InlineKeyboardButton("✏️ Обновить профиль", callback_data="nutrition_setup")],
                [InlineKeyboardButton("◀️ Назад", callback_data="menu_health")],
            ]
        else:
            context.user_data["nutrition_setup"] = True
            context.user_data["nutrition_step"] = "intro"
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="menu_health")]]
            text = ("Нутрициология 🥗\n\nЭтот раздел — ваш личный нутрициолог!\n\nЧто я умею:\n• Анализировать фото еды и считать КБЖУ\n• Записывать питание в журнал\n• Считать сколько калорий осталось до нормы\n• Давать персональные рекомендации\n\nДля начала нужно заполнить ваш профиль.\n\nВаш рост в см:")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "food_log_view":
        async with db_pool.acquire() as conn:
            profile = await conn.fetchrow("SELECT calories_goal FROM nutrition_profile WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1", user_id)
            logs = await conn.fetch("SELECT description, calories, protein, fat, carbs, created_at FROM food_logs WHERE user_id = $1 AND created_at >= CURRENT_DATE ORDER BY created_at", user_id)
        if logs:
            total_cal = sum(l["calories"] or 0 for l in logs)
            total_prot = sum(l["protein"] or 0 for l in logs)
            total_fat = sum(l["fat"] or 0 for l in logs)
            total_carb = sum(l["carbs"] or 0 for l in logs)
            lines = []
            for l in logs:
                t_str = l["created_at"].strftime("%H:%M")
                lines.append(t_str + " " + l["description"][:25] + " — " + str(l["calories"]) + " ккал")
            norm = profile["calories_goal"] if profile else 0
            text = "Журнал питания сегодня:\n\n" + "\n".join(lines)
            text += "\n\nИтого: " + str(total_cal) + " ккал | Б: " + str(round(total_prot, 1)) + " г | Ж: " + str(round(total_fat, 1)) + " г | У: " + str(round(total_carb, 1)) + " г"
            if norm: text += "\nНорма: " + str(norm) + " ккал | Осталось: " + str(max(0, norm - total_cal)) + " ккал"
        else:
            text = "Сегодня записей питания нет.\n\nОтправьте фото еды или напишите что ели!"
        back = InlineKeyboardButton("◀️ Назад", callback_data="health_nutrition")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "nutrition_setup":
        context.user_data["nutrition_setup"] = True
        context.user_data["nutrition_step"] = "height"
        back = InlineKeyboardButton("◀️ Назад", callback_data="health_nutrition")
        await query.edit_message_text("Обновление профиля питания.\n\nВаш рост в см:", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "menu_goals":
        async with db_pool.acquire() as conn:
            goals = await conn.fetch("SELECT id, title, progress, deadline FROM goals WHERE user_id = $1 ORDER BY created_at DESC", user_id)
        if goals:
            lines = []
            for g in goals:
                bar = "█" * (g["progress"] // 10) + "░" * (10 - g["progress"] // 10)
                dl = " (до " + str(g["deadline"]) + ")" if g["deadline"] else ""
                lines.append(g["title"] + dl + "\n" + bar + " " + str(g["progress"]) + "%")
            text = "Мои цели:\n\n" + "\n\n".join(lines)
        else:
            text = "Целей пока нет.\n\nДобавьте первую цель — это поможет фокусироваться каждый день!"
        keyboard = [[InlineKeyboardButton("➕ Добавить цель", callback_data="goal_add")]]
        if goals:
            keyboard.append([InlineKeyboardButton("📊 Обновить прогресс", callback_data="goal_progress")])
            keyboard.append([InlineKeyboardButton("🗑 Удалить цель", callback_data="goal_delete")])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_main")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "goal_add":
        context.user_data["waiting_goal"] = True
        back = InlineKeyboardButton("◀️ Назад", callback_data="menu_goals")
        await query.edit_message_text("Напишите цель и дедлайн через запятую:\n\nНапример: Выучить английский, 31.12.2025\nИли просто: Начать бегать", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "goal_delete":
        async with db_pool.acquire() as conn:
            goals_d = await conn.fetch("SELECT id, title FROM goals WHERE user_id = $1", user_id)
        if not goals_d:
            back = InlineKeyboardButton("◀️ Назад", callback_data="menu_goals")
            await query.edit_message_text("Целей нет.", reply_markup=InlineKeyboardMarkup([[back]]))
            return
        keyboard = [[InlineKeyboardButton("🗑 " + g["title"][:30], callback_data="del_goal_" + str(g["id"]))] for g in goals_d]
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="menu_goals")])
        await query.edit_message_text("Какую цель удалить?", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("del_goal_"):
        gid_del = int(query.data.split("_")[-1])
        async with db_pool.acquire() as conn:
            g_row = await conn.fetchrow("SELECT title FROM goals WHERE id = $1", gid_del)
            await conn.execute("DELETE FROM goals WHERE id = $1", gid_del)
        back = InlineKeyboardButton("◀️ Назад", callback_data="menu_goals")
        await query.edit_message_text("Цель удалена: " + (g_row["title"] if g_row else "") + " 🗑", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "stress_history":
        async with db_pool.acquire() as conn:
            logs = await conn.fetch("SELECT level, created_at FROM stress_logs WHERE user_id = $1 AND created_at >= NOW() - INTERVAL '7 days' ORDER BY created_at", user_id)
        if logs:
            from collections import defaultdict
            days_data = defaultdict(list)
            for l in logs:
                day = l["created_at"].strftime("%d.%m")
                days_data[day].append(l["level"])
            lines = []
            days_ru_short = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
            for day, levels in days_data.items():
                avg = round(sum(levels) / len(levels), 1)
                bar = "█" * int(avg) + "░" * (10 - int(avg))
                lines.append(day + " " + bar + " " + str(avg))
            text = "Стресс за 7 дней (1-10):\n\n" + "\n".join(lines)
        else:
            text = "Данных о стрессе за неделю нет."
        back = InlineKeyboardButton("◀️ Назад", callback_data="health_stress")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "goal_progress":
        async with db_pool.acquire() as conn:
            goals_p = await conn.fetch("SELECT id, title, progress FROM goals WHERE user_id = $1", user_id)
        keyboard = [[InlineKeyboardButton(g["title"][:30] + " (" + str(g["progress"]) + "%)", callback_data="set_progress_" + str(g["id"]))] for g in goals_p]
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="menu_goals")])
        await query.edit_message_text("Выберите цель для обновления:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("set_progress_"):
        goal_id_s = int(query.data.split("_")[-1])
        context.user_data["waiting_progress_goal_id"] = goal_id_s
        async with db_pool.acquire() as conn:
            g_info = await conn.fetchrow("SELECT title, progress FROM goals WHERE id = $1", goal_id_s)
        back = InlineKeyboardButton("◀️ Назад", callback_data="menu_goals")
        title_g = g_info["title"] if g_info else "Цель"
        await query.edit_message_text("Цель: " + title_g + "\n\nРасскажите что сделали по этой цели? Я сама оценю прогресс.\n\nНапример: сходила в зал 3 раза, прочитала 50 страниц, выучила 20 слов", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "diary_finances":
        async with db_pool.acquire() as conn:
            income = await conn.fetchval("SELECT SUM(amount) FROM finances WHERE user_id = $1 AND type = 'income' AND created_at >= NOW() - INTERVAL '30 days'", user_id)
            expense = await conn.fetchval("SELECT SUM(amount) FROM finances WHERE user_id = $1 AND type = 'expense' AND created_at >= NOW() - INTERVAL '30 days'", user_id)
            recent = await conn.fetch("SELECT amount, type, category, description FROM finances WHERE user_id = $1 ORDER BY created_at DESC LIMIT 5", user_id)
        balance = (income or 0) - (expense or 0)
        lines = [f"{'➕' if r['type'] == 'income' else '➖'} {r['amount']:.0f} — {r['category']} {r['description']}" for r in recent]
        if ru:
            text = f"Финансы за месяц:\n\n➕ Доходы: {income or 0:.0f}\n➖ Расходы: {expense or 0:.0f}\n💵 Баланс: {balance:.0f}\n\n"
            text += "\n".join(lines) if lines else "Записей пока нет."
            text += "\n\nДобавить доход: +1000 зарплата\nДобавить расход: -500 еда кофе"
        else:
            text = f"Finances this month:\n\n➕ Income: {income or 0:.0f}\n➖ Expenses: {expense or 0:.0f}\n💵 Balance: {balance:.0f}\n\n"
            text += "\n".join(lines) if lines else "No records yet."
            text += "\n\nAdd income: +1000 salary\nAdd expense: -500 food coffee"
        context.user_data["waiting_finance"] = True
        back = InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_diary")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "diary_sleep":
        keyboard = [
            [InlineKeyboardButton("6:00", callback_data="sleep_6_0"), InlineKeyboardButton("7:00", callback_data="sleep_7_0"), InlineKeyboardButton("8:00", callback_data="sleep_8_0")],
            [InlineKeyboardButton("9:00", callback_data="sleep_9_0"), InlineKeyboardButton("10:00", callback_data="sleep_10_0")],
            [InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_diary")],
        ]
        await query.edit_message_text("Во сколько хотите проснуться?" if ru else "What time do you want to wake up?", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("sleep_"):
        parts = query.data.split("_")
        wh, wm = int(parts[1]), int(parts[2])
        times = calculate_sleep_times(wh, wm)
        text = f"Чтобы проснуться в {wh:02d}:{wm:02d} бодрой, ложитесь в:\n\n" if ru else f"To wake up at {wh:02d}:{wm:02d} refreshed, go to bed at:\n\n"
        for ti in times:
            text += f"🌙 {ti}\n"
        text += "\n+15 минут на засыпание учтены" if ru else "\n+15 min to fall asleep included"
        back = InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="diary_sleep")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "diary_notes":
        async with db_pool.acquire() as conn:
            notes = await conn.fetch("SELECT text FROM notes WHERE user_id = $1 ORDER BY created_at DESC LIMIT 5", user_id)
        if notes:
            lines = [f"• {n['text'][:60]}{'...' if len(n['text']) > 60 else ''}" for n in notes]
            text = ("Ваши заметки:\n\n" if ru else "Your notes:\n\n") + "\n".join(lines)
        else:
            text = "Заметок пока нет." if ru else "No notes yet."
        text += "\n\nНапишите что угодно и я сохраню!" if ru else "\n\nWrite anything and I will save it!"
        context.user_data["waiting_note"] = True
        back = InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_diary")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "diary_recipe":
        keyboard = [
            [InlineKeyboardButton("❤️ Мои рецепты", callback_data="recipes_saved")],
            [InlineKeyboardButton("🎲 Рандомный рецепт", callback_data="recipes_random")],
            [InlineKeyboardButton("◀️ Назад", callback_data="menu_diary")],
        ]
        await query.edit_message_text("Рецепты:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "recipes_saved":
        async with db_pool.acquire() as conn:
            recipes = await conn.fetch("SELECT id, title FROM saved_recipes WHERE user_id = $1 ORDER BY created_at DESC LIMIT 10", user_id)
        if not recipes:
            back = InlineKeyboardButton("◀️ Назад", callback_data="diary_recipe")
            await query.edit_message_text("Сохранённых рецептов пока нет. Попросите меня написать рецепт!", reply_markup=InlineKeyboardMarkup([[back]]))
            return
        keyboard = [[InlineKeyboardButton("❤️ " + r["title"][:30], callback_data="view_recipe_" + str(r["id"]))] for r in recipes]
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="diary_recipe")])
        await query.edit_message_text("Ваши любимые рецепты:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("view_recipe_"):
        recipe_id = int(query.data.split("_")[-1])
        async with db_pool.acquire() as conn:
            recipe = await conn.fetchrow("SELECT title, content FROM saved_recipes WHERE id = $1", recipe_id)
        if recipe:
            back = InlineKeyboardButton("◀️ Назад", callback_data="recipes_saved")
            del_btn = InlineKeyboardButton("🗑 Удалить", callback_data="del_recipe_" + str(recipe_id))
            text = recipe["title"] + "\n\n" + recipe["content"]
            if len(text) > 4000: text = text[:4000] + "..."
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back, del_btn]]))

    elif query.data.startswith("del_recipe_"):
        recipe_id = int(query.data.split("_")[-1])
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM saved_recipes WHERE id = $1", recipe_id)
        back = InlineKeyboardButton("◀️ Назад", callback_data="recipes_saved")
        await query.edit_message_text("Рецепт удалён.", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "recipes_random":
        keyboard = [
            [InlineKeyboardButton("🍲 Супы", callback_data="recipe_cat_soups"), InlineKeyboardButton("🍽 Второе", callback_data="recipe_cat_main")],
            [InlineKeyboardButton("🥗 Салаты", callback_data="recipe_cat_salads"), InlineKeyboardButton("🍰 Десерты", callback_data="recipe_cat_desserts")],
            [InlineKeyboardButton("🔥 Тренды", callback_data="recipe_cat_trends")],
            [InlineKeyboardButton("◀️ Назад", callback_data="diary_recipe")],
        ]
        await query.edit_message_text("Выберите категорию:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("recipe_cat_"):
        cat_key = query.data.replace("recipe_cat_", "")
        cat_names = {"soups": "Супы", "main": "Второе", "salads": "Салаты", "desserts": "Десерты", "trends": "Тренды"}
        cat_name = cat_names.get(cat_key, "Рецепты")
        await query.edit_message_text("Подбираю " + cat_name + "...")
        recipe_list = await get_recipe_list(cat_key, lang)
        if not recipe_list:
            back = InlineKeyboardButton("◀️ Назад", callback_data="recipes_random")
            await query.edit_message_text("Рецепты временно недоступны.", reply_markup=InlineKeyboardMarkup([[back]]))
            return
        context.user_data["waiting_recipe_choice"] = cat_key
        context.user_data["recipe_list_" + cat_key] = recipe_list
        text = cat_name + "\n\n" + recipe_list + "\n\nНапишите цифру рецепта который хотите получить!"
        keyboard = [
            [InlineKeyboardButton("🔄 Другие варианты", callback_data="recipe_cat_" + cat_key)],
            [InlineKeyboardButton("◀️ Назад", callback_data="recipes_random")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "save_recipe_yes":
        title = context.user_data.get("last_recipe_title", "Рецепт")
        content = context.user_data.get("last_recipe_content", "")
        if content:
            async with db_pool.acquire() as conn:
                await conn.execute("INSERT INTO saved_recipes (user_id, title, content) VALUES ($1, $2, $3)", user_id, title, content)
        text = (title + "\n\n" + content if content else "Рецепт сохранён!")
        if len(text) > 4000: text = text[:4000] + "..."
        done_kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Сохранено ❤️", callback_data="recipe_done")]])
        try:
            await query.edit_message_text(text, reply_markup=done_kb)
        except:
            await query.edit_message_text("Рецепт сохранён в ваши любимые! ❤️", reply_markup=done_kb)

    elif query.data == "dont_save_recipe":
        content = context.user_data.get("last_recipe_content", "")
        title = context.user_data.get("last_recipe_title", "")
        text = (title + "\n\n" + content if content else "Хорошо!")
        if len(text) > 4000: text = text[:4000] + "..."
        done_kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Готово", callback_data="recipe_done")]])
        try:
            await query.edit_message_text(text, reply_markup=done_kb)
        except:
            await query.edit_message_text("Хорошо, не сохраняю.", reply_markup=done_kb)

    elif query.data == "recipe_done":
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except:
            pass
    elif query.data == "diary_movie":
        await query.edit_message_text("Подбираю фильм..." if ru else "Finding a movie...")
        movie = await get_ai_movie(lang)
        keyboard = [[InlineKeyboardButton("🔄 Другой" if ru else "🔄 Another", callback_data="diary_movie")], [InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_diary")]]
        await query.edit_message_text(f"Рекомендация:\n\n{movie}" if ru else f"Recommendation:\n\n{movie}", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "menu_profile":
        async with db_pool.acquire() as conn:
            total_msg = await conn.fetchval("SELECT COUNT(*) FROM history WHERE user_id = $1 AND role = 'user'", user_id)
            habits_count = await conn.fetchval("SELECT COUNT(*) FROM habits WHERE user_id = $1", user_id)
            income = await conn.fetchval("SELECT SUM(amount) FROM finances WHERE user_id = $1 AND type = 'income' AND created_at >= NOW() - INTERVAL '30 days'", user_id)
            expense = await conn.fetchval("SELECT SUM(amount) FROM finances WHERE user_id = $1 AND type = 'expense' AND created_at >= NOW() - INTERVAL '30 days'", user_id)
        created = user.get("created_at")
        days = (datetime.now() - created).days if created else 0
        tz = user.get("timezone") or "Europe/Moscow"
        balance = (income or 0) - (expense or 0)
        comm = user.get("comm_style", "наставник")
        if ru:
            text = f"Мой профиль\n\nИмя: {name}\nГород: {city}\nЧасовой пояс: {tz}\nЯзык: Русский 🇷🇺\nСтиль общения: {comm}\nДней с нами: {days}\nСообщений: {total_msg}\nПривычек: {habits_count}\nБаланс за месяц: {balance:.0f}"
            keyboard = [
                [InlineKeyboardButton("🌍 Изменить город", callback_data="profile_city")],
                [InlineKeyboardButton("💬 Сменить стиль общения", callback_data="change_comm_style")],
                [InlineKeyboardButton("🌐 Switch to English 🇬🇧", callback_data="switch_lang_en")],
                [InlineKeyboardButton("🗑 Забудь всё обо мне", callback_data="confirm_forget")],
                [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
            ]
        else:
            text = f"My profile\n\nName: {name}\nCity: {city}\nTimezone: {tz}\nLanguage: English 🇬🇧\nCommunication style: {comm}\nDays with us: {days}\nMessages: {total_msg}\nHabits: {habits_count}\nBalance this month: {balance:.0f}"
            keyboard = [
                [InlineKeyboardButton("🌍 Change city", callback_data="profile_city")],
                [InlineKeyboardButton("💬 Change communication style", callback_data="change_comm_style")],
                [InlineKeyboardButton("🌐 Switch to Russian 🇷🇺", callback_data="switch_lang_ru")],
                [InlineKeyboardButton("🗑 Forget everything about me", callback_data="confirm_forget")],
                [InlineKeyboardButton("◀️ Back", callback_data="back_main")],
            ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "change_comm_style":
        if ru:
            keyboard = [
                [InlineKeyboardButton("👭 Подружка — на ты, тепло", callback_data="set_style_подружка")],
                [InlineKeyboardButton("🎯 Наставник — на вы, мотивирующий", callback_data="set_style_наставник")],
                [InlineKeyboardButton("💼 Профессионал — чётко и по делу", callback_data="set_style_профессионал")],
                [InlineKeyboardButton("◀️ Назад", callback_data="menu_profile")],
            ]
            await query.edit_message_text("Выберите стиль общения:", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            keyboard = [
                [InlineKeyboardButton("👭 Friend — casual, informal", callback_data="set_style_friend")],
                [InlineKeyboardButton("🎯 Mentor — motivating, formal", callback_data="set_style_mentor")],
                [InlineKeyboardButton("💼 Professional — clear, concise", callback_data="set_style_professional")],
                [InlineKeyboardButton("◀️ Back", callback_data="menu_profile")],
            ]
            await query.edit_message_text("Choose communication style:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("set_style_"):
        style = query.data.replace("set_style_", "")
        await save_user(user_id, comm_style=style)
        await save_memory_item(user_id, "стиль_общения", style)
        back = InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_profile")
        style_names = {"подружка": "Подружка 👭", "наставник": "Наставник 🎯", "профессионал": "Профессионал 💼", "friend": "Friend 👭", "mentor": "Mentor 🎯", "professional": "Professional 💼"}
        style_name = style_names.get(style, style)
        text = f"Стиль общения изменён: {style_name}" if ru else f"Communication style changed: {style_name}"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "confirm_forget":
        keyboard = [
            [InlineKeyboardButton("🗑 Да, удалить всё" if ru else "🗑 Yes, delete everything", callback_data="do_forget")],
            [InlineKeyboardButton("❌ Отмена" if ru else "❌ Cancel", callback_data="menu_profile")],
        ]
        await query.edit_message_text("Вы уверены? Это удалит всю историю, заметки, напоминания и личные данные." if ru else "Are you sure? This will delete all history, notes, reminders and personal data.", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "do_forget":
        async with db_pool.acquire() as conn:
            for tbl in ["history", "reminders", "notes", "habits", "habit_logs", "finances", "user_memory", "sleep_logs", "shopping_list", "saved_recipes", "planner"]:
                try:
                    await conn.execute(f"DELETE FROM {tbl} WHERE user_id = $1", user_id)
                except:
                    pass
            await conn.execute("UPDATE users SET onboarded = FALSE, name = NULL, morning_plan = FALSE, evening_news = FALSE, water_reminders = FALSE WHERE user_id = $1", user_id)
        for job in context.application.job_queue.jobs():
            if hasattr(job, "data") and (job.data == user_id or (isinstance(job.data, dict) and job.data.get("user_id") == user_id)):
                job.schedule_removal()
        await query.edit_message_text("Все ваши данные удалены. Можем начать заново — напишите /start 🌸" if ru else "All data deleted. Start fresh — type /start 🌸")

    elif query.data == "switch_lang_en":
        await save_user(user_id, language="en")
        await query.edit_message_text("Language switched to English 🇬🇧\n\nType /menu to continue!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="back_main")]]))

    elif query.data == "switch_lang_ru":
        await save_user(user_id, language="ru")
        await query.edit_message_text("Язык изменён на русский 🇷🇺\n\nНапишите /menu чтобы продолжить!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="back_main")]]))

    elif query.data == "profile_city":
        context.user_data["waiting_city"] = True
        back = InlineKeyboardButton("◀️ Отмена" if ru else "◀️ Cancel", callback_data="menu_profile")
        await query.edit_message_text("Напишите название вашего города" if ru else "Write your city name", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "menu_settings":
        mw = "✅" if user.get("morning_weather") else "❌"
        mm = "✅" if user.get("morning_motivation") else "❌"
        w = "✅" if user.get("water_reminders") else "❌"
        ev = "✅" if user.get("evening_news") else "❌"
        comm = user.get("comm_style", "наставник")
        if ru:
            keyboard = [
                [InlineKeyboardButton("👤 Профиль", callback_data="menu_profile")],
                [InlineKeyboardButton("💬 Стиль: " + comm, callback_data="change_comm_style")],
                [InlineKeyboardButton("🌍 Изменить город", callback_data="profile_city")],
                [InlineKeyboardButton("🌐 Switch to English", callback_data="switch_lang_en")],
                [InlineKeyboardButton(mw + " Погода утром", callback_data="toggle_morning_weather")],
                [InlineKeyboardButton(mm + " Мотивация утром", callback_data="toggle_morning_motivation")],
                [InlineKeyboardButton(w + " Напоминания о воде", callback_data="water_toggle")],
                [InlineKeyboardButton(ev + " Вечерняя сводка", callback_data="toggle_evening_news")],
                [InlineKeyboardButton("🗑 Забудь всё обо мне", callback_data="confirm_forget")],
                [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
            ]
        else:
            keyboard = [
                [InlineKeyboardButton("👤 Profile", callback_data="menu_profile")],
                [InlineKeyboardButton("💬 Style: " + comm, callback_data="change_comm_style")],
                [InlineKeyboardButton("🌍 Change city", callback_data="profile_city")],
                [InlineKeyboardButton("🌐 Switch to Russian", callback_data="switch_lang_ru")],
                [InlineKeyboardButton(mw + " Weather in morning", callback_data="toggle_morning_weather")],
                [InlineKeyboardButton(mm + " Motivation in morning", callback_data="toggle_morning_motivation")],
                [InlineKeyboardButton(w + " Water reminders", callback_data="water_toggle")],
                [InlineKeyboardButton(ev + " Evening summary", callback_data="toggle_evening_news")],
                [InlineKeyboardButton("🗑 Forget everything", callback_data="confirm_forget")],
                [InlineKeyboardButton("◀️ Back", callback_data="back_main")],
            ]
        await query.edit_message_text("Настройки" if ru else "Settings", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "toggle_morning_weather":
        new = not user.get("morning_weather", False)
        await save_user(user_id, morning_weather=new)
        status = ("включена ✅" if new else "выключена ❌") if ru else ("on ✅" if new else "off ❌")
        back = InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_settings")
        await query.edit_message_text(f"Погода утром {status}" if ru else f"Morning weather {status}", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "toggle_morning_motivation":
        new = not user.get("morning_motivation", False)
        await save_user(user_id, morning_motivation=new)
        status = ("включена ✅" if new else "выключена ❌") if ru else ("on ✅" if new else "off ❌")
        back = InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_settings")
        await query.edit_message_text(f"Мотивация утром {status}" if ru else f"Morning motivation {status}", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "toggle_evening_news":
        new = not user.get("evening_news", False)
        await save_user(user_id, evening_news=new)
        if new:
            evening_time = user.get("evening_time", "21:00")
            tz = pytz.timezone(user.get("timezone", "Europe/Moscow"))
            hour = int(evening_time.split(":")[0])
            context.application.job_queue.run_daily(send_evening_news, time=time(hour=hour, minute=0, tzinfo=tz), data=user_id, name=f"evening_{user_id}")
            text = f"Вечерняя сводка включена! В {evening_time}" if ru else f"Evening summary on! At {evening_time}"
        else:
            for job in context.application.job_queue.get_jobs_by_name(f"evening_{user_id}"):
                job.schedule_removal()
            text = "Вечерняя сводка выключена." if ru else "Evening summary off."
        back = InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_settings")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "count_food_calories":
        image_data = context.user_data.pop("pending_food_photo", None)
        if not image_data:
            await query.edit_message_text("Фото не найдено. Отправьте снова.")
            return
        await query.edit_message_text("Анализирую... 🔍")
        food_res = await analyze_food_photo(image_data)
        if food_res and "Калории:" in food_res:
            import re as _rfc
            cal_m = _rfc.search(r"Калории:\s*(\d+)", food_res)
            prot_m = _rfc.search(r"Белки:\s*([\d.]+)", food_res)
            fat_m = _rfc.search(r"Жиры:\s*([\d.]+)", food_res)
            carb_m = _rfc.search(r"Углеводы:\s*([\d.]+)", food_res)
            dish_m = _rfc.search(r"Блюдо:\s*(.+)", food_res)
            async with db_pool.acquire() as conn:
                await conn.execute("INSERT INTO food_logs (user_id, description, calories, protein, fat, carbs) VALUES ($1, $2, $3, $4, $5, $6)", user_id, dish_m.group(1).strip() if dish_m else "Блюдо", int(cal_m.group(1)) if cal_m else 0, float(prot_m.group(1)) if prot_m else 0, float(fat_m.group(1)) if fat_m else 0, float(carb_m.group(1)) if carb_m else 0)
            await query.edit_message_text(food_res + "\n\nЗаписала в журнал питания! 🥗\nЭто приблизительная оценка — для точности укажите граммы в подписи к фото.")
        else:
            await query.edit_message_text("Не смогла определить КБЖУ. Попробуйте другое фото.")

    elif query.data == "just_describe_photo":
        image_data = context.user_data.pop("pending_food_photo", None)
        if not image_data:
            await query.edit_message_text("Фото не найдено.")
            return
        await query.edit_message_text("Описываю фото...")
        reply = await analyze_image(image_data, "", lang)
        await query.edit_message_text(reply)

    elif query.data == "close_menu":
        await query.edit_message_text("Меню закрыто. Напишите /menu чтобы открыть снова 🌸" if ru else "Menu closed. Type /menu to open again 🌸")

    elif query.data == "back_main":
        await query.edit_message_text("🌸", reply_markup=get_main_menu(lang))

async def announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Нет доступа.")
        return
    if not context.args:
        await update.message.reply_text("Пример: /announce Текст")
        return
    text = " ".join(context.args)
    all_users = await get_all_users()
    sent = 0
    failed = 0
    await update.message.reply_text(f"Рассылка для {len(all_users)} пользователей...")
    for uid in all_users:
        try:
            await context.bot.send_message(chat_id=uid, text=f"📢 {text}")
            sent += 1
        except:
            failed += 1
    await update.message.reply_text(f"Отправлено: {sent}\nНе доставлено: {failed}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "Пользователь"
    username = update.effective_user.username or "нет username"
    # Если уже онбордингован — просто открываем меню
    existing = await get_user(user_id)
    if existing and existing.get("onboarded"):
        lang = existing.get("language", "ru")
        await update.message.reply_text("🌸", reply_markup=get_main_menu(lang))
        return ConversationHandler.END
    await save_user(user_id, username=username)
    await update.message.reply_text(t("ru", "welcome"))
    await notify_admin(context, user_name, username, f"Новый пользователь (ID: {user_id})", "Начал онбординг")
    return ASK_NAME

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    name = update.message.text.strip()
    await save_user(user_id, name=name, username=update.effective_user.username or "")
    await save_memory_item(user_id, "имя", name)
    await update.message.reply_text(t("ru", "ask_city", name=name), reply_markup=ReplyKeyboardRemove())
    return ASK_CITY

async def ask_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    city = update.message.text.strip()
    timezone = await get_timezone_by_city(city)
    await save_user(user_id, city=city, timezone=timezone)
    await save_memory_item(user_id, "город", city)
    keyboard = [["🇷🇺 Русский", "🇬🇧 English"]]
    await update.message.reply_text(t("ru", "ask_language", city=city), reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
    return ASK_LANGUAGE

async def ask_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = "en" if "English" in update.message.text else "ru"
    await save_user(user_id, language=lang)
    keyboard = [["✅ Да, каждое утро" if lang == "ru" else "✅ Yes, every morning", "❌ Нет, не нужно" if lang == "ru" else "❌ No, thanks"]]
    await update.message.reply_text(t(lang, "ask_morning"), reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
    return ASK_MORNING_PLAN

async def ask_morning_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    lang = user.get("language", "ru") if user else "ru"
    wants = "Да" in update.message.text or "Yes" in update.message.text
    await save_user(user_id, morning_plan=wants)
    if wants:
        keyboard = [["7:00", "8:00", "9:00"], ["10:00", "Другое" if lang == "ru" else "Other"]]
        await update.message.reply_text(t(lang, "ask_morning_time"), reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
        return ASK_MORNING_TIME
    return await ask_reminders_step(update, context)

async def ask_morning_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        hour = int(update.message.text.replace(":00", "").replace(":30", ""))
        morning_time = f"{hour:02d}:00"
    except:
        morning_time = "08:00"
    await save_user(user_id, morning_time=morning_time)
    return await ask_reminders_step(update, context)

async def ask_reminders_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    lang = user.get("language", "ru") if user else "ru"
    keyboard = [["✅ За час", "⏰ За 30 минут", "❌ Не нужно"]] if lang == "ru" else [["✅ 1 hour before", "⏰ 30 minutes before", "❌ No thanks"]]
    await update.message.reply_text(t(lang, "ask_reminders"), reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
    return ASK_REMINDERS

async def finish_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    user = await get_user(user_id)
    lang = user.get("language", "ru") if user else "ru"
    if "час" in text or "1 hour" in text:
        reminder_before = 60
    elif "30" in text:
        reminder_before = 30
    else:
        reminder_before = 0
    await save_user(user_id, reminder_before=reminder_before)
    return await ask_evening_news_step(update, context)

async def ask_evening_news_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    lang = user.get("language", "ru") if user else "ru"
    keyboard = [["✅ Да, вечером", "❌ Не нужно"]] if lang == "ru" else [["✅ Yes, in the evening", "❌ No thanks"]]
    await update.message.reply_text(t(lang, "ask_evening_news"), reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
    return ASK_EVENING_NEWS

async def handle_evening_news_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    lang = user.get("language", "ru") if user else "ru"
    wants = "Да" in update.message.text or "Yes" in update.message.text
    await save_user(user_id, evening_news=wants)
    if wants:
        keyboard = [["20:00", "21:00", "22:00"], ["19:00", "Другое" if lang == "ru" else "Other"]]
        await update.message.reply_text(t(lang, "ask_evening_time"), reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
        return ASK_EVENING_TIME
    return await ask_comm_style_step(update, context)

async def handle_evening_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        hour = int(update.message.text.replace(":00", "").replace(":30", ""))
        evening_time = f"{hour:02d}:00"
    except:
        evening_time = "21:00"
    await save_user(user_id, evening_time=evening_time)
    return await ask_comm_style_step(update, context)

async def ask_comm_style_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    lang = user.get("language", "ru") if user else "ru"
    if lang == "en":
        keyboard = [["👭 Friend — casual, on first name basis"], ["🎯 Mentor — motivating, formal"], ["💼 Professional — clear and concise"], ["✍️ My own style — I'll describe"]]
        text = "How would you like me to communicate with you?"
    else:
        keyboard = [["👭 Подружка — тепло, неформально, на ты"], ["🎯 Наставник — мотивирующий, на вы"], ["💼 Профессионал — чётко и по делу"], ["✍️ Свой стиль — напишу сама"]]
        text = "Как вам удобнее чтобы я общалась с вами?"
    await update.message.reply_text(text, reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
    return ASK_COMM_STYLE

async def handle_comm_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    lang = user.get("language", "ru") if user else "ru"
    text = update.message.text
    if "Подружка" in text or "Friend" in text:
        style = "подружка" if lang == "ru" else "friend"
    elif "Наставник" in text or "Mentor" in text:
        style = "наставник" if lang == "ru" else "mentor"
    elif "Профессионал" in text or "Professional" in text:
        style = "профессионал" if lang == "ru" else "professional"
    else:
        style = text.strip()[:50]
    await save_user(user_id, comm_style=style)
    await save_memory_item(user_id, "стиль_общения", style)
    confirm = f"Отлично, запомнила! Стиль: {style} 🌸" if lang == "ru" else f"Got it! Style: {style} 🌸"
    await update.message.reply_text(confirm, reply_markup=ReplyKeyboardRemove())
    return await finish_onboarding_final(update, context)

async def finish_onboarding_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await save_user(user_id, onboarded=True)
    user = await get_user(user_id)
    lang = user.get("language", "ru") if user else "ru"
    name = user["name"] if user else ""
    morning_time = user["morning_time"] if user else "08:00"
    has_plan = user["morning_plan"] if user else False
    has_evening = user.get("evening_news", False)
    evening_time = user.get("evening_time", "21:00")
    await update.message.reply_text(t(lang, "finish", name=name), reply_markup=ReplyKeyboardRemove())
    username = update.effective_user.username or "нет username"
    await notify_admin(context, name, username, "Завершил онбординг", f"Стиль: {user.get('comm_style', 'н/а')}, Язык: {lang}")
    if has_plan and morning_time:
        tz = pytz.timezone(user["timezone"] if user else "Europe/Moscow")
        context.application.job_queue.run_daily(send_morning_plan, time=time(hour=int(morning_time.split(":")[0]), minute=0, tzinfo=tz), data=user_id, name=f"morning_{user_id}")
    if has_evening and evening_time:
        tz = pytz.timezone(user["timezone"] if user else "Europe/Moscow")
        context.application.job_queue.run_daily(send_evening_news, time=time(hour=int(evening_time.split(":")[0]), minute=0, tzinfo=tz), data=user_id, name=f"evening_{user_id}")
    return ConversationHandler.END

async def process_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    if not user or not user["onboarded"]:
        await update.message.reply_text(t("ru", "not_started"))
        return
    name = user["name"]
    lang = user.get("language", "ru")
    ru = lang == "ru"
    user_name = update.effective_user.first_name or "Пользователь"
    username = update.effective_user.username or "нет username"

    # Смена стиля через чат
    if is_change_style_request(user_text):
        text_lower = user_text.lower()
        if "подруж" in text_lower or "friend" in text_lower or "на ты" in text_lower:
            new_style = "подружка" if ru else "friend"
        elif "наставник" in text_lower or "mentor" in text_lower or "на вы" in text_lower:
            new_style = "наставник" if ru else "mentor"
        elif "профессионал" in text_lower or "professional" in text_lower:
            new_style = "профессионал" if ru else "professional"
        else:
            new_style = None
        if new_style:
            await save_user(user_id, comm_style=new_style)
            await save_memory_item(user_id, "стиль_общения", new_style)
            reply = f"Стиль изменён на «{new_style}»! Теперь буду общаться именно так 🌸" if ru else f"Style changed to «{new_style}»! I'll communicate that way now 🌸"
            await update.message.reply_text(reply)
            await notify_admin(context, user_name, username, user_text, reply)
            return

    # Пользователь ответил "да" на предложение добавить в планер
    if user_text.strip().lower() in ["да", "yes", "добавь", "запиши"] and context.user_data.get("pending_planner_text"):
        original_text = context.user_data.pop("pending_planner_text")
        h, m = extract_exact_time(original_text)
        if h is None:
            # Времени нет — спрашиваем
            context.user_data["waiting_planner_time"] = original_text
            await update.message.reply_text("В какое время? Напишите например 19:00")
            return
        # Время есть — ищем день
        text_lower = original_text.lower()
        day_num = None
        for day_name, day_idx in DAYS_RU.items():
            if day_name in text_lower:
                day_num = day_idx
                break
        if day_num is None:
            context.user_data["waiting_planner_day"] = original_text
            await update.message.reply_text("В какой день недели? Напишите например: пятница")
            return
        time_str = str(h).zfill(2) + ":" + str(m).zfill(2)
        parts = original_text.split(time_str)
        import re as _rp2
        raw_title = parts[-1].strip().lstrip("-— ") if len(parts) > 1 else original_text
        event_title = _rp2.sub(r"(каждый|каждую|каждое|всегда|регулярно|по\s+\w+|у меня)\s*", "", raw_title, flags=_rp2.IGNORECASE).strip()
        if not event_title or len(event_title) < 2:
            words = [w for w in original_text.split() if len(w) > 3 and ":" not in w]
            event_title = words[-1] if words else raw_title
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO planner (user_id, day_of_week, time_str, title) VALUES ($1, $2, $3, $4)", user_id, day_num, time_str, event_title)
        day_display = DAYS_RU_NAMES[day_num]
        await update.message.reply_text("Записала! Каждый " + day_display + " в " + time_str + " — " + event_title + " 📅")
        return

    # Пользователь уточнил время для планера
    if context.user_data.get("waiting_planner_time"):
        original_text = context.user_data.pop("waiting_planner_time")
        h, m = extract_exact_time(user_text)
        if h is None:
            await update.message.reply_text("Не поняла время. Напишите например 19:00")
            return
        time_str = str(h).zfill(2) + ":" + str(m).zfill(2)
        text_lower = original_text.lower()
        day_num = None
        for day_name, day_idx in DAYS_RU.items():
            if day_name in text_lower:
                day_num = day_idx
                break
        if day_num is None:
            context.user_data["waiting_planner_day_and_time"] = original_text + " в " + time_str
            await update.message.reply_text("В какой день недели? Напишите например: пятница")
            return
        import re as _re_pl
        event_title = _re_pl.sub(r"(каждый|каждую|каждое|всегда|регулярно|по\s+\w+)\s*", "", original_text, flags=_re_pl.IGNORECASE).strip()
        event_title = _re_pl.sub(r"\d{1,2}[:.\s]\d{2}", "", event_title).strip().lstrip("-— ")
        if not event_title or len(event_title) < 2:
            words = [w for w in original_text.split() if len(w) > 3 and ":" not in w]
            event_title = words[-1] if words else original_text
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO planner (user_id, day_of_week, time_str, title) VALUES ($1, $2, $3, $4)", user_id, day_num, time_str, event_title)
        day_display = DAYS_RU_NAMES[day_num]
        await update.message.reply_text("Записала! Каждый " + day_display + " в " + time_str + " — " + event_title + " 📅")
        return

    # Пользователь уточнил день для планера (когда было время но не было дня)
    if context.user_data.get("waiting_planner_day"):
        original_text = context.user_data.pop("waiting_planner_day")
        day_num = None
        for day_name, day_idx in DAYS_RU.items():
            if day_name in user_text.lower():
                day_num = day_idx
                break
        if day_num is None:
            await update.message.reply_text("Не поняла день. Напишите например: пятница")
            return
        h, m = extract_exact_time(original_text)
        time_str = str(h).zfill(2) + ":" + str(m).zfill(2)
        parts = original_text.split(time_str)
        event_title = parts[-1].strip().lstrip("-— ") if len(parts) > 1 else original_text
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO planner (user_id, day_of_week, time_str, title) VALUES ($1, $2, $3, $4)", user_id, day_num, time_str, event_title)
        day_display = DAYS_RU_NAMES[day_num]
        await update.message.reply_text("Записала! Каждый " + day_display + " в " + time_str + " — " + event_title + " 📅")
        return

    if context.user_data.get("waiting_recipe_choice"):
        cat_key = context.user_data["waiting_recipe_choice"]
        if user_text.strip().isdigit():
            idx = int(user_text.strip())
            recipe_list = context.user_data.get("recipe_list_" + cat_key, "")
            lines = [l.strip() for l in recipe_list.split("\n") if l.strip() and l.strip()[0].isdigit()]
            if 1 <= idx <= len(lines):
                import re as _re
                dish_name = _re.sub(r"^\d+[.)] ?", "", lines[idx-1]).strip()
                context.user_data["waiting_recipe_choice"] = None
                await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
                await update.message.reply_text("Готовлю рецепт: " + dish_name + "...")
                recipe_content = await get_full_recipe(dish_name, lang)
                if recipe_content:
                    context.user_data["last_recipe_title"] = dish_name
                    context.user_data["last_recipe_content"] = recipe_content
                    save_text = "\n\nХотите сохранить этот рецепт в ваши любимые?"
                    keyboard = InlineKeyboardMarkup([[
                        InlineKeyboardButton("❤️ Сохранить", callback_data="save_recipe_yes"),
                        InlineKeyboardButton("✖️ Не нужно", callback_data="dont_save_recipe"),
                    ]])
                    await update.message.reply_text(recipe_content + save_text, reply_markup=keyboard)
                return

    if context.user_data.get("waiting_planner"):
        context.user_data["waiting_planner"] = False
        text_lower = user_text.lower()
        day_num = None
        for day_name, day_idx in DAYS_RU.items():
            if day_name in text_lower:
                day_num = day_idx
                break
        h, m = extract_exact_time(user_text)
        if day_num is not None and h is not None:
            time_str = str(h).zfill(2) + ":" + str(m).zfill(2)
            parts = user_text.split(str(h).zfill(2) + ":" + str(m).zfill(2))
            event_title = parts[-1].strip().lstrip("-— ") if len(parts) > 1 else user_text
            async with db_pool.acquire() as conn:
                await conn.execute("INSERT INTO planner (user_id, day_of_week, time_str, title) VALUES ($1, $2, $3, $4)", user_id, day_num, time_str, event_title)
            day_display = DAYS_RU_NAMES[day_num]
            reply = "Записала в планер! Каждый " + day_display + " в " + time_str + " — " + event_title
            await update.message.reply_text(reply)
        else:
            await update.message.reply_text("Не смогла распознать. Напишите например: каждую среду в 17:00 танцы")
        return

    if context.user_data.get("waiting_interesting"):
        category = context.user_data["waiting_interesting"]
        if user_text.strip().isdigit():
            idx = int(user_text.strip()) - 1
            articles = context.user_data.get(f"interesting_articles_{category}", [])
            translated = context.user_data.get(f"interesting_translated_{category}", [])
            if 0 <= idx < len(articles):
                context.user_data["waiting_interesting"] = None
                await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
                title = translated[idx] if idx < len(translated) else articles[idx]["title"]
                loading = f"Читаю про «{title}»..." if ru else f"Reading about «{title}»..."
                await update.message.reply_text(loading)
                details = await get_article_details(articles[idx], lang)
                await update.message.reply_text(details)
                return
            else:
                max_n = len(articles)
                await update.message.reply_text(f"Введите число от 1 до {max_n}" if ru else f"Enter a number from 1 to {max_n}")
                return

    if context.user_data.get("waiting_habit"):
        context.user_data["waiting_habit"] = False
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO habits (user_id, name) VALUES ($1, $2)", user_id, user_text)
        await update.message.reply_text(f"Привычка '{user_text}' добавлена!" if ru else f"Habit '{user_text}' added!")
        return

    if context.user_data.get("waiting_shopping"):
        context.user_data["waiting_shopping"] = False
        items = [i.strip() for i in re.split(r'[,\n;]', user_text) if i.strip()]
        async with db_pool.acquire() as conn:
            for item in items:
                await conn.execute("INSERT INTO shopping_list (user_id, item) VALUES ($1, $2)", user_id, item)
        count = len(items)
        reply = f"Добавлено {count} {'позиция' if count == 1 else 'позиций'} в список покупок!" if ru else f"Added {count} item{'s' if count > 1 else ''} to shopping list!"
        await update.message.reply_text(reply)
        return

    if context.user_data.get("waiting_city"):
        context.user_data["waiting_city"] = False
        timezone = await get_timezone_by_city(user_text)
        await save_user(user_id, city=user_text, timezone=timezone)
        await save_memory_item(user_id, "город", user_text)
        await update.message.reply_text(f"Город изменён на {user_text}" if ru else f"City changed to {user_text}")
        return

    if context.user_data.get("waiting_note"):
        context.user_data["waiting_note"] = False
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO notes (user_id, text) VALUES ($1, $2)", user_id, user_text)
        await update.message.reply_text("Заметка сохранена!" if ru else "Note saved!")
        return

    if context.user_data.get("waiting_weight"):
        context.user_data["waiting_weight"] = False
        try:
            pw = user_text.strip().split()
            weight_v = float(pw[0].replace(",", "."))
            height_v = float(pw[1].replace(",", ".")) if len(pw) > 1 else None
            async with db_pool.acquire() as conn:
                await conn.execute("INSERT INTO weight_logs (user_id, weight, height) VALUES ($1, $2, $3)", user_id, weight_v, height_v)
                # Синхронизируем с профилем нутрициологии
                nutr = await conn.fetchrow("SELECT id FROM nutrition_profile WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1", user_id)
                if nutr:
                    await conn.execute("UPDATE nutrition_profile SET weight = $1 WHERE user_id = $2", weight_v, user_id)
            rw = "Вес записан: " + str(weight_v) + " кг"
            if height_v:
                bmi = round(weight_v / ((height_v / 100) ** 2), 1)
                rw += ", рост: " + str(height_v) + " см, ИМТ: " + str(bmi)
            await update.message.reply_text(rw + " ⚖️")
        except:
            await update.message.reply_text("Не поняла. Напишите например: 65 или 65 170")
        return

    if context.user_data.get("nutrition_setup"):
        step = context.user_data.get("nutrition_step", "height")
        if step in ["intro", "height"]:
            try:
                context.user_data["nutrition_height"] = float(user_text.replace(",", "."))
                context.user_data["nutrition_step"] = "weight"
                await update.message.reply_text("Отлично! Теперь ваш вес в кг:")
            except:
                await update.message.reply_text("Напишите число, например: 165")
            return
        elif step == "weight":
            try:
                context.user_data["nutrition_weight"] = float(user_text.replace(",", "."))
                context.user_data["nutrition_step"] = "age"
                await update.message.reply_text("Сколько вам лет?")
            except:
                await update.message.reply_text("Напишите число, например: 60")
            return
        elif step == "age":
            try:
                context.user_data["nutrition_age"] = int(user_text.strip())
                context.user_data["nutrition_step"] = "goal"
                keyboard = ReplyKeyboardMarkup([["Похудеть", "Набрать вес"], ["Поддержать вес", "Оздоровиться"]], one_time_keyboard=True, resize_keyboard=True)
                await update.message.reply_text("Какая ваша цель?", reply_markup=keyboard)
            except:
                await update.message.reply_text("Напишите число, например: 25")
            return
        elif step == "goal":
            context.user_data["nutrition_goal"] = user_text.strip()
            context.user_data["nutrition_step"] = "pregnant"
            keyboard = ReplyKeyboardMarkup([["Нет", "Да, беременна"]], one_time_keyboard=True, resize_keyboard=True)
            await update.message.reply_text("Вы беременны или кормите грудью?", reply_markup=keyboard)
            return
        elif step == "pregnant":
            is_preg = "да" in user_text.lower()
            context.user_data["nutrition_pregnant"] = is_preg
            context.user_data["nutrition_step"] = "meds"
            await update.message.reply_text("Принимаете ли вы препараты или витамины? Напишите список или нет:", reply_markup=ReplyKeyboardRemove())
            return
        elif step == "meds":
            meds_val = None if user_text.strip().lower() in ["нет", "no", "-"] else user_text.strip()
            h_n = context.user_data.get("nutrition_height", 165)
            w_n = context.user_data.get("nutrition_weight", 60)
            age_n = context.user_data.get("nutrition_age", 25)
            goal_n = context.user_data.get("nutrition_goal", "Поддержать вес")
            preg_n = context.user_data.get("nutrition_pregnant", False)
            if "похудеть" in goal_n.lower():
                cal = int(w_n * 30 * 0.8)
            elif "набрать" in goal_n.lower():
                cal = int(w_n * 30 * 1.2)
            else:
                cal = int(w_n * 30)
            if preg_n: cal = max(cal, 2200)
            try:
                async with db_pool.acquire() as conn:
                    await conn.execute("INSERT INTO nutrition_profile (user_id, height, weight, age, goal, calories_goal, pregnant, medications) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)", user_id, h_n, w_n, age_n, goal_n, cal, preg_n, meds_val)
                context.user_data["nutrition_setup"] = False
                context.user_data["nutrition_step"] = None
                recs = ""
                if age_n and age_n < 25: recs += "\nВ вашем возрасте важны кальций и витамин D."
                if preg_n: recs += "\nПри беременности добавьте фолиевую кислоту и омега-3."
                if meds_val: recs += "\nНекоторые препараты влияют на усвоение витаминов."
                reply_txt = "Профиль создан!\n\nРост: " + str(int(h_n)) + " см\nВес: " + str(int(w_n)) + " кг\nВозраст: " + str(age_n) + " лет\nЦель: " + goal_n + "\nКалорий/день: " + str(cal) + " ккал"
                if recs: reply_txt += "\n\nРекомендации для вас:" + recs
                reply_txt += "\n\nОтправляйте фото еды или пишите что ели — я посчитаю КБЖУ!"
                await update.message.reply_text(reply_txt)
            except Exception as ne:
                logging.error("Ошибка нутрициологии: " + str(ne))
                await update.message.reply_text("Что-то пошло не так. Попробуйте ещё раз — напишите /menu и откройте Здоровье → Нутрициология")
            return

    if context.user_data.get("waiting_goal"):
        context.user_data["waiting_goal"] = False
        parts_g = user_text.strip().split(",")
        title_g = parts_g[0].strip()
        deadline_g = None
        if len(parts_g) > 1:
            try:
                from datetime import datetime as _dtg
                deadline_g = _dtg.strptime(parts_g[1].strip(), "%d.%m.%Y").date()
            except:
                pass
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO goals (user_id, title, deadline) VALUES ($1, $2, $3)", user_id, title_g, deadline_g)
        rg = "Цель добавлена: " + title_g + (" (до " + str(deadline_g) + ")" if deadline_g else "") + " 🎯"
        await update.message.reply_text(rg)
        return

    if context.user_data.get("waiting_progress_goal_id"):
        gid = context.user_data.pop("waiting_progress_goal_id")
        try:
            async with db_pool.acquire() as conn:
                g_data = await conn.fetchrow("SELECT title FROM goals WHERE id = $1", gid)
            goal_title = g_data["title"] if g_data else "цель"
            prog_prompt = "Цель: " + goal_title + "\nЧто сделано: " + user_text + "\n\nОцени прогресс в % (0-100). Ответь ТОЛЬКО числом от 0 до 100."
            prog_resp = ai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prog_prompt}], max_tokens=10, temperature=0.1)
            prog_text = prog_resp.choices[0].message.content.strip().replace("%", "")
            prog = max(0, min(100, int("".join(filter(str.isdigit, prog_text)) or "0")))
            async with db_pool.acquire() as conn:
                await conn.execute("UPDATE goals SET progress = $1 WHERE id = $2", prog, gid)
            await update.message.reply_text("Отлично! Прогресс по цели \"" + goal_title + "\" обновлён до " + str(prog) + "% 🎯")
        except Exception as pe:
            logging.error("Ошибка прогресса: " + str(pe))
            await update.message.reply_text("Не смогла оценить. Напишите подробнее что сделали.")
        return

    if context.user_data.get("waiting_cycle_length"):
        context.user_data["waiting_cycle_length"] = False
        try:
            lc = int(user_text.strip())
            if 20 <= lc <= 45:
                async with db_pool.acquire() as conn:
                    await conn.execute("UPDATE cycle_tracking SET cycle_length = $1 WHERE user_id = $2", lc, user_id)
                await update.message.reply_text("Длина цикла обновлена: " + str(lc) + " дней 🩸")
            else:
                await update.message.reply_text("Длина цикла должна быть от 20 до 45 дней.")
        except:
            await update.message.reply_text("Напишите число, например: 28")
        return

    if context.user_data.get("waiting_cycle_date"):
        context.user_data["waiting_cycle_date"] = False
        try:
            from datetime import datetime as _dt2
            date_obj = _dt2.strptime(user_text.strip(), "%d.%m.%Y").date()
            async with db_pool.acquire() as conn:
                ex = await conn.fetchrow("SELECT cycle_length FROM cycle_tracking WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1", user_id)
                length = ex["cycle_length"] if ex else 28
                await conn.execute("INSERT INTO cycle_tracking (user_id, start_date, cycle_length) VALUES ($1, $2, $3)", user_id, date_obj, length)
            await update.message.reply_text("Дата начала цикла сохранена: " + str(date_obj) + " 🩸")
        except:
            await update.message.reply_text("Не поняла дату. Напишите в формате ДД.ММ.ГГГГ, например: 01.06.2025")
        return

    if context.user_data.get("waiting_med_name"):
        context.user_data["waiting_med_name"] = False
        parts = user_text.strip().rsplit(" ", 1)
        med_name = parts[0] if len(parts) > 1 else user_text.strip()
        med_time_str = parts[1] if len(parts) > 1 else "08:00"
        h_m, m_m = extract_exact_time(med_time_str)
        if h_m is None: h_m, m_m = 8, 0
        ts = str(h_m).zfill(2) + ":" + str(m_m).zfill(2)
        async with db_pool.acquire() as conn:
            med_id = await conn.fetchval("INSERT INTO medications (user_id, name, time_str) VALUES ($1, $2, $3) RETURNING id", user_id, med_name, ts)
        tz_u = pytz.timezone(user.get("timezone") or "Europe/Moscow")
        context.application.job_queue.run_daily(send_med_reminder, time=time(hour=h_m, minute=m_m, tzinfo=tz_u), data={"user_id": user_id, "med_name": med_name}, name="med_" + str(user_id) + "_" + str(med_id))
        await update.message.reply_text("Таблетка добавлена: " + med_name + " в " + ts + " 💊 Напоминание установлено!")
        return

    if context.user_data.get("waiting_finance"):
        context.user_data["waiting_finance"] = False
        parts = user_text.split()
        try:
            raw = parts[0].replace(",", ".")
            is_income = raw.startswith("+")
            amount = float(raw.replace("+", "").replace("-", ""))
            finance_type = "income" if is_income else "expense"
            category = parts[1] if len(parts) > 1 else ("Другое" if ru else "Other")
            description = " ".join(parts[2:]) if len(parts) > 2 else ""
            async with db_pool.acquire() as conn:
                await conn.execute("INSERT INTO finances (user_id, amount, type, category, description) VALUES ($1, $2, $3, $4, $5)", user_id, amount, finance_type, category, description)
            await update.message.reply_text(f"{'Доход' if is_income else 'Расход'} {amount:.0f} ({category}) сохранён!" if ru else f"{'Income' if is_income else 'Expense'} {amount:.0f} ({category}) saved!")
        except:
            await update.message.reply_text("Формат: +1000 зарплата или -500 еда кофе" if ru else "Format: +1000 salary or -500 food coffee")
        return

    await add_history(user_id, "user", user_text)
    await extract_and_save_memory(user_id, user_text, lang)
    history = await get_history_db(user_id)
    memory = await get_user_memory(user_id)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        # Генерация изображений
        if is_image_gen_request(user_text):
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_photo")
            prompt = user_text
            for kw in ["нарисуй", "сгенерируй картинку", "создай изображение", "сделай картинку", "draw", "generate image", "create image"]:
                prompt = re.sub(kw, "", prompt, flags=re.IGNORECASE).strip()
            msg = "Генерирую изображение, подождите..." if ru else "Generating image, please wait..."
            sent_msg = await update.message.reply_text(msg)
            image_url = await generate_image(prompt)
            if image_url:
                if image_url.startswith("data:image"):
                    import io
                    img_data = base64.b64decode(image_url.split(",")[1])
                    await context.bot.send_photo(chat_id=update.effective_chat.id, photo=io.BytesIO(img_data))
                else:
                    await context.bot.send_photo(chat_id=update.effective_chat.id, photo=image_url)
                await notify_admin(context, user_name, username, user_text, "[Сгенерировано изображение]")
            else:
                await update.message.reply_text("Не удалось сгенерировать изображение." if ru else "Could not generate image.")
            return

        # Новости
        if is_news_request(user_text):
            query_text = None
            for kw in ["новости про", "новости о", "news about", "news on"]:
                if kw in user_text.lower():
                    query_text = user_text.lower().split(kw)[-1].strip()
                    break
            news = await get_news(query=query_text, lang=lang)
            if news:
                await update.message.reply_text(news)
                await notify_admin(context, user_name, username, user_text, news[:200])
                return

        # Погода в чате
        if is_weather_request(user_text) and not is_reminder_request(user_text):
            try:
                await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
                user_city = user.get("city") or "Москва"
                if "завтра" in user_text.lower() or "tomorrow" in user_text.lower():
                    forecast = await get_weather_forecast(user_city, lang)
                    if forecast and "\n\n" in forecast:
                        day_lines = forecast.split("\n\n")[1].split("\n")
                        if len(day_lines) > 1:
                            city_f = city_in_form(user_city) if lang == "ru" else user_city
                            reply = "Завтра в " + city_f + ":\n" + day_lines[1]
                            await update.message.reply_text(reply)
                            await notify_admin(context, user_name, username, user_text, reply)
                            return
                weather = await get_weather(user_city, lang)
                await update.message.reply_text(weather)
                await notify_admin(context, user_name, username, user_text, weather)
                return
            except Exception as we:
                logging.error("Погода ошибка: " + str(we))
        # Проверка таблеток из БД
        med_kw = ["пила ли я", "принимала ли", "выпила ли я", "таблетку сегодня", "пила сегодня", "принимала сегодня"]
        if any(k in user_text.lower() for k in med_kw):
            async with db_pool.acquire() as conn:
                meds_today = await conn.fetch("SELECT id, name, time_str FROM medications WHERE user_id = $1", user_id)
            if meds_today:
                lines_m = []
                async with db_pool.acquire() as conn:
                    for med in meds_today:
                        taken = await conn.fetchval("SELECT COUNT(*) FROM medication_logs WHERE med_id = $1 AND taken_at >= NOW() - INTERVAL '1 day'", med["id"])
                        lines_m.append(med["name"] + ": " + ("да, принимала" if taken > 0 else "нет, ещё не отмечено"))
                reply_m = "Таблетки сегодня:\n\n" + "\n".join(lines_m)
                await update.message.reply_text(reply_m)
                await notify_admin(context, user_name, username, user_text, reply_m)
                return

        # Нутрициология — текстовый ввод еды
        food_kw = ["съела", "съел", "поела", "поел", "покушала", "перекусила", "на завтрак", "на обед", "на ужин", "выпила", "выпил"]
        async with db_pool.acquire() as conn:
            has_nutr_txt = await conn.fetchrow("SELECT id FROM nutrition_profile WHERE user_id = $1", user_id)
        if has_nutr_txt and any(k in user_text.lower() for k in food_kw):
            try:
                food_prompt = "Пользователь написал о еде: " + user_text + "\n\nОпредели КБЖУ. Отвечай ТОЛЬКО в формате:\nБлюдо: название\nКалории: число\nБелки: число\nЖиры: число\nУглеводы: число\nКомментарий: совет"
                food_resp = ai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": food_prompt}], max_tokens=200, temperature=0.3)
                food_text_res = food_resp.choices[0].message.content
                if "Калории:" in food_text_res:
                    import re as _ref
                    cal_m = _ref.search(r"Калории:\s*(\d+)", food_text_res)
                    prot_m = _ref.search(r"Белки:\s*([\d.]+)", food_text_res)
                    fat_m = _ref.search(r"Жиры:\s*([\d.]+)", food_text_res)
                    carb_m = _ref.search(r"Углеводы:\s*([\d.]+)", food_text_res)
                    dish_m = _ref.search(r"Блюдо:\s*(.+)", food_text_res)
                    async with db_pool.acquire() as conn:
                        await conn.execute("INSERT INTO food_logs (user_id, description, calories, protein, fat, carbs) VALUES ($1, $2, $3, $4, $5, $6)", user_id, dish_m.group(1).strip() if dish_m else user_text[:50], int(cal_m.group(1)) if cal_m else 0, float(prot_m.group(1)) if prot_m else 0, float(fat_m.group(1)) if fat_m else 0, float(carb_m.group(1)) if carb_m else 0)
                    await update.message.reply_text(food_text_res + "\n\nЗаписала в журнал питания! 🥗\nЭто примерная оценка — точность зависит от размера порции.")
                    await notify_admin(context, user_name, username, user_text, food_text_res[:200])
                    return
            except Exception as fe:
                logging.error("Ошибка подсчёта еды: " + str(fe))

        # Регулярные занятия — предлагаем планер
        regular_kw = ["всегда", "каждый ", "каждую ", "каждое ", "регулярно", "постоянно",
                      "по понедельникам", "по вторникам", "по средам", "по четвергам",
                      "по пятницам", "по субботам", "по воскресеньям"]
        if any(k in user_text.lower() for k in regular_kw):
            context.user_data["pending_planner_text"] = user_text

        # Напоминания
        if is_reminder_request(user_text):
            tz = pytz.timezone(user["timezone"] or "Europe/Moscow")
            now = datetime.now(tz)
            essence = await rephrase_reminder(user_text, lang)
            rel_value, rel_unit = extract_relative_time(user_text)
            if rel_value is not None:
                remind_dt = now + (timedelta(minutes=rel_value) if rel_unit == 'minutes' else timedelta(hours=rel_value))
                job_name = f"once_{user_id}_{remind_dt.strftime('%H%M%S')}"
                context.application.job_queue.run_once(send_scheduled_reminder, when=remind_dt, data={"user_id": user_id, "essence": essence}, name=job_name)
                await add_reminder(user_id, remind_dt.strftime("%H:%M"), essence)
            else:
                hour, minute = extract_exact_time(user_text)
                if hour is not None:
                    time_str = f"{hour:02d}:{minute:02d}"
                    conflict = await check_conflict_db(user_id, time_str)
                    if conflict:
                        await update.message.reply_text(f"В {time_str} уже запланировано: «{conflict}». Выбрать другое время?" if ru else f"At {time_str} already scheduled: «{conflict}». Choose another time?")
                        return
                    job_name = f"reminder_{user_id}_{hour}_{minute}"
                    for job in context.application.job_queue.get_jobs_by_name(job_name):
                        job.schedule_removal()
                    tz2 = pytz.timezone(user["timezone"] or "Europe/Moscow")
                    context.application.job_queue.run_daily(send_scheduled_reminder, time=time(hour=hour, minute=minute, tzinfo=tz2), data={"user_id": user_id, "essence": essence}, name=job_name)
                    await add_reminder(user_id, time_str, essence)

        dt = get_current_datetime(user.get("timezone", "Europe/Moscow"))
        date_str = dt["ru"] if ru else dt["en"]
        comm_style = user.get("comm_style", "наставник" if ru else "mentor")
        system_prompt = SYSTEM_PROMPT_RU if ru else SYSTEM_PROMPT_EN
        memory_block = f"\n\nЧто я знаю об этом пользователе:\n{memory}" if memory else ""
        full_system = f"Сегодня: {date_str}\nСтиль общения: {comm_style}{memory_block}\n\n{system_prompt}" if ru else f"Today: {date_str}\nCommunication style: {comm_style}{memory_block}\n\n{system_prompt}"

        response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": full_system}] + history,
            max_tokens=1000, temperature=0.7
        )
        reply = response.choices[0].message.content
        await add_history(user_id, "assistant", reply)
        recipe_kw = ["ингредиент", "приготовлени", "рецепт", "ingredients", "recipe", "шаг 1", "step 1"]
        is_recipe_reply = any(k in reply.lower() for k in recipe_kw) and len(reply) > 300
        if is_recipe_reply:
            context.user_data["last_recipe_title"] = user_text[:50]
            context.user_data["last_recipe_content"] = reply
            save_q = "\n\nХотите сохранить этот рецепт в ваши любимые?" if ru else "\n\nWould you like to save this recipe?"
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("❤️ Сохранить", callback_data="save_recipe_yes"),
                InlineKeyboardButton("✖️ Не нужно", callback_data="dont_save_recipe"),
            ]])
            await update.message.reply_text(reply + save_q, reply_markup=kb)
        else:
            await update.message.reply_text(reply)
        await notify_admin(context, user_name, username, user_text, reply)
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await update.message.reply_text(t(lang, "error"))


async def analyze_food_photo(image_data):
    try:
        prompt = "Определи что на фото еды. Оцени порцию и дай КБЖУ.\nОтвечай ТОЛЬКО в формате:\nБлюдо: название\nПорция: примерно X г\nКалории: число\nБелки: число г\nЖиры: число г\nУглеводы: число г\nКомментарий: совет"
        response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image_data}}]}],
            max_tokens=250
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error("Ошибка анализа еды: " + str(e))
        return None

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    if not user or not user["onboarded"]:
        await update.message.reply_text(t("ru", "not_started"))
        return
    lang = user.get("language", "ru")
    ru = lang == "ru"
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name
        await file.download_to_drive(tmp_path)
        with open(tmp_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")
        os.unlink(tmp_path)
        caption = update.message.caption or ""
        user_name = update.effective_user.first_name or "Пользователь"
        username = update.effective_user.username or "нет username"
        async with db_pool.acquire() as conn:
            has_nutr = await conn.fetchrow("SELECT id FROM nutrition_profile WHERE user_id = $1", user_id)
        if has_nutr and not caption:
            context.user_data["pending_food_photo"] = image_data
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("🍽 Да, посчитай калории", callback_data="count_food_calories"),
                InlineKeyboardButton("🖼 Нет, просто опиши", callback_data="just_describe_photo"),
            ]])
            await update.message.reply_text("Это фото еды? Посчитать калории и записать в журнал?", reply_markup=kb)
            return
        if has_nutr and caption:
            food_res = await analyze_food_photo(image_data)
            if food_res and "Калории:" in food_res:
                import re as _rff
                cal_m = _rff.search(r"Калории:\s*(\d+)", food_res)
                prot_m = _rff.search(r"Белки:\s*([\d.]+)", food_res)
                fat_m = _rff.search(r"Жиры:\s*([\d.]+)", food_res)
                carb_m = _rff.search(r"Углеводы:\s*([\d.]+)", food_res)
                dish_m = _rff.search(r"Блюдо:\s*(.+)", food_res)
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO food_logs (user_id, description, calories, protein, fat, carbs) VALUES ($1, $2, $3, $4, $5, $6)",
                        user_id,
                        dish_m.group(1).strip() if dish_m else caption,
                        int(cal_m.group(1)) if cal_m else 0,
                        float(prot_m.group(1)) if prot_m else 0,
                        float(fat_m.group(1)) if fat_m else 0,
                        float(carb_m.group(1)) if carb_m else 0
                    )
                await update.message.reply_text(food_res + "\n\nЗаписала в журнал! 🥗\nДля точности укажите граммы в подписи к фото.")
                await notify_admin(context, user_name, username, "[Фото еды] " + caption, food_res[:200])
                return
        reply = await analyze_image(image_data, caption, lang)
        await update.message.reply_text(reply)
        await notify_admin(context, user_name, username, "[Фото]" + (" " + caption if caption else ""), reply)
    except Exception as e:
        logging.error(f"Ошибка фото: {e}")
        await update.message.reply_text("Не удалось проанализировать фото." if ru else "Could not analyze the photo.")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    if not user or not user["onboarded"]:
        await update.message.reply_text(t("ru", "not_started"))
        return
    lang = user.get("language", "ru")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name
        await file.download_to_drive(tmp_path)
        user_text = await transcribe_voice(tmp_path)
        os.unlink(tmp_path)
        if not user_text:
            await update.message.reply_text("Не смогла распознать голосовое. Попробуйте ещё раз." if lang == "ru" else "Could not recognize voice. Please try again.")
            return
        await process_text_message(update, context, user_text)
    except Exception as e:
        logging.error(f"Ошибка голосового: {e}")
        import traceback
        logging.error(traceback.format_exc())
        await update.message.reply_text("Не удалось обработать голосовое. Попробуйте текстом." if lang == "ru" else "Could not process voice. Try typing instead.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_text_message(update, context, update.message.text)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Нет доступа.")
        return
    async with db_pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM users WHERE onboarded = TRUE")
        today = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM history WHERE created_at >= NOW() - INTERVAL '1 day'")
        week = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM history WHERE created_at >= NOW() - INTERVAL '7 days'")
        total_msg = await conn.fetchval("SELECT COUNT(*) FROM history WHERE role = 'user'")
        ru_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE language = 'ru' AND onboarded = TRUE")
        en_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE language = 'en' AND onboarded = TRUE")
    await update.message.reply_text(
        f"София — статистика\n\nВсего: {total}\nРусский: {ru_users}\nEnglish: {en_users}\nАктивны сегодня: {today}\nЗа 7 дней: {week}\nВсего сообщений: {total_msg}"
    )


async def check_cycle_reminders(context: ContextTypes.DEFAULT_TYPE):
    try:
        async with db_pool.acquire() as conn:
            users = await conn.fetch("SELECT user_id FROM users WHERE onboarded = TRUE")
        from datetime import date as _dc, timedelta as _tdc
        today = _dc.today()
        for ur in users:
            uid = ur["user_id"]
            try:
                async with db_pool.acquire() as conn:
                    last = await conn.fetchrow("SELECT start_date, cycle_length FROM cycle_tracking WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1", uid)
                if not last or not last["start_date"]:
                    continue
                start = last["start_date"]
                length = last["cycle_length"] or 28
                next_start = start
                while (next_start - today).days <= 0:
                    next_start = next_start + _tdc(days=length)
                days_left = (next_start - today).days
                if days_left in [3, 1]:
                    user = await get_user(uid)
                    name = user["name"] if user else ""
                    days_word = "день" if days_left == 1 else "дня"
                    msg = name + ", через " + str(days_left) + " " + days_word + " ожидается начало цикла. Подготовьтесь заранее! 🩸"
                    await context.application.bot.send_message(chat_id=uid, text=msg)
            except:
                pass
    except Exception as e:
        logging.error("Ошибка cycle_check: " + str(e))


async def check_goal_reminders(context: ContextTypes.DEFAULT_TYPE):
    try:
        async with db_pool.acquire() as conn:
            users = await conn.fetch("SELECT user_id FROM users WHERE onboarded = TRUE")
        import random as _rg
        from datetime import date as _dg
        today = _dg.today()
        for ur in users:
            uid = ur["user_id"]
            try:
                async with db_pool.acquire() as conn:
                    goals = await conn.fetch("SELECT id, title, progress FROM goals WHERE user_id = $1 AND progress < 100", uid)
                if not goals:
                    continue
                async with db_pool.acquire() as conn:
                    last_msg = await conn.fetchval("SELECT created_at FROM history WHERE user_id = $1 AND role = 'assistant' ORDER BY created_at DESC LIMIT 1", uid)
                if last_msg and (today - last_msg.date()).days < 3:
                    continue
                user = await get_user(uid)
                name = user["name"] if user else ""
                goal = _rg.choice(list(goals))
                variants = [
                    name + ", как дела с целью \"" + goal["title"] + "\"? 🎯 Расскажите что удалось сделать!",
                    "Привет, " + name + "! Есть ли прогресс по цели \"" + goal["title"] + "\"? 🌸",
                    name + ", помните про цель \"" + goal["title"] + "\"? Прогресс " + str(goal["progress"]) + "%. Что нового? 💪",
                ]
                await context.application.bot.send_message(chat_id=uid, text=_rg.choice(variants))
            except:
                pass
    except Exception as e:
        logging.error("Ошибка goal_check: " + str(e))

async def post_init(application):
    await init_db()
    await restore_reminders(application)
    application.job_queue.run_daily(check_cycle_reminders, time=time(hour=9, minute=0), name="cycle_check")
    application.job_queue.run_daily(check_goal_reminders, time=time(hour=12, minute=0), name="goal_check")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_city)],
            ASK_LANGUAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_language)],
            ASK_MORNING_PLAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_morning_plan)],
            ASK_MORNING_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_morning_time)],
            ASK_REMINDERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, finish_onboarding)],
            ASK_EVENING_NEWS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_evening_news_answer)],
            ASK_EVENING_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_evening_time)],
            ASK_COMM_STYLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_comm_style)],
        },
        fallbacks=[CommandHandler("start", start)]
    )
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("menu", show_menu))
    app.add_handler(CommandHandler("skills", skills_command))
    app.add_handler(CommandHandler("announce", announce))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🌸 София v5.0 запущена!")
    app.run_polling()
