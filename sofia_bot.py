import logging
import re
import os
import tempfile
from datetime import datetime, time, timedelta
import pytz
import asyncpg
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
from groq import Groq

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
ADMIN_ID = 944447597
DATABASE_URL = os.environ.get("DATABASE_URL")

logging.basicConfig(level=logging.INFO)
groq_client = Groq(api_key=GROQ_API_KEY)

ASK_NAME, ASK_TIMEZONE, ASK_MORNING_PLAN, ASK_MORNING_TIME, ASK_REMINDERS = range(5)

SYSTEM_PROMPT = """Ты — София, личный ассистент, стратег и умный помощник. Общаешься вежливо и профессионально, обращаешься на "Вы". Деловой стиль, но живой. Умеренно используй эмодзи.

Что ты умеешь:

1. Планирование — составляешь план на день, завтра, неделю, месяц по запросу. Пишешь структурированно, по времени, в столбик.

2. История — помнишь всё что пользователь делал и говорил. Отвечаешь на вопросы типа "что я делала вчера" или "что у меня запланировано на пятницу".

3. Стратегия целей — когда человек называет цель, действуй строго по шагам:
   Шаг 1 — уточни текущий уровень или ситуацию (если нужно) и дедлайн
   Шаг 2 — рассчитай сколько часов всего нужно на достижение цели
   Шаг 3 — раздели на количество дней до дедлайна — получи часы в день
   Шаг 4 — спроси в какое время удобно заниматься
   Шаг 5 — составь конкретное расписание и добавь повторяющееся напоминание
   Шаг 6 — через 7 дней напомни спросить как идут дела и скорректируй план если нужно

4. Напоминания — присылаешь точно в срок. Следишь за конфликтами в расписании.

5. Умный помощник — отвечаешь на любые вопросы как искусственный интеллект.

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
                onboarded BOOLEAN DEFAULT FALSE
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
