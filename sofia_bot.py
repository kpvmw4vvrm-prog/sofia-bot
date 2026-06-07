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

ASK_NAME, ASK_CITY, ASK_MORNING_PLAN, ASK_MORNING_TIME, ASK_REMINDERS = range(5)

MOTIVATIONAL_QUOTES = [
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
]

SYSTEM_PROMPT = """Ты — София, личный ассистент, стратег и умный помощник. Общаешься вежливо и профессионально, обращаешься на "Вы". Деловой стиль, но живой. Умеренно используй эмодзи.

Что ты умеешь:
1. Планирование — составляешь план на день, завтра, неделю, месяц по запросу.
2. История — помнишь всё что пользователь делал и говорил.
3. Стратегия целей — ведёшь по шагам к достижению цели.
4. Напоминания — присылаешь точно в срок.
5. Умный помощник — отвечаешь на любые вопросы.

Правила оформления:
— Списки нумеруй: 1. 2. 3.
— Планы пиши по времени в столбик
— Пиши коротко и по существу
— Один вопрос за раз

Формат плана дня:
🕘 09:00 — задача
🕙 10:00 — задача
"""

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
                morning_motivation BOOLEAN DEFAULT FALSE
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
            CREATE TABLE IF NOT EXISTS expenses (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                amount FLOAT,
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

async def get_weather(city):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={
                    "q": city,
                    "appid": WEATHER_API_KEY,
                    "units": "metric",
                    "lang": "ru"
                }
            )
        data = response.json()
        if data.get("cod") != 200:
            return f"Не удалось получить погоду для города {city}."
        temp = round(data["main"]["temp"])
        feels = round(data["main"]["feels_like"])
        desc = data["weather"][0]["description"]
        humidity = data["main"]["humidity"]
        wind = data["wind"]["speed"]
        advice = ""
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
        return (
            f"🌤️ Погода в {city}:\n\n"
            f"🌡️ {temp}°C (ощущается как {feels}°C)\n"
            f"☁️ {desc.capitalize()}\n"
            f"💧 Влажность: {humidity}%\n"
            f"💨 Ветер: {wind} м/с\n\n"
            f"{advice}"
        )
    except Exception as e:
        logging.error(f"Ошибка погоды: {e}")
        return "Не удалось получить данные о погоде."

def calculate_sleep_times(wake_hour, wake_minute):
    total_minutes = wake_hour * 60 + wake_minute
    times = []
    for cycles in [6, 5, 4]:
        sleep_minutes = total_minutes - cycles * 90 - 15
        if sleep_minutes < 0:
            sleep_minutes += 24 * 60
        h = sleep_minutes // 60
        m = sleep_minutes % 60
        times.append(f"{h:02d}:{m:02d} ({cycles} цикла = {cycles * 1.5:.0f}ч сна)")
    return times

async def get_ai_recipe():
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "Ты кулинарный помощник. Предложи один простой рецепт блюда. Напиши название, список ингредиентов и краткий способ приготовления. Пиши по-русски, коротко и понятно."
                },
                {"role": "user", "content": "Предложи мне рецепт на сегодня"}
            ],
            max_tokens=500,
            temperature=0.9
        )
        return response.choices[0].message.content
    except:
        return "Не удалось получить рецепт. Попробуйте позже."

async def get_ai_movie():
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "Ты кинокритик. Посоветуй один фильм или сериал для вечернего просмотра. Напиши название, жанр, краткое описание и почему стоит посмотреть. Пиши по-русски."
                },
                {"role": "user", "content": "Что посмотреть сегодня вечером?"}
            ],
            max_tokens=300,
            temperature=0.9
        )
        return response.choices[0].message.content
    except:
        return "Не удалось получить рекомендацию. Попробуйте позже."

async def rephrase_reminder(text):
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "Перефразируй напоминание от лица ассистента — коротко, без 'мне', без 'напомни', без времени, без 'через X минут'. Только суть. Отвечай только перефразированным текстом."
                },
                {"role": "user", "content": text}
            ],
            max_tokens=100,
            temperature=0.3
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
        raise Exception(f"Ошибка транскрипции: {transcript.error}")
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
    match = re.search(r'через\s+(\d+)\s*(минут|мин|минуты|минуту)', text, re.IGNORECASE)
    if match:
        return int(match.group(1)), 'minutes'
    match = re.search(r'через\s+(\d+)\s*(час|часа|часов)', text, re.IGNORECASE)
    if match:
        return int(match.group(1)), 'hours'
    return None, None

def is_reminder_request(text):
    keywords = ["напомни", "напоминание", "пришли", "отправь", "напиши"]
    has_time = re.search(r'\d{1,2}[:.]\d{2}', text) or re.search(r'через\s+\d+', text, re.IGNORECASE)
    return has_time and any(k in text.lower() for k in keywords)

async def send_scheduled_reminder(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    user_id = job_data["user_id"]
    essence = job_data["essence"]
    user = await get_user(user_id)
    name = user["name"] if user else ""
    await context.bot.send_message(
        chat_id=user_id,
        text=f"⏰ {name}, напоминаю!\n\n{essence}"
    )

async def send_water_reminder(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    user = await get_user(user_id)
    name = user["name"] if user else ""
    await context.bot.send_message(
        chat_id=user_id,
        text=f"💧 {name}, не забудьте выпить стакан воды! 🌊"
    )

async def send_morning_plan(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    user = await get_user(user_id)
    if not user:
        return
    name = user["name"]
    city = user.get("city") or "Москва"
    reminders = await get_reminders(user_id)
    text = f"☀️ Доброе утро, {name}!\n\n"
    if user.get("morning_motivation"):
        quote = random.choice(MOTIVATIONAL_QUOTES)
        text += f"💫 *Мотивация дня:*\n{quote}\n\n"
    if user.get("morning_weather"):
        weather = await get_weather(city)
        text += f"{weather}\n\n"
    if reminders:
        plan_text = "\n".join([f"🕐 {r['time']} — {r['text']}" for r in sorted(reminders, key=lambda x: x["time"])])
        text += f"📋 *Ваш план на сегодня:*\n\n{plan_text}"
    else:
        text += "📋 На сегодня задачи не добавлены."
    await context.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")

def get_main_menu():
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
        await update.message.reply_text("Напишите /start чтобы начать 🌸")
        return
    name = user["name"]
    await update.message.reply_text(
        f"🌸 *Меню Софии*\n\nЗдравствуйте, {name}! Чем могу помочь?",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = await get_user(user_id)
    if not user:
        return
    name = user["name"]
    city = user.get("city") or "Москва"

    if query.data == "menu_morning":
        keyboard = [
            [InlineKeyboardButton("📋 План на день", callback_data="morning_plan")],
            [InlineKeyboardButton("🌤️ Погода", callback_data="morning_weather_btn")],
            [InlineKeyboardButton("🧘 Мотивация", callback_data="morning_motivation")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
        ]
        await query.edit_message_text(
            "🌅 *Утреннее меню*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif query.data == "morning_plan":
        reminders = await get_reminders(user_id)
        if reminders:
            plan_text = "\n".join([f"🕐 {r['time']} — {r['text']}" for r in sorted(reminders, key=lambda x: x["time"])])
            text = f"📋 *Ваш план на сегодня:*\n\n{plan_text}"
        else:
            text = "📋 На сегодня задачи не добавлены.\n\nНапишите мне чтобы добавить напоминание!"
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="menu_morning")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data == "morning_weather_btn":
        await query.edit_message_text(f"🌤️ Получаю погоду для {city}...")
        weather = await get_weather(city)
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="menu_morning")]]
        await query.edit_message_text(weather, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "morning_motivation":
        quote = random.choice(MOTIVATIONAL_QUOTES)
        keyboard = [
            [InlineKeyboardButton("🔄 Ещё цитата", callback_data="morning_motivation")],
            [InlineKeyboardButton("◀️ Назад", callback_data="menu_morning")],
        ]
        await query.edit_message_text(
            f"🧘 *Мотивация дня:*\n\n{quote}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif query.data == "menu_habits":
        async with db_pool.acquire() as conn:
            habits = await conn.fetch("SELECT id, name FROM habits WHERE user_id = $1", user_id)
        if habits:
            lines = [f"✅ {h['name']}" for h in habits]
            text = "💪 *Ваши привычки:*\n\n" + "\n".join(lines)
        else:
            text = "💪 *Трекер привычек*\n\nУ вас пока нет привычек."
        keyboard = [
            [InlineKeyboardButton("➕ Добавить привычку", callback_data="habit_add")],
            [InlineKeyboardButton("✅ Отметить выполнение", callback_data="habit_log")],
            [InlineKeyboardButton("📊 Статистика", callback_data="habit_stats")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data == "habit_add":
        context.user_data["waiting_habit"] = True
        keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data="menu_habits")]]
        await query.edit_message_text(
            "➕ Напишите название привычки\n\nНапример: Медитация, Чтение, Зарядка",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "habit_log":
        async with db_pool.acquire() as conn:
            habits = await conn.fetch("SELECT id, name FROM habits WHERE user_id = $1", user_id)
        if not habits:
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="menu_habits")]]
            await query.edit_message_text("Сначала добавьте привычку!", reply_markup=InlineKeyboardMarkup(keyboard))
            return
        keyboard = [[InlineKeyboardButton(f"✅ {h['name']}", callback_data=f"log_habit_{h['id']}")] for h in habits]
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="menu_habits")])
        await query.edit_message_text("✅ Какую привычку отмечаем?", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("log_habit_"):
        habit_id = int(query.data.split("_")[-1])
        async with db_pool.acquire() as conn:
            habit = await conn.fetchrow("SELECT name FROM habits WHERE id = $1", habit_id)
            await conn.execute("INSERT INTO habit_logs (user_id, habit_id) VALUES ($1, $2)", user_id, habit_id)
        keyboard = [[InlineKeyboardButton("◀️ К привычкам", callback_data="menu_habits")]]
        await query.edit_message_text(
            f"🎉 Привычка *{habit['name']}* отмечена! Так держать! 💪",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif query.data == "habit_stats":
        async with db_pool.acquire() as conn:
            habits = await conn.fetch("SELECT id, name FROM habits WHERE user_id = $1", user_id)
            lines = []
            for h in habits:
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM habit_logs WHERE habit_id = $1 AND logged_at >= NOW() - INTERVAL '7 days'",
                    h["id"]
                )
                lines.append(f"📊 {h['name']}: {count}/7 дней")
        text = "📊 *Статистика за 7 дней:*\n\n" + "\n".join(lines) if lines else "Нет данных."
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="menu_habits")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data == "menu_water":
        water_on = user.get("water_reminders", False)
        status = "✅ Включены" if water_on else "❌ Выключены"
        interval = user.get("water_interval", 2)
        keyboard = [
            [InlineKeyboardButton("💧 Выпил воду!", callback_data="water_drink")],
            [InlineKeyboardButton("🔔 Выключить" if water_on else "🔔 Включить напоминания", callback_data="water_toggle")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
        ]
        await query.edit_message_text(
            f"💧 *Трекер воды*\n\nНапоминания: {status}\nКаждые {interval} часа\nНорма: 8 стаканов 🌊",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif query.data == "water_drink":
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="menu_water")]]
        await query.edit_message_text("💧 Отлично! Стакан воды засчитан! 🌊", reply_markup=InlineKeyboardMarkup(keyboard))

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
            text = f"✅ Напоминания включены! Каждые {interval} часа 💧"
        else:
            for job in context.application.job_queue.get_jobs_by_name(f"water_{user_id}"):
                job.schedule_removal()
            text = "❌ Напоминания выключены."
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="menu_water")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "menu_diary":
        keyboard = [
            [InlineKeyboardButton("💰 Расходы", callback_data="diary_expenses"),
             InlineKeyboardButton("😴 Сон", callback_data="diary_sleep")],
            [InlineKeyboardButton("📝 Заметки", callback_data="diary_notes"),
             InlineKeyboardButton("🍳 Рецепты", callback_data="diary_recipe")],
            [InlineKeyboardButton("🎬 Что посмотреть", callback_data="diary_movie")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
        ]
        await query.edit_message_text(
            "📒 *Дневник*\n\nВыберите раздел:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif query.data == "diary_expenses":
        async with db_pool.acquire() as conn:
            total = await conn.fetchval(
                "SELECT SUM(amount) FROM expenses WHERE user_id = $1 AND created_at >= NOW() - INTERVAL '30 days'",
                user_id
            )
            recent = await conn.fetch(
                "SELECT amount, category, description FROM expenses WHERE user_id = $1 ORDER BY created_at DESC LIMIT 5",
                user_id
            )
        total_text = f"{total:.0f} руб" if total else "0 руб"
        lines = [f"• {r['category']}: {r['amount']:.0f} руб — {r['description']}" for r in recent]
        text = f"💰 *Расходы за месяц: {total_text}*\n\n"
        text += "\n".join(lines) if lines else "Расходов пока нет."
        text += "\n\nНапишите расход в формате:\n*500 еда кофе* или *1200 транспорт такси*"
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="menu_diary")]]
        context.user_data["waiting_expense"] = True
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data == "diary_sleep":
        keyboard = [
            [InlineKeyboardButton("6:00", callback_data="sleep_6_0"),
             InlineKeyboardButton("7:00", callback_data="sleep_7_0"),
             InlineKeyboardButton("8:00", callback_data="sleep_8_0")],
            [InlineKeyboardButton("9:00", callback_data="sleep_9_0"),
             InlineKeyboardButton("10:00", callback_data="sleep_10_0")],
            [InlineKeyboardButton("◀️ Назад", callback_data="menu_diary")],
        ]
        await query.edit_message_text(
            "😴 *Трекер сна*\n\nВо сколько хотите проснуться?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif query.data.startswith("sleep_"):
        parts = query.data.split("_")
        wake_hour = int(parts[1])
        wake_minute = int(parts[2])
        times = calculate_sleep_times(wake_hour, wake_minute)
        text = f"😴 *Чтобы проснуться в {wake_hour:02d}:{wake_minute:02d} бодрым:*\n\n"
        text += "Ложитесь спать в:\n"
        for t in times:
            text += f"🌙 {t}\n"
        text += "\n_+15 минут на засыпание уже учтены_"
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="diary_sleep")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data == "diary_notes":
        async with db_pool.acquire() as conn:
            notes = await conn.fetch(
                "SELECT id, text, created_at FROM notes WHERE user_id = $1 ORDER BY created_at DESC LIMIT 5",
                user_id
            )
        if notes:
            lines = [f"📝 {n['text'][:50]}{'...' if len(n['text']) > 50 else ''}" for n in notes]
            text = "📝 *Ваши заметки:*\n\n" + "\n".join(lines)
        else:
            text = "📝 *Заметки*\n\nУ вас пока нет заметок."
        text += "\n\nНапишите заметку и я её сохраню!"
        context.user_data["waiting_note"] = True
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="menu_diary")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data == "diary_recipe":
        await query.edit_message_text("🍳 Подбираю рецепт...")
        recipe = await get_ai_recipe()
        keyboard = [
            [InlineKeyboardButton("🔄 Другой рецепт", callback_data="diary_recipe")],
            [InlineKeyboardButton("◀️ Назад", callback_data="menu_diary")],
        ]
        await query.edit_message_text(
            f"🍳 *Рецепт дня:*\n\n{recipe}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif query.data == "diary_movie":
        await query.edit_message_text("🎬 Подбираю фильм...")
        movie = await get_ai_movie()
        keyboard = [
            [InlineKeyboardButton("🔄 Другой фильм", callback_data="diary_movie")],
            [InlineKeyboardButton("◀️ Назад", callback_data="menu_diary")],
        ]
        await query.edit_message_text(
            f"🎬 *Рекомендация:*\n\n{movie}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif query.data == "menu_profile":
        async with db_pool.acquire() as conn:
            total_messages = await conn.fetchval(
                "SELECT COUNT(*) FROM history WHERE user_id = $1 AND role = 'user'", user_id
            )
            habits_count = await conn.fetchval("SELECT COUNT(*) FROM habits WHERE user_id = $1", user_id)
            expenses_total = await conn.fetchval(
                "SELECT SUM(amount) FROM expenses WHERE user_id = $1 AND created_at >= NOW() - INTERVAL '30 days'",
                user_id
            )
        created = user.get("created_at")
        days = (datetime.now() - created).days if created else 0
        tz = user.get("timezone") or "Europe/Moscow"
        expenses_text = f"{expenses_total:.0f} руб" if expenses_total else "0 руб"
        text = (
            f"👤 *Мой профиль*\n\n"
            f"👋 Имя: {name}\n"
            f"🌍 Город: {city}\n"
            f"🕐 Часовой пояс: {tz}\n"
            f"📅 Дней с нами: {days}\n"
            f"💬 Сообщений: {total_messages}\n"
            f"💪 Привычек: {habits_count}\n"
            f"💰 Расходы за месяц: {expenses_text}"
        )
        keyboard = [
            [InlineKeyboardButton("🌍 Изменить город", callback_data="profile_city")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data == "profile_city":
        context.user_data["waiting_city"] = True
        keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data="menu_profile")]]
        await query.edit_message_text(
            "🌍 Напишите название вашего города",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "menu_settings":
        morning_weather = "✅" if user.get("morning_weather") else "❌"
        morning_motivation = "✅" if user.get("morning_motivation") else "❌"
        water = "✅" if user.get("water_reminders") else "❌"
        keyboard = [
            [InlineKeyboardButton(f"{morning_weather} Погода утром", callback_data="toggle_morning_weather")],
            [InlineKeyboardButton(f"{morning_motivation} Мотивация утром", callback_data="toggle_morning_motivation")],
            [InlineKeyboardButton(f"{water} Напоминания о воде", callback_data="water_toggle")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
        ]
        await query.edit_message_text(
            "⚙️ *Настройки*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif query.data == "toggle_morning_weather":
        new = not user.get("morning_weather", False)
        await save_user(user_id, morning_weather=new)
        status = "включена ✅" if new else "выключена ❌"
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="menu_settings")]]
        await query.edit_message_text(f"🌤️ Погода утром {status}", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "toggle_morning_motivation":
        new = not user.get("morning_motivation", False)
        await save_user(user_id, morning_motivation=new)
        status = "включена ✅" if new else "выключена ❌"
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="menu_settings")]]
        await query.edit_message_text(f"🧘 Мотивация утром {status}", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "back_main":
        await query.edit_message_text(
            f"🌸 *Меню Софии*\n\nЗдравствуйте, {name}! Чем могу помочь?",
            reply_markup=get_main_menu(),
            parse_mode="Markdown"
        )

async def announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("У вас нет доступа к этой команде.")
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
    await update.message.reply_text(
        "Добрый день!\n\n"
        "Рада познакомиться! Я здесь чтобы помочь вам с планами, целями и важными делами.\n\n"
        "Давайте начнём — как вас зовут? )"
    )
    await notify_admin(context, user_name, username, f"Новый пользователь (ID: {user_id})", "Начал онбординг")
    return ASK_NAME

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    name = update.message.text.strip()
    username = update.effective_user.username or "нет username"
    await save_user(user_id, name=name, username=username)
    await notify_admin(context, update.effective_user.first_name or "?", username, f"Представился: {name}", "Онбординг")
    await update.message.reply_text(
        f"Очень приятно, {name}! 😊\n\n"
        "🌍 В каком городе вы находитесь?\n\nНапример: Москва, Алматы, Дубай",
        reply_markup=ReplyKeyboardRemove()
    )
    return ASK_CITY

async def ask_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    city = update.message.text.strip()
    timezone = await get_timezone_by_city(city)
    await save_user(user_id, city=city, timezone=timezone)
    keyboard = [["✅ Да, каждое утро", "❌ Нет, не нужно"]]
    await update.message.reply_text(
        f"Отлично! Запомнила — {city} 🌍\n\n"
        "Хотите чтобы я каждое утро присылала план дня? 📋",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return ASK_MORNING_PLAN

async def ask_morning_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    wants_plan = "Да" in update.message.text
    await save_user(user_id, morning_plan=wants_plan)
    if wants_plan:
        keyboard = [["7:00", "8:00", "9:00"], ["10:00", "Другое"]]
        await update.message.reply_text(
            "В какое время присылать утренний план? ☀️",
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
    keyboard = [["✅ За час", "⏰ За 30 минут", "❌ Не нужно"]]
    await update.message.reply_text(
        "Напоминать о делах заранее? 🙂",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return ASK_REMINDERS

async def finish_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    if "час" in text:
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
    summary = f"Всё готово, {name}! 🌸\n\nЯ запомнила:\n"
    if has_plan:
        summary += f"\n📋 Утренний план в {morning_time}"
    if reminder_before > 0:
        summary += f"\n⏰ Напоминания за {reminder_before} минут"
    summary += "\n\nНапишите /menu чтобы открыть меню 🌸"
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
        await update.message.reply_text("Напишите /start чтобы начать 🌸")
        return
    user_name = update.effective_user.first_name or "Пользователь"
    username = update.effective_user.username or "нет username"
    name = user["name"]

    if context.user_data.get("waiting_habit"):
        context.user_data["waiting_habit"] = False
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO habits (user_id, name) VALUES ($1, $2)", user_id, user_text)
        await update.message.reply_text(f"✅ Привычка *{user_text}* добавлена!", parse_mode="Markdown")
        return

    if context.user_data.get("waiting_city"):
        context.user_data["waiting_city"] = False
        timezone = await get_timezone_by_city(user_text)
        await save_user(user_id, city=user_text, timezone=timezone)
        await update.message.reply_text(f"🌍 Город изменён на *{user_text}*!", parse_mode="Markdown")
        return

    if context.user_data.get("waiting_note"):
        context.user_data["waiting_note"] = False
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO notes (user_id, text) VALUES ($1, $2)", user_id, user_text)
        await update.message.reply_text("📝 Заметка сохранена!", parse_mode="Markdown")
        return

    if context.user_data.get("waiting_expense"):
        context.user_data["waiting_expense"] = False
        parts = user_text.split()
        try:
            amount = float(parts[0])
            category = parts[1] if len(parts) > 1 else "Другое"
            description = " ".join(parts[2:]) if len(parts) > 2 else ""
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO expenses (user_id, amount, category, description) VALUES ($1, $2, $3, $4)",
                    user_id, amount, category, description
                )
            await update.message.reply_text(f"💰 Расход *{amount:.0f} руб* ({category}) сохранён!", parse_mode="Markdown")
        except:
            await update.message.reply_text("Не понял формат. Напишите так: *500 еда кофе*", parse_mode="Markdown")
        return

    await add_history(user_id, "user", user_text)
    history = await get_history_db(user_id)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        if is_reminder_request(user_text):
            tz = pytz.timezone(user["timezone"] or "Europe/Moscow")
            now = datetime.now(tz)
            essence = await rephrase_reminder(user_text)
            rel_value, rel_unit = extract_relative_time(user_text)
            if rel_value is not None:
                if rel_unit == 'minutes':
                    remind_dt = now + timedelta(minutes=rel_value)
                else:
                    remind_dt = now + timedelta(hours=rel_value)
                job_name = f"once_{user_id}_{remind_dt.strftime('%H%M%S')}"
                context.application.job_queue.run_once(
                    send_scheduled_reminder,
                    when=remind_dt,
                    data={"user_id": user_id, "essence": essence},
                    name=job_name
                )
                await add_reminder(user_id, remind_dt.strftime("%H:%M"), essence)
            else:
                hour, minute = extract_exact_time(user_text)
                if hour is not None:
                    time_str = f"{hour:02d}:{minute:02d}"
                    conflict = await check_conflict_db(user_id, time_str)
                    if conflict:
                        conflict_msg = f"⚠️ {name}, в {time_str} уже запланировано:\n\n«{conflict}»\n\nВыбрать другое время?"
                        await update.message.reply_text(conflict_msg)
                        return
                    job_name = f"reminder_{user_id}_{hour}_{minute}"
                    for job in context.application.job_queue.get_jobs_by_name(job_name):
                        job.schedule_removal()
                    context.application.job_queue.run_daily(
                        send_scheduled_reminder,
                        time=time(hour=hour, minute=minute, tzinfo=tz),
                        data={"user_id": user_id, "essence": essence},
                        name=job_name
                    )
                    await add_reminder(user_id, time_str, essence)

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, *history],
            max_tokens=1000,
            temperature=0.7
        )
        reply = response.choices[0].message.content
        await add_history(user_id, "assistant", reply)
        await update.message.reply_text(reply)
        await notify_admin(context, user_name, username, user_text, reply)
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await update.message.reply_text("Прошу прощения, техническая ошибка. Попробуйте ещё раз.")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    if not user or not user["onboarded"]:
        await update.message.reply_text("Напишите /start чтобы начать 🌸")
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
            await update.message.reply_text("Не смогла распознать. Попробуйте ещё раз.")
            return
        await process_text_message(update, context, user_text)
    except Exception as e:
        logging.error(f"Ошибка голосового: {e}")
        await update.message.reply_text("Не удалось обработать голосовое. Попробуйте написать текстом.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_text_message(update, context, update.message.text)

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM history WHERE user_id = $1", user_id)
    await update.message.reply_text("История очищена 🌸")

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
    text = (
        "📊 *Статистика Софии*\n\n"
        f"👥 Всего: *{total}*\n"
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
            ASK_MORNING_PLAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_morning_plan)],
            ASK_MORNING_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_morning_time)],
            ASK_REMINDERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, finish_onboarding)],
        },
        fallbacks=[CommandHandler("start", start)]
    )
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("menu", show_menu))
    app.add_handler(CommandHandler("announce", announce))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🌸 София запущена с полным меню!")
    app.run_polling()
