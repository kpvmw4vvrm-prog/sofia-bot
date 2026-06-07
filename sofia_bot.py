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
from groq import Groq

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
ASSEMBLYAI_KEY = os.environ.get("ASSEMBLYAI_KEY")
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY")
ADMIN_ID = 944447597
DATABASE_URL = os.environ.get("DATABASE_URL")

logging.basicConfig(level=logging.INFO)
groq_client = Groq(api_key=GROQ_API_KEY)
aai.settings.api_key = ASSEMBLYAI_KEY
tf = TimezoneFinder()

ASK_NAME, ASK_CITY, ASK_LANGUAGE, ASK_MORNING_PLAN, ASK_MORNING_TIME, ASK_REMINDERS = range(6)

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
        "welcome": "Добрый день!\n\nРада познакомиться! Я здесь чтобы помочь вам с планами, целями и важными делами.\n\nДавайте начнём — как вас зовут? )",
        "ask_city": "Очень приятно, {name}! 😊\n\n🌍 В каком городе вы находитесь?\n\nНапример: Москва, Алматы, Дубай",
        "ask_language": "Отлично! Запомнила — {city} 🌍\n\nНа каком языке вам удобнее общаться?",
        "ask_morning": "Хотите чтобы я каждое утро присылала план дня? 📋",
        "ask_morning_time": "В какое время присылать утренний план? ☀️",
        "ask_reminders": "Напоминать о делах заранее? 🙂",
        "finish": "Всё готово, {name}! 🌸\n\nНапишите /menu чтобы открыть меню 🌸",
        "menu_title": "🌸 *Меню Софии*\n\nЗдравствуйте, {name}! Чем могу помочь?",
        "not_started": "Напишите /start чтобы начать 🌸",
        "error": "Прошу прощения, техническая ошибка. Попробуйте ещё раз.",
        "water": "💧 {name}, не забудьте выпить стакан воды! 🌊",
        "reminder": "⏰ {name}, напоминаю!\n\n{text}",
        "morning": "☀️ Доброе утро, {name}!\n\n",
        "no_plan": "📋 На сегодня задачи не добавлены.",
        "history_cleared": "История очищена 🌸",
        "lang_changed": "🌍 Язык изменён на русский!",
    },
    "en": {
        "welcome": "Good day!\n\nNice to meet you! I'm here to help you with plans, goals and important tasks.\n\nLet's start — what's your name? )",
        "ask_city": "Nice to meet you, {name}! 😊\n\n🌍 What city are you in?\n\nFor example: London, New York, Dubai",
        "ask_language": "Got it — {city} 🌍\n\nWhat language would you prefer?",
        "ask_morning": "Would you like me to send you a daily plan every morning? 📋",
        "ask_morning_time": "What time should I send the morning plan? ☀️",
        "ask_reminders": "Remind you about tasks in advance? 🙂",
        "finish": "All done, {name}! 🌸\n\nType /menu to open the menu 🌸",
        "menu_title": "🌸 *Sofia's Menu*\n\nHello, {name}! How can I help?",
        "not_started": "Type /start to begin 🌸",
        "error": "Sorry, technical error. Please try again.",
        "water": "💧 {name}, don't forget to drink a glass of water! 🌊",
        "reminder": "⏰ {name}, reminder!\n\n{text}",
        "morning": "☀️ Good morning, {name}!\n\n",
        "no_plan": "📋 No tasks added for today.",
        "history_cleared": "History cleared 🌸",
        "lang_changed": "🌍 Language changed to English!",
    }
}

def t(lang, key, **kwargs):
    text = TEXTS.get(lang, TEXTS["ru"]).get(key, TEXTS["ru"].get(key, ""))
    return text.format(**kwargs) if kwargs else text

SYSTEM_PROMPT_RU = """Ты — София, личный ассистент, стратег и умный помощник. Общаешься вежливо и профессионально, обращаешься на "Вы". Деловой стиль, но живой. Умеренно используй эмодзи.

Что ты умеешь:
1. Планирование — составляешь план на день, завтра, неделю, месяц по запросу.
2. История — помнишь всё что пользователь делал и говорил.
3. Стратегия целей — ведёшь по шагам к достижению цели.
4. Напоминания — присылаешь точно в срок.
5. Психологическая поддержка — выслушаешь и поможешь.
6. Нутрициолог — посоветуешь по питанию и здоровью.
7. Умный помощник — отвечаешь на любые вопросы.

Правила оформления:
— Списки нумеруй: 1. 2. 3.
— Планы пиши по времени в столбик
— Пиши коротко и по существу
— Один вопрос за раз

Формат плана дня:
🕘 09:00 — задача
🕙 10:00 — задача
"""

SYSTEM_PROMPT_EN = """You are Sofia, a personal assistant, strategist and smart helper. You communicate politely and professionally. Business style but lively. Use emojis moderately.

What you can do:
1. Planning — create plans for today, tomorrow, week, month on request.
2. Memory — remember everything the user has done and said.
3. Goal strategy — guide step by step to achieve any goal.
4. Reminders — send exactly on time.
5. Psychological support — listen and help.
6. Nutritionist — advise on nutrition and health.
7. Smart assistant — answer any questions.

Formatting rules:
— Number lists: 1. 2. 3.
— Write plans by time in a column
— Be brief and to the point
— One question at a time

Day plan format:
🕘 09:00 — task
🕙 10:00 — task
"""

SKILLS_RU = """🌸 *Вот что я умею:*

🧠 *Обучаюсь под вас*
Запоминаю ваши предпочтения и со временем становлюсь лучше

🎯 *Стратегия достижения целей*
Строю пошаговый план с расписанием для любой вашей цели

🎤 *Голосовые сообщения*
Говорите вслух — я пойму и отвечу

🌍 *Два языка*
Русский и английский — переключайтесь в любой момент 🇷🇺 🇬🇧

⏰ *Умные напоминания*
Напомню за нужное время до события

📋 *Утренний план*
Каждое утро — план дел, погода и мотивация

💪 *Трекер привычек*
Отмечайте прогресс и следите за статистикой

😴 *Трекер сна*
Рассчитаю идеальное время отхода ко сну

💰 *Контроль финансов*
Записывайте доходы и расходы, смотрите статистику

📝 *Заметки*
Сохраняю ваши идеи мгновенно

🍳 *Рецепты*
Новая идея что приготовить каждый день

🎬 *Что посмотреть*
Персональная рекомендация фильма на вечер

🧘 *Психологическая поддержка*
Выслушаю и помогу в любой ситуации

🥗 *Личный нутрициолог*
Советы по питанию и здоровому образу жизни

💧 *Напоминания о воде*
Забочусь о вашем здоровье каждый день

_Напишите /menu чтобы открыть меню_ 🌸"""

SKILLS_EN = """🌸 *Here's what I can do:*

🧠 *I learn from you*
I remember your preferences and get better over time

🎯 *Goal achievement strategy*
I build a step-by-step plan with schedule for any goal

🎤 *Voice messages*
Speak out loud — I'll understand and respond

🌍 *Two languages*
Russian and English — switch anytime 🇷🇺 🇬🇧

⏰ *Smart reminders*
I'll remind you the right time before any event

📋 *Morning plan*
Every morning — tasks, weather and motivation

💪 *Habit tracker*
Track progress and monitor statistics

😴 *Sleep tracker*
I'll calculate the ideal bedtime for you

💰 *Finance control*
Record income and expenses, view statistics

📝 *Notes*
I save your ideas instantly

🍳 *Recipes*
A new cooking idea every day

🎬 *What to watch*
Personal movie recommendation for the evening

🧘 *Psychological support*
I'll listen and help in any situation

🥗 *Personal nutritionist*
Nutrition and healthy lifestyle advice

💧 *Water reminders*
I take care of your health every day

_Type /menu to open the menu_ 🌸"""

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
                language TEXT DEFAULT 'ru'
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
        for col, definition in [
            ("city", "TEXT DEFAULT 'Москва'"),
            ("water_reminders", "BOOLEAN DEFAULT FALSE"),
            ("water_interval", "INTEGER DEFAULT 2"),
            ("morning_weather", "BOOLEAN DEFAULT FALSE"),
            ("morning_motivation", "BOOLEAN DEFAULT FALSE"),
            ("language", "TEXT DEFAULT 'ru'"),
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

async def get_history_db(user_id, limit=20):
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
                ORDER BY created_at DESC OFFSET 20
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
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
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
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={
                    "q": city,
                    "appid": WEATHER_API_KEY,
                    "units": "metric",
                    "lang": lang
                }
            )
        data = response.json()
        if data.get("cod") != 200:
            return f"Could not get weather for {city}." if lang == "en" else f"Не удалось получить погоду для {city}."
        temp = round(data["main"]["temp"])
        feels = round(data["main"]["feels_like"])
        desc = data["weather"][0]["description"]
        humidity = data["main"]["humidity"]
        wind = data["wind"]["speed"]
        if lang == "en":
            if temp < 0:
                advice = "🧥 Dress warmly, it's freezing outside!"
            elif temp < 10:
                advice = "🧣 Take a jacket and scarf."
            elif temp < 18:
                advice = "👕 A light jacket will do."
            else:
                advice = "☀️ Perfect weather for a walk!"
            if "rain" in desc:
                advice += " ☂️ Don't forget your umbrella!"
            return f"🌤️ Weather in {city}:\n\n🌡️ {temp}°C (feels like {feels}°C)\n☁️ {desc.capitalize()}\n💧 Humidity: {humidity}%\n💨 Wind: {wind} m/s\n\n{advice}"
        else:
            if temp < 0:
                advice = "🧥 Оденьтесь тепло, на улице мороз!"
            elif temp < 10:
                advice = "🧣 Возьмите куртку и шарф."
            elif temp < 18:
                advice = "👕 Лёгкая куртка будет в самый раз."
            else:
                advice = "☀️ Отличная погода для прогулки!"
            if "дождь" in desc or "ливень" in desc:
                advice += " ☂️ Не забудьте зонт!"
            return f"🌤️ Погода в {city}:\n\n🌡️ {temp}°C (ощущается как {feels}°C)\n☁️ {desc.capitalize()}\n💧 Влажность: {humidity}%\n💨 Ветер: {wind} м/с\n\n{advice}"
    except Exception as e:
        logging.error(f"Ошибка погоды: {e}")
        return "Weather unavailable." if lang == "en" else "Погода недоступна."

def calculate_sleep_times(wake_hour, wake_minute):
    total_minutes = wake_hour * 60 + wake_minute
    times = []
    for cycles in [6, 5, 4]:
        sleep_minutes = total_minutes - cycles * 90 - 15
        if sleep_minutes < 0:
            sleep_minutes += 24 * 60
        h = sleep_minutes // 60
        m = sleep_minutes % 60
        times.append(f"{h:02d}:{m:02d} ({cycles} cycles = {cycles * 1.5:.0f}h)" if False else f"{h:02d}:{m:02d} ({cycles} цикла = {cycles * 1.5:.0f}ч)")
    return times

async def get_ai_recipe(lang="ru"):
    try:
        prompt = "Suggest one simple recipe. Write the name, ingredients list and brief cooking method. Be concise." if lang == "en" else "Предложи один простой рецепт блюда. Напиши название, список ингредиентов и краткий способ приготовления. Пиши коротко."
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": "Recipe please" if lang == "en" else "Предложи рецепт"}],
            max_tokens=500, temperature=0.9
        )
        return response.choices[0].message.content
    except:
        return "Recipe unavailable." if lang == "en" else "Рецепт недоступен."

async def get_ai_movie(lang="ru"):
    try:
        prompt = "Recommend one movie or series for evening viewing. Write the title, genre, brief description and why to watch it." if lang == "en" else "Посоветуй один фильм или сериал для вечернего просмотра. Напиши название, жанр, краткое описание и почему стоит посмотреть."
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": "Recommend something" if lang == "en" else "Что посмотреть?"}],
            max_tokens=300, temperature=0.9
        )
        return response.choices[0].message.content
    except:
        return "Recommendation unavailable." if lang == "en" else "Рекомендация недоступна."

async def rephrase_reminder(text, lang="ru"):
    try:
        system = "Rephrase the reminder on behalf of the assistant — briefly, without 'me', without 'remind', without time. Just the essence. Reply with only the rephrased text." if lang == "en" else "Перефразируй напоминание от лица ассистента — коротко, без 'мне', без 'напомни', без времени. Только суть. Отвечай только перефразированным текстом."
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
            max_tokens=100, temperature=0.3
        )
        result = response.choices[0].message.content.strip()
        return result[0].upper() + result[1:] if result else text
    except:
        return text

async def transcribe_voice(file_path):
    transcriber = aai.Transcriber()
    config = aai.TranscriptionConfig(language_code="ru")
    transcript = transcriber.transcribe(file_path, config=config)
    if transcript.status == aai.TranscriptStatus.error:
        raise Exception(f"Transcription error: {transcript.error}")
    return transcript.text

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
        text += f"💫 *{'Motivation' if lang == 'en' else 'Мотивация'}:*\n{quote}\n\n"
    if user.get("morning_weather"):
        weather = await get_weather(city, lang)
        text += f"{weather}\n\n"
    if reminders:
        plan_text = "\n".join([f"🕐 {r['time']} — {r['text']}" for r in sorted(reminders, key=lambda x: x["time"])])
        text += f"📋 *{'Your plan for today' if lang == 'en' else 'Ваш план на сегодня'}:*\n\n{plan_text}"
    else:
        text += t(lang, "no_plan")
    await context.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")

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
        reply_markup=get_main_menu(lang),
        parse_mode="Markdown"
    )

async def skills_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    lang = user.get("language", "ru") if user else "ru"
    text = SKILLS_EN if lang == "en" else SKILLS_RU
    await update.message.reply_text(text, parse_mode="Markdown")

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
        if is_en:
            keyboard = [
                [InlineKeyboardButton("📋 Day plan", callback_data="morning_plan")],
                [InlineKeyboardButton("🌤️ Weather", callback_data="morning_weather_btn")],
                [InlineKeyboardButton("🧘 Motivation", callback_data="morning_motivation")],
                [InlineKeyboardButton("◀️ Back", callback_data="back_main")],
            ]
            await query.edit_message_text("🌅 *Morning menu*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            keyboard = [
                [InlineKeyboardButton("📋 План на день", callback_data="morning_plan")],
                [InlineKeyboardButton("🌤️ Погода", callback_data="morning_weather_btn")],
                [InlineKeyboardButton("🧘 Мотивация", callback_data="morning_motivation")],
                [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
            ]
            await query.edit_message_text("🌅 *Утреннее меню*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data == "morning_plan":
        reminders = await get_reminders(user_id)
        back_btn = InlineKeyboardButton("◀️ Back" if is_en else "◀️ Назад", callback_data="menu_morning")
        if reminders:
            plan_text = "\n".join([f"🕐 {r['time']} — {r['text']}" for r in sorted(reminders, key=lambda x: x["time"])])
            title = "📋 *Your plan for today:*" if is_en else "📋 *Ваш план на сегодня:*"
            text = f"{title}\n\n{plan_text}"
        else:
            text = "📋 No tasks for today." if is_en else "📋 На сегодня задачи не добавлены."
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]), parse_mode="Markdown")

    elif query.data == "morning_weather_btn":
        await query.edit_message_text(f"🌤️ {'Getting weather for' if is_en else 'Получаю погоду для'} {city}...")
        weather = await get_weather(city, lang)
        back_btn = InlineKeyboardButton("◀️ Back" if is_en else "◀️ Назад", callback_data="menu_morning")
        await query.edit_message_text(weather, reply_markup=InlineKeyboardMarkup([[back_btn]]))

    elif query.data == "morning_motivation":
        quote = random.choice(MOTIVATIONAL_QUOTES[lang])
        title = "🧘 *Motivation:*" if is_en else "🧘 *Мотивация дня:*"
        keyboard = [
            [InlineKeyboardButton("🔄 Another" if is_en else "🔄 Ещё цитата", callback_data="morning_motivation")],
            [InlineKeyboardButton("◀️ Back" if is_en else "◀️ Назад", callback_data="menu_morning")],
        ]
        await query.edit_message_text(f"{title}\n\n{quote}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data == "menu_habits":
        async with db_pool.acquire() as conn:
            habits = await conn.fetch("SELECT id, name FROM habits WHERE user_id = $1", user_id)
        if habits:
            lines = [f"✅ {h['name']}" for h in habits]
            title = "💪 *Your habits:*" if is_en else "💪 *Ваши привычки:*"
            text = f"{title}\n\n" + "\n".join(lines)
        else:
            text = "💪 *Habit tracker*\n\nNo habits yet." if is_en else "💪 *Трекер привычек*\n\nУ вас пока нет привычек."
        keyboard = [
            [InlineKeyboardButton("➕ Add habit" if is_en else "➕ Добавить привычку", callback_data="habit_add")],
            [InlineKeyboardButton("✅ Mark done" if is_en else "✅ Отметить выполнение", callback_data="habit_log")],
            [InlineKeyboardButton("📊 Statistics" if is_en else "📊 Статистика", callback_data="habit_stats")],
            [InlineKeyboardButton("◀️ Back" if is_en else "◀️ Назад", callback_data="back_main")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data == "habit_add":
        context.user_data["waiting_habit"] = True
        back_btn = InlineKeyboardButton("◀️ Cancel" if is_en else "◀️ Отмена", callback_data="menu_habits")
        text = "➕ Write the habit name\n\nFor example: Meditation, Reading, Exercise" if is_en else "➕ Напишите название привычки\n\nНапример: Медитация, Чтение, Зарядка"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]))

    elif query.data == "habit_log":
        async with db_pool.acquire() as conn:
            habits = await conn.fetch("SELECT id, name FROM habits WHERE user_id = $1", user_id)
        if not habits:
            back_btn = InlineKeyboardButton("◀️ Back" if is_en else "◀️ Назад", callback_data="menu_habits")
            text = "Add a habit first!" if is_en else "Сначала добавьте привычку!"
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]))
            return
        keyboard = [[InlineKeyboardButton(f"✅ {h['name']}", callback_data=f"log_habit_{h['id']}")] for h in habits]
        keyboard.append([InlineKeyboardButton("◀️ Back" if is_en else "◀️ Назад", callback_data="menu_habits")])
        text = "✅ Which habit to mark?" if is_en else "✅ Какую привычку отмечаем?"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("log_habit_"):
        habit_id = int(query.data.split("_")[-1])
        async with db_pool.acquire() as conn:
            habit = await conn.fetchrow("SELECT name FROM habits WHERE id = $1", habit_id)
            await conn.execute("INSERT INTO habit_logs (user_id, habit_id) VALUES ($1, $2)", user_id, habit_id)
        back_btn = InlineKeyboardButton("◀️ Back" if is_en else "◀️ К привычкам", callback_data="menu_habits")
        text = f"🎉 Habit *{habit['name']}* marked! Keep it up! 💪" if is_en else f"🎉 Привычка *{habit['name']}* отмечена! Так держать! 💪"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]), parse_mode="Markdown")

    elif query.data == "habit_stats":
        async with db_pool.acquire() as conn:
            habits = await conn.fetch("SELECT id, name FROM habits WHERE user_id = $1", user_id)
            lines = []
            for h in habits:
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM habit_logs WHERE habit_id = $1 AND logged_at >= NOW() - INTERVAL '7 days'", h["id"]
                )
                lines.append(f"📊 {h['name']}: {count}/7 {'days' if is_en else 'дней'}")
        title = "📊 *Stats for 7 days:*" if is_en else "📊 *Статистика за 7 дней:*"
        text = f"{title}\n\n" + "\n".join(lines) if lines else "No data." if is_en else "Нет данных."
        back_btn = InlineKeyboardButton("◀️ Back" if is_en else "◀️ Назад", callback_data="menu_habits")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]), parse_mode="Markdown")

    elif query.data == "menu_water":
        water_on = user.get("water_reminders", False)
        interval = user.get("water_interval", 2)
        if is_en:
            status = "✅ On" if water_on else "❌ Off"
            keyboard = [
                [InlineKeyboardButton("💧 Drank water!", callback_data="water_drink")],
                [InlineKeyboardButton("🔔 Turn off" if water_on else "🔔 Turn on reminders", callback_data="water_toggle")],
                [InlineKeyboardButton("◀️ Back", callback_data="back_main")],
            ]
            text = f"💧 *Water tracker*\n\nReminders: {status}\nEvery {interval} hours\nNorm: 8 glasses 🌊"
        else:
            status = "✅ Включены" if water_on else "❌ Выключены"
            keyboard = [
                [InlineKeyboardButton("💧 Выпила воду!", callback_data="water_drink")],
                [InlineKeyboardButton("🔔 Выключить" if water_on else "🔔 Включить напоминания", callback_data="water_toggle")],
                [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
            ]
            text = f"💧 *Трекер воды*\n\nНапоминания: {status}\nКаждые {interval} часа\nНорма: 8 стаканов 🌊"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data == "water_drink":
        back_btn = InlineKeyboardButton("◀️ Back" if is_en else "◀️ Назад", callback_data="menu_water")
        text = "💧 Great! Glass of water counted! 🌊" if is_en else "💧 Отлично! Стакан воды засчитан! 🌊"
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
            text = f"✅ Water reminders on! Every {interval} hours 💧" if is_en else f"✅ Напоминания включены! Каждые {interval} часа 💧"
        else:
            for job in context.application.job_queue.get_jobs_by_name(f"water_{user_id}"):
                job.schedule_removal()
            text = "❌ Water reminders off." if is_en else "❌ Напоминания выключены."
        back_btn = InlineKeyboardButton("◀️ Back" if is_en else "◀️ Назад", callback_data="menu_water")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]))

    elif query.data == "menu_diary":
        if is_en:
            keyboard = [
                [InlineKeyboardButton("💰 Finances", callback_data="diary_finances"),
                 InlineKeyboardButton("😴 Sleep", callback_data="diary_sleep")],
                [InlineKeyboardButton("📝 Notes", callback_data="diary_notes"),
                 InlineKeyboardButton("🍳 Recipes", callback_data="diary_recipe")],
                [InlineKeyboardButton("🎬 What to watch", callback_data="diary_movie")],
                [InlineKeyboardButton("◀️ Back", callback_data="back_main")],
            ]
            await query.edit_message_text("📒 *Diary*\n\nChoose a section:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            keyboard = [
                [InlineKeyboardButton("💰 Финансы", callback_data="diary_finances"),
                 InlineKeyboardButton("😴 Сон", callback_data="diary_sleep")],
                [InlineKeyboardButton("📝 Заметки", callback_data="diary_notes"),
                 InlineKeyboardButton("🍳 Рецепты", callback_data="diary_recipe")],
                [InlineKeyboardButton("🎬 Что посмотреть", callback_data="diary_movie")],
                [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
            ]
            await query.edit_message_text("📒 *Дневник*\n\nВыберите раздел:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data == "diary_finances":
        async with db_pool.acquire() as conn:
            income = await conn.fetchval(
                "SELECT SUM(amount) FROM finances WHERE user_id = $1 AND type = 'income' AND created_at >= NOW() - INTERVAL '30 days'", user_id
            )
            expense = await conn.fetchval(
                "SELECT SUM(amount) FROM finances WHERE user_id = $1 AND type = 'expense' AND created_at >= NOW() - INTERVAL '30 days'", user_id
            )
            recent = await conn.fetch(
                "SELECT amount, type, category, description FROM finances WHERE user_id = $1 ORDER BY created_at DESC LIMIT 5", user_id
            )
        income_text = f"{income:.0f}" if income else "0"
        expense_text = f"{expense:.0f}" if expense else "0"
        balance = (income or 0) - (expense or 0)
        if is_en:
            lines = [f"{'➕' if r['type'] == 'income' else '➖'} {r['amount']:.0f} — {r['category']} {r['description']}" for r in recent]
            text = f"💰 *Finances this month:*\n\n➕ Income: {income_text}\n➖ Expenses: {expense_text}\n💵 Balance: {balance:.0f}\n\n"
            text += "\n".join(lines) if lines else "No records yet."
            text += "\n\n*Add income:* +1000 salary\n*Add expense:* -500 food coffee"
        else:
            lines = [f"{'➕' if r['type'] == 'income' else '➖'} {r['amount']:.0f} — {r['category']} {r['description']}" for r in recent]
            text = f"💰 *Финансы за месяц:*\n\n➕ Доходы: {income_text}\n➖ Расходы: {expense_text}\n💵 Баланс: {balance:.0f}\n\n"
            text += "\n".join(lines) if lines else "Записей пока нет."
            text += "\n\n*Добавить доход:* +1000 зарплата\n*Добавить расход:* -500 еда кофе"
        context.user_data["waiting_finance"] = True
        back_btn = InlineKeyboardButton("◀️ Back" if is_en else "◀️ Назад", callback_data="menu_diary")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]), parse_mode="Markdown")

    elif query.data == "diary_sleep":
        if is_en:
            keyboard = [
                [InlineKeyboardButton("6:00", callback_data="sleep_6_0"),
                 InlineKeyboardButton("7:00", callback_data="sleep_7_0"),
                 InlineKeyboardButton("8:00", callback_data="sleep_8_0")],
                [InlineKeyboardButton("9:00", callback_data="sleep_9_0"),
                 InlineKeyboardButton("10:00", callback_data="sleep_10_0")],
                [InlineKeyboardButton("◀️ Back", callback_data="menu_diary")],
            ]
            await query.edit_message_text("😴 *Sleep tracker*\n\nWhat time do you want to wake up?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            keyboard = [
                [InlineKeyboardButton("6:00", callback_data="sleep_6_0"),
                 InlineKeyboardButton("7:00", callback_data="sleep_7_0"),
                 InlineKeyboardButton("8:00", callback_data="sleep_8_0")],
                [InlineKeyboardButton("9:00", callback_data="sleep_9_0"),
                 InlineKeyboardButton("10:00", callback_data="sleep_10_0")],
                [InlineKeyboardButton("◀️ Назад", callback_data="menu_diary")],
            ]
            await query.edit_message_text("😴 *Трекер сна*\n\nВо сколько хотите проснуться?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data.startswith("sleep_"):
        parts = query.data.split("_")
        wake_hour = int(parts[1])
        wake_minute = int(parts[2])
        times = calculate_sleep_times(wake_hour, wake_minute)
        if is_en:
            text = f"😴 *To wake up at {wake_hour:02d}:{wake_minute:02d} refreshed:*\n\nGo to bed at:\n"
            for t_item in times:
                text += f"🌙 {t_item}\n"
            text += "\n_+15 minutes to fall asleep already included_"
        else:
            text = f"😴 *Чтобы проснуться в {wake_hour:02d}:{wake_minute:02d} бодрой:*\n\nЛожитесь спать в:\n"
            for t_item in times:
                text += f"🌙 {t_item}\n"
            text += "\n_+15 минут на засыпание уже учтены_"
        back_btn = InlineKeyboardButton("◀️ Back" if is_en else "◀️ Назад", callback_data="diary_sleep")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]), parse_mode="Markdown")

    elif query.data == "diary_notes":
        async with db_pool.acquire() as conn:
            notes = await conn.fetch(
                "SELECT text FROM notes WHERE user_id = $1 ORDER BY created_at DESC LIMIT 5", user_id
            )
        if is_en:
            if notes:
                lines = [f"📝 {n['text'][:50]}{'...' if len(n['text']) > 50 else ''}" for n in notes]
                text = "📝 *Your notes:*\n\n" + "\n".join(lines)
            else:
                text = "📝 *Notes*\n\nNo notes yet."
            text += "\n\nWrite anything and I'll save it!"
        else:
            if notes:
                lines = [f"📝 {n['text'][:50]}{'...' if len(n['text']) > 50 else ''}" for n in notes]
                text = "📝 *Ваши заметки:*\n\n" + "\n".join(lines)
            else:
                text = "📝 *Заметки*\n\nЗаметок пока нет."
            text += "\n\nНапишите что угодно и я сохраню!"
        context.user_data["waiting_note"] = True
        back_btn = InlineKeyboardButton("◀️ Back" if is_en else "◀️ Назад", callback_data="menu_diary")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]), parse_mode="Markdown")

    elif query.data == "diary_recipe":
        loading = "🍳 Finding a recipe..." if is_en else "🍳 Подбираю рецепт..."
        await query.edit_message_text(loading)
        recipe = await get_ai_recipe(lang)
        title = "🍳 *Recipe of the day:*" if is_en else "🍳 *Рецепт дня:*"
        keyboard = [
            [InlineKeyboardButton("🔄 Another recipe" if is_en else "🔄 Другой рецепт", callback_data="diary_recipe")],
            [InlineKeyboardButton("◀️ Back" if is_en else "◀️ Назад", callback_data="menu_diary")],
        ]
        await query.edit_message_text(f"{title}\n\n{recipe}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data == "diary_movie":
        loading = "🎬 Finding a movie..." if is_en else "🎬 Подбираю фильм..."
        await query.edit_message_text(loading)
        movie = await get_ai_movie(lang)
        title = "🎬 *Recommendation:*" if is_en else "🎬 *Рекомендация:*"
        keyboard = [
            [InlineKeyboardButton("🔄 Another movie" if is_en else "🔄 Другой фильм", callback_data="diary_movie")],
            [InlineKeyboardButton("◀️ Back" if is_en else "◀️ Назад", callback_data="menu_diary")],
        ]
        await query.edit_message_text(f"{title}\n\n{movie}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

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
        if is_en:
            text = (
                f"👤 *My profile*\n\n"
                f"👋 Name: {name}\n"
                f"🌍 City: {city}\n"
                f"🕐 Timezone: {tz}\n"
                f"🌐 Language: English 🇬🇧\n"
                f"📅 Days with us: {days}\n"
                f"💬 Messages: {total_messages}\n"
                f"💪 Habits: {habits_count}\n"
                f"💰 Balance this month: {balance:.0f}"
            )
            keyboard = [
                [InlineKeyboardButton("🌍 Change city", callback_data="profile_city")],
                [InlineKeyboardButton("🌐 Switch to Russian 🇷🇺", callback_data="switch_lang_ru")],
                [InlineKeyboardButton("◀️ Back", callback_data="back_main")],
            ]
        else:
            text = (
                f"👤 *Мой профиль*\n\n"
                f"👋 Имя: {name}\n"
                f"🌍 Город: {city}\n"
                f"🕐 Часовой пояс: {tz}\n"
                f"🌐 Язык: Русский 🇷🇺\n"
                f"📅 Дней с нами: {days}\n"
                f"💬 Сообщений: {total_messages}\n"
                f"💪 Привычек: {habits_count}\n"
                f"💰 Баланс за месяц: {balance:.0f}"
            )
            keyboard = [
                [InlineKeyboardButton("🌍 Изменить город", callback_data="profile_city")],
                [InlineKeyboardButton("🌐 Switch to English 🇬🇧", callback_data="switch_lang_en")],
                [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
            ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data == "switch_lang_en":
        await save_user(user_id, language="en")
        await query.edit_message_text(
            "🌐 Language switched to English 🇬🇧\n\nType /menu to continue!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="back_main")]])
        )

    elif query.data == "switch_lang_ru":
        await save_user(user_id, language="ru")
        await query.edit_message_text(
            "🌐 Язык изменён на русский 🇷🇺\n\nНапишите /menu чтобы продолжить!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="back_main")]])
        )

    elif query.data == "profile_city":
        context.user_data["waiting_city"] = True
        back_btn = InlineKeyboardButton("◀️ Back" if is_en else "◀️ Отмена", callback_data="menu_profile")
        text = "🌍 Write your city name" if is_en else "🌍 Напишите название вашего города"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]))

    elif query.data == "menu_settings":
        morning_weather = "✅" if user.get("morning_weather") else "❌"
        morning_motivation = "✅" if user.get("morning_motivation") else "❌"
        water = "✅" if user.get("water_reminders") else "❌"
        if is_en:
            keyboard = [
                [InlineKeyboardButton(f"{morning_weather} Weather in morning", callback_data="toggle_morning_weather")],
                [InlineKeyboardButton(f"{morning_motivation} Motivation in morning", callback_data="toggle_morning_motivation")],
                [InlineKeyboardButton(f"{water} Water reminders", callback_data="water_toggle")],
                [InlineKeyboardButton("◀️ Back", callback_data="back_main")],
            ]
            await query.edit_message_text("⚙️ *Settings*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            keyboard = [
                [InlineKeyboardButton(f"{morning_weather} Погода утром", callback_data="toggle_morning_weather")],
                [InlineKeyboardButton(f"{morning_motivation} Мотивация утром", callback_data="toggle_morning_motivation")],
                [InlineKeyboardButton(f"{water} Напоминания о воде", callback_data="water_toggle")],
                [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
            ]
            await query.edit_message_text("⚙️ *Настройки*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data == "toggle_morning_weather":
        new = not user.get("morning_weather", False)
        await save_user(user_id, morning_weather=new)
        status = ("on ✅" if new else "off ❌") if is_en else ("включена ✅" if new else "выключена ❌")
        text = f"🌤️ Morning weather {status}" if is_en else f"🌤️ Погода утром {status}"
        back_btn = InlineKeyboardButton("◀️ Back" if is_en else "◀️ Назад", callback_data="menu_settings")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]))

    elif query.data == "toggle_morning_motivation":
        new = not user.get("morning_motivation", False)
        await save_user(user_id, morning_motivation=new)
        status = ("on ✅" if new else "off ❌") if is_en else ("включена ✅" if new else "выключена ❌")
        text = f"🧘 Morning motivation {status}" if is_en else f"🧘 Мотивация утром {status}"
        back_btn = InlineKeyboardButton("◀️ Back" if is_en else "◀️ Назад", callback_data="menu_settings")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[back_btn]]))

    elif query.data == "back_main":
        await query.edit_message_text(
            t(lang, "menu_title", name=name),
            reply_markup=get_main_menu(lang),
            parse_mode="Markdown"
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
    await update.message.reply_text(f"✅ Отправлено: {sent}\n❌ Не доставлено: {failed}")

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
    await update.message.reply_text(t("ru", "ask_city", name=name), reply_markup=ReplyKeyboardRemove())
    return ASK_CITY

async def ask_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    city = update.message.text.strip()
    timezone = await get_timezone_by_city(city)
    await save_user(user_id, city=city, timezone=timezone)
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
    keyboard = [
        ["✅ Да, каждое утро" if lang == "ru" else "✅ Yes, every morning",
         "❌ Нет, не нужно" if lang == "ru" else "❌ No, thanks"]
    ]
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
    await save_user(user_id, reminder_before=reminder_before, onboarded=True)
    user = await get_user(user_id)
    name = user["name"] if user else ""
    morning_time = user["morning_time"] if user else "08:00"
    has_plan = user["morning_plan"] if user else False
    summary = t(lang, "finish", name=name)
    await update.message.reply_text(summary, reply_markup=ReplyKeyboardRemove())
    username = update.effective_user.username or "нет username"
    await notify_admin(context, name, username, "Завершил онбординг", summary)
    if has_plan and morning_time:
        tz = pytz.timezone(user["timezone"] if user else "Europe/Moscow")
        context.application.job_queue.run_daily(
            send_morning_plan,
            time=time(hour=int(morning_time.split(":")[0]), minute=0, tzinfo=tz),
            data=user_id,
            name=f"morning_{user_id}"
        )
    return ConversationHandler.END

async def process_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    if not user or not user["onboarded"]:
        await update.message.reply_text(t("ru", "not_started"))
        return
    user_name = update.effective_user.first_name or "Пользователь"
    username = update.effective_user.username or "нет username"
    name = user["name"]
    lang = user.get("language", "ru")
    is_en = lang == "en"

    if context.user_data.get("waiting_habit"):
        context.user_data["waiting_habit"] = False
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO habits (user_id, name) VALUES ($1, $2)", user_id, user_text)
        text = f"✅ Habit *{user_text}* added!" if is_en else f"✅ Привычка *{user_text}* добавлена!"
        await update.message.reply_text(text, parse_mode="Markdown")
        return

    if context.user_data.get("waiting_city"):
        context.user_data["waiting_city"] = False
        timezone = await get_timezone_by_city(user_text)
        await save_user(user_id, city=user_text, timezone=timezone)
        text = f"🌍 City changed to *{user_text}*!" if is_en else f"🌍 Город изменён на *{user_text}*!"
        await update.message.reply_text(text, parse_mode="Markdown")
        return

    if context.user_data.get("waiting_note"):
        context.user_data["waiting_note"] = False
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO notes (user_id, text) VALUES ($1, $2)", user_id, user_text)
        text = "📝 Note saved!" if is_en else "📝 Заметка сохранена!"
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
            if is_en:
                text = f"{'➕ Income' if is_income else '➖ Expense'} *{amount:.0f}* ({category}) saved!"
            else:
                text = f"{'➕ Доход' if is_income else '➖ Расход'} *{amount:.0f}* ({category}) сохранён!"
            await update.message.reply_text(text, parse_mode="Markdown")
        except:
            text = "Format: +1000 salary or -500 food coffee" if is_en else "Формат: +1000 зарплата или -500 еда кофе"
            await update.message.reply_text(text)
        return

    await add_history(user_id, "user", user_text)
    history = await get_history_db(user_id)
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
                        if is_en:
                            msg = f"⚠️ {name}, at {time_str} you already have:\n\n«{conflict}»\n\nChoose another time?"
                        else:
                            msg = f"⚠️ {name}, в {time_str} уже запланировано:\n\n«{conflict}»\n\nВыбрать другое время?"
                        await update.message.reply_text(msg)
                        return
                    job_name = f"reminder_{user_id}_{hour}_{minute}"
                    for job in context.application.job_queue.get_jobs_by_name(job_name):
                        job.schedule_removal()
                    context.application.job_queue.run_daily(
                        send_scheduled_reminder,
                        time=time(hour=hour, minute=minute, tzinfo=tz),
                        data={"user_id": user_id, "essence": essence}, name=job_name
                    )
                    await add_reminder(user_id, time_str, essence)

        system_prompt = SYSTEM_PROMPT_EN if is_en else SYSTEM_PROMPT_RU
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": system_prompt}, *history],
            max_tokens=1000, temperature=0.7
        )
        reply = response.choices[0].message.content
        await add_history(user_id, "assistant", reply)
        await update.message.reply_text(reply)
        await notify_admin(context, user_name, username, user_text, reply)
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await update.message.reply_text(t(lang, "error"))

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    if not user or not user["onboarded"]:
        await update.message.reply_text(t("ru", "not_started"))
        return
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
            lang = user.get("language", "ru")
            text = "Could not recognize voice message. Please try again." if lang == "en" else "Не смогла распознать голосовое. Попробуйте ещё раз."
            await update.message.reply_text(text)
            return
        await process_text_message(update, context, user_text)
    except Exception as e:
        logging.error(f"Ошибка голосового: {e}")
        lang = user.get("language", "ru") if user else "ru"
        text = "Could not process voice message. Try typing instead." if lang == "en" else "Не удалось обработать голосовое. Попробуйте написать текстом."
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
        "📊 *Статистика Софии*\n\n"
        f"👥 Всего: *{total}*\n"
        f"🇷🇺 Русский: *{ru_users}*\n"
        f"🇬🇧 English: *{en_users}*\n"
        f"🟢 Сегодня: *{today}*\n"
        f"📅 За 7 дней: *{week}*\n"
        f"💬 Сообщений: *{total_messages}*"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

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
        },
        fallbacks=[CommandHandler("start", start)]
    )
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("menu", show_menu))
    app.add_handler(CommandHandler("skills", skills_command))
    app.add_handler(CommandHandler("announce", announce))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🌸 София запущена с двумя языками!")
    app.run_polling()
