import logging
import re
import os
import tempfile
import httpx
import random
from datetime import datetime, time, timedelta
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

ASK_NAME, ASK_TIMEZONE, ASK_CITY, ASK_MORNING_PLAN, ASK_MORNING_TIME, ASK_REMINDERS = range(6)

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
        return (
            f"🌤️ Погода в {city}:\n\n"
            f"🌡️ Температура: {temp}°C (ощущается как {feels}°C)\n"
            f"☁️ {desc.capitalize()}\n"
            f"💧 Влажность: {humidity}%\n"
            f"💨 Ветер: {wind} м/с"
        )
    except Exception as e:
        logging.error(f"Ошибка погоды: {e}")
        return "Не удалось получить данные о погоде."

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
         InlineKeyboardButton("👤 Профиль", callback_data="menu_profile")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="menu_settings")],
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
            [InlineKeyboardButton("🌤️ Погода", callback_data="morning_weather")],
            [InlineKeyboardButton("🧘 Мотивация", callback_data="morning_motivation")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
        ]
        await query.edit_message_text(
            "🌅 *Утреннее меню*\n\nВыберите что вас интересует:",
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

    elif query.data == "morning_weather":
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
            "➕ *Добавить привычку*\n\nНапишите название привычки\n\nНапример: Медитация, Чтение, Зарядка",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif query.data == "habit_log":
        async with db_pool.acquire() as conn:
            habits = await conn.fetch("SELECT id, name FROM habits WHERE user_id = $1", user_id)
        if not habits:
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="menu_habits")]]
            await query.edit_message_text(
                "У вас нет привычек. Сначала добавьте привычку!",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        keyboard = [[InlineKeyboardButton(f"✅ {h['name']}", callback_data=f"log_habit_{h['id']}")] for h in habits]
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="menu_habits")])
        await query.edit_message_text(
            "✅ Какую привычку отмечаем?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith("log_habit_"):
        habit_id = int(query.data.split("_")[-1])
        async with db_pool.acquire() as conn:
            habit = await conn.fetchrow("SELECT name FROM habits WHERE id = $1", habit_id)
            await conn.execute(
                "INSERT INTO habit_logs (user_id, habit_id) VALUES ($1, $2)",
                user_id, habit_id
            )
        keyboard = [[InlineKeyboardButton("◀️ К привычкам", callback_data="menu_habits")]]
        await query.edit_message_text(
            f"🎉 Отлично! Привычка *{habit['name']}* отмечена!\n\nТак держать! 💪",
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
                lines.append(f"📊 {h['name']}: {count}/7 дней на этой неделе")
        text = "📊 *Статистика привычек за 7 дней:*\n\n" + "\n".join(lines) if lines else "Нет данных."
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="menu_habits")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data == "menu_water":
        water_on = user.get("water_reminders", False)
        status = "✅ Включены" if water_on else "❌ Выключены"
        interval = user.get("water_interval", 2)
        keyboard = [
            [InlineKeyboardButton("💧 Выпил воду сейчас!", callback_data="water_drink")],
            [InlineKeyboardButton(
                "🔔 Выключить напоминания" if water_on else "🔔 Включить напоминания",
                callback_data="water_toggle"
            )],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
        ]
        await query.edit_message_text(
            f"💧 *Трекер воды*\n\nНапоминания: {status}\nИнтервал: каждые {interval} часа\n\nНорма воды: 8 стаканов в день 🌊",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif query.data == "water_drink":
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="menu_water")]]
        await query.edit_message_text(
            "💧 Отлично! Вы выпили стакан воды!\n\nПродолжайте в том же духе! 🌊",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "water_toggle":
        water_on = user.get("water_reminders", False)
        new_state = not water_on
        await save_user(user_id, water_reminders=new_state)
        if new_state:
            interval = user.get("water_interval", 2)
            context.application.job_queue.run_repeating(
                send_water_reminder,
                interval=interval * 3600,
                first=interval * 3600,
                data=user_id,
                name=f"water_{user_id}"
            )
            text = f"✅ Напоминания о воде включены!\nБуду напоминать каждые {interval} часа. 💧"
        else:
            jobs = context.application.job_queue.get_jobs_by_name(f"water_{user_id}")
            for job in jobs:
                job.schedule_removal()
            text = "❌ Напоминания о воде выключены."
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="menu_water")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "menu_profile":
        async with db_pool.acquire() as conn:
            total_messages = await conn.fetchval(
                "SELECT COUNT(*) FROM history WHERE user_id = $1 AND role = 'user'", user_id
            )
            habits_count = await conn.fetchval(
                "SELECT COUNT(*) FROM habits WHERE user_id = $1", user_id
            )
        created = user.get("created_at")
        days = (datetime.now() - created).days if created else 0
        tz = user.get("timezone") or "Europe/Moscow"
        text = (
            f"👤 *Мой профиль*\n\n"
            f"👋 Имя: {name}\n"
            f"🌍 Город: {city}\n"
            f"🕐 Часовой пояс: {tz}\n"
            f"📅 Дней с нами: {days}\n"
            f"💬 Сообщений отправлено: {total_messages}\n"
            f"💪 Привычек отслеживается: {habits_count}"
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
            "🌍 Напишите название вашего города\n\nНапример: Москва, Алматы, Киев",
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
            "⚙️ *Настройки уведомлений*\n\nВключите или выключите что вам нужно:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif query.data == "toggle_morning_weather":
        new = not user.get("morning_weather", False)
        await save_user(user_id, morning_weather=new)
        status = "включена ✅" if new else "выключена ❌"
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="menu_settings")]]
        await query.edit_message_text(
            f"🌤️ Погода утром {status}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "toggle_morning_motivation":
        new = not user.get("morning_motivation", False)
        await save_user(user_id, morning_motivation=new)
        status = "включена ✅" if new else "выключена ❌"
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="menu_settings")]]
        await query.edit_message_text(
            f"🧘 Мотивация утром {status}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

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
        await update.message.reply_text("Пример:\n/announce Привет! У Софии новые функции 🎉")
        return
    text = " ".join(context.args)
    all_users = await get_all_users()
    sent = 0
    failed = 0
    await update.message.reply_text(f"Начинаю рассылку для {len(all_users)} пользователей...")
    for uid in all_users:
        try:
            await context.bot.send_message(chat_id=uid, text=f"📢 {text}")
            sent += 1
        except Exception as e:
            logging.error(f"Не удалось отправить {uid}: {e}")
            failed += 1
    await update.message.reply_text(f"Рассылка завершена!\n\n✅ Отправлено: {sent}\n❌ Не доставлено: {failed}")

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
    keyboard = [["🇷🇺 Москва (UTC+3)", "🇰🇿 Алматы (UTC+5)"],
                ["🇺🇦 Киев (UTC+2)", "Другой"]]
    await update.message.reply_text(
        f"Очень приятно, {name}! 😊\n\n"
        "Укажите ваш часовой пояс — это нужно для точных напоминаний.",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return ASK_TIMEZONE

async def ask_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    tz_map = {
        "🇷🇺 Москва (UTC+3)": "Europe/Moscow",
        "🇰🇿 Алматы (UTC+5)": "Asia/Almaty",
        "🇺🇦 Киев (UTC+2)": "Europe/Kiev",
    }
    tz = tz_map.get(text, "Europe/Moscow")
    await save_user(user_id, timezone=tz)
    await update.message.reply_text(
        "🌍 В каком городе вы находитесь?\n\nЭто нужно для точной погоды.\n\nНапример: Москва, Алматы, Киев",
        reply_markup=ReplyKeyboardRemove()
    )
    return ASK_CITY

async def ask_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    city = update.message.text.strip()
    await save_user(user_id, city=city)
    keyboard = [["✅ Да, каждое утро", "❌ Нет, не нужно"]]
    await update.message.reply_text(
        f"Отлично! Запомнила — {city} 🌍\n\n"
        "Хотите, чтобы я каждое утро присылала план дня? 📋",
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
        "Напоминать о запланированных делах заранее? 🙂",
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
        summary += f"\n📋 Утренний план — каждый день в {morning_time}"
    if reminder_before > 0:
        summary += f"\n⏰ Напоминания — за {reminder_before} минут до события"
    summary += "\n\nМожете начинать! Напишите /menu чтобы открыть меню 🌸"
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
            await conn.execute(
                "INSERT INTO habits (user_id, name) VALUES ($1, $2)",
                user_id, user_text
            )
        await update.message.reply_text(
            f"✅ Привычка *{user_text}* добавлена!\n\nОткройте /menu → Привычки чтобы отмечать выполнение.",
            parse_mode="Markdown"
        )
        return

    if context.user_data.get("waiting_city"):
        context.user_data["waiting_city"] = False
        await save_user(user_id, city=user_text)
        await update.message.reply_text(f"🌍 Город изменён на *{user_text}*!", parse_mode="Markdown")
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
                        conflict_msg = f"⚠️ {name}, в {time_str} у вас уже запланировано:\n\n«{conflict}»\n\nВыбрать другое время?"
                        await update.message.reply_text(conflict_msg)
                        await notify_admin(context, user_name, username, user_text, conflict_msg)
                        return
                    job_name = f"reminder_{user_id}_{hour}_{minute}"
                    old_jobs = context.application.job_queue.get_jobs_by_name(job_name)
                    for job in old_jobs:
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
        await update.message.reply_text("Прошу прощения, произошла техническая ошибка. Попробуйте ещё раз.")

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
            await update.message.reply_text("Не смогла распознать голосовое сообщение. Попробуйте ещё раз.")
            return
        await process_text_message(update, context, user_text)
    except Exception as e:
        logging.error(f"Ошибка голосового: {e}")
        await update.message.reply_text("Не удалось обработать голосовое сообщение. Попробуйте написать текстом.")

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
        await update.message.reply_text("У вас нет доступа к этой команде.")
        return
    async with db_pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM users WHERE onboarded = TRUE")
        today = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM history WHERE created_at >= NOW() - INTERVAL '1 day'")
        week = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM history WHERE created_at >= NOW() - INTERVAL '7 days'")
        total_messages = await conn.fetchval("SELECT COUNT(*) FROM history WHERE role = 'user'")
    text = (
        "📊 *Статистика Софии*\n\n"
        f"👥 Всего пользователей: *{total}*\n"
        f"🟢 Активных сегодня: *{today}*\n"
        f"📅 Активных за 7 дней: *{week}*\n"
        f"💬 Всего сообщений: *{total_messages}*"
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
            ASK_TIMEZONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_timezone)],
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
