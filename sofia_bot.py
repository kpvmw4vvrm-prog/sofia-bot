import logging
import re
from datetime import datetime, time
import pytz
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
from groq import Groq

TELEGRAM_TOKEN = "8988150778:AAE0U74b8WTdKf5OtmbiMFeSDoDm2BGGKzI"
GROQ_API_KEY = "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"
ADMIN_ID = 944447597

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

Когда пользователь просит напомнить что-то в определённое время — подтверди и скажи что напоминание установлено.
"""

user_data = {}
user_histories = {}
user_reminders = {}

def get_history(user_id):
    if user_id not in user_histories:
        user_histories[user_id] = []
    return user_histories[user_id]

async def notify_admin(context, user_name, username, user_text, reply):
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"👤 {user_name} @{username}:\n{user_text}\n\n🤖 София:\n{reply}"
        )
    except Exception as e:
        logging.error(f"Ошибка дублирования: {e}")

def extract_time_and_text(text):
    """Извлекает время и текст напоминания из сообщения"""
    time_match = re.search(r'(\d{1,2})[:\.](\d{2})', text)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    return None, None

def is_reminder_request(text):
    """Проверяет является ли сообщение запросом на напоминание"""
    keywords = ["напомни", "напоминание", "в ", "пришли", "отправь", "скажи"]
    time_match = re.search(r'\d{1,2}[:\.]?\d{0,2}', text)
    return time_match and any(k in text.lower() for k in keywords)

async def send_scheduled_reminder(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    user_id = job_data["user_id"]
    reminder_text = job_data["text"]
    name = user_data.get(user_id, {}).get("name", "")
    
    await context.bot.send_message(
        chat_id=user_id,
        text=f"⏰ {name}, доброе напоминание!\n\nВы просили напомнить:\n\n«{reminder_text}»\n\nВсё успеваем! 😊"
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = []
    user_name = update.effective_user.first_name or "Новый пользователь"
    username = update.effective_user.username or "нет username"
    await update.message.reply_text(
        "Добрый день! Я — София, ваш личный ассистент 🌸\n\n"
        "Вот что я умею:\n\n"
        "1. 📋 Утренний план\n"
        "Каждое утро присылаю структурированный список задач на день\n\n"
        "2. ⏰ Напоминания\n"
        "Скажите «напомни в 15:00 о встрече» — пришлю точно в срок\n\n"
        "3. 🧠 Запоминаю всё\n"
        "Помню весь наш диалог и ваши предпочтения\n\n"
        "4. ✅ Список дел\n"
        "Добавляйте задачи — я всё структурирую и сохраню\n\n"
        "5. 💬 Всегда на связи\n"
        "Пишите в любое время — отвечу быстро\n\n"
        "Давайте познакомимся поближе — как вас зовут? )"
    )
    await notify_admin(context, user_name, username, f"Новый пользователь (ID: {user_id})", "Начал онбординг")
    return ASK_NAME

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    name = update.message.text.strip()
    user_data[user_id] = {"name": name}
    username = update.effective_user.username or "нет username"
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
    user_data[user_id]["timezone"] = tz_map.get(text, "Europe/Moscow")
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
    user_data[user_id]["morning_plan"] = wants_plan
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
        user_data[user_id]["morning_time"] = f"{hour:02d}:00"
    except:
        user_data[user_id]["morning_time"] = "08:00"
    return await ask_reminders_step(update, context)

async def ask_reminders_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["✅ За час", "⏰ За 30 минут", "❌ Не нужно"]]
    await update.message.reply_text(
        "Напоминать о запланированных делах заранее? 🙂\n\n"
        "Например: «Через час у вас встреча в 15:00»",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return ASK_REMINDERS

async def finish_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    if "час" in text:
        user_data[user_id]["reminder_before"] = 60
    elif "30" in text:
        user_data[user_id]["reminder_before"] = 30
    else:
        user_data[user_id]["reminder_before"] = 0
    name = user_data[user_id].get("name", "")
    morning_time = user_data[user_id].get("morning_time", "")
    has_plan = user_data[user_id].get("morning_plan", False)
    summary = f"Всё готово, {name}! 🌸\n\nЯ запомнила:\n"
    if has_plan:
        summary += f"\n📋 Утренний план — каждый день в {morning_time}"
    if user_data[user_id].get("reminder_before", 0) > 0:
        mins = user_data[user_id]["reminder_before"]
        summary += f"\n⏰ Напоминания — за {mins} минут до события"
    summary += "\n\nМожете начинать! Чем могу помочь? )"
    await update.message.reply_text(summary, reply_markup=ReplyKeyboardRemove())
    username = update.effective_user.username or "нет username"
    await notify_admin(context, name, username, "Завершил онбординг", summary)
    if has_plan and morning_time:
        context.application.job_queue.run_daily(
            send_morning_plan,
            time=time(
                hour=int(morning_time.split(":")[0]),
                minute=0,
                tzinfo=pytz.timezone(user_data[user_id].get("timezone", "Europe/Moscow"))
            ),
            data=user_id,
            name=f"morning_{user_id}"
        )
    return ConversationHandler.END

async def send_morning_plan(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    name = user_data.get(user_id, {}).get("name", "")
    reminders = user_reminders.get(user_id, [])
    if reminders:
        plan_text = "\n".join([f"🕐 {r['time']} — {r['text']}" for r in sorted(reminders, key=lambda x: x["time"])])
    else:
        plan_text = "На сегодня задачи не добавлены.\nНапишите мне что запланировано — я структурирую )"
    await context.bot.send_message(
        chat_id=user_id,
        text=f"Доброе утро, {name}! ☀️\n\nВаш план на сегодня:\n\n{plan_text}"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_data:
        await update.message.reply_text("Напишите /start чтобы начать 🌸")
        return
    user_text = update.message.text
    user_name = update.effective_user.first_name or "Пользователь"
    username = update.effective_user.username or "нет username"
    history = get_history(user_id)
    history.append({"role": "user", "content": user_text})
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, *history],
            max_tokens=1000,
            temperature=0.7
        )
        reply = response.choices[0].message.content
        history.append({"role": "assistant", "content": reply})
        if len(history) > 20:
            user_histories[user_id] = history[-20:]

        # Проверяем запрос на напоминание
        if is_reminder_request(user_text):
            hour, minute = extract_time_and_text(user_text)
            if hour is not None:
                tz = pytz.timezone(user_data.get(user_id, {}).get("timezone", "Europe/Moscow"))
                now = datetime.now(tz)
                remind_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

                # Если время уже прошло — ставим на следующий день через run_daily
                job_name = f"reminder_{user_id}_{hour}_{minute}"

                # Удаляем старое напоминание с тем же именем если есть
                old_jobs = context.application.job_queue.get_jobs_by_name(job_name)
                for job in old_jobs:
                    job.schedule_removal()

                # Добавляем задачу
                context.application.job_queue.run_daily(
                    send_scheduled_reminder,
                    time=time(hour=hour, minute=minute, tzinfo=tz),
                    data={"user_id": user_id, "text": user_text},
                    name=job_name
                )

                if user_id not in user_reminders:
                    user_reminders[user_id] = []
                user_reminders[user_id].append({"time": f"{hour:02d}:{minute:02d}", "text": user_text})

        await update.message.reply_text(reply)
        await notify_admin(context, user_name, username, user_text, reply)
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await update.message.reply_text("Прошу прощения, произошла техническая ошибка. Попробуйте ещё раз.")

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = []
    await update.message.reply_text("История очищена 🌸")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
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
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🌸 София запущена!")
    app.run_polling()
