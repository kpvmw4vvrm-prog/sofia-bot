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
try:
    from fastapi import FastAPI, HTTPException, Depends
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    import uvicorn
    import threading
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

# ─── КОНФИГУРАЦИЯ ───────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY   = os.environ.get("OPENAI_API_KEY")
ASSEMBLYAI_KEY   = os.environ.get("ASSEMBLYAI_KEY")
WEATHER_API_KEY  = os.environ.get("WEATHER_API_KEY")
NEWS_API_KEY     = os.environ.get("NEWS_API_KEY")
TAVILY_API_KEY   = os.environ.get("TAVILY_API_KEY", "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")
DATABASE_URL     = os.environ.get("DATABASE_URL")
ADMIN_ID         = 944447597   # Telegram ID Ирины — ТОЛЬКО сюда идут уведомления

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
        "not_started": "Напишите /start чтобы начать",
        "error": "Что-то пошло не так, попробуйте ещё раз.",
        "water": "{name}, самое время выпить стакан воды! 💧",
        "reminder": "{name}, напоминаю!\n\n{text}",
        "morning": "Доброе утро, {name}!\n\n",
        "no_plan": "На сегодня задачи не добавлены. Напишите мне что планируете — составлю расписание.",
    },
    "en": {
        "welcome": "Good day!\n\nNice to meet you! I'm Sofia — your personal assistant.\n\nLet's start — what's your name?",
        "ask_city": "Nice to meet you, {name}!\n\nWhat city are you in?",
        "ask_language": "Got it — {city}\n\nWhat language would you prefer?",
        "ask_morning": "Would you like me to send you a daily plan every morning?",
        "ask_morning_time": "What time should I send the morning plan?",
        "ask_reminders": "Remind you about tasks in advance?",
        "ask_evening_news": "Would you like an evening summary — habits, finances, progress?",
        "ask_evening_time": "What time should I send the evening summary?",
        "ask_comm_style": "How would you like me to communicate with you?",
        "finish": "All done, {name}! 🌸\n\nType /menu to open the menu.",
        "not_started": "Type /start to begin",
        "error": "Something went wrong, please try again.",
        "water": "{name}, time to drink a glass of water! 💧",
        "reminder": "{name}, reminder!\n\n{text}",
        "morning": "Good morning, {name}!\n\n",
        "no_plan": "No tasks for today. Tell me what you're planning.",
    }
}

def t(lang, key, **kwargs):
    text = TEXTS.get(lang, TEXTS["ru"]).get(key, TEXTS["ru"].get(key, ""))
    return text.format(**kwargs) if kwargs else text

CITY_PREPOSITIONS = {
    "москва": "Москве", "санкт-петербург": "Санкт-Петербурге",
    "казань": "Казани", "пермь": "Перми", "тюмень": "Тюмени",
    "дубай": "Дубае", "алматы": "Алматы", "ташкент": "Ташкенте",
    "минск": "Минске", "баку": "Баку", "ереван": "Ереване",
    "лондон": "Лондоне", "париж": "Париже", "берлин": "Берлине",
    "волгоград": "Волгограде", "краснодар": "Краснодаре",
}

def city_in_form(city):
    key = city.lower().strip()
    if key in CITY_PREPOSITIONS:
        return CITY_PREPOSITIONS[key]
    if key.endswith("а"):
        return city[:-1] + "е"
    if key.endswith("ль"):
        return city[:-1] + "е"
    if key.endswith("ов") or key.endswith("ев"):
        return city + "е"
    return city

def get_current_datetime(timezone_str="Europe/Moscow"):
    try:
        tz = pytz.timezone(timezone_str)
        now = datetime.now(tz)
        months_ru = ["января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"]
        days_ru = ["понедельник","вторник","среда","четверг","пятница","суббота","воскресенье"]
        return {
            "ru": f"{now.day} {months_ru[now.month-1]} {now.year}, {days_ru[now.weekday()]}, {now.strftime('%H:%M')}",
            "en": now.strftime("%B %d, %Y, %A, %H:%M"),
        }
    except:
        now = datetime.now()
        return {"ru": now.strftime("%d.%m.%Y %H:%M"), "en": now.strftime("%B %d, %Y %H:%M")}

# ─── ПРОМПТЫ ────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT_RU = """Ты — София, личный ассистент и наставник.

СТИЛЬ ОБЩЕНИЯ — СТРОГО соблюдай стиль из профиля:
подружка → ОБЯЗАТЕЛЬНО на ты, тепло, неформально, как близкая подруга, можно с юмором. НИКОГДА не говори "вы" при этом стиле!
наставник → на вы, мотивирующе, поддерживающе, вдохновляюще
мотиватор → на ты, очень энергично, вдохновляюще, с восклицаниями, максимум поддержки и веры в человека!
официальный помощник → на вы, строго, профессионально, без лишних слов, НИКАКИХ эмодзи
профессионал → на вы, чётко, коротко, НИКАКИХ эмодзи, НИКАКИХ цветочков 🌸, только текст

ФОРМАТИРОВАНИЕ — СТРОГО:
Пиши как живой человек в мессенджере. НИКОГДА не используй: # ## ### заголовки, * ** звёздочки, _ курсив, --- разделители. Никакого Markdown! Только чистый текст. Для списков используй цифры или • без звёздочек. Эмодзи умеренно. Короткие абзацы. Один вопрос за раз.

ДАТА И ВРЕМЯ:
Текущая дата и время указаны в начале сообщения. Ты ВСЕГДА знаешь дату и время. Никогда не говори что не знаешь.

ПАМЯТЬ И ЧЕСТНОСТЬ:
Помнишь всё что пользователь говорил. Используй естественно. Никогда не говори "я не помню".
Если пользователь спрашивает что он просил или о чём говорил — посмотри в историю и ответь честно.
Если пользователь утверждает что-то неверное — мягко но уверенно поправь. Не соглашайся слепо.
НИКОГДА не говори "вы меня не просили" если в истории это есть.
Если информации в истории нет — честно скажи: "Не нашла этого в нашем разговоре, возможно это было раньше."
Когда пользователь спрашивает про цель — отвечай про ЦЕЛЬ, не путай с именами людей.

О СОЗДАТЕЛЕ — дозированно:
"кто создал" → "Меня создала Ирина Солодкова 🌸"
"расскажи больше" → "Ирине 17 лет, она из Волгограда, сейчас живёт и учится в Дубае. Увлекается ИИ и бизнесом."
"контакты" → "irinasa_00@mail.ru"

ЧТО УМЕЕШЬ: планирование, напоминания, поддержка, цели, рецепты, погода, поиск, любые вопросы.

МЕДИЦИНА — СТРОГИЕ ПРАВИЛА:
НИКОГДА не советуй лекарства, препараты, дозировки, витамины к приёму.
НИКОГДА не ставь диагнозы и не интерпретируй симптомы.
НИКОГДА не говори "попробуй выпить", "тебе поможет", "рекомендую принять".
Если спрашивают про здоровье — мягко скажи что это лучше обсудить с врачом.
Таблетки в планере = только напоминания о том что человек УЖЕ назначил себе сам или врач.
НЕ давай никаких медицинских рекомендаций вообще.

ПЛАНЕР:
Если слышишь слова "всегда", "каждый", "каждую", "регулярно", "постоянно", "по пятницам", "по средам" или любой день недели в контексте регулярного занятия — в конце ответа ОБЯЗАТЕЛЬНО напиши: "Хотите добавить это в ваш планер? Напишите да и я запишу!"
ВАЖНО: в планере ВСЕГДА нужно время. Если не указано — спроси.

РЕЦЕПТЫ:
Когда пишешь рецепт — в конце ВСЕГДА добавляй: "Хотите сохранить этот рецепт в ваши любимые?"

ЦЕЛИ:
Если пользователь говорит о своих целях — напомни что можно добавить в раздел Цели для отслеживания прогресса.

Формат плана (только когда просят):
09:00 — задача
10:00 — задача"""

SYSTEM_PROMPT_EN = """You are Sofia, a personal assistant and mentor.

STYLE: strictly follow profile style.
friend → casual, informal, first name basis — NEVER use formal tone!
mentor → formal, motivating, inspiring
professional → formal, clear, brief

FORMATTING: No Markdown, no headers, no asterisks. Conversational text only.

MEMORY: Remember everything. Never say "I don't remember".

ABOUT CREATOR: "Irina Solodkova created me 🌸" (17 years old, from Volgograd, lives in Dubai, loves AI and business)

Plan format: 09:00 — task"""

SKILLS_RU = """Вот всё что я умею:

Общение и память
Запоминаю всё что вы рассказываете. Голосовые сообщения, фото, любые вопросы.

Интернет и поиск
Подключена к интернету — напишите "найди" или "что такое..." и я найду актуальную информацию.

Планирование
План на день, неделю или месяц. Напоминания в любое время. Планер регулярных занятий.

Утро и вечер
Утром — план дня, погода и мотивация. Вечером — итог дня как колесо баланса 🌸

Здоровье
Цикл, таблетки, стресс, вес и рост, нутрициология, настроение.

Цели
Добавляю цели с дедлайном и прогресс-баром.

Дневник
Финансы, сон, вода, привычки, заметки, рецепты, что посмотреть, покупки, планер, дни рождения.

Интересное
Свежие статьи: наука, технологии и ИИ, здоровье, вдохновляющие истории.

Дополнительно
Генерирую изображения — напишите "нарисуй...". Погода сейчас и на неделю. Два языка 🇷🇺 🇬🇧

Наш сайт — sofia-assistant.netlify.app

Напишите /menu чтобы открыть меню 🌸"""

DAYS_RU = {"понедельник": 0, "понедельникам": 0, "вторник": 1, "вторникам": 1, "среду": 2, "средам": 2, "среда": 2, "четверг": 3, "четвергам": 3, "пятницу": 4, "пятницам": 4, "пятница": 4, "субботу": 5, "субботам": 5, "суббота": 5, "воскресенье": 6, "воскресеньям": 6}
DAYS_RU_NAMES = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

RECIPE_CATEGORIES = {
    "soups": "супы и первые блюда",
    "main": "вторые блюда из мяса рыбы или овощей",
    "salads": "салаты и закуски",
    "desserts": "десерты торты и выпечка",
    "trends": "модные и трендовые блюда 2025",
}

INTERESTING_QUERIES = {
    "science": {"query": "science discovery research breakthrough", "ru": "🔬 Научные открытия", "en": "🔬 Science Discoveries"},
    "technology": {"query": "technology AI innovation future", "ru": "💻 Технологии и ИИ", "en": "💻 Technology & AI"},
    "health": {"query": "health wellness longevity medicine", "ru": "💚 Здоровье и долголетие", "en": "💚 Health & Wellness"},
    "inspiration": {"query": "inspiring success achievement positive story", "ru": "✨ Вдохновляющие истории", "en": "✨ Inspiring Stories"},
}

# ─── БД ─────────────────────────────────────────────────────────────────────────
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
        tables = [
            "CREATE TABLE IF NOT EXISTS reminders (id SERIAL PRIMARY KEY, user_id BIGINT, time_str TEXT, text TEXT, created_at TIMESTAMP DEFAULT NOW())",
            "CREATE TABLE IF NOT EXISTS history (id SERIAL PRIMARY KEY, user_id BIGINT, role TEXT, content TEXT, created_at TIMESTAMP DEFAULT NOW())",
            "CREATE TABLE IF NOT EXISTS habits (id SERIAL PRIMARY KEY, user_id BIGINT, name TEXT, created_at TIMESTAMP DEFAULT NOW())",
            "CREATE TABLE IF NOT EXISTS habit_logs (id SERIAL PRIMARY KEY, user_id BIGINT, habit_id INTEGER, logged_at TIMESTAMP DEFAULT NOW())",
            "CREATE TABLE IF NOT EXISTS finances (id SERIAL PRIMARY KEY, user_id BIGINT, amount FLOAT, type TEXT, category TEXT, description TEXT, created_at TIMESTAMP DEFAULT NOW())",
            "CREATE TABLE IF NOT EXISTS sleep_logs (id SERIAL PRIMARY KEY, user_id BIGINT, bedtime TEXT, wake_time TEXT, created_at TIMESTAMP DEFAULT NOW())",
            "CREATE TABLE IF NOT EXISTS notes (id SERIAL PRIMARY KEY, user_id BIGINT, text TEXT, created_at TIMESTAMP DEFAULT NOW())",
            "CREATE TABLE IF NOT EXISTS user_memory (id SERIAL PRIMARY KEY, user_id BIGINT, key TEXT, value TEXT, updated_at TIMESTAMP DEFAULT NOW())",
            "CREATE TABLE IF NOT EXISTS shopping_list (id SERIAL PRIMARY KEY, user_id BIGINT, item TEXT, done BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT NOW())",
            "CREATE TABLE IF NOT EXISTS saved_recipes (id SERIAL PRIMARY KEY, user_id BIGINT, title TEXT, content TEXT, created_at TIMESTAMP DEFAULT NOW())",
            "CREATE TABLE IF NOT EXISTS planner (id SERIAL PRIMARY KEY, user_id BIGINT, day_of_week INTEGER, time_str TEXT, title TEXT, created_at TIMESTAMP DEFAULT NOW())",
            "CREATE TABLE IF NOT EXISTS events (id SERIAL PRIMARY KEY, user_id BIGINT, title TEXT, person_name TEXT, event_date DATE, event_time TEXT, repeat_type TEXT DEFAULT 'once', repeat_day INTEGER, repeat_month_day INTEGER, created_at TIMESTAMP DEFAULT NOW())",
            "CREATE TABLE IF NOT EXISTS cycle_tracking (id SERIAL PRIMARY KEY, user_id BIGINT, start_date DATE, cycle_length INTEGER DEFAULT 28, created_at TIMESTAMP DEFAULT NOW())",
            "CREATE TABLE IF NOT EXISTS medications (id SERIAL PRIMARY KEY, user_id BIGINT, name TEXT, time_str TEXT, created_at TIMESTAMP DEFAULT NOW())",
            "CREATE TABLE IF NOT EXISTS medication_logs (id SERIAL PRIMARY KEY, user_id BIGINT, med_id INTEGER, taken_at TIMESTAMP DEFAULT NOW())",
            "CREATE TABLE IF NOT EXISTS stress_logs (id SERIAL PRIMARY KEY, user_id BIGINT, level INTEGER, note TEXT, created_at TIMESTAMP DEFAULT NOW())",
            "CREATE TABLE IF NOT EXISTS goals (id SERIAL PRIMARY KEY, user_id BIGINT, title TEXT, description TEXT, deadline DATE, progress INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT NOW())",
            "CREATE TABLE IF NOT EXISTS weight_logs (id SERIAL PRIMARY KEY, user_id BIGINT, weight FLOAT, height FLOAT, created_at TIMESTAMP DEFAULT NOW())",
            "CREATE TABLE IF NOT EXISTS nutrition_profile (id SERIAL PRIMARY KEY, user_id BIGINT, height FLOAT, weight FLOAT, age INTEGER, goal TEXT, calories_goal INTEGER, pregnant BOOLEAN DEFAULT FALSE, medications TEXT, created_at TIMESTAMP DEFAULT NOW())",
            "CREATE TABLE IF NOT EXISTS food_logs (id SERIAL PRIMARY KEY, user_id BIGINT, description TEXT, calories INTEGER, protein FLOAT, fat FLOAT, carbs FLOAT, created_at TIMESTAMP DEFAULT NOW())",
            "CREATE TABLE IF NOT EXISTS birthdays (id SERIAL PRIMARY KEY, user_id BIGINT, person_name TEXT, birth_date TEXT, created_at TIMESTAMP DEFAULT NOW())",
            "CREATE TABLE IF NOT EXISTS mood_logs (id SERIAL PRIMARY KEY, user_id BIGINT, mood INTEGER, note TEXT, created_at TIMESTAMP DEFAULT NOW())",
            "CREATE TABLE IF NOT EXISTS water_logs (id SERIAL PRIMARY KEY, user_id BIGINT, glasses INTEGER DEFAULT 0, log_date DATE DEFAULT CURRENT_DATE, created_at TIMESTAMP DEFAULT NOW())",
        ]
        for tbl in tables:
            await conn.execute(tbl)
        # Миграция events таблицы
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    title TEXT,
                    person_name TEXT DEFAULT '',
                    event_date DATE,
                    event_time TEXT DEFAULT '',
                    repeat_type TEXT DEFAULT 'once',
                    repeat_day INTEGER DEFAULT -1,
                    repeat_month_day INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
        except:
            pass

        for col, defn in [
            ("city","TEXT DEFAULT 'Москва'"), ("water_reminders","BOOLEAN DEFAULT FALSE"),
            ("water_interval","INTEGER DEFAULT 2"), ("morning_weather","BOOLEAN DEFAULT FALSE"),
            ("morning_motivation","BOOLEAN DEFAULT FALSE"), ("language","TEXT DEFAULT 'ru'"),
            ("evening_news","BOOLEAN DEFAULT FALSE"), ("evening_time","TEXT DEFAULT '21:00'"),
            ("comm_style","TEXT DEFAULT 'наставник'"),
        ]:
            try:
                await conn.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {defn}")
            except:
                pass

async def get_user(user_id):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)

async def save_user(user_id, **kwargs):
    async with db_pool.acquire() as conn:
        exists = await conn.fetchrow("SELECT user_id FROM users WHERE user_id = $1", user_id)
        if exists:
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
        return "\n".join([f"{r['key']}: {r['value']}" for r in rows]) if rows else ""

async def save_memory_item(user_id, key, value):
    async with db_pool.acquire() as conn:
        ex = await conn.fetchrow("SELECT id FROM user_memory WHERE user_id = $1 AND key = $2", user_id, key)
        if ex:
            await conn.execute("UPDATE user_memory SET value = $1, updated_at = NOW() WHERE user_id = $2 AND key = $3", value, user_id, key)
        else:
            await conn.execute("INSERT INTO user_memory (user_id, key, value) VALUES ($1, $2, $3)", user_id, key, value)

async def extract_and_save_memory(user_id, user_text, lang):
    kw_ru = ["меня зовут","мой ","моя ","моё ","мои ","я работаю","я живу","я учусь","ребёнок","дети","муж","жена","день рождения","люблю","не люблю","аллергия"]
    kw_en = ["my name","my ","i work","i live","i study","birthday","i love","i hate","allergy"]
    if not any(k in user_text.lower() for k in (kw_ru if lang=="ru" else kw_en)) or len(user_text) < 10:
        return
    try:
        system = 'Извлекай ТОЛЬКО конкретные личные факты. ТОЛЬКО валидный JSON: {"ключ": "значение"} или {}'
        resp = ai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"system","content":system},{"role":"user","content":user_text}], max_tokens=150, temperature=0.1)
        result = resp.choices[0].message.content.strip().replace("```json","").replace("```","").strip()
        if result and result != "{}":
            for k, v in json.loads(result).items():
                if v and isinstance(v, str):
                    await save_memory_item(user_id, k, v)
    except:
        pass

async def get_history_db(user_id, limit=25):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT role, content FROM history WHERE user_id = $1 AND role != 'system' ORDER BY created_at DESC LIMIT $2", user_id, limit)
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

async def add_history(user_id, role, content):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO history (user_id, role, content) VALUES ($1, $2, $3)", user_id, role, content)
        await conn.execute("DELETE FROM history WHERE id IN (SELECT id FROM history WHERE user_id = $1 ORDER BY created_at DESC OFFSET 500)", user_id)

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

# ─── УВЕДОМЛЕНИЯ АДМИНУ ─────────────────────────────────────────────────────────
# ВАЖНО: notify_admin и notify_admin_event шлют ТОЛЬКО на ADMIN_ID = 944447597
# Это Telegram-чат Ирины "Sofia Admin" — НЕ чат с ботом "София Ассистент"

async def notify_admin(context, user_name, username, user_text, reply):
    """Дублирует ВСЕ переписки пользователей администратору (ADMIN_ID)."""
    try:
        msg = f"👤 {user_name} @{username}:\n{user_text}\n\n🤖 София:\n{reply}"
        await context.bot.send_message(chat_id=ADMIN_ID, text=msg[:4000])
    except Exception as e:
        logging.error(f"notify_admin error: {e}")

async def notify_admin_event(context, text):
    """Системные события — новые пользователи, онбординг и т.д."""
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=text[:4000])
    except Exception as e:
        logging.error(f"notify_admin_event error: {e}")

# ─── ПОГОДА ─────────────────────────────────────────────────────────────────────
async def get_timezone_by_city(city):
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.get("https://api.openweathermap.org/data/2.5/weather", params={"q": city, "appid": WEATHER_API_KEY})
        data = r.json()
        if data.get("cod") != 200:
            return "Europe/Moscow"
        tz = tf.timezone_at(lat=data["coord"]["lat"], lng=data["coord"]["lon"])
        return tz or "Europe/Moscow"
    except:
        return "Europe/Moscow"

async def get_weather(city, lang="ru"):
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.get("https://api.openweathermap.org/data/2.5/weather", params={"q": city, "appid": WEATHER_API_KEY, "units": "metric", "lang": lang})
        data = r.json()
        if data.get("cod") != 200:
            return "Не удалось получить погоду." if lang=="ru" else "Could not get weather."
        temp = round(data["main"]["temp"])
        feels = round(data["main"]["feels_like"])
        desc = data["weather"][0]["description"]
        humidity = data["main"]["humidity"]
        wind = data["wind"]["speed"]
        city_form = city_in_form(city) if lang=="ru" else city
        if lang == "en":
            advice = "🧥 Dress warmly!" if temp<0 else "🧣 Take a jacket." if temp<10 else "👕 Light jacket." if temp<18 else "☀️ Perfect weather!"
            if "rain" in desc: advice += " ☂️ Umbrella!"
            return f"Weather in {city}:\n\n🌡 {temp}°C (feels {feels}°C)\n{desc.capitalize()}\nHumidity: {humidity}%\nWind: {wind} m/s\n\n{advice}"
        else:
            advice = "🧥 Оденьтесь тепло!" if temp<0 else "🧣 Возьмите куртку." if temp<10 else "👕 Лёгкая куртка." if temp<18 else "☀️ Отличная погода!"
            if "дождь" in desc or "ливень" in desc: advice += " ☂️ Зонт!"
            return f"Погода в {city_form}:\n\n🌡 {temp}°C (ощущается {feels}°C)\n{desc.capitalize()}\nВлажность: {humidity}%\nВетер: {wind} м/с\n\n{advice}"
    except Exception as e:
        logging.error(f"Погода: {e}")
        return "Погода недоступна." if lang=="ru" else "Weather unavailable."

async def get_weather_hourly(city, lang="ru"):
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.get("https://api.openweathermap.org/data/2.5/forecast", params={"q": city, "appid": WEATHER_API_KEY, "units": "metric", "lang": lang, "cnt": 8})
        data = r.json()
        if data.get("cod") != "200":
            return None
        city_form = city_in_form(city) if lang=="ru" else city
        lines = []
        for item in data["list"][:8]:
            dt = datetime.fromtimestamp(item["dt"])
            lines.append(f"{dt.strftime('%H:%M')} — {round(item['main']['temp'])}°C, {item['weather'][0]['description']}")
        title = f"Погода в {city_form} по часам:" if lang=="ru" else f"Hourly weather in {city}:"
        return f"{title}\n\n" + "\n".join(lines)
    except:
        return None

async def get_weather_forecast(city, lang="ru"):
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.get("https://api.openweathermap.org/data/2.5/forecast", params={"q": city, "appid": WEATHER_API_KEY, "units": "metric", "lang": lang, "cnt": 40})
        data = r.json()
        if data.get("cod") != "200":
            return None
        city_form = city_in_form(city) if lang=="ru" else city
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
            date_str = f"{dt.day} {months_ru[dt.month-1]}" if lang=="ru" else dt.strftime("%b %d")
            result.append(f"{date_str}: {round(min(info['temps']))}°C — {round(max(info['temps']))}°C, {info['desc']}")
        title = f"Прогноз погоды в {city_form}:" if lang=="ru" else f"Weather forecast for {city}:"
        return f"{title}\n\n" + "\n".join(result)
    except:
        return None

# ─── НОВОСТИ / ПОИСК ────────────────────────────────────────────────────────────
async def fetch_articles(query, count=10, page=1):
    if not NEWS_API_KEY:
        return []
    try:
        params = {"apiKey": NEWS_API_KEY, "q": query, "language": "en", "pageSize": count, "sortBy": "publishedAt", "page": page}
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.get("https://newsapi.org/v2/everything", params=params)
        data = r.json()
        if data.get("status") != "ok":
            return []
        articles = []
        for a in data.get("articles", []):
            title = a.get("title", "").split(" - ")[0].strip()
            if title and title != "[Removed]" and len(title) > 10:
                articles.append({"title": title, "description": a.get("description",""), "url": a.get("url","")})
        return articles[:count]
    except Exception as e:
        logging.error(f"fetch_articles: {e}")
        return []

async def translate_titles(titles, lang="ru"):
    if lang != "ru":
        return titles
    try:
        text = "\n".join([f"{i+1}. {t}" for i, t in enumerate(titles)])
        resp = ai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"system","content":"Переведи заголовки на русский. ТОЛЬКО строки вида: 1. Заголовок"},{"role":"user","content":text}], max_tokens=800, temperature=0.1)
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
        title = article.get("title","")
        desc = article.get("description","")
        url = article.get("url","")
        prompt = f"Расскажи подробнее об этой теме: {title}. {desc}\n\nНапиши 3-4 абзаца по-человечески, без форматирования." if lang=="ru" else f"Tell more about: {title}. {desc}\n\nWrite 3-4 paragraphs, conversational."
        resp = ai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":prompt}], max_tokens=600, temperature=0.7)
        summary = resp.choices[0].message.content.strip()
        if url:
            link = "Читать оригинал" if lang=="ru" else "Read original"
            return f"{summary}\n\n🔗 {link}: {url}"
        return summary
    except:
        return article.get("description") or "Описание недоступно."

async def get_news(query=None, lang="ru"):
    articles = await fetch_articles(query or "positive world news", 5)
    if not articles:
        return None
    titles = [a["title"] for a in articles]
    translated = await translate_titles(titles, lang)
    return "\n".join([f"{i+1}. {t}" for i, t in enumerate(translated)])

async def web_search_tavily(query, lang="ru"):
    if not TAVILY_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.post("https://api.tavily.com/search", json={
                "api_key": TAVILY_API_KEY, "query": query,
                "search_depth": "basic", "max_results": 5, "include_answer": True,
            })
        data = r.json()
        if data.get("answer"):
            sources = []
            for res in data.get("results", [])[:3]:
                if res.get("title") and res.get("url"):
                    sources.append(res["title"] + ": " + res["url"])
            src_label = "Источники" if lang=="ru" else "Sources"
            return data["answer"] + ("\n\n" + src_label + ":\n" + "\n".join(sources) if sources else "")
        results = data.get("results", [])
        if results:
            lines = [r.get("title","") + "\n" + r.get("content","")[:200] for r in results[:4] if r.get("title")]
            return "\n\n".join(lines) if lines else None
        return None
    except Exception as e:
        logging.error(f"Tavily: {e}")
        return None

# ─── ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЙ ──────────────────────────────────────────────────────
async def generate_image(prompt):
    try:
        response = ai_client.images.generate(model="gpt-image-1-mini", prompt=prompt, size="1024x1024", n=1)
        item = response.data[0]
        if hasattr(item, "url") and item.url:
            return item.url
        elif hasattr(item, "b64_json") and item.b64_json:
            return f"data:image/png;base64,{item.b64_json}"
        return None
    except Exception as e:
        logging.error(f"Image gen: {e}")
        return None

async def get_recipe_list(cat_key, lang="ru"):
    topic = RECIPE_CATEGORIES.get(cat_key, "блюда")
    try:
        resp = ai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":"Предложи 5 разных названий блюд на тему: " + topic + ". ТОЛЬКО пронумерованный список 1-5."}], max_tokens=150, temperature=0.9)
        return resp.choices[0].message.content.strip()
    except:
        return None

async def get_full_recipe(dish_name, lang="ru"):
    try:
        resp = ai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":"Напиши подробный рецепт: " + dish_name + ". Ингредиенты и пошаговое приготовление. По-человечески, без звёздочек."}], max_tokens=600, temperature=0.7)
        return resp.choices[0].message.content.strip()
    except:
        return None

async def get_ai_movie(lang="ru"):
    try:
        prompt = "Посоветуй один фильм или сериал. Название, жанр, описание, почему стоит. По-человечески." if lang=="ru" else "Recommend one movie or series. Title, genre, brief description. Conversational."
        resp = ai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"system","content":prompt},{"role":"user","content":"Что посмотреть?"}], max_tokens=250, temperature=0.9)
        return resp.choices[0].message.content
    except:
        return "Рекомендация недоступна."

async def analyze_image(image_data, user_question, lang="ru"):
    try:
        prompt = user_question if user_question else ("Опиши что на этом фото подробно" if lang=="ru" else "Describe what's in this photo in detail")
        resp = ai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{image_data}"}}]}], max_tokens=600)
        return resp.choices[0].message.content
    except Exception as e:
        logging.error(f"analyze_image: {e}")
        return "Не удалось проанализировать фото."

async def analyze_food_photo(image_data):
    try:
        prompt = "Определи что на фото еды. Оцени порцию и дай КБЖУ.\nОтвечай ТОЛЬКО в формате:\nБлюдо: название\nПорция: примерно X г\nКалории: число\nБелки: число г\nЖиры: число г\nУглеводы: число г\nКомментарий: совет"
        resp = ai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,"+image_data}}]}], max_tokens=250)
        return resp.choices[0].message.content
    except Exception as e:
        logging.error(f"analyze_food: {e}")
        return None

# ─── ВСПОМОГАТЕЛЬНЫЕ ────────────────────────────────────────────────────────────
def calculate_sleep_times(wake_hour, wake_minute):
    total = wake_hour * 60 + wake_minute
    times = []
    for cycles in [6, 5, 4]:
        sleep_min = total - cycles * 90 - 15
        if sleep_min < 0:
            sleep_min += 24 * 60
        h, m = sleep_min // 60, sleep_min % 60
        times.append(f"{h:02d}:{m:02d} ({cycles} цикла = {cycles * 1.5:.0f}ч)")
    return times

def extract_exact_time(text):
    m = re.search(r'(\d{1,2})[:\.](\d{2})', text)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mn <= 59:
            return h, mn
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
    kw = ["новост","что случилось","что происходит","последние события","в мире сейчас","расскажи новости","news","what happened","latest events","current events"]
    return any(k in text.lower() for k in kw)

def is_image_gen_request(text):
    kw = ["нарисуй","сгенерируй картинку","создай изображение","сделай картинку","draw","generate image","create image","make a picture"]
    return any(k in text.lower() for k in kw)

def is_weather_request(text):
    kw = ["погода","какая погода","погоду","температура","тепло ли","холодно ли","weather","temperature","rain","sunny","cold outside","warm outside"]
    return any(k in text.lower() for k in kw)

def is_change_style_request(text):
    kw = ["измени стиль","смени стиль","общайся как","хочу чтобы ты общалась","перейди на","говори со мной как","change style","communicate as","talk to me as"]
    return any(k in text.lower() for k in kw)

def is_search_request(text):
    kw = ["найди","поищи","загугли","что такое","кто такой","найти информацию","search for","find information","what is","who is"]
    return any(k in text.lower() for k in kw)

async def rephrase_reminder(text, lang="ru"):
    try:
        system = "Перефразируй как напоминание — коротко, без 'мне', без 'напомни', без времени. Только суть."
        resp = ai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"system","content":system},{"role":"user","content":text}], max_tokens=80, temperature=0.3)
        result = resp.choices[0].message.content.strip()
        return result[0].upper() + result[1:] if result else text
    except:
        return text

# ─── ПЕРИОДИЧЕСКИЕ ЗАДАЧИ ───────────────────────────────────────────────────────

async def parse_events_ai(user_text, user_id):
    """AI парсит сообщение и возвращает список событий"""
    from datetime import date as _d, datetime as _dt
    today = _d.today()
    try:
        system = f"""Сегодня {today.strftime('%d.%m.%Y')}, {['понедельник','вторник','среда','четверг','пятница','суббота','воскресенье'][today.weekday()]}.

Извлеки все события из сообщения. Ответь ТОЛЬКО валидным JSON массивом:
[
  {{
    "title": "название события",
    "person": "имя человека или пустая строка",
    "time": "ЧЧ:ММ или пустая строка",
    "repeat_type": "once/weekly/monthly_day/daily",
    "date": "ДД.ММ.ГГГГ если конкретная дата, иначе пустая строка",
    "weekdays": [0,1,2,3,4,5,6] если еженедельно (0=пн), иначе [],
    "month_day": число если каждое N-е число месяца, иначе 0
  }}
]

Примеры:
"пилатес каждую пятницу в 10:00" → repeat_type=weekly, weekdays=[4], time=10:00
"ногти каждое 1-е число в 17:00" → repeat_type=monthly_day, month_day=1, time=17:00
"завтра в 14:00 стрижка" → repeat_type=once, date=завтрашняя дата
"у Влада тренировка пн вт ср чт пт в 15:00, у Лизы танцы вт чт в 18:00" → два события
"""
        resp = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"system","content":system},{"role":"user","content":user_text}],
            max_tokens=600, temperature=0.1
        )
        result = resp.choices[0].message.content.strip()
        result = result.replace("```json","").replace("```","").strip()
        events = json.loads(result)
        return events if isinstance(events, list) else []
    except Exception as e:
        logging.error(f"parse_events_ai: {e}")
        return []

async def save_events_to_db(user_id, events):
    """Сохраняет распарсенные события в БД"""
    from datetime import date as _d, datetime as _dt
    today = _d.today()
    saved = []
    async with db_pool.acquire() as conn:
        for ev in events:
            title = ev.get("title","")
            person = ev.get("person","")
            ev_time = ev.get("time","") or ""
            repeat_type = ev.get("repeat_type","once")
            date_str = ev.get("date","")
            weekdays = ev.get("weekdays",[])
            month_day = ev.get("month_day",0)

            if not title:
                continue

            # Конкретная дата
            if repeat_type == "once":
                try:
                    ev_date = _dt.strptime(date_str, "%d.%m.%Y").date() if date_str else today
                except:
                    ev_date = today
                await conn.execute(
                    "INSERT INTO events (user_id, title, person_name, event_date, event_time, repeat_type) VALUES ($1,$2,$3,$4,$5,$6)",
                    user_id, title, person, ev_date, ev_time, "once"
                )
                saved.append(f"{ev_date.strftime('%d.%m')} {ev_time} — {title}" + (f" ({person})" if person else ""))

            # Еженедельно
            elif repeat_type == "weekly" and weekdays:
                for wd in weekdays:
                    # Найти ближайшую дату этого дня недели
                    days_ahead = wd - today.weekday()
                    if days_ahead < 0:
                        days_ahead += 7
                    from datetime import timedelta
                    next_date = today + timedelta(days=days_ahead)
                    await conn.execute(
                        "INSERT INTO events (user_id, title, person_name, event_date, event_time, repeat_type, repeat_day) VALUES ($1,$2,$3,$4,$5,$6,$7)",
                        user_id, title, person, next_date, ev_time, "weekly", wd
                    )
                days_names = ["пн","вт","ср","чт","пт","сб","вс"]
                days_str = ", ".join([days_names[d] for d in sorted(weekdays)])
                saved.append(f"Каждые {days_str} в {ev_time} — {title}" + (f" ({person})" if person else ""))

            # Каждое N-е число
            elif repeat_type == "monthly_day" and month_day:
                from datetime import timedelta
                # Найти ближайшую дату
                if today.day <= month_day:
                    try:
                        next_date = today.replace(day=month_day)
                    except:
                        next_date = today
                else:
                    m = today.month + 1 if today.month < 12 else 1
                    y = today.year if today.month < 12 else today.year + 1
                    try:
                        next_date = today.replace(year=y, month=m, day=month_day)
                    except:
                        next_date = today
                await conn.execute(
                    "INSERT INTO events (user_id, title, person_name, event_date, event_time, repeat_type, repeat_month_day) VALUES ($1,$2,$3,$4,$5,$6,$7)",
                    user_id, title, person, next_date, ev_time, "monthly_day", month_day
                )
                saved.append(f"Каждое {month_day}-е число в {ev_time} — {title}" + (f" ({person})" if person else ""))

    return saved

async def get_upcoming_events(user_id, days=14):
    """Получить события на ближайшие N дней"""
    from datetime import date as _d, timedelta, datetime as _dt
    today = _d.today()
    result = {}

    async with db_pool.acquire() as conn:
        # Разовые события
        rows = await conn.fetch(
            "SELECT * FROM events WHERE user_id=$1 AND event_date >= $2 AND event_date <= $3 AND repeat_type='once' ORDER BY event_date, event_time",
            user_id, today, today + timedelta(days=days)
        )
        for r in rows:
            key = r["event_date"]
            if key not in result: result[key] = []
            result[key].append(r)

        # Еженедельные — генерируем даты
        weekly = await conn.fetch(
            "SELECT * FROM events WHERE user_id=$1 AND repeat_type='weekly'", user_id
        )
        for r in weekly:
            wd = r["repeat_day"]
            for i in range(days+1):
                d = today + timedelta(days=i)
                if d.weekday() == wd:
                    if d not in result: result[d] = []
                    result[d].append(r)

        # Ежемесячные
        monthly = await conn.fetch(
            "SELECT * FROM events WHERE user_id=$1 AND repeat_type='monthly_day'", user_id
        )
        for r in monthly:
            md = r["repeat_month_day"]
            for i in range(days+1):
                d = today + timedelta(days=i)
                if d.day == md:
                    if d not in result: result[d] = []
                    result[d].append(r)

    # Сортируем по дате
    sorted_result = {}
    for k in sorted(result.keys()):
        evs = sorted(result[k], key=lambda x: x["event_time"] or "00:00")
        sorted_result[k] = evs
    return sorted_result

def format_events_text(events_by_date, lang="ru"):
    """Форматирует события как текст"""
    from datetime import date as _d
    today = _d.today()
    months_ru = ["января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"]
    days_names = ["Понедельник","Вторник","Среда","Четверг","Пятница","Суббота","Воскресенье"]

    if not events_by_date:
        return "Событий пока нет. Напишите что добавить!"

    lines = []
    for date, evs in events_by_date.items():
        if date == today:
            day_label = "Сегодня"
        elif (date - today).days == 1:
            day_label = "Завтра"
        else:
            day_label = days_names[date.weekday()]
        date_str = f"{date.day} {months_ru[date.month-1]}"
        lines.append(f"\n📅 {day_label}, {date_str}")
        for ev in evs:
            time_part = f"{ev['event_time']} " if ev['event_time'] else ""
            person_part = f" ({ev['person_name']})" if ev['person_name'] else ""
            repeat_icon = "🔄" if ev['repeat_type'] != 'once' else "•"
            lines.append(f"{repeat_icon} {time_part}{ev['title']}{person_part}")
    return "\n".join(lines)


async def send_scheduled_reminder(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    user = await get_user(job_data["user_id"])
    name = user["name"] if user else ""
    lang = user.get("language","ru") if user else "ru"
    await context.bot.send_message(chat_id=job_data["user_id"], text=t(lang, "reminder", name=name, text=job_data["essence"]))

async def send_med_reminder(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    user = await get_user(job_data["user_id"])
    name = user["name"] if user else ""
    await context.bot.send_message(chat_id=job_data["user_id"], text=f"💊 {name}, не забудьте принять {job_data['med_name']}!")

async def send_water_reminder(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    user = await get_user(user_id)
    name = user["name"] if user else ""
    lang = user.get("language","ru") if user else "ru"
    await context.bot.send_message(chat_id=user_id, text=t(lang, "water", name=name))

async def send_morning_plan(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    user = await get_user(user_id)
    if not user:
        return
    lang = user.get("language","ru")
    reminders = await get_reminders(user_id)
    text = t(lang, "morning", name=user["name"])
    if user.get("morning_motivation"):
        text += f"{random.choice(MOTIVATIONAL_QUOTES[lang])}\n\n"
    if user.get("morning_weather"):
        text += (await get_weather(user.get("city") or "Москва", lang)) + "\n\n"
    if reminders:
        plan = "\n".join([f"{r['time']} — {r['text']}" for r in sorted(reminders, key=lambda x: x["time"])])
        text += ("Ваш план на сегодня:" if lang=="ru" else "Your plan for today:") + f"\n\n{plan}"
    else:
        text += t(lang, "no_plan")
    await context.bot.send_message(chat_id=user_id, text=text)

async def send_evening_news(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    user = await get_user(user_id)
    if not user:
        return
    lang = user.get("language","ru")
    dt = get_current_datetime(user.get("timezone","Europe/Moscow"))
    try:
        async with db_pool.acquire() as conn:
            habits = await conn.fetch("SELECT id, name FROM habits WHERE user_id = $1", user_id)
            habit_lines = []
            for h in habits:
                count = await conn.fetchval("SELECT COUNT(*) FROM habit_logs WHERE habit_id = $1 AND logged_at >= NOW() - INTERVAL '1 day'", h["id"])
                habit_lines.append(h["name"] + ": " + ("выполнена" if count > 0 else "не отмечена"))
            income = await conn.fetchval("SELECT SUM(amount) FROM finances WHERE user_id = $1 AND type = 'income' AND created_at >= NOW() - INTERVAL '1 day'", user_id) or 0
            expense = await conn.fetchval("SELECT SUM(amount) FROM finances WHERE user_id = $1 AND type = 'expense' AND created_at >= NOW() - INTERVAL '1 day'", user_id) or 0
        habits_text = ", ".join(habit_lines) if habit_lines else "привычки не добавлены"
        date_str = dt["ru"] if lang=="ru" else dt["en"]
        data_block = f"Привычки за сегодня: {habits_text}\nФинансы: доходы {int(income)}, расходы {int(expense)}"
        comm_style = user.get("comm_style", "наставник")
        try:
            async with db_pool.acquire() as conn3:
                tasks_done = await conn3.fetchval("SELECT COUNT(*) FROM notes WHERE user_id=$1 AND text LIKE 'DONE:%'", user_id) or 0
                tasks_active = await conn3.fetchval("SELECT COUNT(*) FROM notes WHERE user_id=$1 AND text LIKE 'TASK:%'", user_id) or 0
                active_goals = await conn3.fetch("SELECT title, progress FROM goals WHERE user_id=$1 AND progress < 100 LIMIT 3", user_id)
        except:
            tasks_done = 0
            tasks_active = 0
            active_goals = []
        goals_text = ""
        if active_goals:
            goals_list = [str(g["title"]) + " (" + str(g["progress"]) + "%)" for g in active_goals]
            goals_text = "Активные цели: " + ", ".join(goals_list)
        uname = user["name"]
        prompt = (
            f"Составь короткий вечерний отчёт для {uname}. Сегодня {date_str}. Стиль: {comm_style}.\n\n"
            f"Данные: {data_block}\n"
            f"Задач выполнено: {tasks_done}. Задач осталось: {tasks_active}.\n"
            f"{goals_text}\n\n"
            "ПРАВИЛА: максимум 5-6 строк. Только конкретика по данным. "
            "Если нет данных — спроси как прошёл день. Предложи 1 задачу на завтра. "
            "Если есть цели — упомяни прогресс. Никаких общих фраз. Без markdown. "
            "В конце 1 вопрос: что главное успели сделать сегодня?"
        )
    except Exception as e:
        logging.error(f"evening_news: {e}")

async def check_cycle_reminders(context: ContextTypes.DEFAULT_TYPE):
    try:
        async with db_pool.acquire() as conn:
            users = await conn.fetch("SELECT user_id FROM users WHERE onboarded = TRUE")
        from datetime import date as _d, timedelta as _td
        today = _d.today()
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
                    next_start = next_start + _td(days=length)
                days_left = (next_start - today).days
                if days_left in [3, 1]:
                    user = await get_user(uid)
                    name = user["name"] if user else ""
                    days_word = "день" if days_left == 1 else "дня"
                    await context.application.bot.send_message(chat_id=uid, text=f"{name}, через {days_left} {days_word} ожидается начало цикла. Подготовьтесь заранее! 🩸")
            except:
                pass
    except Exception as e:
        logging.error(f"cycle_check: {e}")

async def check_goal_reminders(context: ContextTypes.DEFAULT_TYPE):
    try:
        async with db_pool.acquire() as conn:
            users = await conn.fetch("SELECT user_id FROM users WHERE onboarded = TRUE")
        from datetime import date as _d
        today = _d.today()
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
                goal = random.choice(list(goals))
                variants = [
                    f"{name}, как дела с целью \"{goal['title']}\"? 🎯 Расскажите что удалось!",
                    f"Привет, {name}! Есть ли прогресс по цели \"{goal['title']}\"? 🌸",
                    f"{name}, помните про цель \"{goal['title']}\"? Прогресс {goal['progress']}%. Что нового? 💪",
                ]
                await context.application.bot.send_message(chat_id=uid, text=random.choice(variants))
            except:
                pass
    except Exception as e:
        logging.error(f"goal_check: {e}")

async def send_midday_checkin(context: ContextTypes.DEFAULT_TYPE):
    """В 17:00 спрашивает что успели сделать"""
    try:
        async with db_pool.acquire() as conn:
            users = await conn.fetch("SELECT user_id FROM users WHERE onboarded=TRUE AND evening_news=TRUE")
        for ur in users:
            uid = ur["user_id"]
            try:
                user = await get_user(uid)
                if not user: continue
                name = user["name"]
                lang = user.get("language","ru")
                comm_style = user.get("comm_style","наставник")
                async with db_pool.acquire() as conn:
                    goals = await conn.fetch("SELECT title FROM goals WHERE user_id=$1 AND progress < 100 LIMIT 2", uid)
                goals_mention = ""
                if goals:
                    goals_mention = " Кстати, у вас есть активные цели: " + ", ".join([g["title"] for g in goals]) + "."
                if lang == "ru":
                    if comm_style == "подружка":
                        msg = f"Привет, {name}! Как дела? Что успела сделать за день?{goals_mention} 🌸"
                    elif comm_style == "мотиватор":
                        msg = f"{name}, день ещё не закончен! Что уже успела сделать? Давай проверим прогресс!{goals_mention} 💪"
                    else:
                        msg = f"{name}, добрый вечер. Как прошёл день? Что удалось выполнить?{goals_mention}"
                else:
                    msg = f"{name}, good evening! How was your day? What did you manage to accomplish?"
                await context.bot.send_message(chat_id=uid, text=msg)
            except:
                pass
    except Exception as e:
        logging.error(f"midday_checkin: {e}")

async def send_weekly_habit_report(context: ContextTypes.DEFAULT_TYPE):
    try:
        async with db_pool.acquire() as conn:
            users = await conn.fetch("SELECT user_id FROM users WHERE onboarded = TRUE")
        for ur in users:
            uid = ur["user_id"]
            try:
                async with db_pool.acquire() as conn:
                    habits = await conn.fetch("SELECT id, name FROM habits WHERE user_id = $1", uid)
                if not habits:
                    continue
                user = await get_user(uid)
                name = user["name"] if user else ""
                lines = []
                async with db_pool.acquire() as conn:
                    for h in habits:
                        count = await conn.fetchval("SELECT COUNT(*) FROM habit_logs WHERE habit_id = $1 AND logged_at >= NOW() - INTERVAL '7 days'", h["id"])
                        bar = "█" * count + "░" * (7 - min(count, 7))
                        pct = round(count / 7 * 100)
                        lines.append(f"{h['name']}: {bar} {count}/7 ({pct}%)")
                avg_pct = sum(int(l.split("(")[1].replace("%)", "")) for l in lines if "(" in l) / len(lines) if lines else 0
                summary = "Отличная неделя! Вы молодец 🌟" if avg_pct >= 80 else "Хорошие результаты! Продолжайте 💪" if avg_pct >= 50 else "На следующей неделе получится лучше 🌸"
                await context.application.bot.send_message(chat_id=uid, text=f"{name}, итоги недели по привычкам:\n\n" + "\n".join(lines) + f"\n\n{summary}")
            except:
                pass
    except Exception as e:
        logging.error(f"weekly_habits: {e}")

async def check_birthday_reminders(context: ContextTypes.DEFAULT_TYPE):
    try:
        async with db_pool.acquire() as conn:
            all_bdays = await conn.fetch("SELECT user_id, person_name, birth_date FROM birthdays")
        from datetime import date as _d, datetime as _dt
        today = _d.today()
        for b in all_bdays:
            try:
                bd_str = b["birth_date"]
                bd = (_dt.strptime(bd_str, "%d.%m.%Y").date() if len(bd_str) > 5 else _dt.strptime(bd_str, "%d.%m").replace(year=today.year).date()).replace(year=today.year)
                if bd < today:
                    bd = bd.replace(year=today.year + 1)
                days_left = (bd - today).days
                if days_left in [7, 3, 1, 0]:
                    user = await get_user(b["user_id"])
                    name = user["name"] if user else ""
                    msg = f"{name}, сегодня день рождения у {b['person_name']}! 🎉🎂 Не забудьте поздравить!" if days_left == 0 else f"{name}, через {'день' if days_left==1 else str(days_left)+' дн.'} день рождения у {b['person_name']} 🎂"
                    await context.application.bot.send_message(chat_id=b["user_id"], text=msg)
            except:
                pass
    except Exception as e:
        logging.error(f"birthday_check: {e}")

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
                    application.job_queue.run_daily(send_morning_plan, time=time(hour=h, minute=0, tzinfo=tz), data=user_id, name=f"morning_{user_id}")
                except:
                    pass
            if user.get("evening_news") and user.get("evening_time"):
                try:
                    h = int(user["evening_time"].split(":")[0])
                    application.job_queue.run_daily(send_evening_news, time=time(hour=h, minute=0, tzinfo=tz), data=user_id, name=f"evening_{user_id}")
                except:
                    pass
            if user.get("water_reminders"):
                try:
                    interval = user.get("water_interval") or 2
                    application.job_queue.run_repeating(send_water_reminder, interval=interval*3600, first=interval*3600, data=user_id, name=f"water_{user_id}")
                except:
                    pass
            async with db_pool.acquire() as conn:
                reminders = await conn.fetch("SELECT * FROM reminders WHERE user_id = $1", user_id)
            for r in reminders:
                try:
                    h, m = map(int, r["time_str"].split(":"))
                    application.job_queue.run_daily(send_scheduled_reminder, time=time(hour=h, minute=m, tzinfo=tz), data={"user_id": user_id, "essence": r["text"]}, name=f"reminder_{user_id}_{h}_{m}")
                except:
                    pass
            async with db_pool.acquire() as conn:
                meds = await conn.fetch("SELECT * FROM medications WHERE user_id = $1", user_id)
            for med in meds:
                try:
                    h, m = map(int, med["time_str"].split(":"))
                    application.job_queue.run_daily(send_med_reminder, time=time(hour=h, minute=m, tzinfo=tz), data={"user_id": user_id, "med_name": med["name"]}, name=f"med_{user_id}_{med['id']}")
                except:
                    pass
        logging.info("Напоминания восстановлены из БД")
    except Exception as e:
        logging.error(f"restore_reminders: {e}")

# ─── МЕНЮ ───────────────────────────────────────────────────────────────────────
def get_main_menu(lang="ru"):
    ru = lang == "ru"
    keyboard = [
        [
            InlineKeyboardButton("📅 Планирование" if ru else "📅 Planning", callback_data="sub_planning"),
            InlineKeyboardButton("🎯 Цели" if ru else "🎯 Goals", callback_data="sub_goals"),
        ],
        [
            InlineKeyboardButton("📓 Дневник" if ru else "📓 Diary", callback_data="sub_diary"),
            InlineKeyboardButton("❤️ Здоровье" if ru else "❤️ Health", callback_data="sub_health"),
        ],
        [InlineKeyboardButton("⚙️ Настройки" if ru else "⚙️ Settings", callback_data="menu_settings")],
        [InlineKeyboardButton("✨ Возможности Софии" if ru else "✨ Sofia's Features", callback_data="sub_about")],
        [InlineKeyboardButton("✖️ Закрыть меню" if ru else "✖️ Close", callback_data="close_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_submenu(section, lang="ru"):
    from telegram import WebAppInfo
    BASE = "https://sofia-production-fcc2.up.railway.app/planner.html"
    ru = lang == "ru"
    back = InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="back_main")
    
    if section == "planning":
        keyboard = [
            [InlineKeyboardButton("📆 Календарь", web_app=WebAppInfo(url=f"{BASE}?tab=planning&view=cal")),
             InlineKeyboardButton("✅ Задачи", web_app=WebAppInfo(url=f"{BASE}?tab=planning&view=tasks"))],
            [InlineKeyboardButton("⏰ Напоминания", web_app=WebAppInfo(url=f"{BASE}?tab=planning&view=rems")),
             InlineKeyboardButton("⏳ Таймер", web_app=WebAppInfo(url=f"{BASE}?tab=planning&view=timer"))],
            [back],
        ]
        title = "📅 Планирование" if ru else "📅 Planning"
    elif section == "goals":
        keyboard = [
            [InlineKeyboardButton("🔥 Активные цели", web_app=WebAppInfo(url=f"{BASE}?tab=goals&view=active")),
             InlineKeyboardButton("✅ Завершённые", web_app=WebAppInfo(url=f"{BASE}?tab=goals&view=done"))],
            [InlineKeyboardButton("📊 Статистика", web_app=WebAppInfo(url=f"{BASE}?tab=goals&view=stats"))],
            [back],
        ]
        title = "🎯 Цели" if ru else "🎯 Goals"
    elif section == "diary":
        keyboard = [
            [InlineKeyboardButton("🛒 Покупки", web_app=WebAppInfo(url=f"{BASE}?tab=diary&view=shop{uid_param}")),
             InlineKeyboardButton("💰 Финансы", web_app=WebAppInfo(url=f"{BASE}?tab=diary&view=fin{uid_param}"))],
            [InlineKeyboardButton("📝 Заметки", web_app=WebAppInfo(url=f"{BASE}?tab=diary&view=notes{uid_param}")),
             InlineKeyboardButton("🎂 Дни рождения", web_app=WebAppInfo(url=f"{BASE}?tab=diary&view=bdays{uid_param}"))],
            [InlineKeyboardButton("🍳 Рецепты", web_app=WebAppInfo(url=f"{BASE}?tab=diary&view=recipes{uid_param}"))],
            [back],
        ]
        title = "📓 Дневник" if ru else "📓 Diary"
    elif section == "health":
        keyboard = [
            [InlineKeyboardButton("💧 Вода", web_app=WebAppInfo(url=f"{BASE}?tab=health&view=water")),
             InlineKeyboardButton("💊 Таблетки", web_app=WebAppInfo(url=f"{BASE}?tab=health&view=meds"))],
            [InlineKeyboardButton("🩸 Цикл", web_app=WebAppInfo(url=f"{BASE}?tab=health&view=cycle")),
             InlineKeyboardButton("😰 Стресс", web_app=WebAppInfo(url=f"{BASE}?tab=health&view=stress"))],
            [back],
        ]
        title = "❤️ Здоровье" if ru else "❤️ Health"
    elif section == "about":
        keyboard = [
            [InlineKeyboardButton("✨ Открыть", web_app=WebAppInfo(url=f"{BASE}?tab=about"))],
            [back],
        ]
        title = "✨ Возможности Софии"
    else:
        return get_main_menu(lang)
    return title, InlineKeyboardMarkup(keyboard)

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    if not user or not user["onboarded"]:
        await update.message.reply_text(t("ru", "not_started"))
        return
    lang = user.get("language","ru")
    await update.message.reply_text("🌸", reply_markup=get_main_menu(lang))

async def skills_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    lang = user.get("language","ru") if user else "ru"
    await update.message.reply_text(SKILLS_RU if lang=="ru" else SKILLS_RU)

# ─── ОНБОРДИНГ ─── START = ВСЕГДА онбординг/приветствие, НЕ меню ────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start — точка входа.
    Если уже зарегистрирован → приветствуем и предлагаем открыть меню через /menu.
    Если новый → начинаем онбординг.
    ВАЖНО: /start НЕ открывает меню! Для меню есть /menu.
    """
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "Пользователь"
    username = update.effective_user.username or "нет username"
    existing = await get_user(user_id)
    if existing and existing.get("onboarded"):
        lang = existing.get("language","ru")
        name = existing.get("name","")
        if lang == "ru":
            msg = f"С возвращением, {name}! 🌸\n\nРада видеть тебя снова! Напиши /menu чтобы открыть меню."
        else:
            msg = f"Welcome back, {name}! 🌸\n\nGlad to see you again! Type /menu to open the menu."
        await update.message.reply_text(msg)
        return ConversationHandler.END
    await save_user(user_id, username=username)
    await update.message.reply_text(t("ru", "welcome"))
    await notify_admin_event(context, f"🆕 Новый пользователь!\nИмя: {user_name}\nUsername: @{username}\nID: {user_id}")
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
    keyboard = [["✅ Да, каждое утро" if lang=="ru" else "✅ Yes, every morning", "❌ Нет, не нужно" if lang=="ru" else "❌ No, thanks"]]
    await update.message.reply_text(t(lang, "ask_morning"), reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
    return ASK_MORNING_PLAN

async def ask_morning_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    lang = user.get("language","ru") if user else "ru"
    wants = "Да" in update.message.text or "Yes" in update.message.text
    await save_user(user_id, morning_plan=wants)
    if wants:
        keyboard = [["7:00","8:00","9:00"],["10:00","Другое" if lang=="ru" else "Other"]]
        await update.message.reply_text(t(lang, "ask_morning_time"), reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
        return ASK_MORNING_TIME
    return await ask_reminders_step(update, context)

async def ask_morning_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        hour = int(update.message.text.replace(":00","").replace(":30",""))
        morning_time = f"{hour:02d}:00"
    except:
        morning_time = "08:00"
    await save_user(user_id, morning_time=morning_time)
    return await ask_reminders_step(update, context)

async def ask_reminders_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    lang = user.get("language","ru") if user else "ru"
    keyboard = [["✅ За час","⏰ За 30 минут","❌ Не нужно"]] if lang=="ru" else [["✅ 1 hour before","⏰ 30 minutes before","❌ No thanks"]]
    await update.message.reply_text(t(lang, "ask_reminders"), reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
    return ASK_REMINDERS

async def finish_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    reminder_before = 60 if "час" in text or "1 hour" in text else 30 if "30" in text else 0
    await save_user(user_id, reminder_before=reminder_before)
    return await ask_evening_news_step(update, context)

async def ask_evening_news_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    lang = user.get("language","ru") if user else "ru"
    keyboard = [["✅ Да, вечером","❌ Не нужно"]] if lang=="ru" else [["✅ Yes, in the evening","❌ No thanks"]]
    await update.message.reply_text(t(lang, "ask_evening_news"), reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
    return ASK_EVENING_NEWS

async def handle_evening_news_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    lang = user.get("language","ru") if user else "ru"
    wants = "Да" in update.message.text or "Yes" in update.message.text
    await save_user(user_id, evening_news=wants)
    if wants:
        keyboard = [["20:00","21:00","22:00"],["19:00","Другое" if lang=="ru" else "Other"]]
        await update.message.reply_text(t(lang, "ask_evening_time"), reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
        return ASK_EVENING_TIME
    return await ask_comm_style_step(update, context)

async def handle_evening_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        hour = int(update.message.text.replace(":00","").replace(":30",""))
        evening_time = f"{hour:02d}:00"
    except:
        evening_time = "21:00"
    await save_user(user_id, evening_time=evening_time)
    return await ask_comm_style_step(update, context)

async def ask_comm_style_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    lang = user.get("language","ru") if user else "ru"
    if lang == "en":
        keyboard = [["👭 Friend — casual, on first name basis"],["🎯 Mentor — motivating, formal"],["💼 Professional — clear and concise"]]
        text = "How would you like me to communicate with you?"
    else:
        keyboard = [["👭 Подружка — тепло, неформально, на ты"],["🎯 Наставник — мотивирующий, на вы"],["🔥 Мотиватор — энергично, вдохновляюще"],["💼 Официальный помощник — строго, по делу"]]
        text = "Как вам удобнее чтобы я общалась с вами?"
    await update.message.reply_text(text, reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
    return ASK_COMM_STYLE

async def handle_comm_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    lang = user.get("language","ru") if user else "ru"
    text = update.message.text
    if "Подружка" in text or "Friend" in text:
        style = "подружка"
    elif "Наставник" in text or "Mentor" in text:
        style = "наставник"
    elif "Мотиватор" in text or "Motivator" in text:
        style = "мотиватор"
    elif "Официальный" in text or "Official" in text:
        style = "официальный помощник"
    elif "Профессионал" in text or "Professional" in text:
        style = "профессионал"
    else:
        style = text.strip()[:50]
    await save_user(user_id, comm_style=style)
    await save_memory_item(user_id, "стиль_общения", style)
    await update.message.reply_text(f"Отлично, запомнила! Стиль: {style} 🌸", reply_markup=ReplyKeyboardRemove())
    return await finish_onboarding_final(update, context)

async def finish_onboarding_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await save_user(user_id, onboarded=True)
    user = await get_user(user_id)
    lang = user.get("language","ru") if user else "ru"
    name = user["name"] if user else ""
    await update.message.reply_text(t(lang, "finish", name=name), reply_markup=ReplyKeyboardRemove())
    username = update.effective_user.username or "нет username"
    await notify_admin_event(context, f"✅ Онбординг завершён!\nИмя: {name}\nUsername: @{username}\nID: {user_id}\nСтиль: {user.get('comm_style','?')}\nЯзык: {lang}\nГород: {user.get('city','?')}")
    if user.get("morning_plan") and user.get("morning_time"):
        try:
            tz = pytz.timezone(user.get("timezone","Europe/Moscow"))
            h = int(user["morning_time"].split(":")[0])
            context.application.job_queue.run_daily(send_morning_plan, time=time(hour=h, minute=0, tzinfo=tz), data=user_id, name=f"morning_{user_id}")
        except:
            pass
    if user.get("evening_news") and user.get("evening_time"):
        try:
            tz = pytz.timezone(user.get("timezone","Europe/Moscow"))
            h = int(user["evening_time"].split(":")[0])
            context.application.job_queue.run_daily(send_evening_news, time=time(hour=h, minute=0, tzinfo=tz), data=user_id, name=f"evening_{user_id}")
        except:
            pass
    return ConversationHandler.END

# ─── КНОПКИ (button_handler) ────────────────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = await get_user(user_id)
    if not user:
        return
    name = user["name"]
    city = user.get("city") or "Москва"
    lang = user.get("language","ru")
    ru = lang == "ru"

    # Утро
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
            text = ("Ваш план на сегодня" if ru else "Your plan for today") + f":\n\n{plan}"
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
        await query.edit_message_text(hourly or ("Прогноз недоступен." if ru else "Forecast unavailable."), reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "morning_forecast":
        await query.edit_message_text("Получаю прогноз на неделю..." if ru else "Getting weekly forecast...")
        forecast = await get_weather_forecast(city, lang)
        back = InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_morning")
        await query.edit_message_text(forecast or ("Прогноз недоступен." if ru else "Forecast unavailable."), reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "morning_motivation":
        quote = random.choice(MOTIVATIONAL_QUOTES[lang])
        keyboard = [[InlineKeyboardButton("🔄 Ещё" if ru else "🔄 Another", callback_data="morning_motivation")],[InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_morning")]]
        await query.edit_message_text(("Мотивация дня" if ru else "Motivation") + f":\n\n{quote}", reply_markup=InlineKeyboardMarkup(keyboard))

    # Интересное
    elif query.data == "menu_interesting":
        keyboard = [
            [InlineKeyboardButton("🔬 Научные открытия" if ru else "🔬 Science", callback_data="interesting_science")],
            [InlineKeyboardButton("💻 Технологии и ИИ" if ru else "💻 Technology & AI", callback_data="interesting_technology")],
            [InlineKeyboardButton("💚 Здоровье и долголетие" if ru else "💚 Health", callback_data="interesting_health")],
            [InlineKeyboardButton("✨ Вдохновляющие истории" if ru else "✨ Inspiring Stories", callback_data="interesting_inspiration")],
            [InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="back_main")],
        ]
        await query.edit_message_text("Интересное — выберите тему:" if ru else "Choose a topic:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("interesting_"):
        category = query.data.replace("interesting_", "")
        cat_info = INTERESTING_QUERIES.get(category, {})
        title = cat_info.get("ru" if ru else "en", "Интересное")
        await query.edit_message_text(f"Загружаю {title}..." if ru else f"Loading {title}...")
        context.user_data.pop(f"interesting_articles_{category}", None)
        context.user_data.pop(f"interesting_translated_{category}", None)
        page = random.randint(1, 3)
        articles = await fetch_articles(cat_info.get("query","interesting news"), 10, page=page)
        if not articles:
            articles = await fetch_articles(cat_info.get("query","interesting news"), 10, page=1)
        if not articles:
            back = InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_interesting")
            await query.edit_message_text("Материалы временно недоступны." if ru else "Temporarily unavailable.", reply_markup=InlineKeyboardMarkup([[back]]))
            return
        titles = [a["title"] for a in articles]
        translated = await translate_titles(titles, lang)
        context.user_data[f"interesting_articles_{category}"] = articles
        context.user_data[f"interesting_translated_{category}"] = translated
        lines = [f"{i+1}. {tl}" for i, tl in enumerate(translated)]
        text = f"{title}\n\n" + "\n".join(lines)
        text += "\n\nНапишите цифру чтобы узнать подробнее" if ru else "\n\nType a number to read more"
        context.user_data["waiting_interesting"] = category
        keyboard = [
            [InlineKeyboardButton("🔄 Обновить" if ru else "🔄 Refresh", callback_data=f"interesting_{category}")],
            [InlineKeyboardButton("◀️ Назад" if ru else "◀️ Back", callback_data="menu_interesting")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    # Дневник
    elif query.data == "menu_diary":
        keyboard = [
            [InlineKeyboardButton("💰 Финансы", callback_data="diary_finances"), InlineKeyboardButton("😴 Сон", callback_data="diary_sleep")],
            [InlineKeyboardButton("💧 Вода", callback_data="diary_water"), InlineKeyboardButton("💪 Привычки", callback_data="diary_habits")],
            [InlineKeyboardButton("📝 Заметки", callback_data="diary_notes"), InlineKeyboardButton("🍳 Рецепты", callback_data="diary_recipe")],
            [InlineKeyboardButton("🎬 Что посмотреть", callback_data="diary_movie"), InlineKeyboardButton("🛒 Покупки", callback_data="diary_shopping")],
            [InlineKeyboardButton("📅 Планер", callback_data="diary_planner"), InlineKeyboardButton("🎂 Дни рождения", callback_data="diary_birthdays")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
        ]
        await query.edit_message_text("Дневник:" if ru else "Diary:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "diary_water":
        water_on = user.get("water_reminders", False)
        interval = user.get("water_interval", 2)
        async with db_pool.acquire() as conn:
            wlog = await conn.fetchrow("SELECT glasses FROM water_logs WHERE user_id = $1 AND log_date = CURRENT_DATE", user_id)
        glasses_today = wlog["glasses"] if wlog else 0
        progress_bar = "💧" * glasses_today + "⬜" * max(0, 8 - glasses_today)
        keyboard = [
            [InlineKeyboardButton("💧 Выпила стакан (+1)", callback_data="water_drink_count")],
            [InlineKeyboardButton("Выключить" if water_on else "Включить", callback_data="water_toggle")],
            [InlineKeyboardButton("◀️ Назад", callback_data="menu_diary")],
        ]
        text = f"Трекер воды\n\n{progress_bar}\nСегодня: {glasses_today}/8 стаканов\n\nНапоминания: {'Включены' if water_on else 'Выключены'}\nКаждые {interval} часа"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "water_drink_count":
        async with db_pool.acquire() as conn:
            wlog = await conn.fetchrow("SELECT id, glasses FROM water_logs WHERE user_id = $1 AND log_date = CURRENT_DATE", user_id)
            if wlog:
                new_glasses = wlog["glasses"] + 1
                await conn.execute("UPDATE water_logs SET glasses = $1 WHERE id = $2", new_glasses, wlog["id"])
            else:
                new_glasses = 1
                await conn.execute("INSERT INTO water_logs (user_id, glasses) VALUES ($1, $2)", user_id, new_glasses)
        progress_bar = "💧" * new_glasses + "⬜" * max(0, 8 - new_glasses)
        msg = f"Стакан засчитан! {new_glasses}/8 💧" if new_glasses < 8 else f"Норма выполнена! 🎉 {new_glasses} стаканов сегодня"
        back = InlineKeyboardButton("◀️ Назад", callback_data="diary_water")
        await query.edit_message_text(f"{progress_bar}\n\n{msg}", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "water_toggle":
        water_on = user.get("water_reminders", False)
        new_state = not water_on
        await save_user(user_id, water_reminders=new_state)
        if new_state:
            interval = user.get("water_interval", 2)
            context.application.job_queue.run_repeating(send_water_reminder, interval=interval*3600, first=interval*3600, data=user_id, name=f"water_{user_id}")
            text = f"Напоминания включены! Каждые {interval} часа 💧"
        else:
            for job in context.application.job_queue.get_jobs_by_name(f"water_{user_id}"):
                job.schedule_removal()
            text = "Напоминания выключены."
        back = InlineKeyboardButton("◀️ Назад", callback_data="diary_water")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "diary_habits":
        async with db_pool.acquire() as conn:
            habits = await conn.fetch("SELECT id, name FROM habits WHERE user_id = $1", user_id)
        text = "Ваши привычки:\n\n" + "\n".join(["• " + h["name"] for h in habits]) if habits else "Привычек пока нет."
        keyboard = [
            [InlineKeyboardButton("➕ Добавить", callback_data="habit_add")],
            [InlineKeyboardButton("✅ Отметить", callback_data="habit_log")],
            [InlineKeyboardButton("📊 Статистика", callback_data="habit_stats")],
            [InlineKeyboardButton("◀️ Назад", callback_data="menu_diary")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "habit_add":
        context.user_data["waiting_habit"] = True
        back = InlineKeyboardButton("◀️ Назад", callback_data="diary_habits")
        await query.edit_message_text("Напишите название привычки\n\nНапример: Медитация, Чтение, Зарядка", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "habit_log":
        async with db_pool.acquire() as conn:
            habits = await conn.fetch("SELECT id, name FROM habits WHERE user_id = $1", user_id)
        if not habits:
            back = InlineKeyboardButton("◀️ Назад", callback_data="diary_habits")
            await query.edit_message_text("Сначала добавьте привычку!", reply_markup=InlineKeyboardMarkup([[back]]))
            return
        keyboard = [[InlineKeyboardButton(f"✅ {h['name']}", callback_data=f"log_habit_{h['id']}")] for h in habits]
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="diary_habits")])
        await query.edit_message_text("Какую привычку отмечаем?", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("log_habit_"):
        habit_id = int(query.data.split("_")[-1])
        async with db_pool.acquire() as conn:
            habit = await conn.fetchrow("SELECT name FROM habits WHERE id = $1", habit_id)
            await conn.execute("INSERT INTO habit_logs (user_id, habit_id) VALUES ($1, $2)", user_id, habit_id)
        back = InlineKeyboardButton("◀️ Назад", callback_data="diary_habits")
        await query.edit_message_text(f"Привычка {habit['name']} отмечена! 💪", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "habit_stats":
        async with db_pool.acquire() as conn:
            habits = await conn.fetch("SELECT id, name FROM habits WHERE user_id = $1", user_id)
            lines = []
            for h in habits:
                count = await conn.fetchval("SELECT COUNT(*) FROM habit_logs WHERE habit_id = $1 AND logged_at >= NOW() - INTERVAL '7 days'", h["id"])
                lines.append(f"{h['name']}: {count}/7 дней")
        text = "Статистика за 7 дней:\n\n" + "\n".join(lines) if lines else "Нет данных."
        back = InlineKeyboardButton("◀️ Назад", callback_data="diary_habits")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "diary_shopping":
        async with db_pool.acquire() as conn:
            items = await conn.fetch("SELECT id, item, done FROM shopping_list WHERE user_id = $1 ORDER BY created_at", user_id)
        if items:
            lines = [("✅ " if i["done"] else "⬜ ") + i["item"] for i in items]
            text = "Список покупок:\n\n" + "\n".join(lines)
        else:
            text = "Список покупок пуст.\n\nНапишите что добавить!"
        context.user_data["waiting_shopping"] = True
        keyboard = [[InlineKeyboardButton("🗑 Очистить", callback_data="shopping_clear")],[InlineKeyboardButton("◀️ Назад", callback_data="menu_diary")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "shopping_clear":
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM shopping_list WHERE user_id = $1", user_id)
        back = InlineKeyboardButton("◀️ Назад", callback_data="diary_shopping")
        await query.edit_message_text("Список покупок очищен!", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "diary_planner":
        await query.edit_message_text("Загружаю планер...")
        events_by_date = await get_upcoming_events(user_id, days=365)
        text = "📅 Ваш планер на год:\n" + format_events_text(events_by_date)
        if len(text) > 4000: text = text[:4000] + "..."
        keyboard = [
            [InlineKeyboardButton("➕ Добавить событие", callback_data="planner_add")],
            [InlineKeyboardButton("🗑 Удалить событие", callback_data="planner_delete_list")],
            [InlineKeyboardButton("◀️ Назад", callback_data="menu_diary")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "planner_add":
        context.user_data["waiting_planner"] = True
        back = InlineKeyboardButton("◀️ Назад", callback_data="diary_planner")
        msg = ("Напишите что добавить — одним сообщением можно несколько событий!\n\n"
               "Примеры:\n"
               "• пилатес каждую пятницу в 10:00\n"
               "• ногти каждое 1-е число в 17:00\n"
               "• завтра в 14:00 встреча с Аней\n"
               "• у Влада тренировка пн-пт в 15:00, у Лизы танцы вт и чт в 18:00")
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "planner_delete_list":
        async with db_pool.acquire() as conn:
            evs = await conn.fetch(
                "SELECT id, title, person_name, event_time, repeat_type FROM events WHERE user_id=$1 ORDER BY created_at DESC LIMIT 20",
                user_id
            )
        if not evs:
            back = InlineKeyboardButton("◀️ Назад", callback_data="diary_planner")
            await query.edit_message_text("Событий нет.", reply_markup=InlineKeyboardMarkup([[back]]))
            return
        keyboard = []
        for e in evs:
            icon = "🔄" if e["repeat_type"] != "once" else "•"
            label = f"{icon} {e['event_time'] or ''} {e['title']}"
            if e["person_name"]: label += f" ({e['person_name']})"
            keyboard.append([InlineKeyboardButton("🗑 " + label[:40], callback_data=f"del_event_{e['id']}")])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="diary_planner")])
        await query.edit_message_text("Какое событие удалить?", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("del_event_"):
        ev_id = int(query.data.split("_")[-1])
        async with db_pool.acquire() as conn:
            ev_row = await conn.fetchrow("SELECT title, repeat_type FROM events WHERE id=$1", ev_id)
            if ev_row and ev_row["repeat_type"] != "once":
                await conn.execute("DELETE FROM events WHERE user_id=$1 AND title=$2 AND repeat_type=$3", user_id, ev_row["title"], ev_row["repeat_type"])
            else:
                await conn.execute("DELETE FROM events WHERE id=$1", ev_id)
        back = InlineKeyboardButton("◀️ Назад", callback_data="diary_planner")
        await query.edit_message_text(f"Удалено: {ev_row['title'] if ev_row else ''} 🗑", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data in ["diary_health", "menu_health"]:
        back_cb = "back_main" if query.data == "menu_health" else "menu_diary"
        keyboard = [
            [InlineKeyboardButton("🩸 Цикл", callback_data="health_cycle"), InlineKeyboardButton("💊 Таблетки", callback_data="health_meds")],
            [InlineKeyboardButton("😰 Стресс", callback_data="health_stress"), InlineKeyboardButton("⚖️ Вес и рост", callback_data="health_weight")],
            [InlineKeyboardButton("🥗 Нутрициология", callback_data="health_nutrition"), InlineKeyboardButton("😊 Настроение", callback_data="health_mood")],
            [InlineKeyboardButton("◀️ Назад", callback_data=back_cb)],
        ]
        await query.edit_message_text("Здоровье:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "health_cycle":
        async with db_pool.acquire() as conn:
            last = await conn.fetchrow("SELECT start_date, cycle_length FROM cycle_tracking WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1", user_id)
        if last and last["start_date"]:
            from datetime import date as _d, timedelta as _td
            start = last["start_date"]
            length = last["cycle_length"] or 28
            today = _d.today()
            day_of_cycle = ((today - start).days % length) + 1
            next_start = start
            while (next_start - today).days <= 0:
                from datetime import timedelta as _td2
                next_start = next_start + _td2(days=length)
            text = f"Цикл:\n\nПоследнее начало: {start}\nПримерное окончание: {start + _td(days=5)}\nДлина: {length} дней\nДень цикла: {day_of_cycle}\nСледующий через: {(next_start - today).days} дней"
        else:
            text = "Цикл ещё не отслеживается."
        keyboard = [
            [InlineKeyboardButton("📝 Отметить начало цикла", callback_data="cycle_start")],
            [InlineKeyboardButton("📋 История циклов", callback_data="cycle_history")],
            [InlineKeyboardButton("⚙️ Длина цикла", callback_data="cycle_set_length")],
            [InlineKeyboardButton("◀️ Назад", callback_data="menu_health")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "cycle_history":
        async with db_pool.acquire() as conn:
            cycles = await conn.fetch("SELECT start_date FROM cycle_tracking WHERE user_id = $1 ORDER BY start_date DESC LIMIT 12", user_id)
        from datetime import timedelta as _td3
        if cycles:
            lines = [str(c["start_date"]) + " — примерно до " + str(c["start_date"] + _td3(days=5)) for c in cycles]
            text = "История циклов:\n\n" + "\n".join(lines)
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
            keyboard.append([InlineKeyboardButton("🗑 Удалить таблетку", callback_data="med_delete")])
        keyboard.append([InlineKeyboardButton("➕ Добавить таблетку", callback_data="med_add")])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="menu_health")])
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
        await query.edit_message_text(f"Приём {med['name']} отмечен! 💊", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "med_delete":
        async with db_pool.acquire() as conn:
            meds_del = await conn.fetch("SELECT id, name, time_str FROM medications WHERE user_id = $1 ORDER BY time_str", user_id)
        if not meds_del:
            back = InlineKeyboardButton("◀️ Назад", callback_data="health_meds")
            await query.edit_message_text("Таблеток нет.", reply_markup=InlineKeyboardMarkup([[back]]))
            return
        keyboard = [[InlineKeyboardButton("🗑 " + m["time_str"] + " " + m["name"], callback_data="del_med_" + str(m["id"]))] for m in meds_del]
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="health_meds")])
        await query.edit_message_text("Какую таблетку удалить?", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("del_med_"):
        med_id_del = int(query.data.split("_")[-1])
        async with db_pool.acquire() as conn:
            med_row = await conn.fetchrow("SELECT name FROM medications WHERE id = $1", med_id_del)
            await conn.execute("DELETE FROM medication_logs WHERE med_id = $1", med_id_del)
            await conn.execute("DELETE FROM medications WHERE id = $1", med_id_del)
        for job in context.application.job_queue.get_jobs_by_name(f"med_{user_id}_{med_id_del}"):
            job.schedule_removal()
        back = InlineKeyboardButton("◀️ Назад", callback_data="health_meds")
        await query.edit_message_text(f"Таблетка {med_row['name'] if med_row else ''} удалена 🗑", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "health_stress":
        keyboard = [
            [InlineKeyboardButton(str(i), callback_data=f"stress_{i}") for i in range(1, 4)],
            [InlineKeyboardButton(str(i), callback_data=f"stress_{i}") for i in range(4, 7)],
            [InlineKeyboardButton(str(i), callback_data=f"stress_{i}") for i in range(7, 10)],
            [InlineKeyboardButton("10", callback_data="stress_10")],
            [InlineKeyboardButton("📊 История за неделю", callback_data="stress_history")],
            [InlineKeyboardButton("◀️ Назад", callback_data="menu_health")],
        ]
        await query.edit_message_text("Оцените уровень стресса:\n\n1 — всё спокойно\n10 — очень высокий стресс", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("stress_") and query.data != "stress_history":
        level = int(query.data.replace("stress_",""))
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO stress_logs (user_id, level) VALUES ($1, $2)", user_id, level)
        if level <= 3: advice = "Отличное состояние! Продолжайте в том же духе 🌸"
        elif level <= 6: advice = "Умеренный стресс. Попробуйте 5 минут глубокого дыхания."
        elif level <= 8: advice = "Высокий стресс. Сделайте перерыв, выпейте воды."
        else: advice = "Очень высокий стресс! Остановитесь, сделайте 10 глубоких вдохов 💙"
        back = InlineKeyboardButton("◀️ Назад", callback_data="health_stress")
        await query.edit_message_text(f"Уровень стресса {level}/10 отмечен.\n\n{advice}", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "stress_history":
        async with db_pool.acquire() as conn:
            logs = await conn.fetch("SELECT level, created_at FROM stress_logs WHERE user_id = $1 AND created_at >= NOW() - INTERVAL '7 days' ORDER BY created_at", user_id)
        if logs:
            from collections import defaultdict
            days_data = defaultdict(list)
            for l in logs:
                days_data[l["created_at"].strftime("%d.%m")].append(l["level"])
            lines = []
            for day, levels in days_data.items():
                avg = round(sum(levels)/len(levels), 1)
                lines.append(day + " " + "█"*int(avg) + "░"*(10-int(avg)) + " " + str(avg))
            text = "Стресс за 7 дней (1-10):\n\n" + "\n".join(lines)
        else:
            text = "Данных о стрессе за неделю нет."
        back = InlineKeyboardButton("◀️ Назад", callback_data="health_stress")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "health_weight":
        async with db_pool.acquire() as conn:
            logs = await conn.fetch("SELECT weight, height, created_at FROM weight_logs WHERE user_id = $1 ORDER BY created_at DESC LIMIT 8", user_id)
        if logs:
            lines = [l["created_at"].strftime("%d.%m.%Y") + ": " + str(l["weight"]) + " кг" + (" / " + str(l["height"]) + " см" if l["height"] else "") for l in logs]
            diff = round(logs[0]["weight"] - logs[-1]["weight"], 1)
            text = "Вес и рост:\n\n" + "\n".join(lines) + "\n\nДинамика: " + ("+" if diff > 0 else "") + str(diff) + " кг за период"
        else:
            text = "Записей пока нет."
        keyboard = [[InlineKeyboardButton("➕ Записать вес", callback_data="weight_add")],[InlineKeyboardButton("◀️ Назад", callback_data="menu_health")]]
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
            norm = profile["calories_goal"] or 0
            text = f"Нутрициология 🥗\n\nРост: {int(profile['height'])} см\nВес: {int(profile['weight'])} кг\nЦель: {profile['goal']}\nНорма: {norm} ккал\nСегодня: {today_cal} ккал\nОсталось: {max(0, norm-today_cal)} ккал\n\nОтправьте фото еды или напишите что ели!"
            keyboard = [[InlineKeyboardButton("📋 Журнал питания", callback_data="food_log_view")],[InlineKeyboardButton("✏️ Обновить профиль", callback_data="nutrition_setup")],[InlineKeyboardButton("◀️ Назад", callback_data="menu_health")]]
        else:
            context.user_data["nutrition_setup"] = True
            context.user_data["nutrition_step"] = "height"
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="menu_health")]]
            text = "Нутрициология 🥗\n\nДля начала заполните профиль.\n\nВаш рост в см:"
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
            lines = [l["created_at"].strftime("%H:%M") + " " + l["description"][:25] + " — " + str(l["calories"]) + " ккал" for l in logs]
            norm = profile["calories_goal"] if profile else 0
            text = "Журнал питания сегодня:\n\n" + "\n".join(lines)
            text += f"\n\nИтого: {total_cal} ккал | Б: {round(total_prot,1)} г | Ж: {round(total_fat,1)} г | У: {round(total_carb,1)} г"
            if norm: text += f"\nНорма: {norm} ккал | Осталось: {max(0, norm-total_cal)} ккал"
        else:
            text = "Сегодня записей питания нет."
        back = InlineKeyboardButton("◀️ Назад", callback_data="health_nutrition")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "nutrition_setup":
        context.user_data["nutrition_setup"] = True
        context.user_data["nutrition_step"] = "height"
        back = InlineKeyboardButton("◀️ Назад", callback_data="health_nutrition")
        await query.edit_message_text("Обновление профиля питания.\n\nВаш рост в см:", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "count_food_calories":
        image_data = context.user_data.pop("pending_food_photo", None)
        if not image_data:
            await query.edit_message_text("Фото не найдено. Отправьте снова.")
            return
        await query.edit_message_text("Анализирую... 🔍")
        food_res = await analyze_food_photo(image_data)
        if food_res and "Калории:" in food_res:
            import re as _r
            cal_m = _r.search(r"Калории:\s*(\d+)", food_res)
            prot_m = _r.search(r"Белки:\s*([\d.]+)", food_res)
            fat_m = _r.search(r"Жиры:\s*([\d.]+)", food_res)
            carb_m = _r.search(r"Углеводы:\s*([\d.]+)", food_res)
            dish_m = _r.search(r"Блюдо:\s*(.+)", food_res)
            async with db_pool.acquire() as conn:
                await conn.execute("INSERT INTO food_logs (user_id, description, calories, protein, fat, carbs) VALUES ($1, $2, $3, $4, $5, $6)", user_id, dish_m.group(1).strip() if dish_m else "Блюдо", int(cal_m.group(1)) if cal_m else 0, float(prot_m.group(1)) if prot_m else 0, float(fat_m.group(1)) if fat_m else 0, float(carb_m.group(1)) if carb_m else 0)
            await query.edit_message_text(food_res + "\n\nЗаписала в журнал питания! 🥗")
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

    elif query.data == "health_mood":
        keyboard = [
            [InlineKeyboardButton("😄 Отлично", callback_data="mood_5"), InlineKeyboardButton("🙂 Хорошо", callback_data="mood_4")],
            [InlineKeyboardButton("😐 Нормально", callback_data="mood_3"), InlineKeyboardButton("😔 Грустно", callback_data="mood_2")],
            [InlineKeyboardButton("😢 Плохо", callback_data="mood_1")],
            [InlineKeyboardButton("📊 История за месяц", callback_data="mood_history")],
            [InlineKeyboardButton("◀️ Назад", callback_data="menu_health")],
        ]
        await query.edit_message_text("Как у вас настроение сейчас? 🌸", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("mood_") and query.data != "mood_history":
        mood_val = int(query.data.split("_")[1])
        mood_names = {5: "😄 Отлично", 4: "🙂 Хорошо", 3: "😐 Нормально", 2: "😔 Грустно", 1: "😢 Плохо"}
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO mood_logs (user_id, mood) VALUES ($1, $2)", user_id, mood_val)
        mood_msgs = {5: "Отлично! Так держать! 🌟", 4: "Хорошее настроение — отличный день 🌸", 3: "Нормально — уже хорошо.", 2: "Грустновато. Хотите поговорить? 💙", 1: "Жаль слышать. Вы не одни — я здесь 🌸"}
        back = InlineKeyboardButton("◀️ Назад", callback_data="health_mood")
        await query.edit_message_text(mood_names[mood_val] + " отмечено!\n\n" + mood_msgs[mood_val], reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "mood_history":
        async with db_pool.acquire() as conn:
            logs = await conn.fetch("SELECT mood, created_at FROM mood_logs WHERE user_id = $1 AND created_at >= NOW() - INTERVAL '30 days' ORDER BY created_at", user_id)
        mood_names = {5: "😄", 4: "🙂", 3: "😐", 2: "😔", 1: "😢"}
        if logs:
            from collections import defaultdict
            days_mood = defaultdict(list)
            for l in logs:
                days_mood[l["created_at"].strftime("%d.%m")].append(l["mood"])
            lines = []
            for day, moods in list(days_mood.items())[-14:]:
                avg = sum(moods)/len(moods)
                lines.append(day + " " + mood_names.get(round(avg), "😐") + " " + str(round(avg, 1)))
            text = "Настроение за месяц:\n\n" + "\n".join(lines)
        else:
            text = "Данных о настроении пока нет."
        back = InlineKeyboardButton("◀️ Назад", callback_data="health_mood")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back]]))

    # Цели
    elif query.data == "menu_goals":
        async with db_pool.acquire() as conn:
            goals = await conn.fetch("SELECT id, title, progress, deadline FROM goals WHERE user_id = $1 ORDER BY created_at DESC", user_id)
        if goals:
            lines = []
            for g in goals:
                bar = "█"*(g["progress"]//10) + "░"*(10-g["progress"]//10)
                dl = " (до " + str(g["deadline"]) + ")" if g["deadline"] else ""
                lines.append(g["title"] + dl + "\n" + bar + " " + str(g["progress"]) + "%")
            text = "Мои цели:\n\n" + "\n\n".join(lines)
        else:
            text = "Целей пока нет."
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

    elif query.data == "goal_progress":
        async with db_pool.acquire() as conn:
            goals_p = await conn.fetch("SELECT id, title, progress FROM goals WHERE user_id = $1", user_id)
        keyboard = [[InlineKeyboardButton(g["title"][:30] + f" ({g['progress']}%)", callback_data="set_progress_" + str(g["id"]))] for g in goals_p]
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="menu_goals")])
        await query.edit_message_text("Выберите цель для обновления:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("set_progress_"):
        goal_id_s = int(query.data.split("_")[-1])
        context.user_data["waiting_progress_goal_id"] = goal_id_s
        async with db_pool.acquire() as conn:
            g_info = await conn.fetchrow("SELECT title FROM goals WHERE id = $1", goal_id_s)
        back = InlineKeyboardButton("◀️ Назад", callback_data="menu_goals")
        await query.edit_message_text(f"Цель: {g_info['title'] if g_info else ''}\n\nРасскажите что сделали? Я оценю прогресс.", reply_markup=InlineKeyboardMarkup([[back]]))

    # Финансы
    elif query.data == "diary_finances":
        async with db_pool.acquire() as conn:
            income = await conn.fetchval("SELECT SUM(amount) FROM finances WHERE user_id = $1 AND type = 'income' AND created_at >= NOW() - INTERVAL '30 days'", user_id) or 0
            expense = await conn.fetchval("SELECT SUM(amount) FROM finances WHERE user_id = $1 AND type = 'expense' AND created_at >= NOW() - INTERVAL '30 days'", user_id) or 0
            recent = await conn.fetch("SELECT amount, type, category, description FROM finances WHERE user_id = $1 ORDER BY created_at DESC LIMIT 5", user_id)
        balance = income - expense
        lines = [f"{'➕' if r['type']=='income' else '➖'} {r['amount']:.0f} — {r['category']} {r['description']}" for r in recent]
        text = f"Финансы за месяц:\n\n➕ Доходы: {income:.0f}\n➖ Расходы: {expense:.0f}\n💵 Баланс: {balance:.0f}\n\n"
        text += "\n".join(lines) if lines else "Записей пока нет."
        text += "\n\nДобавить доход: +1000 зарплата\nДобавить расход: -500 еда кофе"
        context.user_data["waiting_finance"] = True
        back = InlineKeyboardButton("◀️ Назад", callback_data="menu_diary")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "diary_sleep":
        keyboard = [
            [InlineKeyboardButton("6:00", callback_data="sleep_6_0"), InlineKeyboardButton("7:00", callback_data="sleep_7_0"), InlineKeyboardButton("8:00", callback_data="sleep_8_0")],
            [InlineKeyboardButton("9:00", callback_data="sleep_9_0"), InlineKeyboardButton("10:00", callback_data="sleep_10_0")],
            [InlineKeyboardButton("◀️ Назад", callback_data="menu_diary")],
        ]
        await query.edit_message_text("Во сколько хотите проснуться?", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("sleep_"):
        parts = query.data.split("_")
        wh, wm = int(parts[1]), int(parts[2])
        times = calculate_sleep_times(wh, wm)
        text = f"Чтобы проснуться в {wh:02d}:{wm:02d} бодрой, ложитесь в:\n\n"
        for ti in times:
            text += f"🌙 {ti}\n"
        text += "\n+15 минут на засыпание учтены"
        back = InlineKeyboardButton("◀️ Назад", callback_data="diary_sleep")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "diary_notes":
        async with db_pool.acquire() as conn:
            notes = await conn.fetch("SELECT text FROM notes WHERE user_id = $1 ORDER BY created_at DESC LIMIT 5", user_id)
        if notes:
            lines = [f"• {n['text'][:60]}{'...' if len(n['text'])>60 else ''}" for n in notes]
            text = "Ваши заметки:\n\n" + "\n".join(lines)
        else:
            text = "Заметок пока нет."
        text += "\n\nНапишите что угодно и я сохраню!"
        context.user_data["waiting_note"] = True
        back = InlineKeyboardButton("◀️ Назад", callback_data="menu_diary")
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
            await query.edit_message_text("Сохранённых рецептов пока нет.", reply_markup=InlineKeyboardMarkup([[back]]))
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
        cat_key = query.data.replace("recipe_cat_","")
        cat_names = {"soups":"Супы","main":"Второе","salads":"Салаты","desserts":"Десерты","trends":"Тренды"}
        cat_name = cat_names.get(cat_key,"Рецепты")
        await query.edit_message_text(f"Подбираю {cat_name}...")
        recipe_list = await get_recipe_list(cat_key, lang)
        if not recipe_list:
            back = InlineKeyboardButton("◀️ Назад", callback_data="recipes_random")
            await query.edit_message_text("Рецепты временно недоступны.", reply_markup=InlineKeyboardMarkup([[back]]))
            return
        context.user_data["waiting_recipe_choice"] = cat_key
        context.user_data[f"recipe_list_{cat_key}"] = recipe_list
        keyboard = [[InlineKeyboardButton("🔄 Другие варианты", callback_data=f"recipe_cat_{cat_key}")],[InlineKeyboardButton("◀️ Назад", callback_data="recipes_random")]]
        await query.edit_message_text(f"{cat_name}\n\n{recipe_list}\n\nНапишите цифру рецепта!", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "save_recipe_yes":
        title_r = context.user_data.get("last_recipe_title","Рецепт")
        content_r = context.user_data.get("last_recipe_content","")
        if content_r:
            async with db_pool.acquire() as conn:
                await conn.execute("INSERT INTO saved_recipes (user_id, title, content) VALUES ($1, $2, $3)", user_id, title_r, content_r)
        done_kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Сохранено ❤️", callback_data="recipe_done")]])
        try:
            await query.edit_message_text((title_r + "\n\n" + content_r)[:4000], reply_markup=done_kb)
        except:
            await query.edit_message_text("Рецепт сохранён! ❤️", reply_markup=done_kb)

    elif query.data == "dont_save_recipe":
        content_r = context.user_data.get("last_recipe_content","")
        title_r = context.user_data.get("last_recipe_title","")
        done_kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Готово", callback_data="recipe_done")]])
        try:
            await query.edit_message_text((title_r + "\n\n" + content_r)[:4000] if content_r else "Хорошо!", reply_markup=done_kb)
        except:
            await query.edit_message_text("Хорошо, не сохраняю.", reply_markup=done_kb)

    elif query.data == "recipe_done":
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except:
            pass

    elif query.data == "diary_movie":
        await query.edit_message_text("Подбираю фильм...")
        movie = await get_ai_movie(lang)
        keyboard = [[InlineKeyboardButton("🔄 Другой", callback_data="diary_movie")],[InlineKeyboardButton("◀️ Назад", callback_data="menu_diary")]]
        await query.edit_message_text(f"Рекомендация:\n\n{movie}", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "diary_birthdays":
        async with db_pool.acquire() as conn:
            bdays = await conn.fetch("SELECT id, person_name, birth_date FROM birthdays WHERE user_id = $1 ORDER BY birth_date", user_id)
        if bdays:
            from datetime import date as _d, datetime as _dt
            today = _d.today()
            lines = []
            for b in bdays:
                try:
                    bd = (_dt.strptime(b["birth_date"], "%d.%m").replace(year=today.year).date())
                    if bd < today: bd = bd.replace(year=today.year+1)
                    days_left = (bd - today).days
                    days_txt = "сегодня! 🎉" if days_left==0 else f"через {days_left} дн."
                    lines.append(f"🎂 {b['person_name']} ({b['birth_date']}) — {days_txt}")
                except:
                    lines.append(f"🎂 {b['person_name']} ({b['birth_date']})")
            text = "Дни рождения:\n\n" + "\n".join(lines)
        else:
            text = "Дней рождения ещё нет."
        keyboard = [[InlineKeyboardButton("➕ Добавить", callback_data="birthday_add")],[InlineKeyboardButton("🗑 Удалить", callback_data="birthday_delete")],[InlineKeyboardButton("◀️ Назад", callback_data="menu_diary")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "birthday_add":
        context.user_data["waiting_birthday"] = True
        back = InlineKeyboardButton("◀️ Назад", callback_data="diary_birthdays")
        await query.edit_message_text("Напишите имя и дату через запятую:\n\nНапример: Мама, 15.03\nИли с годом: Папа, 10.07.1970", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "birthday_delete":
        async with db_pool.acquire() as conn:
            bdays_d = await conn.fetch("SELECT id, person_name, birth_date FROM birthdays WHERE user_id = $1", user_id)
        if not bdays_d:
            back = InlineKeyboardButton("◀️ Назад", callback_data="diary_birthdays")
            await query.edit_message_text("Список пуст.", reply_markup=InlineKeyboardMarkup([[back]]))
            return
        keyboard = [[InlineKeyboardButton("🗑 " + b["person_name"], callback_data="del_bday_" + str(b["id"]))] for b in bdays_d]
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="diary_birthdays")])
        await query.edit_message_text("Кого удалить?", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("del_bday_"):
        bday_id_del = int(query.data.split("_")[-1])
        async with db_pool.acquire() as conn:
            b_row = await conn.fetchrow("SELECT person_name FROM birthdays WHERE id = $1", bday_id_del)
            await conn.execute("DELETE FROM birthdays WHERE id = $1", bday_id_del)
        back = InlineKeyboardButton("◀️ Назад", callback_data="diary_birthdays")
        await query.edit_message_text((b_row["person_name"] if b_row else "") + " удалён 🗑", reply_markup=InlineKeyboardMarkup([[back]]))

    # Настройки
    elif query.data == "menu_settings":
        mw = "✅" if user.get("morning_weather") else "❌"
        mm = "✅" if user.get("morning_motivation") else "❌"
        w = "✅" if user.get("water_reminders") else "❌"
        ev = "✅" if user.get("evening_news") else "❌"
        comm = user.get("comm_style","наставник")
        keyboard = [
            [InlineKeyboardButton("👤 Профиль", callback_data="menu_profile")],
            [InlineKeyboardButton("💬 Стиль: " + comm, callback_data="change_comm_style")],
            [InlineKeyboardButton("🌍 Изменить город", callback_data="profile_city")],
            [InlineKeyboardButton("🌐 Switch to English" if ru else "🌐 Switch to Russian", callback_data="switch_lang_en" if ru else "switch_lang_ru")],
            [InlineKeyboardButton(mw + " Погода утром", callback_data="toggle_morning_weather")],
            [InlineKeyboardButton(mm + " Мотивация утром", callback_data="toggle_morning_motivation")],
            [InlineKeyboardButton(w + " Напоминания о воде", callback_data="water_toggle")],
            [InlineKeyboardButton(ev + " Вечерняя сводка", callback_data="toggle_evening_news")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
        ]
        await query.edit_message_text("Настройки" if ru else "Settings", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "menu_profile":
        async with db_pool.acquire() as conn:
            total_msg = await conn.fetchval("SELECT COUNT(*) FROM history WHERE user_id = $1 AND role = 'user'", user_id)
            habits_count = await conn.fetchval("SELECT COUNT(*) FROM habits WHERE user_id = $1", user_id)
        created = user.get("created_at")
        days = (datetime.now() - created).days if created else 0
        comm = user.get("comm_style","наставник")
        text = f"Мой профиль\n\nИмя: {name}\nГород: {city}\nЯзык: {'Русский 🇷🇺' if ru else 'English 🇬🇧'}\nСтиль: {comm}\nДней с нами: {days}\nСообщений: {total_msg}\nПривычек: {habits_count}"
        keyboard = [
            [InlineKeyboardButton("🌍 Изменить город", callback_data="profile_city")],
            [InlineKeyboardButton("💬 Сменить стиль", callback_data="change_comm_style")],
            [InlineKeyboardButton("🌐 Switch to English 🇬🇧" if ru else "🌐 Switch to Russian 🇷🇺", callback_data="switch_lang_en" if ru else "switch_lang_ru")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "change_comm_style":
        keyboard = [
            [InlineKeyboardButton("👭 Подружка — на ты, тепло", callback_data="set_style_подружка")],
            [InlineKeyboardButton("🎯 Наставник — на вы, мотивирующий", callback_data="set_style_наставник")],
            [InlineKeyboardButton("🔥 Мотиватор — энергично, вдохновляюще", callback_data="set_style_мотиватор")],
            [InlineKeyboardButton("💼 Официальный помощник", callback_data="set_style_официальный помощник")],
            [InlineKeyboardButton("◀️ Назад", callback_data="menu_settings")],
        ]
        await query.edit_message_text("Выберите стиль общения:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("set_style_"):
        style = query.data.replace("set_style_","")
        await save_user(user_id, comm_style=style)
        await save_memory_item(user_id, "стиль_общения", style)
        style_names = {"подружка":"Подружка 👭","наставник":"Наставник 🎯","профессионал":"Профессионал 💼"}
        back = InlineKeyboardButton("◀️ Назад", callback_data="menu_settings")
        await query.edit_message_text(f"Стиль изменён: {style_names.get(style, style)}", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "switch_lang_en":
        await save_user(user_id, language="en")
        await query.edit_message_text("Language switched to English 🇬🇧\n\nType /menu to continue!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="back_main")]]))

    elif query.data == "switch_lang_ru":
        await save_user(user_id, language="ru")
        await query.edit_message_text("Язык изменён на русский 🇷🇺\n\nНапишите /menu!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="back_main")]]))

    elif query.data == "profile_city":
        context.user_data["waiting_city"] = True
        back = InlineKeyboardButton("◀️ Отмена", callback_data="menu_settings")
        await query.edit_message_text("Напишите название вашего города", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "toggle_morning_weather":
        new = not user.get("morning_weather", False)
        await save_user(user_id, morning_weather=new)
        back = InlineKeyboardButton("◀️ Назад", callback_data="menu_settings")
        await query.edit_message_text(f"Погода утром {'включена ✅' if new else 'выключена ❌'}", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "toggle_morning_motivation":
        new = not user.get("morning_motivation", False)
        await save_user(user_id, morning_motivation=new)
        back = InlineKeyboardButton("◀️ Назад", callback_data="menu_settings")
        await query.edit_message_text(f"Мотивация утром {'включена ✅' if new else 'выключена ❌'}", reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "toggle_evening_news":
        new = not user.get("evening_news", False)
        await save_user(user_id, evening_news=new)
        if new:
            evening_time = user.get("evening_time","21:00")
            tz = pytz.timezone(user.get("timezone","Europe/Moscow"))
            hour = int(evening_time.split(":")[0])
            context.application.job_queue.run_daily(send_evening_news, time=time(hour=hour, minute=0, tzinfo=tz), data=user_id, name=f"evening_{user_id}")
            text = f"Вечерняя сводка включена! В {evening_time}"
        else:
            for job in context.application.job_queue.get_jobs_by_name(f"evening_{user_id}"):
                job.schedule_removal()
            text = "Вечерняя сводка выключена."
        back = InlineKeyboardButton("◀️ Назад", callback_data="menu_settings")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back]]))

    elif query.data == "skills_inline":
        await query.edit_message_text(SKILLS_RU)

    elif query.data == "close_menu":
        await query.edit_message_text("Меню закрыто. Напишите /menu чтобы открыть снова 🌸")

    elif query.data.startswith("sub_"):
        section = query.data.replace("sub_", "")
        result = get_submenu(section, lang)
        if isinstance(result, tuple):
            title, markup = result
            await query.edit_message_text(title, reply_markup=markup)
        else:
            await query.edit_message_text("🌸", reply_markup=result)

    elif query.data == "back_main":
        await query.edit_message_text("🌸", reply_markup=get_main_menu(lang))

# ─── ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ ─────────────────────────────────────────────
async def process_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    if not user or not user["onboarded"]:
        await update.message.reply_text(t("ru", "not_started"))
        return
    name = user["name"]
    lang = user.get("language","ru")
    ru = lang == "ru"
    user_name = update.effective_user.first_name or "Пользователь"
    username = update.effective_user.username or "нет username"

    # Ответ "да" на предложение планера
    if user_text.strip().lower() in ["да","yes","добавь","запиши"] and context.user_data.get("pending_planner_text"):
        original_text = context.user_data.pop("pending_planner_text")
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        events = await parse_events_ai(original_text, user_id)
        if events:
            saved = await save_events_to_db(user_id, events)
            if saved:
                reply = "Записала в планер:\n\n" + "\n".join(saved)
                await update.message.reply_text(reply)
                await notify_admin(context, user_name, username, user_text, reply)
                return
        await update.message.reply_text("Уточните время — напишите например: пилатес каждую пятницу в 10:00")
        return

    # Сбрасываем залипшие флаги если сообщение похоже на обычный разговор
    chat_kw = ["что у меня","по плану","завтра","сегодня","расскажи","помоги","как дела",
               "что нового","напомни","погода","привет","спасибо","хочу","могу","буду",
               "что ты","чем","почему","когда","где","кто","план на","что планируешь",
               "что случилось","расскажи мне","помоги мне","можешь ли","умеешь ли"]
    is_chat = any(k in user_text.lower() for k in chat_kw) and len(user_text) > 8
    if is_chat:
        for flag in ["waiting_shopping","waiting_note","waiting_finance","waiting_habit",
                     "waiting_goal","waiting_birthday"]:
            context.user_data.pop(flag, None)

    # Смена стиля
    if is_change_style_request(user_text):
        text_lower = user_text.lower()
        if "подруж" in text_lower or "на ты" in text_lower:
            new_style = "подружка"
        elif "наставник" in text_lower or "на вы" in text_lower:
            new_style = "наставник"
        elif "профессионал" in text_lower:
            new_style = "профессионал"
        else:
            new_style = None
        if new_style:
            await save_user(user_id, comm_style=new_style)
            await save_memory_item(user_id, "стиль_общения", new_style)
            reply = f"Стиль изменён на «{new_style}»! 🌸"
            await update.message.reply_text(reply)
            await notify_admin(context, user_name, username, user_text, reply)
            return



    # Уточнение времени для планера
    if context.user_data.get("waiting_planner_time"):
        original_text = context.user_data.pop("waiting_planner_time")
        h, m = extract_exact_time(user_text)
        if h is None:
            await update.message.reply_text("Не поняла время. Напишите например 19:00")
            return
        time_str = str(h).zfill(2) + ":" + str(m).zfill(2)
        day_num = None
        for day_name, day_idx in DAYS_RU.items():
            if day_name in original_text.lower():
                day_num = day_idx
                break
        if day_num is None:
            context.user_data["waiting_planner_day"] = original_text + " в " + time_str
            await update.message.reply_text("В какой день недели?")
            return
        event_title = re.sub(r"(каждый|каждую|каждое|всегда|регулярно|по\s+\w+)\s*","", original_text, flags=re.IGNORECASE).strip()
        event_title = re.sub(r"\d{1,2}[:.\s]\d{2}","", event_title).strip().lstrip("-— ")
        if not event_title or len(event_title) < 2:
            words = [w for w in original_text.split() if len(w) > 3 and ":" not in w]
            event_title = words[-1] if words else original_text
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO planner (user_id, day_of_week, time_str, title) VALUES ($1, $2, $3, $4)", user_id, day_num, time_str, event_title)
        reply = f"Записала! Каждый {DAYS_RU_NAMES[day_num]} в {time_str} — {event_title} 📅"
        await update.message.reply_text(reply)
        await notify_admin(context, user_name, username, user_text, reply)
        return

    # Уточнение дня для планера
    if context.user_data.get("waiting_planner_day"):
        original_text = context.user_data.pop("waiting_planner_day")
        day_num = None
        for day_name, day_idx in DAYS_RU.items():
            if day_name in user_text.lower():
                day_num = day_idx
                break
        if day_num is None:
            await update.message.reply_text("Не поняла день. Например: пятница")
            return
        h, m = extract_exact_time(original_text)
        if h is None:
            await update.message.reply_text("Не нашла время. Попробуйте ещё раз.")
            return
        time_str = str(h).zfill(2) + ":" + str(m).zfill(2)
        parts = original_text.split(time_str)
        event_title = parts[-1].strip().lstrip("-— ") if len(parts) > 1 else original_text
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO planner (user_id, day_of_week, time_str, title) VALUES ($1, $2, $3, $4)", user_id, day_num, time_str, event_title)
        reply = f"Записала! Каждый {DAYS_RU_NAMES[day_num]} в {time_str} — {event_title} 📅"
        await update.message.reply_text(reply)
        await notify_admin(context, user_name, username, user_text, reply)
        return

    # Выбор рецепта по цифре
    if context.user_data.get("waiting_recipe_choice"):
        cat_key = context.user_data["waiting_recipe_choice"]
        if user_text.strip().isdigit():
            idx = int(user_text.strip())
            recipe_list = context.user_data.get(f"recipe_list_{cat_key}","")
            lines = [l.strip() for l in recipe_list.split("\n") if l.strip() and l.strip()[0].isdigit()]
            if 1 <= idx <= len(lines):
                dish_name = re.sub(r"^\d+[.)] ?","", lines[idx-1]).strip()
                context.user_data["waiting_recipe_choice"] = None
                await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
                await update.message.reply_text(f"Готовлю рецепт: {dish_name}...")
                recipe_content = await get_full_recipe(dish_name, lang)
                if recipe_content:
                    context.user_data["last_recipe_title"] = dish_name
                    context.user_data["last_recipe_content"] = recipe_content
                    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❤️ Сохранить", callback_data="save_recipe_yes"), InlineKeyboardButton("✖️ Не нужно", callback_data="dont_save_recipe")]])
                    await update.message.reply_text(recipe_content + "\n\nХотите сохранить этот рецепт в ваши любимые?", reply_markup=kb)
                return

    # Добавление в планер из меню — AI парсинг
    if context.user_data.get("waiting_planner"):
        context.user_data["waiting_planner"] = False
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        events = await parse_events_ai(user_text, user_id)
        if events:
            saved = await save_events_to_db(user_id, events)
            if saved:
                reply = "Записала в планер:\n\n" + "\n".join(saved)
                await update.message.reply_text(reply)
                await notify_admin(context, user_name, username, user_text, reply)
            else:
                await update.message.reply_text("Не смогла разобрать. Попробуйте написать иначе, например: пилатес каждую пятницу в 10:00")
        else:
            await update.message.reply_text("Не смогла разобрать. Попробуйте: каждую пятницу в 10:00 пилатес")
        return

    # Интересное — выбор статьи
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
                await update.message.reply_text(f"Читаю про «{title}»...")
                details = await get_article_details(articles[idx], lang)
                await update.message.reply_text(details)
                await notify_admin(context, user_name, username, user_text, details[:200])
                return
            else:
                await update.message.reply_text(f"Введите число от 1 до {len(articles)}")
                return

    # Ждём ввода данных
    if context.user_data.get("waiting_habit"):
        context.user_data["waiting_habit"] = False
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO habits (user_id, name) VALUES ($1, $2)", user_id, user_text)
        reply = f"Привычка '{user_text}' добавлена! 💪"
        await update.message.reply_text(reply)
        await notify_admin(context, user_name, username, user_text, reply)
        return

    if context.user_data.get("waiting_shopping"):
        context.user_data["waiting_shopping"] = False
        items = [i.strip() for i in re.split(r'[,\n;]', user_text) if i.strip()]
        async with db_pool.acquire() as conn:
            for item in items:
                await conn.execute("INSERT INTO shopping_list (user_id, item) VALUES ($1, $2)", user_id, item)
        reply = f"Добавлено {len(items)} позиций в список покупок!"
        await update.message.reply_text(reply)
        await notify_admin(context, user_name, username, user_text, reply)
        return

    if context.user_data.get("waiting_city"):
        context.user_data["waiting_city"] = False
        timezone = await get_timezone_by_city(user_text)
        await save_user(user_id, city=user_text, timezone=timezone)
        await save_memory_item(user_id, "город", user_text)
        reply = f"Город изменён на {user_text}"
        await update.message.reply_text(reply)
        await notify_admin(context, user_name, username, user_text, reply)
        return

    if context.user_data.get("waiting_note"):
        context.user_data["waiting_note"] = False
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO notes (user_id, text) VALUES ($1, $2)", user_id, user_text)
        reply = "Заметка сохранена! 📝"
        await update.message.reply_text(reply)
        await notify_admin(context, user_name, username, user_text, reply)
        return

    if context.user_data.get("waiting_weight"):
        context.user_data["waiting_weight"] = False
        try:
            pw = user_text.strip().split()
            weight_v = float(pw[0].replace(",","."))
            height_v = float(pw[1].replace(",",".")) if len(pw) > 1 else None
            async with db_pool.acquire() as conn:
                await conn.execute("INSERT INTO weight_logs (user_id, weight, height) VALUES ($1, $2, $3)", user_id, weight_v, height_v)
                nutr = await conn.fetchrow("SELECT id FROM nutrition_profile WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1", user_id)
                if nutr:
                    await conn.execute("UPDATE nutrition_profile SET weight = $1 WHERE user_id = $2", weight_v, user_id)
            rw = f"Вес записан: {weight_v} кг"
            if height_v:
                bmi = round(weight_v / ((height_v/100)**2), 1)
                rw += f", рост: {height_v} см, ИМТ: {bmi}"
            await update.message.reply_text(rw + " ⚖️")
            await notify_admin(context, user_name, username, user_text, rw)
        except:
            await update.message.reply_text("Не поняла. Напишите например: 65 или 65 170")
        return

    if context.user_data.get("nutrition_setup"):
        step = context.user_data.get("nutrition_step","height")
        if step in ["intro","height"]:
            try:
                context.user_data["nutrition_height"] = float(user_text.replace(",","."))
                context.user_data["nutrition_step"] = "weight"
                await update.message.reply_text("Отлично! Теперь ваш вес в кг:")
            except:
                await update.message.reply_text("Напишите число, например: 165")
            return
        elif step == "weight":
            try:
                context.user_data["nutrition_weight"] = float(user_text.replace(",","."))
                context.user_data["nutrition_step"] = "age"
                await update.message.reply_text("Сколько вам лет?")
            except:
                await update.message.reply_text("Напишите число, например: 60")
            return
        elif step == "age":
            try:
                context.user_data["nutrition_age"] = int(user_text.strip())
                context.user_data["nutrition_step"] = "goal"
                kb = ReplyKeyboardMarkup([["Похудеть","Набрать вес"],["Поддержать вес","Оздоровиться"]], one_time_keyboard=True, resize_keyboard=True)
                await update.message.reply_text("Какая ваша цель?", reply_markup=kb)
            except:
                await update.message.reply_text("Напишите число, например: 25")
            return
        elif step == "goal":
            context.user_data["nutrition_goal"] = user_text.strip()
            context.user_data["nutrition_step"] = "pregnant"
            kb = ReplyKeyboardMarkup([["Нет","Да, беременна"]], one_time_keyboard=True, resize_keyboard=True)
            await update.message.reply_text("Вы беременны или кормите грудью?", reply_markup=kb)
            return
        elif step == "pregnant":
            context.user_data["nutrition_pregnant"] = "да" in user_text.lower()
            context.user_data["nutrition_step"] = "meds"
            await update.message.reply_text("Принимаете ли вы препараты или витамины? Напишите список или нет:", reply_markup=ReplyKeyboardRemove())
            return
        elif step == "meds":
            meds_val = None if user_text.strip().lower() in ["нет","no","-"] else user_text.strip()
            h_n = context.user_data.get("nutrition_height", 165)
            w_n = context.user_data.get("nutrition_weight", 60)
            age_n = context.user_data.get("nutrition_age", 25)
            goal_n = context.user_data.get("nutrition_goal","Поддержать вес")
            preg_n = context.user_data.get("nutrition_pregnant", False)
            cal = int(w_n * 30 * (0.8 if "похудеть" in goal_n.lower() else 1.2 if "набрать" in goal_n.lower() else 1))
            if preg_n: cal = max(cal, 2200)
            try:
                async with db_pool.acquire() as conn:
                    await conn.execute("INSERT INTO nutrition_profile (user_id, height, weight, age, goal, calories_goal, pregnant, medications) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)", user_id, h_n, w_n, age_n, goal_n, cal, preg_n, meds_val)
                context.user_data["nutrition_setup"] = False
                context.user_data["nutrition_step"] = None
                reply_txt = f"Профиль создан!\n\nРост: {int(h_n)} см\nВес: {int(w_n)} кг\nВозраст: {age_n} лет\nЦель: {goal_n}\nКалорий/день: {cal} ккал\n\nОтправляйте фото еды или пишите что ели — посчитаю КБЖУ!"
                await update.message.reply_text(reply_txt)
                await notify_admin(context, user_name, username, "Создал профиль нутрициологии", reply_txt[:100])
            except Exception as ne:
                logging.error(f"nutrition: {ne}")
                await update.message.reply_text("Что-то пошло не так. Попробуйте ещё раз.")
            return

    if context.user_data.get("waiting_birthday"):
        context.user_data["waiting_birthday"] = False
        parts_b = user_text.strip().split(",")
        person_name_b = parts_b[0].strip()
        birth_date_b = parts_b[1].strip() if len(parts_b) > 1 else ""
        if person_name_b and birth_date_b:
            async with db_pool.acquire() as conn:
                await conn.execute("INSERT INTO birthdays (user_id, person_name, birth_date) VALUES ($1, $2, $3)", user_id, person_name_b, birth_date_b)
            reply = f"День рождения {person_name_b} добавлен! Напомню заранее 🎂"
            await update.message.reply_text(reply)
            await notify_admin(context, user_name, username, user_text, reply)
        else:
            await update.message.reply_text("Напишите имя и дату через запятую, например: Мама, 15.03")
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
        reply = f"Цель добавлена: {title_g}" + (f" (до {deadline_g})" if deadline_g else "") + " 🎯"
        await update.message.reply_text(reply)
        await notify_admin(context, user_name, username, user_text, reply)
        return

    if context.user_data.get("waiting_progress_goal_id"):
        gid = context.user_data.pop("waiting_progress_goal_id")
        try:
            async with db_pool.acquire() as conn:
                g_data = await conn.fetchrow("SELECT title FROM goals WHERE id = $1", gid)
            goal_title = g_data["title"] if g_data else "цель"
            prog_resp = ai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":f"Цель: {goal_title}\nЧто сделано: {user_text}\n\nОцени прогресс в % (0-100). Ответь ТОЛЬКО числом."}], max_tokens=10, temperature=0.1)
            prog_text = prog_resp.choices[0].message.content.strip().replace("%","")
            prog = max(0, min(100, int("".join(filter(str.isdigit, prog_text)) or "0")))
            async with db_pool.acquire() as conn:
                await conn.execute("UPDATE goals SET progress = $1 WHERE id = $2", prog, gid)
            reply = f"Прогресс по цели \"{goal_title}\" обновлён до {prog}% 🎯"
            await update.message.reply_text(reply)
            await notify_admin(context, user_name, username, user_text, reply)
        except Exception as pe:
            logging.error(f"goal_progress: {pe}")
            await update.message.reply_text("Не смогла оценить. Напишите подробнее что сделали.")
        return

    if context.user_data.get("waiting_cycle_length"):
        context.user_data["waiting_cycle_length"] = False
        try:
            lc = int(user_text.strip())
            if 20 <= lc <= 45:
                async with db_pool.acquire() as conn:
                    await conn.execute("UPDATE cycle_tracking SET cycle_length = $1 WHERE user_id = $2", lc, user_id)
                reply = f"Длина цикла обновлена: {lc} дней 🩸"
                await update.message.reply_text(reply)
                await notify_admin(context, user_name, username, user_text, reply)
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
            reply = f"Дата начала цикла сохранена: {date_obj} 🩸"
            await update.message.reply_text(reply)
            await notify_admin(context, user_name, username, user_text, reply)
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
        context.application.job_queue.run_daily(send_med_reminder, time=time(hour=h_m, minute=m_m, tzinfo=tz_u), data={"user_id": user_id, "med_name": med_name}, name=f"med_{user_id}_{med_id}")
        reply = f"Таблетка добавлена: {med_name} в {ts} 💊 Напоминание установлено!"
        await update.message.reply_text(reply)
        await notify_admin(context, user_name, username, user_text, reply)
        return

    if context.user_data.get("waiting_finance"):
        context.user_data["waiting_finance"] = False
        parts = user_text.split()
        try:
            raw = parts[0].replace(",",".")
            is_income = raw.startswith("+")
            amount = float(raw.replace("+","").replace("-",""))
            finance_type = "income" if is_income else "expense"
            category = parts[1] if len(parts) > 1 else "Другое"
            description = " ".join(parts[2:]) if len(parts) > 2 else ""
            async with db_pool.acquire() as conn:
                await conn.execute("INSERT INTO finances (user_id, amount, type, category, description) VALUES ($1, $2, $3, $4, $5)", user_id, amount, finance_type, category, description)
            reply = f"{'Доход' if is_income else 'Расход'} {amount:.0f} ({category}) сохранён!"
            await update.message.reply_text(reply)
            await notify_admin(context, user_name, username, user_text, reply)
        except:
            await update.message.reply_text("Формат: +1000 зарплата или -500 еда кофе")
        return

    # ── Ответ на "что умеешь" ──────────────────────────────────────────────────────
    skills_kw = ["что ты умеешь", "что умеешь", "чем можешь помочь", "что можешь", "твои возможности", "что ты делаешь", "на что ты способна"]
    if any(k in user_text.lower() for k in skills_kw):
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📋 Всё что я умею", callback_data="skills_inline")]])
        reply = "Помогаю вам становиться лучше каждый день — планирование, здоровье, цели, напоминания, поиск и многое другое. Нажмите кнопку чтобы увидеть полный список!"
        await update.message.reply_text(reply, reply_markup=kb)
        await notify_admin(context, user_name, username, user_text, reply)
        return

    # ── AI обработка ──────────────────────────────────────────────────────────────
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
            for kw in ["нарисуй","сгенерируй картинку","создай изображение","сделай картинку","draw","generate image","create image"]:
                prompt = re.sub(kw, "", prompt, flags=re.IGNORECASE).strip()
            await update.message.reply_text("Генерирую изображение, подождите...")
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
                await update.message.reply_text("Не удалось сгенерировать изображение.")
            return

        # Новости
        if is_news_request(user_text):
            query_text = None
            for kw in ["новости про","новости о","news about"]:
                if kw in user_text.lower():
                    query_text = user_text.lower().split(kw)[-1].strip()
                    break
            news = await get_news(query=query_text, lang=lang)
            if news:
                await update.message.reply_text(news)
                await notify_admin(context, user_name, username, user_text, news[:200])
                return

        # Погода
        if is_weather_request(user_text) and not is_reminder_request(user_text):
            user_city = user.get("city") or "Москва"
            if "завтра" in user_text.lower() or "tomorrow" in user_text.lower():
                forecast = await get_weather_forecast(user_city, lang)
                if forecast:
                    lines = forecast.split("\n\n")[1].split("\n") if "\n\n" in forecast else []
                    if len(lines) > 1:
                        reply = ("Завтра в " if ru else "Tomorrow in ") + (city_in_form(user_city) if ru else user_city) + ":\n" + lines[1]
                        await update.message.reply_text(reply)
                        await notify_admin(context, user_name, username, user_text, reply)
                        return
            weather = await get_weather(user_city, lang)
            await update.message.reply_text(weather)
            await notify_admin(context, user_name, username, user_text, weather)
            return

        # Таблетки сегодня
        med_kw = ["пила ли я","принимала ли","выпила ли я","таблетку сегодня","пила сегодня"]
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

        # Питание — текстовый ввод
        food_kw = ["съела","съел","поела","поел","покушала","перекусила","на завтрак","на обед","на ужин"]
        async with db_pool.acquire() as conn:
            has_nutr_txt = await conn.fetchrow("SELECT id FROM nutrition_profile WHERE user_id = $1", user_id)
        if has_nutr_txt and any(k in user_text.lower() for k in food_kw):
            try:
                food_prompt = f"Пользователь написал о еде: {user_text}\n\nОпредели КБЖУ. Отвечай ТОЛЬКО в формате:\nБлюдо: название\nКалории: число\nБелки: число\nЖиры: число\nУглеводы: число\nКомментарий: совет"
                food_resp = ai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":food_prompt}], max_tokens=200, temperature=0.3)
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
                    await update.message.reply_text(food_text_res + "\n\nЗаписала в журнал питания! 🥗")
                    await notify_admin(context, user_name, username, user_text, food_text_res[:200])
                    return
            except Exception as fe:
                logging.error(f"food: {fe}")

        # Поиск Tavily
        if is_search_request(user_text) and not is_weather_request(user_text) and not is_news_request(user_text) and not is_image_gen_request(user_text):
            search_result = await web_search_tavily(user_text, lang)
            if search_result:
                await update.message.reply_text(search_result)
                await notify_admin(context, user_name, username, user_text, search_result[:200])
                return

        # Предлагаем планер и сразу парсим событие
        schedule_kw = ["всегда","каждый ","каждую ","каждое ","регулярно","постоянно",
                       "по понедельникам","по вторникам","по средам","по четвергам","по пятницам","по субботам","по воскресеньям",
                       "запиши","запишите","добавь в планер","в планер","в расписание",
                       "января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"]
        date_kw = re.search(r'\b(\d{1,2})\s*(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)', user_text.lower())
        has_time = re.search(r'\d{1,2}[:.:]\d{2}|в\s+\d{1,2}\s*(утра|дня|вечера|:00|часов?)', user_text.lower())
        is_schedule = any(k in user_text.lower() for k in schedule_kw) or (date_kw and has_time)
        if is_schedule:
            context.user_data["pending_planner_text"] = user_text
            try:
                parsed_events = await parse_events_ai(user_text, user_id)
                if parsed_events:
                    saved = await save_events_to_db(user_id, parsed_events)
                    if saved:
                        logging.info(f"Auto-saved to planner: {saved}")
            except Exception as pe:
                logging.error(f"auto_planner: {pe}")

        # Напоминания
        if is_reminder_request(user_text):
            tz = pytz.timezone(user["timezone"] or "Europe/Moscow")
            now = datetime.now(tz)
            essence = await rephrase_reminder(user_text, lang)
            rel_value, rel_unit = extract_relative_time(user_text)
            if rel_value is not None:
                remind_dt = now + (timedelta(minutes=rel_value) if rel_unit=="minutes" else timedelta(hours=rel_value))
                context.application.job_queue.run_once(send_scheduled_reminder, when=remind_dt, data={"user_id": user_id, "essence": essence}, name=f"once_{user_id}_{remind_dt.strftime('%H%M%S')}")
                await add_reminder(user_id, remind_dt.strftime("%H:%M"), essence)
            else:
                hour, minute = extract_exact_time(user_text)
                if hour is not None:
                    time_str = f"{hour:02d}:{minute:02d}"
                    conflict = await check_conflict_db(user_id, time_str)
                    if conflict:
                        await update.message.reply_text(f"В {time_str} уже запланировано: «{conflict}». Выбрать другое время?")
                        return
                    for job in context.application.job_queue.get_jobs_by_name(f"reminder_{user_id}_{hour}_{minute}"):
                        job.schedule_removal()
                    tz2 = pytz.timezone(user["timezone"] or "Europe/Moscow")
                    context.application.job_queue.run_daily(send_scheduled_reminder, time=time(hour=hour, minute=minute, tzinfo=tz2), data={"user_id": user_id, "essence": essence}, name=f"reminder_{user_id}_{hour}_{minute}")
                    await add_reminder(user_id, time_str, essence)

        # AI ответ
        dt = get_current_datetime(user.get("timezone","Europe/Moscow"))
        date_str = dt["ru"] if ru else dt["en"]
        comm_style = user.get("comm_style","наставник")
        system_prompt = SYSTEM_PROMPT_RU if ru else SYSTEM_PROMPT_EN
        memory_block = f"\n\nЧто я знаю об этом пользователе:\n{memory}" if memory else ""
        full_system = f"Сегодня: {date_str}\nСтиль общения: {comm_style}{memory_block}\n\n{system_prompt}"

        response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"system","content":full_system}] + history,
            max_tokens=1000, temperature=0.7
        )
        reply = response.choices[0].message.content
        await add_history(user_id, "assistant", reply)

        # Проверяем рецепт
        recipe_kw = ["ингредиент","приготовлени","рецепт","шаг 1","step 1"]
        if any(k in reply.lower() for k in recipe_kw) and len(reply) > 300:
            context.user_data["last_recipe_title"] = user_text[:50]
            context.user_data["last_recipe_content"] = reply
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("❤️ Сохранить", callback_data="save_recipe_yes"), InlineKeyboardButton("✖️ Не нужно", callback_data="dont_save_recipe")]])
            await update.message.reply_text(reply + "\n\nХотите сохранить этот рецепт в ваши любимые?", reply_markup=kb)
        else:
            await update.message.reply_text(reply)

        # ВСЕГДА отправляем уведомление админу о КАЖДОМ сообщении
        await notify_admin(context, user_name, username, user_text, reply)

    except Exception as e:
        logging.error(f"process_text: {e}")
        await update.message.reply_text(t(lang, "error"))

# ─── ФОТО И ГОЛОС ───────────────────────────────────────────────────────────────
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    if not user or not user["onboarded"]:
        await update.message.reply_text(t("ru", "not_started"))
        return
    lang = user.get("language","ru")
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
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🍽 Да, посчитай калории", callback_data="count_food_calories"), InlineKeyboardButton("🖼 Нет, просто опиши", callback_data="just_describe_photo")]])
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
                    await conn.execute("INSERT INTO food_logs (user_id, description, calories, protein, fat, carbs) VALUES ($1, $2, $3, $4, $5, $6)", user_id, dish_m.group(1).strip() if dish_m else caption, int(cal_m.group(1)) if cal_m else 0, float(prot_m.group(1)) if prot_m else 0, float(fat_m.group(1)) if fat_m else 0, float(carb_m.group(1)) if carb_m else 0)
                await update.message.reply_text(food_res + "\n\nЗаписала в журнал! 🥗")
                await notify_admin(context, user_name, username, "[Фото еды] " + caption, food_res[:200])
                return
        reply = await analyze_image(image_data, caption, lang)
        await update.message.reply_text(reply)
        await notify_admin(context, user_name, username, "[Фото]" + (" " + caption if caption else ""), reply)
    except Exception as e:
        logging.error(f"photo: {e}")
        await update.message.reply_text("Не удалось проанализировать фото.")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    if not user or not user["onboarded"]:
        await update.message.reply_text(t("ru", "not_started"))
        return
    lang = user.get("language","ru")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name
        await file.download_to_drive(tmp_path)
        transcriber = aai.Transcriber()
        config = aai.TranscriptionConfig(language_code="ru")
        transcript = transcriber.transcribe(tmp_path, config=config)
        os.unlink(tmp_path)
        if transcript.status == aai.TranscriptStatus.error or not transcript.text:
            await update.message.reply_text("Не смогла распознать голосовое. Попробуйте ещё раз.")
            return
        await process_text_message(update, context, transcript.text)
    except Exception as e:
        logging.error(f"voice: {e}")
        await update.message.reply_text("Не удалось обработать голосовое. Попробуйте текстом.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_text_message(update, context, update.message.text)

# ─── АДМИН КОМАНДЫ ──────────────────────────────────────────────────────────────
async def admin_check(update: Update) -> bool:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Нет доступа.")
        return False
    return True

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_check(update): return
    async with db_pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM users WHERE onboarded = TRUE")
        today = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM history WHERE created_at >= NOW() - INTERVAL '1 day'")
        week = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM history WHERE created_at >= NOW() - INTERVAL '7 days'")
        total_msg = await conn.fetchval("SELECT COUNT(*) FROM history WHERE role = 'user'")
        ru_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE language = 'ru' AND onboarded = TRUE")
        en_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE language = 'en' AND onboarded = TRUE")
    await update.message.reply_text(f"София — статистика\n\nВсего пользователей: {total}\nРусский: {ru_users}\nEnglish: {en_users}\nАктивны сегодня: {today}\nЗа 7 дней: {week}\nВсего сообщений: {total_msg}")

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info(f"list_users called by {update.effective_user.id}")
    if not await admin_check(update): return
    async with db_pool.acquire() as conn:
        users_list = await conn.fetch("SELECT user_id, name, username, language, comm_style FROM users WHERE onboarded = TRUE LIMIT 50")
    if not users_list:
        await update.message.reply_text("Пользователей нет.")
        return
    lines = []
    for u in users_list:
        lines.append(f"ID: {u['user_id']} | {u['name'] or '?'} @{u['username'] or '?'} | {u['language']} | {u['comm_style']}")
    text = f"Пользователи ({len(users_list)}):\n\n" + "\n".join(lines)
    if len(text) > 4000: text = text[:4000] + "..."
    await update.message.reply_text(text)

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_check(update): return
    if not context.args:
        await update.message.reply_text("Использование: /ban USER_ID")
        return
    try:
        target_id = int(context.args[0])
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE users SET onboarded = FALSE WHERE user_id = $1", target_id)
        await update.message.reply_text(f"Пользователь {target_id} заблокирован.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_check(update): return
    if not context.args:
        await update.message.reply_text("Использование: /unban USER_ID")
        return
    try:
        target_id = int(context.args[0])
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE users SET onboarded = TRUE WHERE user_id = $1", target_id)
        await update.message.reply_text(f"Пользователь {target_id} разблокирован.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def msg_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_check(update): return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Использование: /msg USER_ID Текст\nНапример: /msg 7630390995 Привет!")
        return
    try:
        target_id = int(context.args[0])
        text = " ".join(context.args[1:])
        await context.bot.send_message(chat_id=target_id, text=text)
        await update.message.reply_text(f"Сообщение отправлено пользователю {target_id}.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def reset_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_check(update): return
    if not context.args:
        await update.message.reply_text("Использование: /reset USER_ID\nНапример: /reset 7630390995")
        return
    try:
        target_id = int(context.args[0])
        async with db_pool.acquire() as conn:
            for tbl in ["history","reminders","notes","habits","habit_logs","finances","user_memory","sleep_logs","shopping_list","saved_recipes","planner","cycle_tracking","medications","medication_logs","stress_logs","goals","weight_logs","nutrition_profile","food_logs","birthdays","mood_logs","water_logs"]:
                try:
                    await conn.execute(f"DELETE FROM {tbl} WHERE user_id = $1", target_id)
                except:
                    pass
            await conn.execute("UPDATE users SET onboarded = FALSE, name = NULL, morning_plan = FALSE, evening_news = FALSE, water_reminders = FALSE, comm_style = 'наставник' WHERE user_id = $1", target_id)
        for job in context.application.job_queue.jobs():
            if hasattr(job, "data") and (job.data == target_id or (isinstance(job.data, dict) and job.data.get("user_id") == target_id)):
                job.schedule_removal()
        await update.message.reply_text(f"Пользователь {target_id} сброшен. При следующем /start пройдёт онбординг заново.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_check(update): return
    if not context.args:
        await update.message.reply_text("Пример: /announce Текст сообщения")
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

# ─── ЗАПУСК ─────────────────────────────────────────────────────────────────────
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "sofia2025")

def start_admin_api():
    if not FASTAPI_AVAILABLE:
        logging.warning("FastAPI not available, admin panel disabled")
        return
    import asyncpg as _asyncpg

    admin_app = FastAPI()
    admin_app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    security = HTTPBearer()

    def check_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
        if credentials.credentials != ADMIN_PASSWORD:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return True

    async def db():
        return await _asyncpg.connect(DATABASE_URL)

    @admin_app.get("/admin/stats")
    async def api_stats(auth=Depends(check_token)):
        conn = await db()
        try:
            total = await conn.fetchval("SELECT COUNT(*) FROM users WHERE onboarded=TRUE")
            today_active = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM history WHERE created_at >= CURRENT_DATE AND role='user'")
            today_msg = await conn.fetchval("SELECT COUNT(*) FROM history WHERE created_at >= CURRENT_DATE AND role='user'")
            today_new = await conn.fetchval("SELECT COUNT(*) FROM users WHERE onboarded=TRUE AND user_id IN (SELECT DISTINCT user_id FROM history WHERE created_at >= CURRENT_DATE)")
            week = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM history WHERE created_at >= NOW() - INTERVAL '7 days'")
            banned = await conn.fetchval("SELECT COUNT(*) FROM users WHERE onboarded=FALSE")
            total_msg = await conn.fetchval("SELECT COUNT(*) FROM history WHERE role='user'")
            new_week = await conn.fetchval("SELECT COUNT(*) FROM users WHERE onboarded=TRUE AND user_id IN (SELECT DISTINCT user_id FROM history WHERE created_at >= NOW() - INTERVAL '7 days')")
            ru_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE language='ru' AND onboarded=TRUE")
            en_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE language='en' AND onboarded=TRUE")
            return {"total": total, "today": today_active, "today_msg": today_msg, "today_new": today_new,
                    "week": week, "banned": banned, "total_msg": total_msg,
                    "new_week": new_week, "ru_users": ru_users, "en_users": en_users}
        finally:
            await conn.close()

    @admin_app.get("/admin/users")
    async def api_users(auth=Depends(check_token)):
        conn = await db()
        try:
            rows = await conn.fetch("""
                SELECT u.user_id, u.name, u.username, u.language, u.comm_style, u.onboarded, u.city,
                       COUNT(h.id) as msg_count, MAX(h.created_at) as last_active
                FROM users u
                LEFT JOIN history h ON h.user_id = u.user_id AND h.role = 'user'
                GROUP BY u.user_id, u.name, u.username, u.language, u.comm_style, u.onboarded, u.city
                ORDER BY last_active DESC NULLS LAST
            """)
            return [{"user_id": r["user_id"], "name": r["name"] or "—", "username": r["username"] or "—",
                     "language": r["language"] or "ru", "comm_style": r["comm_style"] or "—",
                     "active": r["onboarded"], "city": r["city"] or "—",
                     "msg_count": r["msg_count"],
                     "last_active": r["last_active"].strftime("%d.%m.%Y %H:%M") if r["last_active"] else "—"} for r in rows]
        finally:
            await conn.close()

    @admin_app.get("/planner/events/{user_id}")
    async def planner_events(user_id: int):
        conn = await db()
        try:
            rows = await conn.fetch(
                "SELECT * FROM events WHERE user_id=$1 ORDER BY event_date, event_time",
                user_id
            )
            result = []
            for r in rows:
                result.append({
                    "id": r["id"],
                    "title": r["title"],
                    "person_name": r["person_name"] or "",
                    "event_date": str(r["event_date"]) if r["event_date"] else "",
                    "event_time": r["event_time"] or "",
                    "repeat_type": r["repeat_type"],
                    "repeat_day": r["repeat_day"] if r["repeat_day"] is not None else -1,
                    "repeat_month_day": r["repeat_month_day"] or 0,
                })
            return result
        finally:
            await conn.close()

    @admin_app.post("/planner/add")
    async def planner_add(body: dict):
        user_id = body.get("user_id")
        text = body.get("text","")
        if not user_id or not text:
            raise HTTPException(status_code=400, detail="Missing user_id or text")
        conn = await db()
        try:
            import json as _json
            from datetime import date as _d
            today = _d.today()
            system = f"""Сегодня {today.strftime('%d.%m.%Y')}.
Извлеки все события. Ответь ТОЛЬКО валидным JSON массивом:
[{{"title":"название","person":"имя или пустая строка","time":"ЧЧ:ММ или пустая строка","repeat_type":"once/weekly/monthly_day","date":"ДД.ММ.ГГГГ если конкретная дата","weekdays":[0-6] если еженедельно,"month_day":число если каждое N-е число}}]"""
            resp = ai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role":"system","content":system},{"role":"user","content":text}],
                max_tokens=400, temperature=0.1
            )
            result = resp.choices[0].message.content.strip().replace("```json","").replace("```","").strip()
            events = _json.loads(result)
            saved = []
            from datetime import timedelta, datetime as _dt
            for ev in events:
                title = ev.get("title","")
                person = ev.get("person","")
                ev_time = ev.get("time","") or ""
                repeat_type = ev.get("repeat_type","once")
                date_str = ev.get("date","")
                weekdays = ev.get("weekdays",[])
                month_day = ev.get("month_day",0)
                if not title: continue
                if repeat_type=="once":
                    try: ev_date = _dt.strptime(date_str,"%d.%m.%Y").date() if date_str else today
                    except: ev_date = today
                    await conn.execute("INSERT INTO events (user_id,title,person_name,event_date,event_time,repeat_type) VALUES ($1,$2,$3,$4,$5,$6)",user_id,title,person,ev_date,ev_time,"once")
                    saved.append(title)
                elif repeat_type=="weekly" and weekdays:
                    for wd in weekdays:
                        days_ahead=wd-today.weekday()
                        if days_ahead<0: days_ahead+=7
                        next_date=today+timedelta(days=days_ahead)
                        await conn.execute("INSERT INTO events (user_id,title,person_name,event_date,event_time,repeat_type,repeat_day) VALUES ($1,$2,$3,$4,$5,$6,$7)",user_id,title,person,next_date,ev_time,"weekly",wd)
                    saved.append(title)
                elif repeat_type=="monthly_day" and month_day:
                    try:
                        next_date=today.replace(day=month_day) if today.day<=month_day else (today.replace(month=today.month%12+1,day=month_day) if today.month<12 else today.replace(year=today.year+1,month=1,day=month_day))
                    except: next_date=today
                    await conn.execute("INSERT INTO events (user_id,title,person_name,event_date,event_time,repeat_type,repeat_month_day) VALUES ($1,$2,$3,$4,$5,$6,$7)",user_id,title,person,next_date,ev_time,"monthly_day",month_day)
                    saved.append(title)
            return {"ok":True,"saved":saved}
        except Exception as e:
            logging.error(f"planner_add: {e}")
            raise HTTPException(status_code=500,detail=str(e))
        finally:
            await conn.close()

    # ── APP ENDPOINTS ──────────────────────────────────────────────────────────

    @admin_app.get("/app/tasks/{user_id}")
    async def get_tasks(user_id: int):
        conn = await db()
        try:
            rows = await conn.fetch("SELECT id, text, done FROM notes WHERE user_id=$1 AND text LIKE 'TASK:%' ORDER BY id DESC LIMIT 50", user_id)
            return [{"id":r["id"],"text":r["text"].replace("TASK:","",1).strip(),"done":r["done"] if "done" in r else False} for r in rows]
        except:
            return []
        finally:
            await conn.close()

    @admin_app.post("/app/tasks")
    async def add_task(body: dict):
        conn = await db()
        try:
            row = await conn.fetchrow("INSERT INTO notes (user_id, text) VALUES ($1, $2) RETURNING id", body["user_id"], "TASK:"+body["text"])
            return {"id":row["id"],"text":body["text"],"done":False}
        finally:
            await conn.close()

    @admin_app.patch("/app/tasks/{task_id}")
    async def toggle_task(task_id: int, body: dict):
        conn = await db()
        try:
            row = await conn.fetchrow("SELECT text FROM notes WHERE id=$1", task_id)
            if row:
                text = row["text"]
                if body.get("done") and not text.startswith("DONE:"):
                    text = text.replace("TASK:", "DONE:", 1)
                elif not body.get("done") and text.startswith("DONE:"):
                    text = text.replace("DONE:", "TASK:", 1)
                await conn.execute("UPDATE notes SET text=$1 WHERE id=$2", text, task_id)
            return {"ok": True}
        finally:
            await conn.close()

    @admin_app.delete("/app/tasks/{task_id}")
    async def del_task(task_id: int, body: dict = None):
        conn = await db()
        try:
            await conn.execute("DELETE FROM notes WHERE id=$1", task_id)
            return {"ok": True}
        finally:
            await conn.close()

    @admin_app.get("/app/goals/{user_id}")
    async def get_goals(user_id: int):
        conn = await db()
        try:
            rows = await conn.fetch("SELECT id, title, progress, deadline FROM goals WHERE user_id=$1 AND progress < 100 ORDER BY id DESC", user_id)
            return [{"id":r["id"],"title":r["title"],"progress":r["progress"],"deadline":str(r["deadline"]) if r["deadline"] else None} for r in rows]
        finally:
            await conn.close()

    @admin_app.post("/app/goals")
    async def add_goal_app(body: dict):
        conn = await db()
        try:
            row = await conn.fetchrow("INSERT INTO goals (user_id, title) VALUES ($1, $2) RETURNING id", body["user_id"], body["title"])
            return {"id":row["id"],"title":body["title"],"progress":0,"deadline":None}
        finally:
            await conn.close()

    @admin_app.get("/app/shopping/{user_id}")
    async def get_shopping(user_id: int):
        conn = await db()
        try:
            rows = await conn.fetch("SELECT id, item, done FROM shopping_list WHERE user_id=$1 ORDER BY created_at DESC", user_id)
            return [{"id":r["id"],"item":r["item"],"done":r["done"]} for r in rows]
        finally:
            await conn.close()

    @admin_app.post("/app/shopping")
    async def add_shopping(body: dict):
        conn = await db()
        try:
            row = await conn.fetchrow("INSERT INTO shopping_list (user_id, item) VALUES ($1, $2) RETURNING id", body["user_id"], body["item"])
            return {"id":row["id"],"item":body["item"],"done":False}
        finally:
            await conn.close()

    @admin_app.patch("/app/shopping/{item_id}")
    async def toggle_shopping(item_id: int, body: dict):
        conn = await db()
        try:
            await conn.execute("UPDATE shopping_list SET done=$1 WHERE id=$2", body.get("done", False), item_id)
            return {"ok": True}
        finally:
            await conn.close()

    @admin_app.delete("/app/shopping/{item_id}")
    async def del_shopping(item_id: int, body: dict = None):
        conn = await db()
        try:
            await conn.execute("DELETE FROM shopping_list WHERE id=$1", item_id)
            return {"ok": True}
        finally:
            await conn.close()

    @admin_app.post("/app/shopping/clear")
    async def clear_shopping(body: dict):
        conn = await db()
        try:
            await conn.execute("DELETE FROM shopping_list WHERE user_id=$1 AND done=TRUE", body["user_id"])
            return {"ok": True}
        finally:
            await conn.close()

    @admin_app.get("/app/finance/{user_id}")
    async def get_finance(user_id: int):
        conn = await db()
        try:
            rows = await conn.fetch("SELECT id, amount, type, category, description FROM finances WHERE user_id=$1 ORDER BY created_at DESC LIMIT 30", user_id)
            return [{"id":r["id"],"amount":r["amount"],"type":r["type"],"category":r["category"],"description":r["description"]} for r in rows]
        finally:
            await conn.close()

    @admin_app.post("/app/finance")
    async def add_finance_app(body: dict):
        conn = await db()
        try:
            row = await conn.fetchrow("INSERT INTO finances (user_id, amount, type, category, description) VALUES ($1,$2,$3,$4,$5) RETURNING id", body["user_id"], body["amount"], body["type"], body.get("category","Другое"), body.get("description",""))
            return {"id":row["id"],"amount":body["amount"],"type":body["type"],"category":body.get("category","Другое"),"description":body.get("description","")}
        finally:
            await conn.close()

    @admin_app.get("/app/meds/{user_id}")
    async def get_meds(user_id: int):
        conn = await db()
        try:
            rows = await conn.fetch("SELECT id, name, time_str FROM medications WHERE user_id=$1 ORDER BY time_str", user_id)
            result = []
            for r in rows:
                taken = await conn.fetchval("SELECT COUNT(*) FROM medication_logs WHERE med_id=$1 AND taken_at >= CURRENT_DATE", r["id"])
                result.append({"id":r["id"],"name":r["name"],"time_str":r["time_str"],"taken":taken>0})
            return result
        finally:
            await conn.close()

    @admin_app.post("/app/meds/{med_id}/take")
    async def take_med_app(med_id: int, body: dict):
        conn = await db()
        try:
            await conn.execute("INSERT INTO medication_logs (user_id, med_id) VALUES ($1,$2)", body["user_id"], med_id)
            return {"ok": True}
        finally:
            await conn.close()

    @admin_app.get("/app/water/{user_id}")
    async def get_water(user_id: int):
        conn = await db()
        try:
            row = await conn.fetchrow("SELECT glasses FROM water_logs WHERE user_id=$1 AND log_date=CURRENT_DATE", user_id)
            return {"glasses": row["glasses"] if row else 0}
        finally:
            await conn.close()

    @admin_app.post("/app/water")
    async def add_water_app(body: dict):
        conn = await db()
        try:
            existing = await conn.fetchrow("SELECT id FROM water_logs WHERE user_id=$1 AND log_date=CURRENT_DATE", body["user_id"])
            if existing:
                await conn.execute("UPDATE water_logs SET glasses=$1 WHERE user_id=$2 AND log_date=CURRENT_DATE", body["glasses"], body["user_id"])
            else:
                await conn.execute("INSERT INTO water_logs (user_id, glasses) VALUES ($1,$2)", body["user_id"], body["glasses"])
            return {"ok": True}
        finally:
            await conn.close()

    @admin_app.post("/app/stress")
    async def add_stress_app(body: dict):
        conn = await db()
        try:
            await conn.execute("INSERT INTO stress_logs (user_id, level) VALUES ($1,$2)", body["user_id"], body["level"])
            return {"ok": True}
        finally:
            await conn.close()

    @admin_app.delete("/app/events/{event_id}")
    async def del_event_app(event_id: int, body: dict = None):
        conn = await db()
        try:
            await conn.execute("DELETE FROM events WHERE id=$1", event_id)
            return {"ok": True}
        finally:
            await conn.close()

    @admin_app.get("/app/reminders/{user_id}")
    async def get_reminders_app(user_id: int):
        conn = await db()
        try:
            rows = await conn.fetch("SELECT id, time_str, text FROM reminders WHERE user_id=$1 ORDER BY time_str", user_id)
            return [{"id":r["id"],"time_str":r["time_str"],"text":r["text"]} for r in rows]
        finally:
            await conn.close()

    @admin_app.get("/app/stress/{user_id}")
    async def get_stress_app(user_id: int):
        conn = await db()
        try:
            rows = await conn.fetch("SELECT level, created_at FROM stress_logs WHERE user_id=$1 AND created_at >= NOW() - INTERVAL '7 days' ORDER BY created_at", user_id)
            return [{"level":r["level"],"date":str(r["created_at"].date())} for r in rows]
        finally:
            await conn.close()

    @admin_app.get("/app/cycle/{user_id}")
    async def get_cycle_app(user_id: int):
        conn = await db()
        try:
            row = await conn.fetchrow("SELECT start_date, cycle_length FROM cycle_tracking WHERE user_id=$1 ORDER BY created_at DESC LIMIT 1", user_id)
            if not row: return None
            return {"start_date":str(row["start_date"]),"cycle_length":row["cycle_length"]}
        finally:
            await conn.close()

    @admin_app.get("/app/usersettings/{user_id}")
    async def get_user_settings(user_id: int):
        conn = await db()
        try:
            row = await conn.fetchrow("SELECT language, comm_style, morning_plan, evening_news, water_reminders FROM users WHERE user_id=$1", user_id)
            if not row: return {}
            return {"lang":row["language"],"style":row["comm_style"],"morning":row["morning_plan"],"evening":row["evening_news"],"water":row["water_reminders"]}
        finally:
            await conn.close()

    @admin_app.post("/app/settings")
    async def save_user_settings(body: dict):
        conn = await db()
        try:
            key = body.get("key")
            val = body.get("value")
            uid = body.get("user_id")
            mapping = {"lang":"language","style":"comm_style","morning":"morning_plan","evening":"evening_news","water":"water_reminders"}
            db_key = mapping.get(key)
            if db_key:
                await conn.execute(f"UPDATE users SET {db_key}=$1 WHERE user_id=$2", val, uid)
            return {"ok": True}
        finally:
            await conn.close()

    @admin_app.get("/app/birthdays/{user_id}")
    async def get_birthdays_app(user_id: int):
        conn = await db()
        try:
            rows = await conn.fetch("SELECT id, person_name, birth_date FROM birthdays WHERE user_id=$1 ORDER BY birth_date", user_id)
            return [{"id":r["id"],"person_name":r["person_name"],"birth_date":r["birth_date"]} for r in rows]
        finally:
            await conn.close()

    @admin_app.post("/app/birthday")
    async def add_birthday_app(body: dict):
        conn = await db()
        try:
            row = await conn.fetchrow("INSERT INTO birthdays (user_id, person_name, birth_date) VALUES ($1,$2,$3) RETURNING id", body["user_id"], body["person_name"], body["birth_date"])
            return {"id":row["id"],"person_name":body["person_name"],"birth_date":body["birth_date"]}
        finally:
            await conn.close()

    @admin_app.get("/app/recipes/{user_id}")
    async def get_recipes_app(user_id: int):
        conn = await db()
        try:
            rows = await conn.fetch("SELECT id, title, content FROM saved_recipes WHERE user_id=$1 ORDER BY created_at DESC", user_id)
            return [{"id":r["id"],"title":r["title"],"content":r["content"]} for r in rows]
        finally:
            await conn.close()

    @admin_app.post("/app/random-recipe")
    async def random_recipe_app(body: dict):
        try:
            resp = ai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role":"user","content":"Придумай случайный рецепт. Напиши название и полный рецепт с ингредиентами и пошаговым приготовлением. Без звёздочек и markdown."}],
                max_tokens=600, temperature=0.9
            )
            text = resp.choices[0].message.content
            lines = text.strip().split("\n")
            title = lines[0].strip() if lines else "Рецепт"
            return {"title": title, "content": text}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @admin_app.post("/app/cycle")
    async def save_cycle_app(body: dict):
        conn = await db()
        try:
            from datetime import datetime as _dt2
            date_obj = _dt2.strptime(body["start_date"], "%Y-%m-%d").date()
            await conn.execute("INSERT INTO cycle_tracking (user_id, start_date, cycle_length) VALUES ($1,$2,$3)", body["user_id"], date_obj, body.get("cycle_length", 28))
            return {"ok": True}
        finally:
            await conn.close()

    @admin_app.get("/admin/activity")
    async def api_activity(auth=Depends(check_token)):
        conn = await db()
        try:
            rows = await conn.fetch("""
                SELECT DATE(created_at) as day, COUNT(*) as count
                FROM history
                WHERE role = 'user' AND created_at >= NOW() - INTERVAL '30 days'
                GROUP BY DATE(created_at)
                ORDER BY day ASC
            """)
            return [{"day": str(r["day"]), "count": r["count"]} for r in rows]
        finally:
            await conn.close()

    @admin_app.get("/admin/history/{user_id}")
    async def api_history(user_id: int, auth=Depends(check_token)):
        conn = await db()
        try:
            rows = await conn.fetch("SELECT role, content, created_at FROM history WHERE user_id=$1 ORDER BY created_at DESC LIMIT 500", user_id)
            return [{"role": r["role"], "content": r["content"], "time": r["created_at"].strftime("%d.%m %H:%M")} for r in rows]
        finally:
            await conn.close()

    @admin_app.post("/admin/ban/{user_id}")
    async def api_ban(user_id: int, auth=Depends(check_token)):
        conn = await db()
        try:
            await conn.execute("UPDATE users SET onboarded=FALSE WHERE user_id=$1", user_id)
            return {"ok": True}
        finally:
            await conn.close()

    @admin_app.post("/admin/unban/{user_id}")
    async def api_unban(user_id: int, auth=Depends(check_token)):
        conn = await db()
        try:
            await conn.execute("UPDATE users SET onboarded=TRUE WHERE user_id=$1", user_id)
            return {"ok": True}
        finally:
            await conn.close()

    @admin_app.post("/admin/reset/{user_id}")
    async def api_reset(user_id: int, auth=Depends(check_token)):
        conn = await db()
        try:
            for tbl in ["history","reminders","notes","habits","habit_logs","finances",
                        "user_memory","shopping_list","saved_recipes","planner","events",
                        "cycle_tracking","medications","medication_logs","stress_logs",
                        "goals","weight_logs","nutrition_profile","food_logs","birthdays","mood_logs","water_logs"]:
                try:
                    await conn.execute(f"DELETE FROM {tbl} WHERE user_id=$1", user_id)
                except: pass
            await conn.execute("UPDATE users SET onboarded=FALSE, name=NULL WHERE user_id=$1", user_id)
            return {"ok": True}
        finally:
            await conn.close()

    @admin_app.post("/admin/message/{user_id}")
    async def api_message(user_id: int, body: dict, auth=Depends(check_token)):
        from telegram import Bot as _Bot
        bot = _Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(chat_id=user_id, text=body.get("text",""))
        return {"ok": True}

    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse
    import os as _os

    @admin_app.get("/planner.html")
    async def serve_planner():
        planner_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "planner.html")
        return FileResponse(planner_path)

    uvicorn.run(admin_app, host="0.0.0.0", port=8080, log_level="warning")

async def post_init(application):
    await init_db()
    await restore_reminders(application)
    application.job_queue.run_daily(check_cycle_reminders, time=time(hour=9, minute=0), name="cycle_check")
    application.job_queue.run_daily(send_midday_checkin, time=time(hour=17, minute=0), name="midday_checkin")
    application.job_queue.run_daily(check_goal_reminders, time=time(hour=12, minute=0), name="goal_check")
    application.job_queue.run_daily(check_birthday_reminders, time=time(hour=10, minute=0), name="birthday_check")
    application.job_queue.run_daily(send_weekly_habit_report, time=time(hour=20, minute=0), name="weekly_habits")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    # ConversationHandler — ТОЛЬКО онбординг, /start НЕ открывает меню!
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [            CommandHandler("users", list_users),
            CommandHandler("stats", stats),
            CommandHandler("reset", reset_user),
            CommandHandler("ban", ban_user),
            CommandHandler("unban", unban_user),
            CommandHandler("msg", msg_user),
            CommandHandler("announce", announce),
            CommandHandler("menu", show_menu),
            CommandHandler("skills", skills_command),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_CITY: [            CommandHandler("users", list_users),
            CommandHandler("stats", stats),
            CommandHandler("reset", reset_user),
            CommandHandler("ban", ban_user),
            CommandHandler("unban", unban_user),
            CommandHandler("msg", msg_user),
            CommandHandler("announce", announce),
            CommandHandler("menu", show_menu),
            CommandHandler("skills", skills_command),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_city)],
            ASK_LANGUAGE: [            CommandHandler("users", list_users),
            CommandHandler("stats", stats),
            CommandHandler("reset", reset_user),
            CommandHandler("ban", ban_user),
            CommandHandler("unban", unban_user),
            CommandHandler("msg", msg_user),
            CommandHandler("announce", announce),
            CommandHandler("menu", show_menu),
            CommandHandler("skills", skills_command),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_language)],
            ASK_MORNING_PLAN: [            CommandHandler("users", list_users),
            CommandHandler("stats", stats),
            CommandHandler("reset", reset_user),
            CommandHandler("ban", ban_user),
            CommandHandler("unban", unban_user),
            CommandHandler("msg", msg_user),
            CommandHandler("announce", announce),
            CommandHandler("menu", show_menu),
            CommandHandler("skills", skills_command),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_morning_plan)],
            ASK_MORNING_TIME: [            CommandHandler("users", list_users),
            CommandHandler("stats", stats),
            CommandHandler("reset", reset_user),
            CommandHandler("ban", ban_user),
            CommandHandler("unban", unban_user),
            CommandHandler("msg", msg_user),
            CommandHandler("announce", announce),
            CommandHandler("menu", show_menu),
            CommandHandler("skills", skills_command),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_morning_time)],
            ASK_REMINDERS: [            CommandHandler("users", list_users),
            CommandHandler("stats", stats),
            CommandHandler("reset", reset_user),
            CommandHandler("ban", ban_user),
            CommandHandler("unban", unban_user),
            CommandHandler("msg", msg_user),
            CommandHandler("announce", announce),
            CommandHandler("menu", show_menu),
            CommandHandler("skills", skills_command),
                MessageHandler(filters.TEXT & ~filters.COMMAND, finish_onboarding)],
            ASK_EVENING_NEWS: [            CommandHandler("users", list_users),
            CommandHandler("stats", stats),
            CommandHandler("reset", reset_user),
            CommandHandler("ban", ban_user),
            CommandHandler("unban", unban_user),
            CommandHandler("msg", msg_user),
            CommandHandler("announce", announce),
            CommandHandler("menu", show_menu),
            CommandHandler("skills", skills_command),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_evening_news_answer)],
            ASK_EVENING_TIME: [            CommandHandler("users", list_users),
            CommandHandler("stats", stats),
            CommandHandler("reset", reset_user),
            CommandHandler("ban", ban_user),
            CommandHandler("unban", unban_user),
            CommandHandler("msg", msg_user),
            CommandHandler("announce", announce),
            CommandHandler("menu", show_menu),
            CommandHandler("skills", skills_command),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_evening_time)],
            ASK_COMM_STYLE: [            CommandHandler("users", list_users),
            CommandHandler("stats", stats),
            CommandHandler("reset", reset_user),
            CommandHandler("ban", ban_user),
            CommandHandler("unban", unban_user),
            CommandHandler("msg", msg_user),
            CommandHandler("announce", announce),
            CommandHandler("menu", show_menu),
            CommandHandler("skills", skills_command),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_comm_style)],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("users", list_users),
            CommandHandler("stats", stats),
            CommandHandler("reset", reset_user),
            CommandHandler("ban", ban_user),
            CommandHandler("unban", unban_user),
            CommandHandler("msg", msg_user),
            CommandHandler("announce", announce),
            CommandHandler("menu", show_menu),
            CommandHandler("skills", skills_command),
        ]
    )
    app.add_handler(conv_handler)

    # Команды
    app.add_handler(CommandHandler("menu", show_menu))       # /menu — открывает меню
    app.add_handler(CommandHandler("skills", skills_command)) # /skills — что умею
    # Админ команды (только ADMIN_ID = 944447597)
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("users", list_users))
    app.add_handler(CommandHandler("announce", announce))
    app.add_handler(CommandHandler("reset", reset_user))
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("unban", unban_user))
    app.add_handler(CommandHandler("msg", msg_user))

    # Обработчики
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🌸 София v6.1 запущена! Admin ID:", ADMIN_ID)
    t = threading.Thread(target=start_admin_api, daemon=True)
    t.start()
    app.run_polling()
