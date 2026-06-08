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
        "ask_evening_news": "Хотите получать вечернюю сводку новостей — главные события дня и полезные советы на вечер?",
        "ask_evening_time": "В какое время присылать вечернюю сводку новостей?",
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

ФОРМАТИРОВАНИЕ:
Пиши как живой человек в мессенджере. Никаких # заголовков. Никаких --- разделителей. Никаких маркеров * или - в начале строк. Жирный (*слово*) только для самого важного, редко. Курсив (_слово_) иногда. Эмодзи умеренно. Короткие абзацы. Один вопрос за раз.

ДАТА И ВРЕМЯ:
Текущая дата и время указаны в начале сообщения. Ты ВСЕГДА знаешь дату и время. Никогда не говори что не знаешь.

ПАМЯТЬ:
Помнишь всё что пользователь говорил. Используй естественно. Никогда не говори "я не помню".

О СОЗДАТЕЛЕ — дозированно:
"кто создал" → "Меня создала Ирина Солодкова 🌸"
"расскажи больше" → "Ирине 17 лет, она из Волгограда, сейчас живёт и учится в Дубае. Увлекается ИИ и бизнесом."
"контакты" → "irinasa_00@mail.ru"

ЧТО УМЕЕШЬ: планирование, напоминания, поддержка, нутрициология, цели, любые вопросы.

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

async def fetch_articles(query, count=10):
    if not NEWS_API_KEY:
        return []
    try:
        params = {"apiKey": NEWS_API_KEY, "q": query, "language": "en", "pageSize": count, "sortBy": "publishedAt"}
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
        news = await get_news(lang=lang)
        news_block = f"\n\nСвежие новости:\n{news}" if news else ""
        prompt = f"Составь короткую вечернюю сводку для {name}. Сегодня {dt['ru']}.{news_block}\n\nВключи: тёплое приветствие, пару полезных советов на вечер, мотивирующее завершение. По-человечески, 3-4 абзаца, без форматирования." if lang == "ru" else f"Create a short evening summary for {name}. Today is {dt['en']}.{news_block}\n\nInclude: warm greeting, evening tips, motivating end. Natural, 3-4 paragraphs."
        response = ai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], max_tokens=500, temperature=0.8)
        await context.bot.send_message(chat_id=user_id, text=response.choices[0].message.content)
    except Exception as e:
        logging.error(f"Ошибка вечерней сводки: {e}")

def get_main_menu(lang="ru"):
    ru = lang == "ru"
    keyboard = [
        [InlineKeyboardButton("🌅 Утро" if ru else "🌅 Morning", callback_data="menu_morning")],
        [InlineKeyboardButton("📒 Дневник" if ru else "📒 Diary", callback_data="menu_diary")],
        [InlineKeyboardButton("✨ Интересное" if ru else "✨ Interesting", callback_data="menu_interesting")],
        [InlineKeyboardButton("⚙️ Настройки" if ru else "⚙️ Settings", callback_data="menu_settings")],
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
        articles = await fetch_articles(cat_info.get("query", "interesting news"), 10)
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
            [InlineKeyboardButton("💰 Финансы" if ru else "💰 Finances", callback_data="diary_finances"), InlineKeyboardButton("😴 Сон" if ru else "😴 Sleep", callback_data="diary_sleep")],
            [InlineKeyboardButton("📝 Заметки" if ru else "📝 Notes", callback_data="diary_notes"), InlineKeyboardButton("🍳 Рецепты" if ru else "🍳 Recipes", callback_data="diary_recipe")],
            [InlineKeyboardButton("🎬 Что посмотреть" if ru else "🎬 What to watch", callback_data="diary_movie")],
            [InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="back_main")],
        ]
        await query.edit_message_text("Дневник — выберите раздел:" if ru else "Diary — choose a section:", reply_markup=InlineKeyboardMarkup(keyboard))

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
        await query.edit_message_text("Подбираю рецепт..." if ru else "Finding a recipe...")
        recipe = await get_ai_recipe(lang)
        keyboard = [[InlineKeyboardButton("🔄 Другой" if ru else "🔄 Another", callback_data="diary_recipe")], [InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_diary")]]
        await query.edit_message_text(f"Рецепт дня:\n\n{recipe}" if ru else f"Recipe of the day:\n\n{recipe}", reply_markup=InlineKeyboardMarkup(keyboard))

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
            for tbl in ["history", "reminders", "notes", "habits", "habit_logs", "finances", "user_memory", "sleep_logs", "shopping_list"]:
                await conn.execute(f"DELETE FROM {tbl} WHERE user_id = $1", user_id)
            await conn.execute("UPDATE users SET onboarded = FALSE, name = NULL WHERE user_id = $1", user_id)
        await query.edit_message_text(t(lang, "memory_cleared"))

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
        if ru:
            keyboard = [
                [InlineKeyboardButton(f"{mw} Погода утром", callback_data="toggle_morning_weather")],
                [InlineKeyboardButton(f"{mm} Мотивация утром", callback_data="toggle_morning_motivation")],
                [InlineKeyboardButton(f"{w} Напоминания о воде", callback_data="water_toggle")],
                [InlineKeyboardButton(f"{ev} Вечерняя сводка", callback_data="toggle_evening_news")],
                [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
            ]
        else:
            keyboard = [
                [InlineKeyboardButton(f"{mw} Weather in morning", callback_data="toggle_morning_weather")],
                [InlineKeyboardButton(f"{mm} Motivation in morning", callback_data="toggle_morning_motivation")],
                [InlineKeyboardButton(f"{w} Water reminders", callback_data="water_toggle")],
                [InlineKeyboardButton(f"{ev} Evening summary", callback_data="toggle_evening_news")],
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
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            # Определяем хочет ли завтрашнюю погоду
            if "завтра" in user_text.lower() or "tomorrow" in user_text.lower():
                forecast = await get_weather_forecast(city, lang)
                if forecast:
                    lines = forecast.split("\n\n")[1].split("\n") if "\n\n" in forecast else []
                    tomorrow = lines[1] if len(lines) > 1 else ""
                    if tomorrow:
                        reply = f"Завтра в {city_in_form(city) if lang == 'ru' else city}: {tomorrow}" if lang == "ru" else f"Tomorrow in {city}: {tomorrow}"
                        await update.message.reply_text(reply)
                        await notify_admin(context, user_name, username, user_text, reply)
                        return
            weather = await get_weather(city, lang)
            await update.message.reply_text(weather)
            await notify_admin(context, user_name, username, user_text, weather)
            return

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
        await update.message.reply_text(reply)
        await notify_admin(context, user_name, username, user_text, reply)
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await update.message.reply_text(t(lang, "error"))

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
        reply = await analyze_image(image_data, caption, lang)
        await update.message.reply_text(reply)
        user_name = update.effective_user.first_name or "Пользователь"
        username = update.effective_user.username or "нет username"
        await notify_admin(context, user_name, username, f"[Фото]{' ' + caption if caption else ''}", reply)
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

async def post_init(application):
    await init_db()

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
