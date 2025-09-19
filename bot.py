import os
import json
import logging
from datetime import date

import aiosqlite
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DB_PATH = os.getenv("DB_PATH", "webdev_tutor.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("webdev-tutor-bot")

DB = None

async def get_db():
    global DB
    if DB is None:
        DB = await aiosqlite.connect(DB_PATH)
        DB.row_factory = aiosqlite.Row
        await DB.executescript("CREATE TABLE IF NOT EXISTS users (telegram_id INTEGER PRIMARY KEY, is_premium INTEGER DEFAULT 0, progress_json TEXT DEFAULT '{}');")
        await DB.commit()
    return DB

async def get_user(tg_id):
    db = await get_db()
    async with db.execute("SELECT * FROM users WHERE telegram_id=?", (tg_id,)) as cur:
        return await cur.fetchone()

async def upsert_user(tg_id):
    db = await get_db()
    await db.execute("INSERT OR IGNORE INTO users (telegram_id) VALUES (?)", (tg_id,))
    await db.commit()

async def set_user_field(tg_id, field, value):
    db = await get_db()
    await db.execute(f"UPDATE users SET {field}=? WHERE telegram_id=?", (value, tg_id))
    await db.commit()

LESSONS = {
    "html": [
        {"title": "HTML Basics", "content": "HTML builds the skeleton of a webpage. Use tags like <h1>, <p>.", "code": "<h1>Hello</h1>\n<p>World</p>", "quiz": {"q": "Which tag creates a paragraph?", "opts": ["<h1>", "<p>", "<div>"], "a": 1}, "premium": False},
        {"title": "Forms (Premium)", "content": "Forms collect user input. Use <form>, <input>, <button>.", "code": "<form>...</form>", "quiz": None, "premium": True}
    ]
}

def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📘 Learn HTML", callback_data="mod:html")],
        [InlineKeyboardButton("📝 Quizzes", callback_data="menu:quizzes")],
        [InlineKeyboardButton("📊 Progress", callback_data="menu:progress")],
        [InlineKeyboardButton("💎 Go Premium", url="https://t.me/JAHONGIR19121")]
    ])

def lesson_kb(module, index, has_quiz):
    kb = [
        [InlineKeyboardButton("➡️ Next", callback_data=f"nav:{module}:{index}:next"),
         InlineKeyboardButton("🔁 Repeat", callback_data=f"nav:{module}:{index}:repeat")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:home")]
    ]
    if has_quiz:
        kb.insert(1, [InlineKeyboardButton("📝 Quiz", callback_data=f"quiz:{module}:{index}")])
    return InlineKeyboardMarkup(kb)

def quiz_kb(module, index):
    q = LESSONS[module][index]["quiz"]
    opts = []
    for i, o in enumerate(q["opts"]):
        opts.append([InlineKeyboardButton(f"[{chr(65+i)}] {o}", callback_data=f"ans:{module}:{index}:{i}")])
    opts.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:home")])
    return InlineKeyboardMarkup(opts)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await upsert_user(update.effective_user.id)
    await update.message.reply_text("Welcome to WebDev Tutor Bot!", reply_markup=main_menu_kb())

async def send_lesson(update: Update, tg_id, module, index):
    lessons = LESSONS[module]
    if index >= len(lessons):
        await update.effective_message.reply_text("No more lessons.")
        return
    l = lessons[index]
    user = await get_user(tg_id)
    if l["premium"] and not user["is_premium"]:
        await update.effective_message.reply_text("💎 This is a Premium lesson. Contact admin to upgrade.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Contact Admin", url="https://t.me/JAHONGIR19121")]]))
        return
    text = f"📘 {l['title']}\n\n{l['content']}\n\n```html\n{l['code']}\n```"
    await update.effective_message.reply_text(text, reply_markup=lesson_kb(module, index, bool(l["quiz"])), parse_mode="Markdown")

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    tg_id = q.from_user.id
    if data == "menu:home":
        await q.message.edit_text("Main Menu:", reply_markup=main_menu_kb())
    elif data.startswith("mod:"):
        module = data.split(":")[1]
        await send_lesson(update, tg_id, module, 0)
    elif data.startswith("nav:"):
        _, module, idx, action = data.split(":")
        idx = int(idx)
        if action == "next":
            await send_lesson(update, tg_id, module, idx+1)
        else:
            await send_lesson(update, tg_id, module, idx)
    elif data.startswith("quiz:"):
        _, module, idx = data.split(":")
        idx = int(idx)
        qobj = LESSONS[module][idx]["quiz"]
        if not qobj:
            await q.message.reply_text("No quiz.")
            return
        await q.message.reply_text(f"❓ {qobj['q']}", reply_markup=quiz_kb(module, idx))
    elif data.startswith("ans:"):
        _, module, idx, choice = data.split(":")
        idx = int(idx); choice = int(choice)
        qobj = LESSONS[module][idx]["quiz"]
        if choice == qobj["a"]:
            await q.message.reply_text("✅ Correct!")
        else:
            await q.message.reply_text("❌ Not quite, try again.")

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.startswith("/start"):
        await start(update, context)
    else:
        await update.message.reply_text("Use the buttons below:", reply_markup=main_menu_kb())

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN missing")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("Bot polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
