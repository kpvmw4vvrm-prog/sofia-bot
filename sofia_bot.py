import logging
import re
import os
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
ADMIN_ID = 944447597
DATABASE_URL = os.environ.get("DATABASE_URL")

logging.basicConfig(level=logging.INFO)
client = OpenAI(api_key=OPENAI_API_KEY, base_url="https://api.aitunnel.ru/v1/")
aai.settings.api_key = ASSEMBLYAI_KEY
tf = TimezoneFinder()

ASK_NAME, ASK_CITY, ASK_LANGUAGE, ASK_MORNING_PLAN, ASK_MORNING_TIME, ASK_REMINDERS, ASK_EVENING_NEWS, ASK_EVENING_TIME, ASK_COMM_STYLE = range(9)

MOTIVATIONAL_QUOTES = {
    "ru": [
        "Каждый день — это новая возможность стать лучше. 🌟",
        "Маленькие шаги каждый день приводят к большим результатам. 💪",
        "Вы способны на большее, чем думаете. 🚀",
        "Успех — это сумма небольших усилий, повторяемых день за днём. ✨",
        "Верьте в себя и всё станет возможным. 🌸",
        "Сегодня — лучший день чтобы начать. 🌅",
        "Ваши мечты заслуживают вашего труда. 💫",
        "Каждая трудность — это возможность для роста. 🌱",
        "Действуйте сейчас, совершенствуйтесь потом. ⚡",
        "Вы сильнее, чем вы думаете. 🦋",
    ],
    "en": [
        "Every day is a new opportunity to be better. 🌟",
        "Small steps every day lead to big results. 💪",
        "You are capable of more than you think. 🚀",
        "Success is the sum of small efforts repeated day after day. ✨",
        "Believe in yourself and everything becomes possible. 🌸",
        "Today is the best day to start. 🌅",
        "Your dreams deserve your effort. 💫",
        "Every challenge is an opportunity to grow. 🌱",
        "Act now, improve later. ⚡",
        "You are stronger than you think. 🦋",
    ]
}

TEXTS = {
    "ru": {
        "welcome": "Добрый день!\n\nРада познакомиться! Я София — ваш личный ассистент. Помогу с планами, целями и важными делами.\n\nДавайте начнём — как вас зовут?",
        "ask_city": "Очень приятно, {name}! 😊\n\nВ каком городе вы находитесь?\n\nНапример: Москва, Алматы, Дубай",
        "ask_language": "Отлично, запомнила — {city} 🌍\n\nНа каком языке вам удобнее общаться?",
        "ask_morning": "Хотите чтобы я каждое утро присылала план дня? 📋",
        "ask_morning_time": "В какое время присылать утренний план? ☀️",
        "ask_reminders": "Напоминать о делах заранее?",
        "ask_evening_news": "Хотите получать вечернюю сводку — краткий итог дня и полезные советы? 🌙",
        "ask_evening_time": "В какое время присылать вечернюю сводку? 🌙",
        "finish": "Всё готово, {name}! 🌸\n\nЯ запомнила ваши настройки. Напишите /menu чтобы открыть меню.",
        "menu_title": "🌸 Меню Софии\n\nЗдравствуйте, {name}! Чем могу помочь?",
        "not_started": "Напишите /start чтобы начать 🌸",
        "error": "Что-то пошло не так, попробуйте ещё раз через секунду.",
        "water": "💧 {name}, самое время выпить стакан воды!",
        "reminder": "⏰ {name}, напоминаю!\n\n{text}",
        "morning": "Доброе утро, {name}! ☀️\n\n",
        "no_plan": "На сегодня задачи не добавлены. Напишите мне что планируете — составлю расписание.",
        "ask_comm_style": "Как вам удобнее общаться со мной? 🌸",
        "comm_style_set": "Отлично, запомнила! Буду общаться именно так 🌸",
        "lang_changed": "Язык изменён на русский 🇷🇺",
        "memory_cleared": "Я всё забыла о вас. Можем начать с чистого листа — напишите /start 🌸",
    },
    "en": {
        "welcome": "Good day!\n\nNice to meet you! I'm Sofia — your personal assistant. I'll help with plans, goals and important tasks.\n\nLet's start — what's your name?",
        "ask_city": "Nice to meet you, {name}! 😊\n\nWhat city are you in?\n\nFor example: London, New York, Dubai",
        "ask_language": "Got it — {city} 🌍\n\nWhat language would you prefer?",
        "ask_morning": "Would you like me to send you a daily plan every morning? 📋",
        "ask_morning_time": "What time should I send the morning plan? ☀️",
        "ask_reminders": "Remind you about tasks in advance?",
        "ask_evening_news": "Would you like to receive an evening summary — a brief recap of the day and useful tips? 🌙",
        "ask_evening_time": "What time should I send the evening summary? 🌙",
        "finish": "All done, {name}! 🌸\n\nI've saved your settings. Type /menu to open the menu.",
        "menu_title": "🌸 Sofia's Menu\n\nHello, {name}! How can I help?",
        "not_started": "Type /start to begin 🌸",
        "error": "Something went wrong, please try again in a moment.",
        "water": "💧 {name}, time to drink a glass of water!",
        "reminder": "⏰ {name}, reminder!\n\n{text}",
        "morning": "Good morning, {name}! ☀️\n\n",
        "no_plan": "No tasks added for today. Tell me what you're planning — I'll create a schedule.",
        "history_cleared": "Done, history cleared 🌸",
        "lang_changed": "Language changed to English 🇬🇧",
        "memory_cleared": "I've forgotten everything about you. We can start fresh — type /start 🌸",
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
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M"),
            "weekday": now.weekday(),
        }
    except:
        return {"ru": "", "en": "", "date": "", "time": "", "weekday": 0}

SYSTEM_PROMPT_RU = """Ты — София, личный ассистент и наставник. 

СТИЛЬ ОБЩЕНИЯ:
Используй стиль который указан в профиле пользователя (comm_style). Варианты:
— подружка: тепло, неформально, на ты, с юмором
— наставник: мотивирующий, поддерживающий, на вы, вдохновляющий  
— профессионал: чётко, по делу, без лишнего, на вы
— свой стиль: адаптируйся под то как пишет пользователь
Если стиль не указан — общайся как наставник на вы.

ФОРМАТИРОВАНИЕ (очень важно):
— Никаких # заголовков, никаких --- разделителей
— Никаких маркеров списка * или - в начале строк  
— Жирный текст (*текст*) используй редко — только для самого важного слова или фразы
— Курсив (_текст_) для мягкого акцента — иногда
— Пиши живыми абзацами как в обычной переписке
— Эмодзи умеренно, только где уместно
— Один вопрос за раз
— Короткие абзацы, воздух между ними

ПАМЯТЬ:
— Текущая дата и время указаны в начале каждого сообщения — ты всегда знаешь который час и какое число
— Помнишь всё что пользователь говорил — имена детей, партнёра, цели, предпочтения, важные даты
— Никогда не говоришь "я не помню" если информация была в разговоре
— Используешь личную информацию естественно — не перечисляешь её, а применяешь в ответах

О СЕБЕ И СОЗДАТЕЛЕ:
Ты — София, AI-ассистент. Отвечай о создателе дозированно — только то что спросили:
— Если спросили просто "кто тебя создал" → "Меня создала Ирина Солодкова 🌸"
— Если спросили больше (откуда, чем занимается) → добавь: "Ирине 17 лет, она из Волгограда, сейчас живёт и учится в Дубае. Увлекается искусственным интеллектом и бизнесом."
— Если спросили контакты → "По вопросам и предложениям можно написать на irinasa_00@mail.ru"
— Никогда не рассказывай всё сразу — только то что спросили
— Вопросы типа "кто твой автор", "кто тебя сделал", "чья ты", "кто за тобой стоит" — всё это про Ирину

ЧТО УМЕЕШЬ:
1. Планирование — план на день, неделю, месяц
2. Напоминания — устанавливаешь и присылаешь вовремя
3. Психологическая поддержка — выслушаешь и поможешь
4. Нутрициолог — советы по питанию и здоровью
5. Цели — ведёшь к достижению шаг за шагом
6. Любые вопросы — отвечаешь развёрнуто и по делу

Формат плана дня (только когда просят):
09:00 — задача
10:00 — задача
"""

SYSTEM_PROMPT_EN = """You are Sofia, a personal assistant and mentor.

COMMUNICATION STYLE:
Use the style specified in the user's profile (comm_style):
— friend: warm, informal, casual, with humor
— mentor: motivating, supportive, inspiring
— professional: clear, to the point, formal
— custom: adapt to how the user writes
If no style specified — communicate as a mentor.

FORMATTING (very important):
— No # headers, no --- separators
— No list markers * or - at the start of lines
— Bold (*text*) rarely — only for the most important word or phrase
— Italics (_text_) for soft emphasis — occasionally
— Write in natural paragraphs like a real conversation
— Emojis in moderation, only where appropriate
— One question at a time
— Short paragraphs with breathing room

MEMORY:
— Current date and time are provided at the start of each message — you always know the time and date
— Remember everything the user said — children's names, partner, goals, preferences, important dates
— Never say "I don't remember" if the information was in the conversation
— Use personal information naturally — don't list it, apply it in responses

ABOUT YOURSELF AND CREATOR:
You are Sofia, an AI assistant. Answer about the creator gradually — only what was asked:
— If asked simply "who created you" → "I was created by Irina Solodkova 🌸"
— If asked more (where from, what she does) → add: "Irina is 17, she's from Volgograd and currently lives and studies in Dubai. She's passionate about artificial intelligence and business."
— If asked for contact → "For questions and suggestions you can write to irinasa_00@mail.ru"
— Never share everything at once — only what was asked
— Questions like "who made you", "who's your author", "who's behind you" — all about Irina

WHAT YOU CAN DO:
1. Planning — plans for day, week, month
2. Reminders — set and send on time
3. Psychological support — listen and help
4. Nutritionist — nutrition and health advice
5. Goals — guide step by step to achieve any goal
6. Any questions — answer thoroughly and to the point

Day plan format (only when asked):
09:00 — task
10:00 — task
"""






SKILLS_RU = """Вот что я умею 🌸

Обучаюсь под вас — запоминаю ваши предпочтения, привычки и цели. Со временем знаю вас всё лучше.

Планирование — составлю план на день, неделю или месяц. Помогу расставить приоритеты.

Голосовые сообщения — говорите вслух, я пойму и отвечу.

Два языка — русский и английский, переключайтесь в любой момент 🇷🇺 🇬🇧

Умные напоминания — напомню за нужное время до события.

Утренний план — каждое утро план дел, погода и мотивация.

Трекер привычек — отмечайте прогресс и следите за статистикой.

Трекер сна — рассчитаю идеальное время отхода ко сну.

Контроль финансов — записывайте доходы и расходы.

Заметки — сохраняю ваши идеи мгновенно.

Рецепты — новая идея что приготовить каждый день.

Что посмотреть — персональная рекомендация фильма.

Психологическая поддержка — выслушаю и помогу в любой ситуации.

Личный нутрициолог — советы по питанию и здоровью.

Напоминания о воде — забочусь о вашем здоровье.

Напишите /menu чтобы открыть меню 🌸"""

SKILLS_EN = """Here's what I can do 🌸

I learn from you — I remember your preferences, habits and goals. Over time I know you better and better.

Planning — I'll create a plan for the day, week or month. Help you prioritize.

Voice messages — speak out loud, I'll understand and respond.

Two languages — Russian and English, switch anytime 🇷🇺 🇬🇧

Smart reminders — I'll remind you at the right time before any event.

Morning plan — every morning tasks, weather and motivation.

Habit tracker — track progress and monitor statistics.

Sleep tracker — I'll calculate the ideal bedtime for you.

Finance control — record income and expenses.

Notes — I save your ideas instantly.

Recipes — a new cooking idea every day.

What to watch — personal movie recommendation.

Psychological support — I'll listen and help in any situation.

Personal nutritionist — nutrition and healthy lifestyle advice.

Water reminders — I take care of your health.

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
                evening_time TEXT DEFAULT '21:00'
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                time_str TEXT,
                text TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                role TEXT,
                content TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS habits (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                name TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS habit_logs (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                habit_id INTEGER,
                logged_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS finances (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                amount FLOAT,
                type TEXT,
                category TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sleep_logs (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                bedtime TEXT,
                wake_time TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                text TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_memory (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                key TEXT,
                value TEXT,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        for col, definition in [
            ("city", "TEXT DEFAULT 'Москва'"),
            ("water_reminders", "BOOLEAN DEFAULT FALSE"),
            ("water_interval", "INTEGER DEFAULT 2"),
            ("morning_weather", "BOOLEAN DEFAULT FALSE"),
            ("morning_motivation", "BOOLEAN DEFAULT FALSE"),
            ("language", "TEXT DEFAULT 'ru'"),
            ("evening_news", "BOOLEAN DEFAULT FALSE"),
            ("evening_time", "TEXT DEFAULT '21:00'"),
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
        rows = await conn.fetch("SELECT key, value FROM user_memory WHERE user_id = $1", user_id)
        if not rows:
            return ""
        lines = [f"{r['key']}: {r['value']}" for r in rows]
        return "\n".join(lines)

async def save_memory_item(user_id, key, value):
    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT id FROM user_memory WHERE user_id = $1 AND key = $2", user_id, key)
        if existing:
            await conn.execute("UPDATE user_memory SET value = $1, updated_at = NOW() WHERE user_id = $2 AND key = $3", value, user_id, key)
        else:
            await conn.execute("INSERT INTO user_memory (user_id, key, value) VALUES ($1, $2, $3)", user_id, key, value)

async def extract_and_save_memory(user_id, user_text, lang):
    try:
        system = """Ты анализируешь сообщение пользователя и извлекаешь важную личную информацию для запоминания.
Извлекай ТОЛЬКО конкретные факты: имена (своё, детей, партнёра), город, работу, цели, предпочтения, важные даты, здоровье.
Отвечай ТОЛЬКО в формате JSON: {"key": "value", "key2": "value2"}
Если нечего запомнить — отвечай: {}
Примеры ключей: имя_ребёнка, город, работа, цель, день_рождения, предпочтения_еда, партнёр""" if lang == "ru" else """You analyze the user's message and extract important personal information to remember.
Extract ONLY specific facts: names (own, children, partner), city, work, goals, preferences, important dates, health.
Reply ONLY in JSON format: {"key": "value", "key2": "value2"}
If nothing to remember — reply: {}"""
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user_text}],
            max_tokens=200, temperature=0.1
        )
        result = response.choices[0].message.content.strip()
        result = result.replace("```json", "").replace("```", "").strip()
        import json
        data = json.loads(result)
        for key, value in data.items():
            if value and str(value) != "{}":
                await save_memory_item(user_id, key, str(value))
    except:
        pass

async def get_history_db(user_id, limit=30):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT role, content FROM history WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
            user_id, limit
        )
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

async def add_history(user_id, role, content):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO history (user_id, role, content) VALUES ($1, $2, $3)",
            user_id, role, content
        )
        await conn.execute("""
            DELETE FROM history WHERE id IN (
                SELECT id FROM history WHERE user_id = $1
                ORDER BY created_at DESC OFFSET 30
            )
        """, user_id)

async def get_reminders(user_id):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT time_str, text FROM reminders WHERE user_id = $1", user_id)
        return [{"time": r["time_str"], "text": r["text"]} for r in rows]

async def add_reminder(user_id, time_str, text):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO reminders (user_id, time_str, text) VALUES ($1, $2, $3)",
            user_id, time_str, text
        )

async def check_conflict_db(user_id, time_str):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT text FROM reminders WHERE user_id = $1 AND time_str = $2",
            user_id, time_str
        )
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
        logging.error(f"Ошибка дублирования: {e}")

async def get_timezone_by_city(city):
    try:
        async with httpx.AsyncClient(timeout=10) as client_http:
            response = await client_http.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"q": city, "appid": WEATHER_API_KEY}
            )
        data = response.json()
        if data.get("cod") != 200:
            return "Europe/Moscow"
        lat = data["coord"]["lat"]
        lon = data["coord"]["lon"]
        timezone = tf.timezone_at(lat=lat, lng=lon)
        return timezone or "Europe/Moscow"
    except:
        return "Europe/Moscow"

async def get_weather(city, lang="ru"):
    try:
        async with httpx.AsyncClient(timeout=10) as client_http:
            response = await client_http.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"q": city, "appid": WEATHER_API_KEY, "units": "metric", "lang": lang}
            )
        data = response.json()
        if data.get("cod") != 200:
            return f"Не удалось получить погоду для {city}." if lang == "ru" else f"Could not get weather for {city}."
        temp = round(data["main"]["temp"])
        feels = round(data["main"]["feels_like"])
        desc = data["weather"][0]["description"]
        humidity = data["main"]["humidity"]
        wind = data["wind"]["speed"]
        if lang == "en":
            advice = "🧥 Dress warmly!" if temp < 0 else "🧣 Take a jacket." if temp < 10 else "👕 Light jacket will do." if temp < 18 else "☀️ Perfect weather!"
            if "rain" in desc:
                advice += " ☂️ Take an umbrella!"
            return f"Weather in {city}:\n\n🌡 {temp}°C (feels like {feels}°C)\n{desc.capitalize()}\nHumidity: {humidity}%\nWind: {wind} m/s\n\n{advice}"
        else:
            advice = "🧥 Оденьтесь тепло!" if temp < 0 else "🧣 Возьмите куртку." if temp < 10 else "👕 Лёгкая куртка в самый раз." if temp < 18 else "☀️ Отличная погода!"
            if "дождь" in desc or "ливень" in desc:
                advice += " ☂️ Возьмите зонт!"
            return f"Погода в {city}:\n\n🌡 {temp}°C (ощущается как {feels}°C)\n{desc.capitalize()}\nВлажность: {humidity}%\nВетер: {wind} м/с\n\n{advice}"
    except Exception as e:
        logging.error(f"Ошибка погоды: {e}")
        return "Погода недоступна." if lang == "ru" else "Weather unavailable."

async def get_weather_forecast(city, lang="ru"):
    try:
        async with httpx.AsyncClient(timeout=10) as client_http:
            response = await client_http.get(
                "https://api.openweathermap.org/data/2.5/forecast",
                params={"q": city, "appid": WEATHER_API_KEY, "units": "metric", "lang": lang, "cnt": 24}
            )
        data = response.json()
        if data.get("cod") != "200":
            return None
        days = {}
        for item in data["list"]:
            date = item["dt_txt"][:10]
            if date not in days:
                days[date] = {"temps": [], "desc": item["weather"][0]["description"]}
            days[date]["temps"].append(item["main"]["temp"])
        result = []
        for date, info in list(days.items())[:5]:
            min_t = round(min(info["temps"]))
            max_t = round(max(info["temps"]))
            result.append(f"{date}: {min_t}°C — {max_t}°C, {info['desc']}")
        return "\n".join(result)
    except:
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
        prompt = "Suggest one simple recipe. Name, ingredients and brief method. Be concise and conversational." if lang == "en" else "Предложи один простой рецепт. Название, ингредиенты и краткий способ приготовления. Пиши коротко и по-человечески."
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": "Recipe please" if lang == "en" else "Предложи рецепт"}],
            max_tokens=400, temperature=0.9
        )
        return response.choices[0].message.content
    except:
        return "Рецепт недоступен." if lang == "ru" else "Recipe unavailable."

async def get_ai_movie(lang="ru"):
    try:
        prompt = "Recommend one movie or series. Title, genre, brief description and why to watch it. Be conversational." if lang == "en" else "Посоветуй один фильм или сериал. Название, жанр, краткое описание и почему стоит посмотреть. Пиши по-человечески."
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": "Recommend something" if lang == "en" else "Что посмотреть?"}],
            max_tokens=250, temperature=0.9
        )
        return response.choices[0].message.content
    except:
        return "Рекомендация недоступна." if lang == "ru" else "Recommendation unavailable."

async def rephrase_reminder(text, lang="ru"):
    try:
        system = "Rephrase as a reminder from assistant — brief, no 'me', no 'remind', no time. Just essence. Reply with only the text." if lang == "en" else "Перефразируй как напоминание от ассистента — коротко, без 'мне', без 'напомни', без времени. Только суть. Отвечай только текстом."
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
            max_tokens=100, temperature=0.3
        )
        result = response.choices[0].message.content.strip()
        return result[0].upper() + result[1:] if result else text
    except:
        return text

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
    time_match = re.search(r'(\d{1,2})[:\.](\d{2})', text)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    return None, None

def extract_relative_time(text):
    match = re.search(r'через\s+(\d+)\s*(минут|мин|минуты|минуту)|in\s+(\d+)\s*(minutes|mins|minute)', text, re.IGNORECASE)
    if match:
        val = int(match.group(1) or match.group(3))
        return val, 'minutes'
    match = re.search(r'через\s+(\d+)\s*(час|часа|часов)|in\s+(\d+)\s*(hours|hour)', text, re.IGNORECASE)
    if match:
        val = int(match.group(1) or match.group(3))
        return val, 'hours'
    return None, None

def is_reminder_request(text):
    keywords_ru = ["напомни", "напоминание", "пришли", "отправь"]
    keywords_en = ["remind", "reminder", "send me"]
    has_time = re.search(r'\d{1,2}[:.]\d{2}', text) or re.search(r'через\s+\d+|in\s+\d+', text, re.IGNORECASE)
    return has_time and (any(k in text.lower() for k in keywords_ru) or any(k in text.lower() for k in keywords_en))

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
        quote = random.choice(MOTIVATIONAL_QUOTES[lang])
        text += f"{quote}\n\n"
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
        prompt = f"Составь короткую вечернюю сводку для {name}. Сегодня {dt['ru']}. Включи: 1) тёплое приветствие, 2) пару полезных советов на вечер (сон, отдых, здоровье), 3) мотивирующее завершение дня. Пиши по-человечески, без лишнего форматирования. 3-4 абзаца." if lang == "ru" else f"Create a short evening summary for {name}. Today is {dt['en']}. Include: 1) warm greeting, 2) a couple of useful evening tips (sleep, rest, health), 3) motivating end of day. Write naturally, no excessive formatting. 3-4 paragraphs."
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400, temperature=0.8
        )
        text = response.choices[0].message.content
        await context.bot.send_message(chat_id=user_id, text=text)
    except Exception as e:
        logging.error(f"Ошибка вечерней сводки: {e}")

def get_main_menu(lang="ru"):
    if lang == "en":
        keyboard = [
            [InlineKeyboardButton("🌅 Morning", callback_data="menu_morning"),
             InlineKeyboardButton("💪 Habits", callback_data="menu_habits")],
            [InlineKeyboardButton("💧 Water", callback_data="menu_water"),
             InlineKeyboardButton("📒 Diary", callback_data="menu_diary")],
            [InlineKeyboardButton("👤 Profile", callback_data="menu_profile"),
             InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings")],
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("🌅 Утро", callback_data="menu_morning"),
             InlineKeyboardButton("💪 Привычки", callback_data="menu_habits")],
            [InlineKeyboardButton("💧 Вода", callback_data="menu_water"),
             InlineKeyboardButton("📒 Дневник", callback_data="menu_diary")],
            [InlineKeyboardButton("👤 Профиль", callback_data="menu_profile"),
             InlineKeyboardButton("⚙️ Настройки", callback_data="menu_settings")],
        ]
    return InlineKeyboardMarkup(keyboard)

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    if not user or not user["onboarded"]:
        await update.message.reply_text(t("ru", "not_started"))
        return
    lang = user.get("language", "ru")
    name = user["name"]
    await update.message.reply_text(
        t(lang, "menu_title", name=name),
        reply_markup=get_main_menu(lang)
    )

async def skills_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    lang = user.get("language", "ru") if user else "ru"
    text = SKILLS_EN if lang == "en" else SKILLS_RU
    await update.message.reply_text(text)

async def forget_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    lang = user.get("language", "ru") if user else "ru"
    if lang == "en":
        keyboard = [["🗑 Yes, forget everything", "❌ Cancel"]]
        await update.message.reply_text(
            "Are you sure you want me to forget everything about you?\n\nThis will delete all your history, notes, reminders, habits and personal data. This cannot be undone.",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
    else:
        keyboard = [["🗑 Да, забудь всё", "❌ Отмена"]]
        await update.message.reply_text(
            "Вы уверены что хотите чтобы я забыла о вас всё?\n\nЭто удалит всю вашу историю, заметки, напоминания, привычки и личные данные. Это нельзя отменить.",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
    context.user_data["waiting_forget_confirm"] = True

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
    is_en = lang == "en"

    if query.data == "menu_morning":
        keyboard = [
            [InlineKeyboardButton("📋 День план" if not is_en else "📋 Day plan", callback_data="morning_plan")],
            [InlineKeyboardButton("🌤️ Погода" if not is_en else "🌤️ Weather", callback_data="morning_weather_btn")],
            [InlineKeyboardButton("🌦 Прогноз на неделю" if not is_en else "🌦 Weekly forecast", callback_data="morning_forecast")],
            [InlineKeyboardButton("🧘 Мотивация" if not is_en else "🧘 Motivation", callback_data="morning_motivation")],
            [InlineKeyboardButton("◀️ Назад" if not is_en else "◀️ Back", callback_data="back_main")],
        ]
        title = "🌅 Утреннее меню" if not is_en else "🌅 Morning menu"
        await query.edit_message_text(title, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "morning_plan":
        reminders = await get_reminders(user_id)
        back_btn = InlineKeyboardButton("◀️ Назад" if not is_en else "◀️ Back", callback_data="menu_morning")
        if reminders:
            plan_text = "\n".join([f"{r['time']} — {r['text']}" for r in sorted(reminders, key=lambda x: x["time"])])
            title = "Ваш план на сегодня:" if not is_en else "Your plan for today:"
            text = f"{title}\n\n{plan_text}"
        else:
            text = "На сегодня задачи не добавлены." if not is_en else "No tasks for today."
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]))

    elif query.data == "morning_weather_btn":
        loading = f"Получаю погоду для {city}..." if not is_en else f"Getting weather for {city}..."
        await query.edit_message_text(loading)
        weather = await get_weather(city, lang)
        back_btn = InlineKeyboardButton("◀️ Назад" if not is_en else "◀️ Back", callback_data="menu_morning")
        await query.edit_message_text(weather, reply_markup=InlineKeyboardMarkup([[back_btn]]))

    elif query.data == "morning_forecast":
        loading = f"Получаю прогноз для {city}..." if not is_en else f"Getting forecast for {city}..."
        await query.edit_message_text(loading)
        forecast = await get_weather_forecast(city, lang)
        back_btn = InlineKeyboardButton("◀️ Назад" if not is_en else "◀️ Back", callback_data="menu_morning")
        if forecast:
            title = f"Прогноз погоды для {city}:" if not is_en else f"Weather forecast for {city}:"
            await query.edit_message_text(f"{title}\n\n{forecast}", reply_markup=InlineKeyboardMarkup([[back_btn]]))
        else:
            text = "Прогноз недоступен." if not is_en else "Forecast unavailable."
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]))

    elif query.data == "morning_motivation":
        quote = random.choice(MOTIVATIONAL_QUOTES[lang])
        title = "Мотивация дня:" if not is_en else "Motivation:"
        keyboard = [
            [InlineKeyboardButton("🔄 Ещё" if not is_en else "🔄 Another", callback_data="morning_motivation")],
            [InlineKeyboardButton("◀️ Назад" if not is_en else "◀️ Back", callback_data="menu_morning")],
        ]
        await query.edit_message_text(f"{title}\n\n{quote}", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "menu_habits":
        async with db_pool.acquire() as conn:
            habits = await conn.fetch("SELECT id, name FROM habits WHERE user_id = $1", user_id)
        if habits:
            lines = [f"✅ {h['name']}" for h in habits]
            title = "Ваши привычки:" if not is_en else "Your habits:"
            text = f"{title}\n\n" + "\n".join(lines)
        else:
            text = "Привычек пока нет." if not is_en else "No habits yet."
        keyboard = [
            [InlineKeyboardButton("➕ Добавить" if not is_en else "➕ Add habit", callback_data="habit_add")],
            [InlineKeyboardButton("✅ Отметить" if not is_en else "✅ Mark done", callback_data="habit_log")],
            [InlineKeyboardButton("📊 Статистика" if not is_en else "📊 Statistics", callback_data="habit_stats")],
            [InlineKeyboardButton("◀️ Назад" if not is_en else "◀️ Back", callback_data="back_main")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "habit_add":
        context.user_data["waiting_habit"] = True
        back_btn = InlineKeyboardButton("◀️ Отмена" if not is_en else "◀️ Cancel", callback_data="menu_habits")
        text = "Напишите название привычки\n\nНапример: Медитация, Чтение, Зарядка" if not is_en else "Write the habit name\n\nFor example: Meditation, Reading, Exercise"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]))

    elif query.data == "habit_log":
        async with db_pool.acquire() as conn:
            habits = await conn.fetch("SELECT id, name FROM habits WHERE user_id = $1", user_id)
        if not habits:
            back_btn = InlineKeyboardButton("◀️ Назад" if not is_en else "◀️ Back", callback_data="menu_habits")
            text = "Сначала добавьте привычку!" if not is_en else "Add a habit first!"
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]))
            return
        keyboard = [[InlineKeyboardButton(f"✅ {h['name']}", callback_data=f"log_habit_{h['id']}")] for h in habits]
        keyboard.append([InlineKeyboardButton("◀️ Назад" if not is_en else "◀️ Back", callback_data="menu_habits")])
        text = "Какую привычку отмечаем?" if not is_en else "Which habit to mark?"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("log_habit_"):
        habit_id = int(query.data.split("_")[-1])
        async with db_pool.acquire() as conn:
            habit = await conn.fetchrow("SELECT name FROM habits WHERE id = $1", habit_id)
            await conn.execute("INSERT INTO habit_logs (user_id, habit_id) VALUES ($1, $2)", user_id, habit_id)
        back_btn = InlineKeyboardButton("◀️ К привычкам" if not is_en else "◀️ Back", callback_data="menu_habits")
        text = f"Привычка {habit['name']} отмечена! Так держать 💪" if not is_en else f"Habit {habit['name']} marked! Keep it up 💪"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]))

    elif query.data == "habit_stats":
        async with db_pool.acquire() as conn:
            habits = await conn.fetch("SELECT id, name FROM habits WHERE user_id = $1", user_id)
            lines = []
            for h in habits:
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM habit_logs WHERE habit_id = $1 AND logged_at >= NOW() - INTERVAL '7 days'", h["id"]
                )
                lines.append(f"{h['name']}: {count}/7 {'дней' if not is_en else 'days'}")
        title = "Статистика за 7 дней:" if not is_en else "Stats for 7 days:"
        text = f"{title}\n\n" + "\n".join(lines) if lines else "Нет данных." if not is_en else "No data."
        back_btn = InlineKeyboardButton("◀️ Назад" if not is_en else "◀️ Back", callback_data="menu_habits")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]))

    elif query.data == "menu_water":
        water_on = user.get("water_reminders", False)
        interval = user.get("water_interval", 2)
        status = "✅ Включены" if water_on else "❌ Выключены"
        if is_en:
            status = "✅ On" if water_on else "❌ Off"
        keyboard = [
            [InlineKeyboardButton("💧 Выпила воду!" if not is_en else "💧 Drank water!", callback_data="water_drink")],
            [InlineKeyboardButton("🔔 Выключить" if water_on else "🔔 Включить" if not is_en else "🔔 Turn off" if water_on else "🔔 Turn on", callback_data="water_toggle")],
            [InlineKeyboardButton("◀️ Назад" if not is_en else "◀️ Back", callback_data="back_main")],
        ]
        text = f"Трекер воды\n\nНапоминания: {status}\nКаждые {interval} часа\nНорма: 8 стаканов 💧" if not is_en else f"Water tracker\n\nReminders: {status}\nEvery {interval} hours\nNorm: 8 glasses 💧"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "water_drink":
        back_btn = InlineKeyboardButton("◀️ Назад" if not is_en else "◀️ Back", callback_data="menu_water")
        text = "Отлично! Стакан воды засчитан 💧" if not is_en else "Great! Glass of water counted 💧"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]))

    elif query.data == "water_toggle":
        water_on = user.get("water_reminders", False)
        new_state = not water_on
        await save_user(user_id, water_reminders=new_state)
        if new_state:
            interval = user.get("water_interval", 2)
            context.application.job_queue.run_repeating(
                send_water_reminder, interval=interval * 3600,
                first=interval * 3600, data=user_id, name=f"water_{user_id}"
            )
            text = f"Напоминания включены! Каждые {interval} часа 💧" if not is_en else f"Water reminders on! Every {interval} hours 💧"
        else:
            for job in context.application.job_queue.get_jobs_by_name(f"water_{user_id}"):
                job.schedule_removal()
            text = "Напоминания выключены." if not is_en else "Water reminders off."
        back_btn = InlineKeyboardButton("◀️ Назад" if not is_en else "◀️ Back", callback_data="menu_water")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]))

    elif query.data == "menu_diary":
        keyboard = [
            [InlineKeyboardButton("💰 Финансы" if not is_en else "💰 Finances", callback_data="diary_finances"),
             InlineKeyboardButton("😴 Сон" if not is_en else "😴 Sleep", callback_data="diary_sleep")],
            [InlineKeyboardButton("📝 Заметки" if not is_en else "📝 Notes", callback_data="diary_notes"),
             InlineKeyboardButton("🍳 Рецепты" if not is_en else "🍳 Recipes", callback_data="diary_recipe")],
            [InlineKeyboardButton("🎬 Что посмотреть" if not is_en else "🎬 What to watch", callback_data="diary_movie")],
            [InlineKeyboardButton("◀️ Назад" if not is_en else "◀️ Back", callback_data="back_main")],
        ]
        title = "Дневник — выберите раздел:" if not is_en else "Diary — choose a section:"
        await query.edit_message_text(title, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "diary_finances":
        async with db_pool.acquire() as conn:
            income = await conn.fetchval("SELECT SUM(amount) FROM finances WHERE user_id = $1 AND type = 'income' AND created_at >= NOW() - INTERVAL '30 days'", user_id)
            expense = await conn.fetchval("SELECT SUM(amount) FROM finances WHERE user_id = $1 AND type = 'expense' AND created_at >= NOW() - INTERVAL '30 days'", user_id)
            recent = await conn.fetch("SELECT amount, type, category, description FROM finances WHERE user_id = $1 ORDER BY created_at DESC LIMIT 5", user_id)
        income_text = f"{income:.0f}" if income else "0"
        expense_text = f"{expense:.0f}" if expense else "0"
        balance = (income or 0) - (expense or 0)
        lines = [f"{'➕' if r['type'] == 'income' else '➖'} {r['amount']:.0f} — {r['category']} {r['description']}" for r in recent]
        if not is_en:
            text = f"Финансы за месяц:\n\n➕ Доходы: {income_text}\n➖ Расходы: {expense_text}\n💵 Баланс: {balance:.0f}\n\n"
            text += "\n".join(lines) if lines else "Записей пока нет."
            text += "\n\nДобавить доход: +1000 зарплата\nДобавить расход: -500 еда кофе"
        else:
            text = f"Finances this month:\n\n➕ Income: {income_text}\n➖ Expenses: {expense_text}\n💵 Balance: {balance:.0f}\n\n"
            text += "\n".join(lines) if lines else "No records yet."
            text += "\n\nAdd income: +1000 salary\nAdd expense: -500 food coffee"
        context.user_data["waiting_finance"] = True
        back_btn = InlineKeyboardButton("◀️ Назад" if not is_en else "◀️ Back", callback_data="menu_diary")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]))

    elif query.data == "diary_sleep":
        keyboard = [
            [InlineKeyboardButton("6:00", callback_data="sleep_6_0"), InlineKeyboardButton("7:00", callback_data="sleep_7_0"), InlineKeyboardButton("8:00", callback_data="sleep_8_0")],
            [InlineKeyboardButton("9:00", callback_data="sleep_9_0"), InlineKeyboardButton("10:00", callback_data="sleep_10_0")],
            [InlineKeyboardButton("◀️ Назад" if not is_en else "◀️ Back", callback_data="menu_diary")],
        ]
        text = "Трекер сна\n\nВо сколько хотите проснуться?" if not is_en else "Sleep tracker\n\nWhat time do you want to wake up?"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("sleep_"):
        parts = query.data.split("_")
        wake_hour = int(parts[1])
        wake_minute = int(parts[2])
        times = calculate_sleep_times(wake_hour, wake_minute)
        text = f"Чтобы проснуться в {wake_hour:02d}:{wake_minute:02d} бодрой, ложитесь спать в:\n\n" if not is_en else f"To wake up at {wake_hour:02d}:{wake_minute:02d} refreshed, go to bed at:\n\n"
        for t_item in times:
            text += f"🌙 {t_item}\n"
        text += "\n+15 минут на засыпание уже учтены" if not is_en else "\n+15 minutes to fall asleep already included"
        back_btn = InlineKeyboardButton("◀️ Назад" if not is_en else "◀️ Back", callback_data="diary_sleep")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]))

    elif query.data == "diary_notes":
        async with db_pool.acquire() as conn:
            notes = await conn.fetch("SELECT text FROM notes WHERE user_id = $1 ORDER BY created_at DESC LIMIT 5", user_id)
        if notes:
            lines = [f"• {n['text'][:60]}{'...' if len(n['text']) > 60 else ''}" for n in notes]
            title = "Ваши последние заметки:" if not is_en else "Your recent notes:"
            text = f"{title}\n\n" + "\n".join(lines)
        else:
            text = "Заметок пока нет." if not is_en else "No notes yet."
        text += "\n\nНапишите что угодно и я сохраню!" if not is_en else "\n\nWrite anything and I'll save it!"
        context.user_data["waiting_note"] = True
        back_btn = InlineKeyboardButton("◀️ Назад" if not is_en else "◀️ Back", callback_data="menu_diary")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]))

    elif query.data == "diary_recipe":
        await query.edit_message_text("Подбираю рецепт..." if not is_en else "Finding a recipe...")
        recipe = await get_ai_recipe(lang)
        keyboard = [
            [InlineKeyboardButton("🔄 Другой рецепт" if not is_en else "🔄 Another recipe", callback_data="diary_recipe")],
            [InlineKeyboardButton("◀️ Назад" if not is_en else "◀️ Back", callback_data="menu_diary")],
        ]
        title = "Рецепт дня:" if not is_en else "Recipe of the day:"
        await query.edit_message_text(f"{title}\n\n{recipe}", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "diary_movie":
        await query.edit_message_text("Подбираю фильм..." if not is_en else "Finding a movie...")
        movie = await get_ai_movie(lang)
        keyboard = [
            [InlineKeyboardButton("🔄 Другой фильм" if not is_en else "🔄 Another movie", callback_data="diary_movie")],
            [InlineKeyboardButton("◀️ Назад" if not is_en else "◀️ Back", callback_data="menu_diary")],
        ]
        title = "Рекомендация:" if not is_en else "Recommendation:"
        await query.edit_message_text(f"{title}\n\n{movie}", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "menu_profile":
        async with db_pool.acquire() as conn:
            total_messages = await conn.fetchval("SELECT COUNT(*) FROM history WHERE user_id = $1 AND role = 'user'", user_id)
            habits_count = await conn.fetchval("SELECT COUNT(*) FROM habits WHERE user_id = $1", user_id)
            income = await conn.fetchval("SELECT SUM(amount) FROM finances WHERE user_id = $1 AND type = 'income' AND created_at >= NOW() - INTERVAL '30 days'", user_id)
            expense = await conn.fetchval("SELECT SUM(amount) FROM finances WHERE user_id = $1 AND type = 'expense' AND created_at >= NOW() - INTERVAL '30 days'", user_id)
        created = user.get("created_at")
        days = (datetime.now() - created).days if created else 0
        tz = user.get("timezone") or "Europe/Moscow"
        balance = (income or 0) - (expense or 0)
        if not is_en:
            text = (f"Мой профиль\n\nИмя: {name}\nГород: {city}\nЧасовой пояс: {tz}\nЯзык: Русский 🇷🇺\nДней с нами: {days}\nСообщений: {total_messages}\nПривычек: {habits_count}\nБаланс за месяц: {balance:.0f}")
            keyboard = [
                [InlineKeyboardButton("🌍 Изменить город", callback_data="profile_city")],
                [InlineKeyboardButton("🌐 Switch to English 🇬🇧", callback_data="switch_lang_en")],
                [InlineKeyboardButton("🗑 Забудь всё обо мне", callback_data="confirm_forget")],
                [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
            ]
        else:
            text = (f"My profile\n\nName: {name}\nCity: {city}\nTimezone: {tz}\nLanguage: English 🇬🇧\nDays with us: {days}\nMessages: {total_messages}\nHabits: {habits_count}\nBalance this month: {balance:.0f}")
            keyboard = [
                [InlineKeyboardButton("🌍 Change city", callback_data="profile_city")],
                [InlineKeyboardButton("🌐 Switch to Russian 🇷🇺", callback_data="switch_lang_ru")],
                [InlineKeyboardButton("🗑 Forget everything about me", callback_data="confirm_forget")],
                [InlineKeyboardButton("◀️ Back", callback_data="back_main")],
            ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "confirm_forget":
        keyboard = [
            [InlineKeyboardButton("🗑 Да, удалить всё" if not is_en else "🗑 Yes, delete everything", callback_data="do_forget")],
            [InlineKeyboardButton("❌ Отмена" if not is_en else "❌ Cancel", callback_data="menu_profile")],
        ]
        text = "Вы уверены? Это удалит всю историю, заметки, напоминания и личные данные. Отменить нельзя." if not is_en else "Are you sure? This will delete all history, notes, reminders and personal data. Cannot be undone."
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "do_forget":
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM history WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM reminders WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM notes WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM habits WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM habit_logs WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM finances WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM user_memory WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM sleep_logs WHERE user_id = $1", user_id)
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
        back_btn = InlineKeyboardButton("◀️ Отмена" if not is_en else "◀️ Cancel", callback_data="menu_profile")
        text = "Напишите название вашего города" if not is_en else "Write your city name"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]))

    elif query.data == "menu_settings":
        morning_weather = "✅" if user.get("morning_weather") else "❌"
        morning_motivation = "✅" if user.get("morning_motivation") else "❌"
        water = "✅" if user.get("water_reminders") else "❌"
        evening = "✅" if user.get("evening_news") else "❌"
        if not is_en:
            keyboard = [
                [InlineKeyboardButton(f"{morning_weather} Погода утром", callback_data="toggle_morning_weather")],
                [InlineKeyboardButton(f"{morning_motivation} Мотивация утром", callback_data="toggle_morning_motivation")],
                [InlineKeyboardButton(f"{water} Напоминания о воде", callback_data="water_toggle")],
                [InlineKeyboardButton(f"{evening} Вечерняя сводка", callback_data="toggle_evening_news")],
                [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
            ]
            await query.edit_message_text("Настройки", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            keyboard = [
                [InlineKeyboardButton(f"{morning_weather} Weather in morning", callback_data="toggle_morning_weather")],
                [InlineKeyboardButton(f"{morning_motivation} Motivation in morning", callback_data="toggle_morning_motivation")],
                [InlineKeyboardButton(f"{water} Water reminders", callback_data="water_toggle")],
                [InlineKeyboardButton(f"{evening} Evening summary", callback_data="toggle_evening_news")],
                [InlineKeyboardButton("◀️ Back", callback_data="back_main")],
            ]
            await query.edit_message_text("Settings", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "toggle_morning_weather":
        new = not user.get("morning_weather", False)
        await save_user(user_id, morning_weather=new)
        status = "включена ✅" if new else "выключена ❌"
        if is_en:
            status = "on ✅" if new else "off ❌"
        text = f"Погода утром {status}" if not is_en else f"Morning weather {status}"
        back_btn = InlineKeyboardButton("◀️ Назад" if not is_en else "◀️ Back", callback_data="menu_settings")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]))

    elif query.data == "toggle_morning_motivation":
        new = not user.get("morning_motivation", False)
        await save_user(user_id, morning_motivation=new)
        status = "включена ✅" if new else "выключена ❌"
        if is_en:
            status = "on ✅" if new else "off ❌"
        text = f"Мотивация утром {status}" if not is_en else f"Morning motivation {status}"
        back_btn = InlineKeyboardButton("◀️ Назад" if not is_en else "◀️ Back", callback_data="menu_settings")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]))

    elif query.data == "toggle_evening_news":
        new = not user.get("evening_news", False)
        await save_user(user_id, evening_news=new)
        if new:
            evening_time = user.get("evening_time", "21:00")
            tz = pytz.timezone(user.get("timezone", "Europe/Moscow"))
            hour = int(evening_time.split(":")[0])
            context.application.job_queue.run_daily(
                send_evening_news,
                time=time(hour=hour, minute=0, tzinfo=tz),
                data=user_id, name=f"evening_{user_id}"
            )
            text = f"Вечерняя сводка включена! В {evening_time} 🌙" if not is_en else f"Evening summary on! At {evening_time} 🌙"
        else:
            for job in context.application.job_queue.get_jobs_by_name(f"evening_{user_id}"):
                job.schedule_removal()
            text = "Вечерняя сводка выключена." if not is_en else "Evening summary off."
        back_btn = InlineKeyboardButton("◀️ Назад" if not is_en else "◀️ Back", callback_data="menu_settings")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]))

    elif query.data == "back_main":
        await query.edit_message_text(
            t(lang, "menu_title", name=name),
            reply_markup=get_main_menu(lang)
        )

async def announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("Нет доступа.")
        return
    if not context.args:
        await update.message.reply_text("Пример:\n/announce Текст")
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
    user_name = update.effective_user.first_name or "Новый пользователь"
    username = update.effective_user.username or "нет username"
    await save_user(user_id, username=username)
    await add_history(user_id, "system", "start")
    await update.message.reply_text(t("ru", "welcome"))
    await notify_admin(context, user_name, username, f"Новый пользователь (ID: {user_id})", "Начал онбординг")
    return ASK_NAME

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    name = update.message.text.strip()
    username = update.effective_user.username or "нет username"
    await save_user(user_id, name=name, username=username)
    await save_memory_item(user_id, "имя", name)
    await update.message.reply_text(t("ru", "ask_city", name=name), reply_markup=ReplyKeyboardRemove())
    return ASK_CITY

async def ask_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    city = update.message.text.strip()
    timezone = await get_timezone_by_city(city)
    await save_user(user_id, city=city, timezone=timezone)
    await save_memory_item(user_id, "город", city)
    context.user_data["onboarding_city"] = city
    keyboard = [["🇷🇺 Русский", "🇬🇧 English"]]
    await update.message.reply_text(
        t("ru", "ask_language", city=city),
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return ASK_LANGUAGE

async def ask_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    lang = "en" if "English" in text else "ru"
    await save_user(user_id, language=lang)
    keyboard = [["✅ Да, каждое утро" if lang == "ru" else "✅ Yes, every morning",
                 "❌ Нет, не нужно" if lang == "ru" else "❌ No, thanks"]]
    await update.message.reply_text(
        t(lang, "ask_morning"),
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return ASK_MORNING_PLAN

async def ask_morning_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    lang = user.get("language", "ru") if user else "ru"
    wants_plan = "Да" in update.message.text or "Yes" in update.message.text
    await save_user(user_id, morning_plan=wants_plan)
    if wants_plan:
        keyboard = [["7:00", "8:00", "9:00"], ["10:00", "Другое" if lang == "ru" else "Other"]]
        await update.message.reply_text(
            t(lang, "ask_morning_time"),
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return ASK_MORNING_TIME
    else:
        return await ask_reminders_step(update, context)

async def ask_morning_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    try:
        hour = int(text.replace(":00", "").replace(":30", ""))
        morning_time = f"{hour:02d}:00"
    except:
        morning_time = "08:00"
    await save_user(user_id, morning_time=morning_time)
    return await ask_reminders_step(update, context)

async def ask_reminders_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    lang = user.get("language", "ru") if user else "ru"
    if lang == "en":
        keyboard = [["✅ 1 hour before", "⏰ 30 minutes before", "❌ No thanks"]]
    else:
        keyboard = [["✅ За час", "⏰ За 30 минут", "❌ Не нужно"]]
    await update.message.reply_text(
        t(lang, "ask_reminders"),
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return ASK_REMINDERS

async def ask_evening_news_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    lang = user.get("language", "ru") if user else "ru"
    if lang == "en":
        keyboard = [["✅ Yes, in the evening", "❌ No thanks"]]
    else:
        keyboard = [["✅ Да, вечером", "❌ Не нужно"]]
    await update.message.reply_text(
        t(lang, "ask_evening_news"),
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return ASK_EVENING_NEWS

async def handle_evening_news_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    lang = user.get("language", "ru") if user else "ru"
    wants_news = "Да" in update.message.text or "Yes" in update.message.text
    await save_user(user_id, evening_news=wants_news)
    if wants_news:
        keyboard = [["20:00", "21:00", "22:00"], ["19:00", "Другое" if lang == "ru" else "Other"]]
        await update.message.reply_text(
            t(lang, "ask_evening_time"),
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return ASK_EVENING_TIME
    else:
        return await ask_comm_style_step(update, context)

async def handle_evening_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    try:
        hour = int(text.replace(":00", "").replace(":30", ""))
        evening_time = f"{hour:02d}:00"
    except:
        evening_time = "21:00"
    await save_user(user_id, evening_time=evening_time)
    return await ask_comm_style_step(update, context)

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

async def ask_comm_style_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    lang = user.get("language", "ru") if user else "ru"
    if lang == "en":
        keyboard = [
            ["👭 Friend — casual, informal"],
            ["🎯 Mentor — motivating, supportive"],
            ["💼 Professional — clear, to the point"],
            ["✍️ My own style — I'll describe it"],
        ]
        text = "How would you like me to communicate with you? 🌸"
    else:
        keyboard = [
            ["👭 Подружка — тепло, неформально, на ты"],
            ["🎯 Наставник — мотивирующий, на вы"],
            ["💼 Профессионал — чётко и по делу"],
            ["✍️ Свой стиль — напишу сама"],
        ]
        text = "Как вам удобнее чтобы я общалась с вами? 🌸"
    await update.message.reply_text(
        text,
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
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
        style = text.strip()
    await save_user(user_id, comm_style=style)
    await save_memory_item(user_id, "стиль_общения", style)
    if lang == "en":
        confirm = f"Got it! I'll be your {style} 🌸"
    else:
        confirm = f"Отлично, запомнила! Буду общаться как {style} 🌸"
    await update.message.reply_text(confirm, reply_markup=ReplyKeyboardRemove())
    return await finish_onboarding_final(update, context)


    user_id = update.effective_user.id
    user = await get_user(user_id)
    lang = user.get("language", "ru") if user else "ru"
    await save_user(user_id, onboarded=True)
    user = await get_user(user_id)
    name = user["name"] if user else ""
    morning_time = user["morning_time"] if user else "08:00"
    has_plan = user["morning_plan"] if user else False
    has_evening = user.get("evening_news", False)
    evening_time = user.get("evening_time", "21:00")
    summary = t(lang, "finish", name=name)
    await update.message.reply_text(summary, reply_markup=ReplyKeyboardRemove())
    username = update.effective_user.username or "нет username"
    await notify_admin(context, name, username, "Завершил онбординг", summary)
    if has_plan and morning_time:
        tz = pytz.timezone(user["timezone"] if user else "Europe/Moscow")
        context.application.job_queue.run_daily(
            send_morning_plan,
            time=time(hour=int(morning_time.split(":")[0]), minute=0, tzinfo=tz),
            data=user_id, name=f"morning_{user_id}"
        )
    if has_evening and evening_time:
        tz = pytz.timezone(user["timezone"] if user else "Europe/Moscow")
        context.application.job_queue.run_daily(
            send_evening_news,
            time=time(hour=int(evening_time.split(":")[0]), minute=0, tzinfo=tz),
            data=user_id, name=f"evening_{user_id}"
        )
    return ConversationHandler.END

async def process_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    if not user or not user["onboarded"]:
        await update.message.reply_text(t("ru", "not_started"))
        return
    name = user["name"]
    lang = user.get("language", "ru")
    is_en = lang == "en"

    if context.user_data.get("waiting_forget_confirm"):
        context.user_data["waiting_forget_confirm"] = False
        if "забудь всё" in user_text.lower() or "yes, forget" in user_text.lower():
            async with db_pool.acquire() as conn:
                await conn.execute("DELETE FROM history WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM reminders WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM notes WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM habits WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM habit_logs WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM finances WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM user_memory WHERE user_id = $1", user_id)
                await conn.execute("UPDATE users SET onboarded = FALSE, name = NULL WHERE user_id = $1", user_id)
            await update.message.reply_text(t(lang, "memory_cleared"), reply_markup=ReplyKeyboardRemove())
        else:
            await update.message.reply_text("Хорошо, ничего не удаляю 🌸" if not is_en else "OK, nothing deleted 🌸", reply_markup=ReplyKeyboardRemove())
        return

    if context.user_data.get("waiting_habit"):
        context.user_data["waiting_habit"] = False
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO habits (user_id, name) VALUES ($1, $2)", user_id, user_text)
        text = f"Привычка {user_text} добавлена!" if not is_en else f"Habit {user_text} added!"
        await update.message.reply_text(text)
        return

    if context.user_data.get("waiting_city"):
        context.user_data["waiting_city"] = False
        timezone = await get_timezone_by_city(user_text)
        await save_user(user_id, city=user_text, timezone=timezone)
        await save_memory_item(user_id, "город", user_text)
        text = f"Город изменён на {user_text}!" if not is_en else f"City changed to {user_text}!"
        await update.message.reply_text(text)
        return

    if context.user_data.get("waiting_note"):
        context.user_data["waiting_note"] = False
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO notes (user_id, text) VALUES ($1, $2)", user_id, user_text)
        text = "Заметка сохранена!" if not is_en else "Note saved!"
        await update.message.reply_text(text)
        return

    if context.user_data.get("waiting_finance"):
        context.user_data["waiting_finance"] = False
        parts = user_text.split()
        try:
            raw = parts[0].replace(",", ".")
            is_income = raw.startswith("+")
            amount = float(raw.replace("+", "").replace("-", ""))
            finance_type = "income" if is_income else "expense"
            category = parts[1] if len(parts) > 1 else ("Other" if is_en else "Другое")
            description = " ".join(parts[2:]) if len(parts) > 2 else ""
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO finances (user_id, amount, type, category, description) VALUES ($1, $2, $3, $4, $5)",
                    user_id, amount, finance_type, category, description
                )
            text = f"{'Доход' if is_income else 'Расход'} {amount:.0f} ({category}) сохранён!" if not is_en else f"{'Income' if is_income else 'Expense'} {amount:.0f} ({category}) saved!"
            await update.message.reply_text(text)
        except:
            text = "Формат: +1000 зарплата или -500 еда кофе" if not is_en else "Format: +1000 salary or -500 food coffee"
            await update.message.reply_text(text)
        return

    await add_history(user_id, "user", user_text)
    await extract_and_save_memory(user_id, user_text, lang)
    history = await get_history_db(user_id)
    memory = await get_user_memory(user_id)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        if is_reminder_request(user_text):
            tz = pytz.timezone(user["timezone"] or "Europe/Moscow")
            now = datetime.now(tz)
            essence = await rephrase_reminder(user_text, lang)
            rel_value, rel_unit = extract_relative_time(user_text)
            if rel_value is not None:
                remind_dt = now + (timedelta(minutes=rel_value) if rel_unit == 'minutes' else timedelta(hours=rel_value))
                job_name = f"once_{user_id}_{remind_dt.strftime('%H%M%S')}"
                context.application.job_queue.run_once(
                    send_scheduled_reminder, when=remind_dt,
                    data={"user_id": user_id, "essence": essence}, name=job_name
                )
                await add_reminder(user_id, remind_dt.strftime("%H:%M"), essence)
            else:
                hour, minute = extract_exact_time(user_text)
                if hour is not None:
                    time_str = f"{hour:02d}:{minute:02d}"
                    conflict = await check_conflict_db(user_id, time_str)
                    if conflict:
                        msg = f"В {time_str} уже запланировано: «{conflict}». Выбрать другое время?" if not is_en else f"At {time_str} already scheduled: «{conflict}». Choose another time?"
                        await update.message.reply_text(msg)
                        return
                    job_name = f"reminder_{user_id}_{hour}_{minute}"
                    for job in context.application.job_queue.get_jobs_by_name(job_name):
                        job.schedule_removal()
                    tz = pytz.timezone(user["timezone"] or "Europe/Moscow")
                    context.application.job_queue.run_daily(
                        send_scheduled_reminder,
                        time=time(hour=hour, minute=minute, tzinfo=tz),
                        data={"user_id": user_id, "essence": essence}, name=job_name
                    )
                    await add_reminder(user_id, time_str, essence)

        dt = get_current_datetime(user.get("timezone", "Europe/Moscow"))
        date_str = dt["ru"] if not is_en else dt["en"]
        comm_style = user.get("comm_style", "наставник" if not is_en else "mentor")
        system_prompt = SYSTEM_PROMPT_EN if is_en else SYSTEM_PROMPT_RU

        memory_block = ""
        if memory:
            memory_block = f"\n\nЧто я знаю об этом пользователе:\n{memory}" if not is_en else f"\n\nWhat I know about this user:\n{memory}"

        full_system = f"Сегодня: {date_str}\nСтиль общения с этим пользователем: {comm_style}{memory_block}\n\n{system_prompt}" if not is_en else f"Today: {date_str}\nCommunication style for this user: {comm_style}{memory_block}\n\n{system_prompt}"

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": full_system}, *history],
            max_tokens=1000, temperature=0.7
        )
        reply = response.choices[0].message.content
        await add_history(user_id, "assistant", reply)
        await update.message.reply_text(reply, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await update.message.reply_text(t(lang, "error"))

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
            text = "Не смогла распознать голосовое. Попробуйте ещё раз." if lang == "ru" else "Could not recognize voice message. Please try again."
            await update.message.reply_text(text)
            return
        await process_text_message(update, context, user_text)
    except Exception as e:
        logging.error(f"Ошибка голосового: {e}")
        text = "Не удалось обработать голосовое. Попробуйте написать текстом." if lang == "ru" else "Could not process voice message. Try typing instead."
        await update.message.reply_text(text)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_text_message(update, context, update.message.text)

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    lang = user.get("language", "ru") if user else "ru"
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM history WHERE user_id = $1", user_id)
    await update.message.reply_text(t(lang, "history_cleared"))

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("Нет доступа.")
        return
    async with db_pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM users WHERE onboarded = TRUE")
        today = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM history WHERE created_at >= NOW() - INTERVAL '1 day'")
        week = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM history WHERE created_at >= NOW() - INTERVAL '7 days'")
        total_messages = await conn.fetchval("SELECT COUNT(*) FROM history WHERE role = 'user'")
        ru_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE language = 'ru' AND onboarded = TRUE")
        en_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE language = 'en' AND onboarded = TRUE")
    text = (
        f"София — статистика\n\n"
        f"Всего пользователей: {total}\n"
        f"Русский: {ru_users}\n"
        f"English: {en_users}\n"
        f"Активны сегодня: {today}\n"
        f"За 7 дней: {week}\n"
        f"Всего сообщений: {total_messages}"
    )
    await update.message.reply_text(text)

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
    app.add_handler(CommandHandler("forget", forget_command))
    app.add_handler(CommandHandler("announce", announce))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🌸 София v3.0 запущена!")
    app.run_polling()
