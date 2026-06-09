import os
import logging
import asyncio
import aiohttp
import json
import random
from datetime import datetime, timedelta
from typing import Optional
import asyncpg
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove, FSInputFile, BufferedInputFile
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import base64
import tempfile

# ─── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ─── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN    = os.getenv("BOT_TOKEN", "")
OPENAI_KEY   = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE  = os.getenv("OPENAI_BASE_URL", "https://api.aitunnel.ru/v1/")
WEATHER_KEY  = os.getenv("WEATHER_API_KEY", "")
NEWS_KEY     = os.getenv("NEWS_API_KEY", "")
ASSEMBLY_KEY = os.getenv("ASSEMBLYAI_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
ADMIN_ID     = int(os.getenv("ADMIN_ID", "944447597"))
MODEL        = "gpt-4o-mini"
IMAGE_MODEL  = "gpt-image-1-mini"

# ─── States ────────────────────────────────────────────────────────────────────
class States(StatesGroup):
    # Finance
    finance_add_income   = State()
    finance_add_expense  = State()
    # Sleep
    sleep_input          = State()
    # Water
    water_input          = State()
    # Habits
    habit_add            = State()
    # Notes
    note_add             = State()
    # Shopping
    shopping_add         = State()
    # Reminders
    reminder_text        = State()
    reminder_time        = State()
    # City
    city_input           = State()
    # Planner
    planner_add          = State()
    planner_day          = State()
    planner_time         = State()
    planner_title        = State()
    # Recipes
    recipe_search        = State()
    # Health - cycle
    cycle_start_date     = State()
    cycle_length         = State()
    # Health - pills
    pill_name            = State()
    pill_time            = State()
    # Health - stress
    stress_score         = State()
    # Goals
    goal_title           = State()
    goal_description     = State()
    goal_update          = State()
    # Watch later
    watch_add            = State()

# ─── Bot & Dispatcher ──────────────────────────────────────────────────────────
bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())
db: asyncpg.Pool = None  # type: ignore

# ─── DB Init ───────────────────────────────────────────────────────────────────
DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     BIGINT PRIMARY KEY,
    username    TEXT,
    first_name  TEXT,
    city        TEXT DEFAULT 'Москва',
    language    TEXT DEFAULT 'ru',
    style       TEXT DEFAULT 'girlfriend',
    morning_weather  BOOLEAN DEFAULT TRUE,
    morning_motivation BOOLEAN DEFAULT TRUE,
    water_remind BOOLEAN DEFAULT TRUE,
    evening_summary BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_memory (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT,
    memory_text TEXT,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reminders (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT,
    text        TEXT,
    remind_at   TIMESTAMP,
    repeat_rule TEXT,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS finances (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT,
    type        TEXT,
    amount      NUMERIC,
    description TEXT,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sleep_log (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT,
    hours       NUMERIC,
    quality     TEXT,
    log_date    DATE DEFAULT CURRENT_DATE,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS water_log (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT,
    ml          INT,
    log_date    DATE DEFAULT CURRENT_DATE,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS habits (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT,
    name        TEXT,
    streak      INT DEFAULT 0,
    last_done   DATE,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS notes (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT,
    text        TEXT,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shopping (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT,
    item        TEXT,
    is_done     BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS recipes (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT,
    title       TEXT,
    content     TEXT,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS planner (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT,
    title       TEXT,
    weekday     INT,
    time_str    TEXT,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS health_cycle (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT,
    start_date  DATE,
    cycle_days  INT DEFAULT 28,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pills (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT,
    name        TEXT,
    remind_time TEXT,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS stress_log (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT,
    score       INT,
    log_date    DATE DEFAULT CURRENT_DATE,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS goals (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT,
    title       TEXT,
    description TEXT,
    progress    INT DEFAULT 0,
    is_done     BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS watch_list (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT,
    title       TEXT,
    genre       TEXT,
    is_watched  BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conversation_history (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT,
    role        TEXT,
    content     TEXT,
    created_at  TIMESTAMP DEFAULT NOW()
);
"""

async def init_db():
    global db
    db = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    async with db.acquire() as conn:
        await conn.execute(DB_SCHEMA)
    log.info("DB initialized")

async def ensure_user(user_id: int, username: str = "", first_name: str = ""):
    await db.execute(
        """INSERT INTO users(user_id, username, first_name)
           VALUES($1,$2,$3) ON CONFLICT(user_id) DO NOTHING""",
        user_id, username, first_name
    )

async def get_user(user_id: int):
    return await db.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)

# ─── Keyboards ─────────────────────────────────────────────────────────────────
def kb_main():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌅 Утро", callback_data="menu_morning"),
         InlineKeyboardButton(text="📒 Дневник", callback_data="menu_diary")],
        [InlineKeyboardButton(text="✨ Интересное", callback_data="menu_interesting"),
         InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu_settings")],
        [InlineKeyboardButton(text="✖️ Закрыть меню", callback_data="menu_close")],
    ])

def kb_diary():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Финансы", callback_data="diary_finance"),
         InlineKeyboardButton(text="😴 Сон", callback_data="diary_sleep")],
        [InlineKeyboardButton(text="💧 Вода", callback_data="diary_water"),
         InlineKeyboardButton(text="✅ Привычки", callback_data="diary_habits")],
        [InlineKeyboardButton(text="📝 Заметки", callback_data="diary_notes"),
         InlineKeyboardButton(text="🍳 Рецепты", callback_data="diary_recipes")],
        [InlineKeyboardButton(text="🎬 Что посмотреть", callback_data="diary_watch"),
         InlineKeyboardButton(text="🗓 Планер", callback_data="diary_planner")],
        [InlineKeyboardButton(text="🛒 Покупки", callback_data="diary_shopping")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_back")],
    ])

def kb_settings():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Профиль", callback_data="settings_profile"),
         InlineKeyboardButton(text="💬 Стиль общения", callback_data="settings_style")],
        [InlineKeyboardButton(text="🏙 Город", callback_data="settings_city"),
         InlineKeyboardButton(text="🌍 Язык", callback_data="settings_lang")],
        [InlineKeyboardButton(text="🌤 Погода утром", callback_data="toggle_morning_weather"),
         InlineKeyboardButton(text="💪 Мотивация утром", callback_data="toggle_morning_motivation")],
        [InlineKeyboardButton(text="💧 Напомн. о воде", callback_data="toggle_water_remind"),
         InlineKeyboardButton(text="🌙 Вечерняя сводка", callback_data="toggle_evening_summary")],
        [InlineKeyboardButton(text="🗑 Забудь всё", callback_data="settings_forget")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_back")],
    ])

def kb_back(callback: str = "menu_back"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=callback)]
    ])

def kb_recipe_actions(recipe_id: int = 0, from_chat: bool = False):
    save_cb = f"recipe_save_{recipe_id}" if recipe_id else "recipe_save_chat"
    skip_cb = "recipe_skip"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💾 Сохранить", callback_data=save_cb),
         InlineKeyboardButton(text="❌ Не нужно", callback_data=skip_cb)],
    ])

# ─── AI Helper ─────────────────────────────────────────────────────────────────
async def ai_chat(user_id: int, user_message: str, system_extra: str = "") -> str:
    user = await get_user(user_id)
    style_map = {
        "girlfriend": "Ты — Cофия, лучшая подруга пользователя. Общаешься тепло, по-дружески, с заботой.",
        "mentor":     "Ты — София, мудрый наставник. Даёшь взвешенные советы, поддерживаешь развитие.",
        "pro":        "Ты — София, профессиональный ассистент. Чёткие, структурированные ответы.",
    }
    style_prompt = style_map.get(user["style"] if user else "girlfriend", style_map["girlfriend"])

    # Load memories
    memories = await db.fetch(
        "SELECT memory_text FROM user_memory WHERE user_id=$1 ORDER BY created_at DESC LIMIT 10",
        user_id
    )
    mem_str = "\n".join(m["memory_text"] for m in memories) if memories else "пока нет"

    system_prompt = f"""{style_prompt}

ВАЖНЫЕ ПРАВИЛА:
- Никогда не используй звёздочки (*) и Markdown разметку в ответах
- Пиши обычным текстом без форматирования
- Ты помнишь всё что пользователь тебе рассказывал
- Всегда подтверждай напоминания с точным временем
- Если слышишь "каждый [день недели] в [время]" — предложи добавить в планер
- Отвечай на языке: {user['language'] if user else 'ru'}

Что ты знаешь о пользователе:
{mem_str}

{system_extra}"""

    # Load recent conversation
    history_rows = await db.fetch(
        "SELECT role, content FROM conversation_history WHERE user_id=$1 ORDER BY created_at DESC LIMIT 20",
        user_id
    )
    messages = [{"role": "system", "content": system_prompt}]
    for row in reversed(history_rows):
        messages.append({"role": row["role"], "content": row["content"]})
    messages.append({"role": "user", "content": user_message})

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{OPENAI_BASE}chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
                json={"model": MODEL, "messages": messages, "max_tokens": 1000, "temperature": 0.7},
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                data = await resp.json()
                reply = data["choices"][0]["message"]["content"].strip()
                # Strip markdown
                reply = reply.replace("**", "").replace("*", "").replace("__", "").replace("`", "")
    except Exception as e:
        log.error(f"AI error: {e}")
        reply = "Прости, что-то пошло не так. Попробуй ещё раз!"

    # Save to history
    await db.execute(
        "INSERT INTO conversation_history(user_id, role, content) VALUES($1,'user',$2)",
        user_id, user_message
    )
    await db.execute(
        "INSERT INTO conversation_history(user_id, role, content) VALUES($1,'assistant',$2)",
        user_id, reply
    )

    # Auto-extract memory
    await auto_save_memory(user_id, user_message)

    # Check for planner suggestion
    await maybe_suggest_planner(user_id, user_message)

    return reply

async def auto_save_memory(user_id: int, text: str):
    keywords = ["меня зовут", "я люблю", "я работаю", "мой город", "у меня есть",
                "я живу", "я учусь", "мне нравится", "я не люблю", "моя семья"]
    text_lower = text.lower()
    if any(kw in text_lower for kw in keywords):
        await db.execute(
            "INSERT INTO user_memory(user_id, memory_text) VALUES($1,$2)",
            user_id, text[:200]
        )

async def maybe_suggest_planner(user_id: int, text: str):
    days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье",
            "пн", "вт", "ср", "чт", "пт", "сб", "вс",
            "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    text_lower = text.lower()
    has_day = any(d in text_lower for d in days)
    has_time = ":" in text or any(w in text_lower for w in ["в ", "утром", "вечером", "в час", "часов"])
    has_repeat = any(w in text_lower for w in ["каждый", "каждую", "каждое", "every", "еженедельно"])
    if has_day and has_time and has_repeat:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📅 Добавить в планер", callback_data=f"planner_quick_add"),
             InlineKeyboardButton(text="Нет, спасибо", callback_data="planner_skip")]
        ])
        await bot.send_message(user_id, "Заметила, что ты говоришь о регулярном занятии. Добавить это в планер?", reply_markup=kb)

# ─── Weather ───────────────────────────────────────────────────────────────────
async def get_weather(city: str, mode: str = "now") -> str:
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_KEY}&units=metric&lang=ru"
            if mode in ("hourly", "week"):
                url = f"https://api.openweathermap.org/data/2.5/forecast?q={city}&appid={WEATHER_KEY}&units=metric&lang=ru&cnt=40"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()

        if mode == "now":
            temp = round(data["main"]["temp"])
            feels = round(data["main"]["feels_like"])
            desc = data["weather"][0]["description"]
            wind = data["wind"]["speed"]
            return f"Погода в {city}: {temp}°C, ощущается как {feels}°C\n{desc.capitalize()}\nВетер: {wind} м/с"

        elif mode == "hourly":
            lines = [f"Погода по часам в {city}:"]
            for item in data["list"][:8]:
                t = datetime.fromtimestamp(item["dt"]).strftime("%H:%M")
                temp = round(item["main"]["temp"])
                desc = item["weather"][0]["description"]
                lines.append(f"{t} — {temp}°C, {desc}")
            return "\n".join(lines)

        elif mode == "week":
            lines = [f"Прогноз на неделю для {city}:"]
            seen_days = set()
            for item in data["list"]:
                day = datetime.fromtimestamp(item["dt"]).strftime("%d.%m %A")
                if day not in seen_days and len(seen_days) < 7:
                    seen_days.add(day)
                    temp = round(item["main"]["temp"])
                    desc = item["weather"][0]["description"]
                    lines.append(f"{day}: {temp}°C, {desc}")
            return "\n".join(lines)

    except Exception as e:
        log.error(f"Weather error: {e}")
        return f"Не могу получить погоду для {city}. Проверь название города."

# ─── News ──────────────────────────────────────────────────────────────────────
async def get_news(query: str = "технологии", lang: str = "ru") -> list:
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://newsapi.org/v2/everything?q={query}&language={lang}&pageSize=5&apiKey={NEWS_KEY}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
        articles = data.get("articles", [])
        return [{"title": a["title"], "url": a["url"], "source": a.get("source", {}).get("name", "")} for a in articles[:5]]
    except Exception as e:
        log.error(f"News error: {e}")
        return []

# ─── Interesting content ───────────────────────────────────────────────────────
INTERESTING_CATEGORIES = {
    "science":  ("Наука", "https://ru.wikipedia.org/wiki/Special:Random"),
    "history":  ("История", "https://ru.wikipedia.org/wiki/Special:Random"),
    "tech":     ("Технологии", "новости технологий"),
    "facts":    ("Интересные факты", "случайный интересный факт"),
}

async def get_interesting_article(category: str = "facts") -> str:
    prompts = {
        "science": "Расскажи один интересный научный факт или открытие (3-4 предложения, без звёздочек)",
        "history": "Расскажи один интересный исторический факт или событие (3-4 предложения, без звёздочек)",
        "tech":    "Расскажи об одной интересной технологии или гаджете (3-4 предложения, без звёздочек)",
        "facts":   "Расскажи один удивительный факт о мире (3-4 предложения, без звёздочек)",
        "travel":  "Расскажи об одном необычном месте на Земле (3-4 предложения, без звёздочек)",
    }
    # Use random seed to get different content each time
    seed = random.randint(1, 10000)
    prompt = prompts.get(category, prompts["facts"]) + f" (вариант #{seed})"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{OPENAI_BASE}chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
                json={"model": MODEL, "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 300, "temperature": 1.0},
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                data = await resp.json()
                text = data["choices"][0]["message"]["content"].strip()
                return text.replace("**", "").replace("*", "").replace("`", "")
    except Exception as e:
        log.error(f"Interesting error: {e}")
        return "Не удалось загрузить статью. Попробуй ещё раз!"

# ─── Image Generation ──────────────────────────────────────────────────────────
async def generate_image(prompt: str) -> Optional[bytes]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{OPENAI_BASE}images/generations",
                headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
                json={"model": IMAGE_MODEL, "prompt": prompt, "n": 1,
                      "size": "1024x1024", "response_format": "b64_json"},
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                data = await resp.json()
                b64 = data["data"][0]["b64_json"]
                return base64.b64decode(b64)
    except Exception as e:
        log.error(f"Image gen error: {e}")
        return None

# ─── Voice ─────────────────────────────────────────────────────────────────────
async def transcribe_voice(file_bytes: bytes) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            # Upload
            async with session.post(
                "https://api.assemblyai.com/v2/upload",
                headers={"authorization": ASSEMBLY_KEY},
                data=file_bytes,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                upload_url = (await resp.json())["upload_url"]
            # Transcribe
            async with session.post(
                "https://api.assemblyai.com/v2/transcript",
                headers={"authorization": ASSEMBLY_KEY, "content-type": "application/json"},
                json={"audio_url": upload_url, "language_code": "ru"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                transcript_id = (await resp.json())["id"]
            # Poll
            for _ in range(30):
                await asyncio.sleep(3)
                async with session.get(
                    f"https://api.assemblyai.com/v2/transcript/{transcript_id}",
                    headers={"authorization": ASSEMBLY_KEY},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    result = await resp.json()
                    if result["status"] == "completed":
                        return result.get("text", "")
                    elif result["status"] == "error":
                        return ""
    except Exception as e:
        log.error(f"Voice error: {e}")
        return ""

# ─── Reminders (DB-backed, survive deploys) ────────────────────────────────────
reminder_tasks = {}

async def restore_reminders():
    """Called on startup — restores all active reminders from DB."""
    rows = await db.fetch(
        "SELECT * FROM reminders WHERE is_active=TRUE AND remind_at > NOW()",
    )
    count = 0
    for row in rows:
        task = asyncio.create_task(reminder_worker(row["id"], row["user_id"], row["text"], row["remind_at"], row["repeat_rule"]))
        reminder_tasks[row["id"]] = task
        count += 1
    log.info(f"Restored {count} reminders")

async def reminder_worker(reminder_id: int, user_id: int, text: str, remind_at: datetime, repeat_rule: Optional[str]):
    now = datetime.now()
    wait_secs = (remind_at - now).total_seconds()
    if wait_secs > 0:
        await asyncio.sleep(wait_secs)
    # Check still active
    row = await db.fetchrow("SELECT is_active FROM reminders WHERE id=$1", reminder_id)
    if not row or not row["is_active"]:
        return
    await bot.send_message(user_id, f"Напоминание: {text}")
    if repeat_rule:
        # weekly: добавляем 7 дней и создаём новое напоминание
        if repeat_rule == "weekly":
            new_time = remind_at + timedelta(weeks=1)
            new_id = await db.fetchval(
                "INSERT INTO reminders(user_id, text, remind_at, repeat_rule) VALUES($1,$2,$3,$4) RETURNING id",
                user_id, text, new_time, repeat_rule
            )
            task = asyncio.create_task(reminder_worker(new_id, user_id, text, new_time, repeat_rule))
            reminder_tasks[new_id] = task
        elif repeat_rule == "daily":
            new_time = remind_at + timedelta(days=1)
            new_id = await db.fetchval(
                "INSERT INTO reminders(user_id, text, remind_at, repeat_rule) VALUES($1,$2,$3,$4) RETURNING id",
                user_id, text, new_time, repeat_rule
            )
            task = asyncio.create_task(reminder_worker(new_id, user_id, text, new_time, repeat_rule))
            reminder_tasks[new_id] = task
    await db.execute("UPDATE reminders SET is_active=FALSE WHERE id=$1", reminder_id)

async def schedule_reminder(user_id: int, text: str, remind_at: datetime, repeat_rule: Optional[str] = None) -> int:
    rid = await db.fetchval(
        "INSERT INTO reminders(user_id, text, remind_at, repeat_rule) VALUES($1,$2,$3,$4) RETURNING id",
        user_id, text, remind_at, repeat_rule
    )
    task = asyncio.create_task(reminder_worker(rid, user_id, text, remind_at, repeat_rule))
    reminder_tasks[rid] = task
    return rid

async def parse_reminder_time(text: str) -> Optional[datetime]:
    """AI-powered time parsing."""
    now = datetime.now()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{OPENAI_BASE}chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
                json={
                    "model": MODEL,
                    "messages": [{
                        "role": "user",
                        "content": f"Сейчас: {now.strftime('%Y-%m-%d %H:%M')}. Извлеки дату и время из текста: '{text}'. Ответь ТОЛЬКО в формате YYYY-MM-DD HH:MM. Если не можешь — ответь NONE."
                    }],
                    "max_tokens": 30, "temperature": 0
                },
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                result = data["choices"][0]["message"]["content"].strip()
                if result == "NONE":
                    return None
                return datetime.strptime(result, "%Y-%m-%d %H:%M")
    except:
        return None

# ─── Pills daily reminder ──────────────────────────────────────────────────────
async def pill_daily_checker():
    """Runs every minute to check pill reminders."""
    while True:
        await asyncio.sleep(60)
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        try:
            rows = await db.fetch(
                "SELECT p.user_id, p.name, p.remind_time FROM pills p WHERE p.is_active=TRUE AND p.remind_time=$1",
                current_time
            )
            for row in rows:
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Принял(а)", callback_data=f"pill_taken_{row['name']}"),
                     InlineKeyboardButton(text="⏰ Напомни позже", callback_data=f"pill_later_{row['name']}")]
                ])
                await bot.send_message(row["user_id"], f"Время принять таблетку: {row['name']}", reply_markup=kb)
        except Exception as e:
            log.error(f"Pill checker error: {e}")

# ─── Morning routine ───────────────────────────────────────────────────────────
async def morning_routine():
    """Sends morning greeting at 8:00."""
    while True:
        now = datetime.now()
        next_8 = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if now >= next_8:
            next_8 += timedelta(days=1)
        await asyncio.sleep((next_8 - now).total_seconds())

        users = await db.fetch("SELECT * FROM users WHERE morning_weather=TRUE OR morning_motivation=TRUE")
        for user in users:
            parts = [f"Доброе утро! Рада тебя видеть."]
            if user["morning_weather"]:
                weather = await get_weather(user["city"] or "Москва")
                parts.append(weather)
            if user["morning_motivation"]:
                motivations = [
                    "Сегодня отличный день, чтобы сделать что-то важное для себя.",
                    "Ты справишься со всем, что запланировала. Верю в тебя!",
                    "Каждый новый день — это новая возможность стать лучше.",
                    "Улыбнись! Ты уже сделала большой шаг, проснувшись с хорошим настроем.",
                ]
                parts.append(random.choice(motivations))
            await bot.send_message(user["user_id"], "\n\n".join(parts))

# ─── Evening summary ───────────────────────────────────────────────────────────
async def evening_summary():
    """Sends evening summary at 21:00."""
    while True:
        now = datetime.now()
        next_21 = now.replace(hour=21, minute=0, second=0, microsecond=0)
        if now >= next_21:
            next_21 += timedelta(days=1)
        await asyncio.sleep((next_21 - now).total_seconds())

        users = await db.fetch("SELECT * FROM users WHERE evening_summary=TRUE")
        for user in users:
            uid = user["user_id"]
            today = datetime.now().date()

            # Water
            water = await db.fetchval("SELECT COALESCE(SUM(ml),0) FROM water_log WHERE user_id=$1 AND log_date=$2", uid, today)
            # Sleep
            sleep = await db.fetchrow("SELECT hours FROM sleep_log WHERE user_id=$1 AND log_date=$2", uid, today)
            # Finance
            income = await db.fetchval("SELECT COALESCE(SUM(amount),0) FROM finances WHERE user_id=$1 AND type='income' AND DATE(created_at)=$2", uid, today)
            expense = await db.fetchval("SELECT COALESCE(SUM(amount),0) FROM finances WHERE user_id=$1 AND type='expense' AND DATE(created_at)=$2", uid, today)

            lines = ["Вечерняя сводка за сегодня:"]
            lines.append(f"Воды выпито: {water} мл")
            if sleep:
                lines.append(f"Сон: {sleep['hours']} ч")
            if income or expense:
                lines.append(f"Доходы: {income} | Расходы: {expense}")
            lines.append("\nКак прошёл твой день?")

            await bot.send_message(uid, "\n".join(lines))

# ─── Goal progress checker ────────────────────────────────────────────────────
async def goal_progress_checker():
    """Periodically asks about goal progress."""
    while True:
        await asyncio.sleep(86400 * 3)  # every 3 days
        try:
            goals = await db.fetch("SELECT g.*, u.user_id FROM goals g JOIN users u ON g.user_id=u.user_id WHERE g.is_done=FALSE")
            for goal in goals:
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Обновить прогресс", callback_data=f"goal_update_{goal['id']}")]
                ])
                await bot.send_message(
                    goal["user_id"],
                    f"Как дела с целью '{goal['title']}'? Текущий прогресс: {goal['progress']}%",
                    reply_markup=kb
                )
        except Exception as e:
            log.error(f"Goal checker error: {e}")

# ─── Cycle reminder ───────────────────────────────────────────────────────────
async def cycle_reminder():
    """Checks cycle and sends reminder 3 days before."""
    while True:
        await asyncio.sleep(3600)  # check every hour
        try:
            cycles = await db.fetch("SELECT * FROM health_cycle")
            for cycle in cycles:
                start = cycle["start_date"]
                length = cycle["cycle_days"]
                next_cycle = start + timedelta(days=length)
                days_left = (next_cycle - datetime.now().date()).days
                if days_left == 3:
                    await bot.send_message(
                        cycle["user_id"],
                        f"Через 3 дня ожидается начало нового цикла (примерно {next_cycle.strftime('%d.%m')}). Позаботься о себе заранее."
                    )
        except Exception as e:
            log.error(f"Cycle reminder error: {e}")

# ─── Handlers: /start ─────────────────────────────────────────────────────────
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    name = message.from_user.first_name or "подруга"
    await message.answer(
        f"Привет, {name}! Я София, твой личный ассистент.\nЧем могу помочь сегодня?",
        reply_markup=kb_main()
    )

@dp.message(Command("menu"))
async def cmd_menu(message: Message):
    await ensure_user(message.from_user.id)
    await message.answer("Главное меню:", reply_markup=kb_main())

# ─── Main menu callbacks ───────────────────────────────────────────────────────
@dp.callback_query(F.data == "menu_back")
async def cb_menu_back(cq: CallbackQuery):
    await cq.message.edit_text("Главное меню:", reply_markup=kb_main())
    await cq.answer()

@dp.callback_query(F.data == "menu_close")
async def cb_menu_close(cq: CallbackQuery):
    await cq.message.delete()
    await cq.answer("Меню закрыто")

@dp.callback_query(F.data == "menu_diary")
async def cb_menu_diary(cq: CallbackQuery):
    await cq.message.edit_text("Дневник:", reply_markup=kb_diary())
    await cq.answer()

@dp.callback_query(F.data == "menu_settings")
async def cb_menu_settings(cq: CallbackQuery):
    await cq.message.edit_text("Настройки:", reply_markup=kb_settings())
    await cq.answer()

# ─── Morning ──────────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "menu_morning")
async def cb_morning(cq: CallbackQuery):
    user = await get_user(cq.from_user.id)
    city = user["city"] if user else "Москва"
    weather = await get_weather(city)
    motivations = [
        "Отличное начало нового дня! Ты готова к новым свершениям.",
        "Каждое утро — это шанс стать лучшей версией себя.",
        "Сегодня будет хороший день. Улыбнись и вперёд!",
        "Ты сильная и всё у тебя получится.",
    ]
    motivation = random.choice(motivations)
    text = f"Доброе утро!\n\n{weather}\n\n{motivation}"
    await cq.message.edit_text(text, reply_markup=kb_back())
    await cq.answer()

# ─── Interesting ──────────────────────────────────────────────────────────────
def kb_interesting():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔬 Наука", callback_data="interesting_science"),
         InlineKeyboardButton(text="📜 История", callback_data="interesting_history")],
        [InlineKeyboardButton(text="💻 Технологии", callback_data="interesting_tech"),
         InlineKeyboardButton(text="🌍 Факты", callback_data="interesting_facts")],
        [InlineKeyboardButton(text="✈️ Путешествия", callback_data="interesting_travel")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_back")],
    ])

@dp.callback_query(F.data == "menu_interesting")
async def cb_interesting(cq: CallbackQuery):
    await cq.message.edit_text("Что тебя интересует?", reply_markup=kb_interesting())
    await cq.answer()

@dp.callback_query(F.data.startswith("interesting_"))
async def cb_interesting_category(cq: CallbackQuery):
    category = cq.data.split("_")[1]
    await cq.message.edit_text("Загружаю статью...")
    text = await get_interesting_article(category)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Ещё", callback_data=cq.data),
         InlineKeyboardButton(text="◀️ Назад", callback_data="menu_interesting")],
    ])
    await cq.message.edit_text(text, reply_markup=kb)
    await cq.answer()

# ─── Settings ─────────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "settings_profile")
async def cb_profile(cq: CallbackQuery):
    user = await get_user(cq.from_user.id)
    if not user:
        await cq.answer("Профиль не найден")
        return
    style_names = {"girlfriend": "Подружка", "mentor": "Наставник", "pro": "Профессионал"}
    text = (
        f"Профиль:\n"
        f"Имя: {cq.from_user.first_name}\n"
        f"Город: {user['city']}\n"
        f"Язык: {user['language']}\n"
        f"Стиль: {style_names.get(user['style'], user['style'])}\n"
        f"Погода утром: {'да' if user['morning_weather'] else 'нет'}\n"
        f"Мотивация утром: {'да' if user['morning_motivation'] else 'нет'}\n"
        f"Напомн. о воде: {'да' if user['water_remind'] else 'нет'}\n"
        f"Вечерняя сводка: {'да' if user['evening_summary'] else 'нет'}"
    )
    await cq.message.edit_text(text, reply_markup=kb_back("menu_settings"))
    await cq.answer()

@dp.callback_query(F.data == "settings_style")
async def cb_style(cq: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💝 Подружка", callback_data="style_set_girlfriend")],
        [InlineKeyboardButton(text="🎓 Наставник", callback_data="style_set_mentor")],
        [InlineKeyboardButton(text="💼 Профессионал", callback_data="style_set_pro")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_settings")],
    ])
    await cq.message.edit_text("Выбери стиль общения:", reply_markup=kb)
    await cq.answer()

@dp.callback_query(F.data.startswith("style_set_"))
async def cb_style_set(cq: CallbackQuery):
    style = cq.data.replace("style_set_", "")
    await db.execute("UPDATE users SET style=$1 WHERE user_id=$2", style, cq.from_user.id)
    names = {"girlfriend": "Подружка", "mentor": "Наставник", "pro": "Профессионал"}
    await cq.message.edit_text(f"Стиль изменён на: {names.get(style, style)}", reply_markup=kb_back("menu_settings"))
    await cq.answer()

@dp.callback_query(F.data == "settings_city")
async def cb_city(cq: CallbackQuery, state: FSMContext):
    await cq.message.edit_text("Напиши название своего города:")
    await state.set_state(States.city_input)
    await cq.answer()

@dp.message(States.city_input)
async def city_input(message: Message, state: FSMContext):
    await db.execute("UPDATE users SET city=$1 WHERE user_id=$2", message.text, message.from_user.id)
    await state.clear()
    await message.answer(f"Город изменён на: {message.text}", reply_markup=kb_main())

@dp.callback_query(F.data == "settings_lang")
async def cb_lang(cq: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_set_ru"),
         InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_set_en")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_settings")],
    ])
    await cq.message.edit_text("Выбери язык:", reply_markup=kb)
    await cq.answer()

@dp.callback_query(F.data.startswith("lang_set_"))
async def cb_lang_set(cq: CallbackQuery):
    lang = cq.data.replace("lang_set_", "")
    await db.execute("UPDATE users SET language=$1 WHERE user_id=$2", lang, cq.from_user.id)
    await cq.message.edit_text(f"Язык изменён", reply_markup=kb_back("menu_settings"))
    await cq.answer()

@dp.callback_query(F.data.startswith("toggle_"))
async def cb_toggle(cq: CallbackQuery):
    field_map = {
        "toggle_morning_weather":    "morning_weather",
        "toggle_morning_motivation": "morning_motivation",
        "toggle_water_remind":       "water_remind",
        "toggle_evening_summary":    "evening_summary",
    }
    field = field_map.get(cq.data)
    if not field:
        await cq.answer()
        return
    current = await db.fetchval(f"SELECT {field} FROM users WHERE user_id=$1", cq.from_user.id)
    await db.execute(f"UPDATE users SET {field}=$1 WHERE user_id=$2", not current, cq.from_user.id)
    state_text = "включено" if not current else "выключено"
    await cq.answer(f"{state_text.capitalize()}")
    await cq.message.edit_text("Настройки:", reply_markup=kb_settings())

@dp.callback_query(F.data == "settings_forget")
async def cb_forget(cq: CallbackQuery):
    await db.execute("DELETE FROM user_memory WHERE user_id=$1", cq.from_user.id)
    await db.execute("DELETE FROM conversation_history WHERE user_id=$1", cq.from_user.id)
    await cq.message.edit_text("Я забыла всё о тебе. Начнём сначала!", reply_markup=kb_main())
    await cq.answer()

# ─── Finance ──────────────────────────────────────────────────────────────────
def kb_finance():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Доход", callback_data="finance_income"),
         InlineKeyboardButton(text="➖ Расход", callback_data="finance_expense")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="finance_stats")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_diary")],
    ])

@dp.callback_query(F.data == "diary_finance")
async def cb_finance(cq: CallbackQuery):
    await cq.message.edit_text("Финансы:", reply_markup=kb_finance())
    await cq.answer()

@dp.callback_query(F.data == "finance_income")
async def cb_finance_income(cq: CallbackQuery, state: FSMContext):
    await cq.message.edit_text("Введи сумму и описание дохода (например: 5000 зарплата):")
    await state.set_state(States.finance_add_income)
    await cq.answer()

@dp.callback_query(F.data == "finance_expense")
async def cb_finance_expense(cq: CallbackQuery, state: FSMContext):
    await cq.message.edit_text("Введи сумму и описание расхода (например: 500 кафе):")
    await state.set_state(States.finance_add_expense)
    await cq.answer()

@dp.message(States.finance_add_income)
async def finance_income_input(message: Message, state: FSMContext):
    parts = message.text.split(maxsplit=1)
    try:
        amount = float(parts[0])
        desc = parts[1] if len(parts) > 1 else ""
        await db.execute("INSERT INTO finances(user_id,type,amount,description) VALUES($1,'income',$2,$3)",
                         message.from_user.id, amount, desc)
        await state.clear()
        await message.answer(f"Доход {amount} добавлен!", reply_markup=kb_finance())
    except:
        await message.answer("Не понял. Введи: сумма описание (например: 5000 зарплата)")

@dp.message(States.finance_add_expense)
async def finance_expense_input(message: Message, state: FSMContext):
    parts = message.text.split(maxsplit=1)
    try:
        amount = float(parts[0])
        desc = parts[1] if len(parts) > 1 else ""
        await db.execute("INSERT INTO finances(user_id,type,amount,description) VALUES($1,'expense',$2,$3)",
                         message.from_user.id, amount, desc)
        await state.clear()
        await message.answer(f"Расход {amount} добавлен!", reply_markup=kb_finance())
    except:
        await message.answer("Не понял. Введи: сумма описание (например: 500 кафе)")

@dp.callback_query(F.data == "finance_stats")
async def cb_finance_stats(cq: CallbackQuery):
    uid = cq.from_user.id
    today = datetime.now().date()
    month_start = today.replace(day=1)
    income = await db.fetchval("SELECT COALESCE(SUM(amount),0) FROM finances WHERE user_id=$1 AND type='income' AND DATE(created_at)>=$2", uid, month_start)
    expense = await db.fetchval("SELECT COALESCE(SUM(amount),0) FROM finances WHERE user_id=$1 AND type='expense' AND DATE(created_at)>=$2", uid, month_start)
    balance = income - expense
    rows = await db.fetch("SELECT type,amount,description,created_at FROM finances WHERE user_id=$1 ORDER BY created_at DESC LIMIT 5", uid)
    lines = [f"Финансы за месяц:", f"Доходы: {income}", f"Расходы: {expense}", f"Баланс: {balance}", "", "Последние операции:"]
    for r in rows:
        sign = "+" if r["type"] == "income" else "-"
        lines.append(f"{sign}{r['amount']} {r['description']} ({r['created_at'].strftime('%d.%m')})")
    await cq.message.edit_text("\n".join(lines), reply_markup=kb_finance())
    await cq.answer()

# ─── Sleep ────────────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "diary_sleep")
async def cb_sleep(cq: CallbackQuery, state: FSMContext):
    await cq.message.edit_text("Сколько часов ты спала? (например: 7.5)")
    await state.set_state(States.sleep_input)
    await cq.answer()

@dp.message(States.sleep_input)
async def sleep_input_handler(message: Message, state: FSMContext):
    try:
        hours = float(message.text.replace(",", "."))
        today = datetime.now().date()
        await db.execute("INSERT INTO sleep_log(user_id,hours,log_date) VALUES($1,$2,$3) ON CONFLICT DO NOTHING",
                         message.from_user.id, hours, today)
        await state.clear()
        if hours < 6:
            comment = "Маловато. Постарайся поспать побольше сегодня!"
        elif hours < 8:
            comment = "Неплохо, но 8 часов были бы идеальны."
        else:
            comment = "Отлично! Хороший сон — основа здоровья."
        await message.answer(f"Записала: {hours} ч. {comment}", reply_markup=kb_diary())
    except:
        await message.answer("Введи число, например: 7 или 7.5")

# ─── Water ────────────────────────────────────────────────────────────────────
def kb_water():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="200 мл", callback_data="water_200"),
         InlineKeyboardButton(text="300 мл", callback_data="water_300"),
         InlineKeyboardButton(text="500 мл", callback_data="water_500")],
        [InlineKeyboardButton(text="📊 Сегодня", callback_data="water_stats"),
         InlineKeyboardButton(text="✏️ Своё", callback_data="water_custom")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_diary")],
    ])

@dp.callback_query(F.data == "diary_water")
async def cb_water(cq: CallbackQuery):
    today = datetime.now().date()
    total = await db.fetchval("SELECT COALESCE(SUM(ml),0) FROM water_log WHERE user_id=$1 AND log_date=$2", cq.from_user.id, today)
    await cq.message.edit_text(f"Вода. Выпито сегодня: {total} мл (цель: 2000 мл)", reply_markup=kb_water())
    await cq.answer()

@dp.callback_query(F.data.startswith("water_") & ~F.data.in_({"water_stats", "water_custom"}))
async def cb_water_add(cq: CallbackQuery):
    ml_map = {"water_200": 200, "water_300": 300, "water_500": 500}
    ml = ml_map.get(cq.data, 0)
    if ml:
        today = datetime.now().date()
        await db.execute("INSERT INTO water_log(user_id,ml,log_date) VALUES($1,$2,$3)", cq.from_user.id, ml, today)
        total = await db.fetchval("SELECT COALESCE(SUM(ml),0) FROM water_log WHERE user_id=$1 AND log_date=$2", cq.from_user.id, today)
        await cq.answer(f"Добавлено {ml} мл. Всего: {total} мл")
        await cq.message.edit_text(f"Вода. Выпито сегодня: {total} мл (цель: 2000 мл)", reply_markup=kb_water())

@dp.callback_query(F.data == "water_custom")
async def cb_water_custom(cq: CallbackQuery, state: FSMContext):
    await cq.message.edit_text("Введи количество мл:")
    await state.set_state(States.water_input)
    await cq.answer()

@dp.message(States.water_input)
async def water_input_handler(message: Message, state: FSMContext):
    try:
        ml = int(message.text)
        today = datetime.now().date()
        await db.execute("INSERT INTO water_log(user_id,ml,log_date) VALUES($1,$2,$3)", message.from_user.id, ml, today)
        total = await db.fetchval("SELECT COALESCE(SUM(ml),0) FROM water_log WHERE user_id=$1 AND log_date=$2", message.from_user.id, today)
        await state.clear()
        await message.answer(f"Добавлено {ml} мл. Всего сегодня: {total} мл", reply_markup=kb_diary())
    except:
        await message.answer("Введи число мл, например: 250")

@dp.callback_query(F.data == "water_stats")
async def cb_water_stats(cq: CallbackQuery):
    today = datetime.now().date()
    total = await db.fetchval("SELECT COALESCE(SUM(ml),0) FROM water_log WHERE user_id=$1 AND log_date=$2", cq.from_user.id, today)
    percent = min(int(total / 2000 * 100), 100)
    bar = "█" * (percent // 10) + "░" * (10 - percent // 10)
    await cq.message.edit_text(f"Вода сегодня: {total} мл из 2000 мл\n[{bar}] {percent}%", reply_markup=kb_water())
    await cq.answer()

# ─── Habits ───────────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "diary_habits")
async def cb_habits(cq: CallbackQuery):
    habits = await db.fetch("SELECT * FROM habits WHERE user_id=$1", cq.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for h in habits:
        done = h["last_done"] == datetime.now().date()
        mark = "✅" if done else "⬜"
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"{mark} {h['name']} (🔥{h['streak']})", callback_data=f"habit_toggle_{h['id']}")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="➕ Добавить привычку", callback_data="habit_add")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu_diary")])
    text = "Привычки:" if habits else "У тебя пока нет привычек. Добавь первую!"
    await cq.message.edit_text(text, reply_markup=kb)
    await cq.answer()

@dp.callback_query(F.data.startswith("habit_toggle_"))
async def cb_habit_toggle(cq: CallbackQuery):
    habit_id = int(cq.data.split("_")[2])
    habit = await db.fetchrow("SELECT * FROM habits WHERE id=$1", habit_id)
    today = datetime.now().date()
    if habit["last_done"] == today:
        await cq.answer("Уже отмечено сегодня!")
        return
    new_streak = habit["streak"] + 1
    await db.execute("UPDATE habits SET streak=$1, last_done=$2 WHERE id=$3", new_streak, today, habit_id)
    await cq.answer(f"Отмечено! Стрик: {new_streak} дней 🔥")
    # Refresh
    await cb_habits(cq)

@dp.callback_query(F.data == "habit_add")
async def cb_habit_add(cq: CallbackQuery, state: FSMContext):
    await cq.message.edit_text("Как называется привычка? (например: Зарядка, Чтение, Медитация)")
    await state.set_state(States.habit_add)
    await cq.answer()

@dp.message(States.habit_add)
async def habit_add_handler(message: Message, state: FSMContext):
    await db.execute("INSERT INTO habits(user_id,name) VALUES($1,$2)", message.from_user.id, message.text)
    await state.clear()
    await message.answer(f"Привычка '{message.text}' добавлена!", reply_markup=kb_diary())

# ─── Notes ────────────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "diary_notes")
async def cb_notes(cq: CallbackQuery):
    notes = await db.fetch("SELECT * FROM notes WHERE user_id=$1 ORDER BY created_at DESC LIMIT 10", cq.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить заметку", callback_data="note_add")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_diary")],
    ])
    if notes:
        lines = ["Твои заметки:"]
        for n in notes:
            lines.append(f"- {n['text'][:50]}{'...' if len(n['text']) > 50 else ''}")
        text = "\n".join(lines)
    else:
        text = "Заметок пока нет."
    await cq.message.edit_text(text, reply_markup=kb)
    await cq.answer()

@dp.callback_query(F.data == "note_add")
async def cb_note_add(cq: CallbackQuery, state: FSMContext):
    await cq.message.edit_text("Напиши заметку:")
    await state.set_state(States.note_add)
    await cq.answer()

@dp.message(States.note_add)
async def note_add_handler(message: Message, state: FSMContext):
    await db.execute("INSERT INTO notes(user_id,text) VALUES($1,$2)", message.from_user.id, message.text)
    await state.clear()
    await message.answer("Заметка сохранена!", reply_markup=kb_diary())

# ─── Shopping ─────────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "diary_shopping")
async def cb_shopping(cq: CallbackQuery):
    items = await db.fetch("SELECT * FROM shopping WHERE user_id=$1 AND is_done=FALSE ORDER BY created_at", cq.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for item in items:
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=f"✅ {item['item']}", callback_data=f"shop_done_{item['id']}")
        ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="➕ Добавить", callback_data="shop_add")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu_diary")])
    text = "Список покупок:" if items else "Список покупок пуст."
    await cq.message.edit_text(text, reply_markup=kb)
    await cq.answer()

@dp.callback_query(F.data.startswith("shop_done_"))
async def cb_shop_done(cq: CallbackQuery):
    item_id = int(cq.data.split("_")[2])
    await db.execute("UPDATE shopping SET is_done=TRUE WHERE id=$1", item_id)
    await cq.answer("Куплено!")
    await cb_shopping(cq)

@dp.callback_query(F.data == "shop_add")
async def cb_shop_add(cq: CallbackQuery, state: FSMContext):
    await cq.message.edit_text("Что добавить в список?")
    await state.set_state(States.shopping_add)
    await cq.answer()

@dp.message(States.shopping_add)
async def shopping_add_handler(message: Message, state: FSMContext):
    items = [i.strip() for i in message.text.replace(",", "\n").split("\n") if i.strip()]
    for item in items:
        await db.execute("INSERT INTO shopping(user_id,item) VALUES($1,$2)", message.from_user.id, item)
    await state.clear()
    await message.answer(f"Добавлено: {', '.join(items)}", reply_markup=kb_diary())

# ─── Recipes ──────────────────────────────────────────────────────────────────
def kb_recipes():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 Мои рецепты", callback_data="recipes_mine")],
        [InlineKeyboardButton(text="🎲 Рандомный рецепт", callback_data="recipes_random")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_diary")],
    ])

def kb_recipe_categories():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍲 Супы", callback_data="recipe_cat_soup"),
         InlineKeyboardButton(text="🍖 Второе", callback_data="recipe_cat_main")],
        [InlineKeyboardButton(text="🥗 Салаты", callback_data="recipe_cat_salad"),
         InlineKeyboardButton(text="🍰 Десерты", callback_data="recipe_cat_dessert")],
        [InlineKeyboardButton(text="🌟 Тренды", callback_data="recipe_cat_trend")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="diary_recipes")],
    ])

@dp.callback_query(F.data == "diary_recipes")
async def cb_recipes(cq: CallbackQuery):
    await cq.message.edit_text("Рецепты:", reply_markup=kb_recipes())
    await cq.answer()

@dp.callback_query(F.data == "recipes_mine")
async def cb_recipes_mine(cq: CallbackQuery):
    recipes = await db.fetch("SELECT * FROM recipes WHERE user_id=$1 ORDER BY created_at DESC", cq.from_user.id)
    if not recipes:
        await cq.message.edit_text("У тебя пока нет сохранённых рецептов.", reply_markup=kb_back("diary_recipes"))
        await cq.answer()
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for r in recipes:
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=f"🍽 {r['title']}", callback_data=f"recipe_view_{r['id']}"),
            InlineKeyboardButton(text="🗑", callback_data=f"recipe_del_{r['id']}"),
        ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="diary_recipes")])
    await cq.message.edit_text("Мои рецепты:", reply_markup=kb)
    await cq.answer()

@dp.callback_query(F.data.startswith("recipe_view_"))
async def cb_recipe_view(cq: CallbackQuery):
    rid = int(cq.data.split("_")[2])
    recipe = await db.fetchrow("SELECT * FROM recipes WHERE id=$1", rid)
    if recipe:
        await cq.message.edit_text(f"{recipe['title']}\n\n{recipe['content']}", reply_markup=kb_back("recipes_mine"))
    await cq.answer()

@dp.callback_query(F.data.startswith("recipe_del_"))
async def cb_recipe_del(cq: CallbackQuery):
    rid = int(cq.data.split("_")[2])
    await db.execute("DELETE FROM recipes WHERE id=$1 AND user_id=$2", rid, cq.from_user.id)
    await cq.answer("Рецепт удалён")
    await cb_recipes_mine(cq)

@dp.callback_query(F.data == "recipes_random")
async def cb_recipes_random(cq: CallbackQuery):
    await cq.message.edit_text("Выбери категорию:", reply_markup=kb_recipe_categories())
    await cq.answer()

@dp.callback_query(F.data.startswith("recipe_cat_"))
async def cb_recipe_category(cq: CallbackQuery):
    cat_map = {
        "recipe_cat_soup":    ("суп", "горячий суп"),
        "recipe_cat_main":    ("второе блюдо", "основное блюдо"),
        "recipe_cat_salad":   ("салат", "свежий салат"),
        "recipe_cat_dessert": ("десерт", "сладкий десерт"),
        "recipe_cat_trend":   ("трендовое блюдо 2024 года", "модное блюдо"),
    }
    cat_key, cat_label = cat_map.get(cq.data, ("блюдо", "блюдо"))
    seed = random.randint(1, 9999)
    await cq.message.edit_text("Готовлю рецепт...")
    prompt = f"Придумай рецепт {cat_key} (вариант #{seed}). Напиши: название, ингредиенты, шаги приготовления. Без звёздочек и Markdown."
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{OPENAI_BASE}chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
                json={"model": MODEL, "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 500, "temperature": 1.0},
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                data = await resp.json()
                recipe_text = data["choices"][0]["message"]["content"].strip()
                recipe_text = recipe_text.replace("**", "").replace("*", "").replace("`", "")
    except Exception as e:
        recipe_text = "Не удалось загрузить рецепт. Попробуй ещё раз!"

    # Store temp recipe in state
    title_line = recipe_text.split("\n")[0][:60]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💾 Сохранить", callback_data=f"recipe_save_temp"),
         InlineKeyboardButton(text="❌ Не нужно", callback_data="recipe_skip")],
        [InlineKeyboardButton(text="🔄 Ещё рецепт", callback_data=cq.data),
         InlineKeyboardButton(text="◀️ Назад", callback_data="recipes_random")],
    ])
    # Save temp to DB with temp flag
    temp_id = await db.fetchval(
        "INSERT INTO recipes(user_id, title, content) VALUES($1,$2,$3) RETURNING id",
        cq.from_user.id, f"[TEMP] {title_line}", recipe_text
    )
    await cq.message.edit_text(recipe_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💾 Сохранить", callback_data=f"recipe_confirm_{temp_id}"),
         InlineKeyboardButton(text="❌ Не нужно", callback_data=f"recipe_discard_{temp_id}")],
        [InlineKeyboardButton(text="🔄 Ещё рецепт", callback_data=cq.data),
         InlineKeyboardButton(text="◀️ Назад", callback_data="recipes_random")],
    ]))
    await cq.answer()

@dp.callback_query(F.data.startswith("recipe_confirm_"))
async def cb_recipe_confirm(cq: CallbackQuery):
    rid = int(cq.data.split("_")[2])
    # Remove [TEMP] prefix
    recipe = await db.fetchrow("SELECT * FROM recipes WHERE id=$1", rid)
    if recipe:
        new_title = recipe["title"].replace("[TEMP] ", "")
        await db.execute("UPDATE recipes SET title=$1 WHERE id=$2", new_title, rid)
    await cq.answer("Рецепт сохранён!")
    await cq.message.edit_reply_markup(reply_markup=kb_back("diary_recipes"))

@dp.callback_query(F.data.startswith("recipe_discard_"))
async def cb_recipe_discard(cq: CallbackQuery):
    rid = int(cq.data.split("_")[2])
    await db.execute("DELETE FROM recipes WHERE id=$1 AND user_id=$2", rid, cq.from_user.id)
    await cq.answer("Рецепт не сохранён")
    await cq.message.edit_reply_markup(reply_markup=kb_back("diary_recipes"))

@dp.callback_query(F.data == "recipe_skip")
async def cb_recipe_skip(cq: CallbackQuery):
    await cq.answer("Хорошо!")
    await cq.message.edit_reply_markup(reply_markup=None)

# ─── Watch list ───────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "diary_watch")
async def cb_watch(cq: CallbackQuery):
    items = await db.fetch("SELECT * FROM watch_list WHERE user_id=$1 AND is_watched=FALSE ORDER BY created_at DESC", cq.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for item in items:
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=f"🎬 {item['title']}", callback_data=f"watch_done_{item['id']}"),
        ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="➕ Добавить", callback_data="watch_add")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu_diary")])
    text = "Что посмотреть:" if items else "Список пуст. Добавь что-нибудь интересное!"
    await cq.message.edit_text(text, reply_markup=kb)
    await cq.answer()

@dp.callback_query(F.data == "watch_add")
async def cb_watch_add(cq: CallbackQuery, state: FSMContext):
    await cq.message.edit_text("Что добавить в список? (название фильма/сериала)")
    await state.set_state(States.watch_add)
    await cq.answer()

@dp.message(States.watch_add)
async def watch_add_handler(message: Message, state: FSMContext):
    await db.execute("INSERT INTO watch_list(user_id,title) VALUES($1,$2)", message.from_user.id, message.text)
    await state.clear()
    await message.answer(f"Добавлено: {message.text}", reply_markup=kb_diary())

@dp.callback_query(F.data.startswith("watch_done_"))
async def cb_watch_done(cq: CallbackQuery):
    item_id = int(cq.data.split("_")[2])
    await db.execute("UPDATE watch_list SET is_watched=TRUE WHERE id=$1", item_id)
    await cq.answer("Отмечено как просмотренное!")
    await cb_watch(cq)

# ─── Planner ──────────────────────────────────────────────────────────────────
WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

def kb_planner():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить занятие", callback_data="planner_add")],
        [InlineKeyboardButton(text="📋 Расписание", callback_data="planner_view")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_diary")],
    ])

@dp.callback_query(F.data == "diary_planner")
async def cb_planner(cq: CallbackQuery):
    await cq.message.edit_text("Планер — еженедельные занятия:", reply_markup=kb_planner())
    await cq.answer()

@dp.callback_query(F.data == "planner_view")
async def cb_planner_view(cq: CallbackQuery):
    events = await db.fetch("SELECT * FROM planner WHERE user_id=$1 ORDER BY weekday, time_str", cq.from_user.id)
    if not events:
        await cq.message.edit_text("Расписание пусто.", reply_markup=kb_planner())
        await cq.answer()
        return
    lines = ["Твоё расписание:"]
    current_day = -1
    for e in events:
        if e["weekday"] != current_day:
            lines.append(f"\n{WEEKDAYS[e['weekday']]}:")
            current_day = e["weekday"]
        lines.append(f"  {e['time_str']} — {e['title']}")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить", callback_data="planner_delete_menu")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="diary_planner")],
    ])
    await cq.message.edit_text("\n".join(lines), reply_markup=kb)
    await cq.answer()

@dp.callback_query(F.data == "planner_add")
async def cb_planner_add(cq: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=day, callback_data=f"planner_day_{i}")] for i, day in enumerate(WEEKDAYS)
    ])
    await cq.message.edit_text("Выбери день:", reply_markup=kb)
    await state.set_state(States.planner_day)
    await cq.answer()

@dp.callback_query(F.data.startswith("planner_day_"), States.planner_day)
async def cb_planner_day(cq: CallbackQuery, state: FSMContext):
    day_idx = int(cq.data.split("_")[2])
    await state.update_data(weekday=day_idx)
    await cq.message.edit_text(f"День: {WEEKDAYS[day_idx]}\nВведи время (например: 17:00):")
    await state.set_state(States.planner_time)
    await cq.answer()

@dp.message(States.planner_time)
async def planner_time_handler(message: Message, state: FSMContext):
    await state.update_data(time_str=message.text)
    await message.answer("Введи название занятия:")
    await state.set_state(States.planner_title)

@dp.message(States.planner_title)
async def planner_title_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    await db.execute(
        "INSERT INTO planner(user_id, title, weekday, time_str) VALUES($1,$2,$3,$4)",
        message.from_user.id, message.text, data["weekday"], data["time_str"]
    )
    await state.clear()
    await message.answer(
        f"Добавлено: {WEEKDAYS[data['weekday']]} в {data['time_str']} — {message.text}",
        reply_markup=kb_planner()
    )

@dp.callback_query(F.data == "planner_delete_menu")
async def cb_planner_delete_menu(cq: CallbackQuery):
    events = await db.fetch("SELECT * FROM planner WHERE user_id=$1 ORDER BY weekday, time_str", cq.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for e in events:
        kb.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"🗑 {WEEKDAYS[e['weekday']]} {e['time_str']} — {e['title']}",
                callback_data=f"planner_del_{e['id']}"
            )
        ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="planner_view")])
    await cq.message.edit_text("Выбери что удалить:", reply_markup=kb)
    await cq.answer()

@dp.callback_query(F.data.startswith("planner_del_"))
async def cb_planner_del(cq: CallbackQuery):
    eid = int(cq.data.split("_")[2])
    await db.execute("DELETE FROM planner WHERE id=$1 AND user_id=$2", eid, cq.from_user.id)
    await cq.answer("Удалено!")
    await cb_planner_view(cq)

@dp.callback_query(F.data == "planner_quick_add")
async def cb_planner_quick_add(cq: CallbackQuery, state: FSMContext):
    await cq.message.edit_text("Отлично! Выбери день:")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=day, callback_data=f"planner_day_{i}")] for i, day in enumerate(WEEKDAYS)
    ])
    await cq.message.edit_text("Выбери день:", reply_markup=kb)
    await state.set_state(States.planner_day)
    await cq.answer()

@dp.callback_query(F.data == "planner_skip")
async def cb_planner_skip(cq: CallbackQuery):
    await cq.answer("Хорошо!")
    await cq.message.edit_reply_markup(reply_markup=None)

# ─── Health ───────────────────────────────────────────────────────────────────
def kb_health():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌸 Цикл", callback_data="health_cycle"),
         InlineKeyboardButton(text="💊 Таблетки", callback_data="health_pills")],
        [InlineKeyboardButton(text="😰 Стресс", callback_data="health_stress")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_diary")],
    ])

# Health is accessible from diary via callback
@dp.callback_query(F.data == "diary_health")
async def cb_health(cq: CallbackQuery):
    await cq.message.edit_text("Здоровье:", reply_markup=kb_health())
    await cq.answer()

# Cycle
@dp.callback_query(F.data == "health_cycle")
async def cb_cycle(cq: CallbackQuery):
    cycle = await db.fetchrow("SELECT * FROM health_cycle WHERE user_id=$1 ORDER BY created_at DESC LIMIT 1", cq.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Установить дату цикла", callback_data="cycle_set")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="diary_health")],
    ])
    if cycle:
        start = cycle["start_date"]
        length = cycle["cycle_days"]
        next_cycle = start + timedelta(days=length)
        days_left = (next_cycle - datetime.now().date()).days
        text = (
            f"Цикл:\nНачало: {start.strftime('%d.%m.%Y')}\n"
            f"Длина цикла: {length} дней\n"
            f"Следующий: {next_cycle.strftime('%d.%m.%Y')} (через {days_left} дн.)"
        )
    else:
        text = "Данных о цикле нет. Установи дату начала последнего цикла."
    await cq.message.edit_text(text, reply_markup=kb)
    await cq.answer()

@dp.callback_query(F.data == "cycle_set")
async def cb_cycle_set(cq: CallbackQuery, state: FSMContext):
    await cq.message.edit_text("Введи дату начала последнего цикла (ДД.ММ.ГГГГ):")
    await state.set_state(States.cycle_start_date)
    await cq.answer()

@dp.message(States.cycle_start_date)
async def cycle_date_handler(message: Message, state: FSMContext):
    try:
        date = datetime.strptime(message.text.strip(), "%d.%m.%Y").date()
        await state.update_data(start_date=date)
        await message.answer("Длина цикла в днях (обычно 28):")
        await state.set_state(States.cycle_length)
    except:
        await message.answer("Неверный формат. Введи: ДД.ММ.ГГГГ")

@dp.message(States.cycle_length)
async def cycle_length_handler(message: Message, state: FSMContext):
    try:
        length = int(message.text.strip())
        data = await state.get_data()
        await db.execute(
            "INSERT INTO health_cycle(user_id, start_date, cycle_days) VALUES($1,$2,$3) ON CONFLICT DO NOTHING",
            message.from_user.id, data["start_date"], length
        )
        await state.clear()
        await message.answer("Цикл сохранён! Напомню за 3 дня до следующего.", reply_markup=kb_health())
    except:
        await message.answer("Введи число дней, например: 28")

# Pills
@dp.callback_query(F.data == "health_pills")
async def cb_pills(cq: CallbackQuery):
    pills = await db.fetch("SELECT * FROM pills WHERE user_id=$1 AND is_active=TRUE", cq.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for p in pills:
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=f"💊 {p['name']} в {p['remind_time']}", callback_data=f"pill_del_{p['id']}")
        ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="➕ Добавить таблетку", callback_data="pill_add")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="diary_health")])
    text = "Таблетки (нажми чтобы удалить):" if pills else "Таблеток нет. Добавь первую!"
    await cq.message.edit_text(text, reply_markup=kb)
    await cq.answer()

@dp.callback_query(F.data == "pill_add")
async def cb_pill_add(cq: CallbackQuery, state: FSMContext):
    await cq.message.edit_text("Название таблетки:")
    await state.set_state(States.pill_name)
    await cq.answer()

@dp.message(States.pill_name)
async def pill_name_handler(message: Message, state: FSMContext):
    await state.update_data(pill_name=message.text)
    await message.answer("Время напоминания (например: 09:00):")
    await state.set_state(States.pill_time)

@dp.message(States.pill_time)
async def pill_time_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    await db.execute(
        "INSERT INTO pills(user_id, name, remind_time) VALUES($1,$2,$3)",
        message.from_user.id, data["pill_name"], message.text.strip()
    )
    await state.clear()
    await message.answer(f"Таблетка '{data['pill_name']}' добавлена. Буду напоминать в {message.text}.", reply_markup=kb_health())

@dp.callback_query(F.data.startswith("pill_del_"))
async def cb_pill_del(cq: CallbackQuery):
    pid = int(cq.data.split("_")[2])
    await db.execute("UPDATE pills SET is_active=FALSE WHERE id=$1", pid)
    await cq.answer("Удалено!")
    await cb_pills(cq)

@dp.callback_query(F.data.startswith("pill_taken_"))
async def cb_pill_taken(cq: CallbackQuery):
    name = cq.data.replace("pill_taken_", "")
    await cq.answer(f"Хорошо, {name} отмечено!")
    await cq.message.edit_reply_markup(reply_markup=None)

@dp.callback_query(F.data.startswith("pill_later_"))
async def cb_pill_later(cq: CallbackQuery):
    name = cq.data.replace("pill_later_", "")
    uid = cq.from_user.id
    remind_at = datetime.now() + timedelta(minutes=30)
    await schedule_reminder(uid, f"Напоминание: прими таблетку {name}", remind_at)
    await cq.answer(f"Напомню через 30 минут!")
    await cq.message.edit_reply_markup(reply_markup=None)

# Stress
@dp.callback_query(F.data == "health_stress")
async def cb_stress(cq: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=str(i), callback_data=f"stress_{i}") for i in range(1, 6)],
        [InlineKeyboardButton(text=str(i), callback_data=f"stress_{i}") for i in range(6, 11)],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="diary_health")],
    ])
    await cq.message.edit_text("Оцени уровень стресса сегодня (1 — спокойно, 10 — очень стрессово):", reply_markup=kb)
    await cq.answer()

@dp.callback_query(F.data.startswith("stress_"))
async def cb_stress_score(cq: CallbackQuery):
    score = int(cq.data.split("_")[1])
    today = datetime.now().date()
    await db.execute(
        "INSERT INTO stress_log(user_id, score, log_date) VALUES($1,$2,$3)",
        cq.from_user.id, score, today
    )
    tips = {
        range(1, 4):  "Отлично! Ты в отличной форме.",
        range(4, 7):  "Умеренный стресс — попробуй сделать перерыв и подышать.",
        range(7, 11): "Высокий стресс. Рекомендую: глубокое дыхание, прогулка, отдых.",
    }
    tip = "Записала."
    for r, t in tips.items():
        if score in r:
            tip = t
            break
    await cq.message.edit_text(f"Стресс: {score}/10. {tip}", reply_markup=kb_back("diary_health"))
    await cq.answer()

# ─── Goals ────────────────────────────────────────────────────────────────────
def kb_goals():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить цель", callback_data="goal_add")],
        [InlineKeyboardButton(text="📋 Мои цели", callback_data="goals_list")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_diary")],
    ])

@dp.callback_query(F.data == "diary_goals")
async def cb_goals(cq: CallbackQuery):
    await cq.message.edit_text("Цели:", reply_markup=kb_goals())
    await cq.answer()

@dp.callback_query(F.data == "goals_list")
async def cb_goals_list(cq: CallbackQuery):
    goals = await db.fetch("SELECT * FROM goals WHERE user_id=$1 AND is_done=FALSE ORDER BY created_at DESC", cq.from_user.id)
    if not goals:
        await cq.message.edit_text("Целей пока нет. Добавь первую!", reply_markup=kb_goals())
        await cq.answer()
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for g in goals:
        bar = "█" * (g["progress"] // 10) + "░" * (10 - g["progress"] // 10)
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=f"{g['title']} [{bar}] {g['progress']}%", callback_data=f"goal_update_{g['id']}")
        ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="diary_goals")])
    await cq.message.edit_text("Мои цели:", reply_markup=kb)
    await cq.answer()

@dp.callback_query(F.data == "goal_add")
async def cb_goal_add(cq: CallbackQuery, state: FSMContext):
    await cq.message.edit_text("Название цели:")
    await state.set_state(States.goal_title)
    await cq.answer()

@dp.message(States.goal_title)
async def goal_title_handler(message: Message, state: FSMContext):
    await state.update_data(goal_title=message.text)
    await message.answer("Описание цели (или /skip):")
    await state.set_state(States.goal_description)

@dp.message(States.goal_description)
async def goal_description_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    desc = "" if message.text == "/skip" else message.text
    await db.execute(
        "INSERT INTO goals(user_id, title, description) VALUES($1,$2,$3)",
        message.from_user.id, data["goal_title"], desc
    )
    await state.clear()
    await message.answer(f"Цель '{data['goal_title']}' добавлена! Буду периодически спрашивать о прогрессе.", reply_markup=kb_goals())

@dp.callback_query(F.data.startswith("goal_update_"))
async def cb_goal_update(cq: CallbackQuery, state: FSMContext):
    gid = int(cq.data.split("_")[2])
    await state.update_data(goal_id=gid)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{p}%", callback_data=f"goal_progress_{gid}_{p}") for p in [25, 50, 75]],
        [InlineKeyboardButton(text="100% (Выполнено!)", callback_data=f"goal_progress_{gid}_100")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="goals_list")],
    ])
    await cq.message.edit_text("Укажи прогресс:", reply_markup=kb)
    await cq.answer()

@dp.callback_query(F.data.startswith("goal_progress_"))
async def cb_goal_progress(cq: CallbackQuery):
    parts = cq.data.split("_")
    gid, progress = int(parts[2]), int(parts[3])
    is_done = progress == 100
    await db.execute("UPDATE goals SET progress=$1, is_done=$2 WHERE id=$3", progress, is_done, gid)
    if is_done:
        await cq.message.edit_text("Поздравляю! Цель достигнута! Ты молодец!", reply_markup=kb_goals())
    else:
        await cq.message.edit_text(f"Прогресс обновлён: {progress}%! Продолжай в том же духе!", reply_markup=kb_goals())
    await cq.answer()

# ─── Voice messages ───────────────────────────────────────────────────────────
@dp.message(F.voice)
async def handle_voice(message: Message):
    await ensure_user(message.from_user.id)
    if not ASSEMBLY_KEY:
        await message.answer("Голосовые сообщения не настроены.")
        return
    file = await bot.get_file(message.voice.file_id)
    file_bytes = await bot.download_file(file.file_path)
    text = await transcribe_voice(file_bytes.read())
    if not text:
        await message.answer("Не смогла распознать голосовое сообщение. Попробуй ещё раз.")
        return
    await message.answer(f"Ты сказала: {text}")
    reply = await ai_chat(message.from_user.id, text)
    await message.answer(reply)
    if message.from_user.id != ADMIN_ID:
        await bot.send_message(ADMIN_ID, f"[Голос от {message.from_user.id}]\n{text}\n---\n{reply}")

# ─── Photo analysis ───────────────────────────────────────────────────────────
@dp.message(F.photo)
async def handle_photo(message: Message):
    await ensure_user(message.from_user.id)
    caption = message.caption or "Опиши что на этом фото"
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    file_bytes = await bot.download_file(file.file_path)
    b64 = base64.b64encode(file_bytes.read()).decode()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{OPENAI_BASE}chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
                json={
                    "model": MODEL,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                            {"type": "text", "text": caption}
                        ]
                    }],
                    "max_tokens": 500
                },
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                data = await resp.json()
                reply = data["choices"][0]["message"]["content"].strip()
                reply = reply.replace("**", "").replace("*", "").replace("`", "")
    except Exception as e:
        reply = "Не могу проанализировать фото."
    await message.answer(reply)

# ─── Main text handler ────────────────────────────────────────────────────────
WEATHER_KEYWORDS = ["погода", "weather", "температура", "дождь", "снег", "солнце", "облачно", "ветер"]

@dp.message(F.text)
async def handle_text(message: Message, state: FSMContext):
    # Don't handle commands
    if message.text.startswith("/"):
        return

    await ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    user = await get_user(message.from_user.id)
    text_lower = message.text.lower()

    # Weather shortcut
    if any(kw in text_lower for kw in WEATHER_KEYWORDS):
        city = user["city"] if user else "Москва"
        mode = "now"
        if "завтра" in text_lower or "tomorrow" in text_lower:
            mode = "hourly"
        elif "неделю" in text_lower or "week" in text_lower:
            mode = "week"
        weather = await get_weather(city, mode)
        await message.answer(weather)
        return

    # Image generation
    if any(kw in text_lower for kw in ["нарисуй", "сгенерируй картинку", "создай изображение", "draw", "generate image"]):
        await message.answer("Генерирую изображение...")
        img_bytes = await generate_image(message.text)
        if img_bytes:
            await message.answer_photo(BufferedInputFile(img_bytes, filename="image.png"))
        else:
            await message.answer("Не удалось создать изображение.")
        return

    # Reminder shortcut
    if any(kw in text_lower for kw in ["напомни", "remind me", "напоминание"]):
        remind_at = await parse_reminder_time(message.text)
        if remind_at:
            clean_text = message.text
            await schedule_reminder(message.from_user.id, clean_text, remind_at)
            await message.answer(f"Напомню: {clean_text}\nВремя: {remind_at.strftime('%d.%m.%Y в %H:%M')}")
            return

    # General AI response
    reply = await ai_chat(message.from_user.id, message.text)
    await message.answer(reply)

    # Admin copy
    if message.from_user.id != ADMIN_ID:
        await bot.send_message(
            ADMIN_ID,
            f"[{message.from_user.id} @{message.from_user.username or 'none'}]\n{message.text}\n---\n{reply}"
        )

# ─── Startup & main ───────────────────────────────────────────────────────────
async def on_startup():
    await init_db()
    await restore_reminders()
    # Start background tasks
    asyncio.create_task(morning_routine())
    asyncio.create_task(evening_summary())
    asyncio.create_task(pill_daily_checker())
    asyncio.create_task(goal_progress_checker())
    asyncio.create_task(cycle_reminder())
    log.info("Sofia bot started!")

async def main():
    dp.startup.register(on_startup)
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
