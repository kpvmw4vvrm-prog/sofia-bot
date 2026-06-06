import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from groq import Groq

# ==============================
# ТВОИ КЛЮЧИ — ВСТАВЬ СЮДА
# ==============================
TELEGRAM_TOKEN = "8988150778:AAE0U74b8WTdKf5OtmbiMFeSDoDm2BGGKzI"
GROQ_API_KEY = "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"

# ==============================
# ЛИЧНОСТЬ СОФИИ
# ==============================
SYSTEM_PROMPT = """Ты — София, заботливый и мягкий личный ассистент. 
Ты говоришь по-русски, тепло и дружелюбно, как хороший друг.

Твои задачи:
- Составлять план дня (по времени, структурированно)
- Помогать записываться на beauty-процедуры, мойку машины, встречи и другие дела
- Напоминать о важных делах
- Отвечать на любые вопросы по организации дня

Когда составляешь план — используй формат:
🕐 09:00 — задача
🕑 11:00 — задача

Когда пишешь о записи на услугу — уточни детали и подтверди что "записала".
Отвечай коротко и по делу, но тепло. Используй иногда эмодзи 🌸✨💕
"""

# ==============================
# НАСТРОЙКА
# ==============================
logging.basicConfig(level=logging.INFO)
groq_client = Groq(api_key=GROQ_API_KEY)

# Память разговоров (у каждого пользователя своя история)
user_histories = {}

def get_history(user_id):
    if user_id not in user_histories:
        user_histories[user_id] = []
    return user_histories[user_id]

# ==============================
# КОМАНДА /start
# ==============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = []  # сбрасываем историю
    
    await update.message.reply_text(
        "Привет! Я София, твой личный ассистент 🌸\n\n"
        "Помогу составить план дня, записаться на процедуры "
        "и не забыть о важных делах.\n\n"
        "Чем могу помочь? ✨"
    )

# ==============================
# КОМАНДА /clear — очистить историю
# ==============================
async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = []
    await update.message.reply_text("История очищена 🌸 Начинаем заново!")

# ==============================
# ОБРАБОТКА СООБЩЕНИЙ
# ==============================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text
    
    history = get_history(user_id)
    history.append({"role": "user", "content": user_text})
    
    # Показываем что София "печатает"
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, 
        action="typing"
    )
    
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                *history
            ],
            max_tokens=1000,
            temperature=0.7
        )
        
        reply = response.choices[0].message.content
        history.append({"role": "assistant", "content": reply})
        
        # Ограничиваем историю (последние 20 сообщений)
        if len(history) > 20:
            user_histories[user_id] = history[-20:]
        
        await update.message.reply_text(reply)
        
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await update.message.reply_text(
            "Упс, что-то пошло не так 🌸 Попробуй ещё раз!"
        )

# ==============================
# ЗАПУСК БОТА
# ==============================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🌸 София запущена! Открывай Telegram и пиши боту.")
    app.run_polling()
