import logging
import re
import os
from datetime import datetime, time, timedelta
import pytz
import asyncpg
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
from groq import Groq

TELEGRAM_TOKEN = "8988150778:AAE0U74b8WTdKf5OtmbiMFeSDoDm2BGGKzI"
GROQ_API_KEY = "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"
ADMIN_ID = 944447597
DATABASE_URL = os.environ.get("DATABASE_URL")

logging.basicConfig(level=logging.INFO)
groq_client = Groq(api_key=GROQ_API_KEY)

ASK_NAME, ASK_TIMEZONE, ASK_MORNING_PLAN, ASK_MORNING_TIME, ASK_REMINDERS = range(5)

SYSTEM_PROMPT = """Ты — София, личный ассистент. Общаешься вежливо и профессионально. Обращаешься на "Вы". Деловой стиль, но живой. Умеренно используй эмодзи.

Правила оформления:
— Списки нумеруй: 1. 2. 3.
— Планы пиши по времени в столбик
— Пиши коротко и по существу

Формат плана дня:
🕘 09:00 — задача
🕙 10:00 — задача

Когда пользователь просит напомнить — подтверди кратко что напоминание установлено.
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
        # Оставляем только последние 20 сообщений
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

async def rephrase_reminder(text):
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "Перефразируй напоминание от лица ассистента — коротко, без 'мне', без 'напомни', без времени, без 'через X минут'. Только суть. Например: 'через 5 минут мне надо сходить в душ' -> 'Сходить в душ'. Отвечай только перефразированным текстом."
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
        text=f"⏰ {name}, напоминаю!\n\n" + essence
    )

async def send_morning_plan(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    user = await get_user(user_id)
    if not user:
        return
    name = user["name"]
    reminders = await get_reminders(user_id)
    if reminders:
        plan_text = "\n".join([f"🕐 {r['time']} — {r['text']}" for r in sorted(reminders, key=lambda x: x["time"])])
    else:
        plan_text = "На сегодня задачи не добавлены."
    await context.bot.send_message(
        chat_id=user_id,
        text=f"Доброе утро, {name}! ☀️\n\nВаш план на сегодня:\n\n{plan_text}"
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
        "Добрый день! Я — София, ваш личный ассистент 🌸\n\n"
        "Вот что я умею:\n\n"
        "1. 📋 Утренний план\n"
        "Каждое утро присылаю структурированный список задач на день\n\n"
        "2. ⏰ Напоминания\n"
        "«Напомни в 15:00» или «напомни через 30 минут» — пришлю точно в срок\n\n"
        "3. 🗓 Контроль расписания\n"
        "Слежу за накладками — предупрежу если время занято\n\n"
        "4. 🧠 Запоминаю всё\n"
        "Помню весь наш диалог и ваши предпочтения\n\n"
        "5. 💬 Всегда на связи\n"
        "Пишите в любое время — отвечу быстро\n\n"
        "Давайте познакомимся поближе — как вас зовут? )"
    )
    await notify_admin(context, user_name, username, f"Новый пользователь (ID: {user_id})", "Начал онбординг")
    return ASK_NAME

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    name = update.message.text.strip()
    username = update.effective_user.username or "нет username"
    await save_user(user_id, name=name, username=username)
    await notify_admin(context, update.effective_user.first_name or "?", username, f"Представился: {name}", "Онбординг")
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
    keyboard = [["✅ Да, каждое утро", "❌ Нет, не нужно"]]
    await update.message.reply_text(
        "Хотите, чтобы я каждое утро присылала план дня? 📋\n\n"
        "Вы заранее добавляете задачи — я пришлю красивый список с утра )",
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
    summary += "\n\nМожете начинать! Чем могу помочь? )"
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

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)
    if not user or not user["onboarded"]:
        await update.message.reply_text("Напишите /start чтобы начать 🌸")
        return
    user_text = update.message.text
    user_name = update.effective_user.first_name or "Пользователь"
    username = update.effective_user.username or "нет username"
    name = user["name"]
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

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM history WHERE user_id = $1", user_id)
    await update.message.reply_text("История очищена 🌸")

async def post_init(application):
    await init_db()

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_TIMEZONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_timezone)],
            ASK_MORNING_PLAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_morning_plan)],
            ASK_MORNING_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_morning_time)],
            ASK_REMINDERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, finish_onboarding)],
        },
        fallbacks=[CommandHandler("start", start)]
    )
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("announce", announce))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🌸 София запущена с базой данных!")
    app.run_polling()
