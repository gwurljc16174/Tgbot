#!/usr/bin/env python3
"""
WebDev Tutor Bot — Telegram bot that teaches HTML, CSS, and JavaScript.

Master Prompt (embedded):
You are "WebDev Tutor Bot", a friendly, interactive teacher for beginners learning web development.

... (full code omitted in docstring for brevity) ...
"""

import os
import json
import logging
from datetime import datetime, date, timedelta, timezone

import aiosqlite
from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

load_dotenv()

# === Config from env ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DB_PATH = os.getenv("DB_PATH", "webdev_tutor_bot.db")
DEFAULT_UTC_OFFSET = float(os.getenv("DEFAULT_UTC_OFFSET", "0"))
ADMIN_CONTACT = os.getenv("ADMIN_CONTACT", "https://t.me/JAHONGIR19121")

# Limits
FREE_DAILY_QUIZZES = int(os.getenv("FREE_DAILY_QUIZZES", "5"))

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("webdev-tutor-bot")

# === Database setup ===
DB = None

CREATE_SQL = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE,
    first_name TEXT,
    username TEXT,
    is_premium INTEGER DEFAULT 0,
    utc_offset REAL DEFAULT 0,
    last_reset_date TEXT,
    progress_json TEXT DEFAULT '{}',
    quizzes_used_today INTEGER DEFAULT 0
);
"""

async def get_db():
    global DB
    if DB is None:
        DB = await aiosqlite.connect(DB_PATH)
        DB.row_factory = aiosqlite.Row
        await DB.executescript(CREATE_SQL)
        await DB.commit()
    return DB

async def upsert_user(tg_id, first_name, username):
    db = await get_db()
    await db.execute(
        "INSERT INTO users (telegram_id, first_name, username, last_reset_date) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(telegram_id) DO UPDATE SET first_name=excluded.first_name, username=excluded.username",
        (tg_id, first_name or "", username or "", date.today().isoformat())
    )
    await db.commit()

async def get_user(tg_id):
    db = await get_db()
    async with db.execute("SELECT * FROM users WHERE telegram_id=?", (tg_id,)) as cur:
        return await cur.fetchone()

async def set_user_field(tg_id, field, value):
    db = await get_db()
    await db.execute(f"UPDATE users SET {field}=? WHERE telegram_id=?", (value, tg_id))
    await db.commit()

# === Lessons & Quizzes ===
LESSONS = {
    "html": [
        {
            "title": "HTML Basics",
            "content": "HTML builds the skeleton of a webpage. Use tags like <h1> for headings and <p> for paragraphs. Think of HTML as labelled boxes that browsers arrange for you.",
            "code": "<!doctype html>\n<html>\n  <head>\n    <title>My Page</title>\n  </head>\n  <body>\n    <h1>Hello World!</h1>\n    <p>This is my first page.</p>\n  </body>\n</html>",
            "quiz": {"q": "Which tag creates a paragraph?", "opts": ["<h1>", "<p>", "<div>"], "a": 1},
            "premium": False
        },
        {
            "title": "HTML Tags & Structure",
            "content": "Tags like <header>, <nav>, <main>, <footer>, <section> help organize content. Use semantic tags to make your page readable for people and machines.",
            "code": "<header>\n  <h1>Site title</h1>\n</header>\n<main>\n  <p>Welcome!</p>\n</main>",
            "quiz": None,
            "premium": False
        },
        {
            "title": "Forms (Intro) — Premium",
            "content": "Forms collect user input. Use <form>, <input>, <label>, <button>. Always label inputs and prefer semantic types (email, number) when possible.",
            "code": "<form action='/submit'>\n  <label>Email: <input type='email' name='email'></label>\n  <button type='submit'>Send</button>\n</form>",
            "quiz": {"q": "Which element wraps input fields to submit data?", "opts": ["<form>", "<div>", "<fieldset>"], "a": 0},
            "premium": True
        },
    ],
    "css":[
        {
            "title":"CSS Basics",
            "content":"CSS styles how HTML looks — colors, spacing, fonts. You target elements using selectors and change their properties.",
            "code":"body {\n  font-family: Arial, sans-serif;\n  color: #222;\n}\nh1 { color: #0a66c2; }",
            "quiz":{"q":"Which property changes text color?","opts":["background","color","font-size"], "a":1},
            "premium": False
        },
        {
            "title":"Flexbox Intro — Premium",
            "content":"Flexbox helps with one-dimensional layouts. Use display:flex on a container and control alignment with justify-content and align-items.",
            "code":".container {\n  display: flex;\n  gap: 12px;\n}\n.item { flex: 1; }",
            "quiz":{"q":"Which property sets an element to use flex layout?","opts":["display:block","display:flex","position:flex"], "a":1},
            "premium": True
        }
    ],
    "js":[
        {
            "title":"JavaScript Basics",
            "content":"JavaScript adds interactivity — variables, functions, and events let you react to user actions.",
            "code":"const msg = 'Hello';\nconsole.log(msg);",
            "quiz":{"q":"Which keyword declares a constant?","opts":["var","let","const"], "a":2},
            "premium": False
        },
        {
            "title":"DOM Interaction — Premium",
            "content":"DOM is the page structure that JS can query and change with document.querySelector and friends.",
            "code":"const p = document.querySelector('p');\np.textContent = 'Updated!';",
            "quiz":{"q":"document.querySelector returns:","opts":["Single element","All matching elements","An array"], "a":0},
            "premium": True
        }
    ]
}

MODULE_ORDER = ["html","css","js"]

# === Progress helpers ===
def default_progress():
    return {"modules": {}, "quizzes": [], "completed": []}

async def get_progress(tg_id):
    user = await get_user(tg_id)
    if not user:
        return default_progress()
    try:
        p = json.loads(user["progress_json"] or "{}")
        if not isinstance(p, dict):
            return default_progress()
        p.setdefault("modules", {})
        p.setdefault("quizzes", [])
        p.setdefault("completed", [])
        return p
    except Exception:
        return default_progress()

async def set_progress(tg_id, progress):
    await set_user_field(tg_id, "progress_json", json.dumps(progress, ensure_ascii=False))

async def reset_daily_counts_if_needed(tg_id):
    user = await get_user(tg_id)
    if not user:
        return
    last_reset = user["last_reset_date"]
    try:
        tz_offset = float(user["utc_offset"] or DEFAULT_UTC_OFFSET)
    except Exception:
        tz_offset = DEFAULT_UTC_OFFSET
    local_today = (datetime.utcnow() + timedelta(hours=tz_offset)).date().isoformat()
    if last_reset != local_today:
        db = await get_db()
        await db.execute("UPDATE users SET quizzes_used_today=0, last_reset_date=? WHERE telegram_id=?", (local_today, tg_id))
        await db.commit()

# === Keyboard builders ===
def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📘 Learn HTML", callback_data="mod:html")],
        [InlineKeyboardButton("🎨 Learn CSS", callback_data="mod:css")],
        [InlineKeyboardButton("⚡ Learn JavaScript", callback_data="mod:js")],
        [InlineKeyboardButton("📝 Quizzes / Practice", callback_data="menu:quizzes")],
        [InlineKeyboardButton("📊 Progress", callback_data="menu:progress")],
        [InlineKeyboardButton("💎 Go Premium", url=ADMIN_CONTACT)]
    ])

def lesson_nav_kb(module, index, has_quiz=False, is_premium_user=False):
    row = [
        InlineKeyboardButton("➡️ Next Lesson", callback_data=f"nav:{module}:{index}:next"),
        InlineKeyboardButton("🔁 Repeat Lesson", callback_data=f"nav:{module}:{index}:repeat"),
    ]
    kb = [row]
    if has_quiz:
        kb.append([InlineKeyboardButton("📝 Quiz", callback_data=f"quiz:{module}:{index}")])
    kb.append([InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")])
    lesson = LESSONS[module][index]
    if lesson.get("premium") and not is_premium_user:
        kb.append([InlineKeyboardButton("💎 Unlock Premium", url=ADMIN_CONTACT)])
    return InlineKeyboardMarkup(kb)

def quiz_kb(module, index):
    q = LESSONS[module][index]["quiz"]
    opts = []
    for i, opt in enumerate(q["opts"]):
        opts.append([InlineKeyboardButton(f"[{chr(65+i)}] {opt}", callback_data=f"ans:{module}:{index}:{i}")])
    opts.append([InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")])
    return InlineKeyboardMarkup(opts)

# === Message sending ===
async def send_lesson(app, chat_id, tg_id, module, index):
    if module not in LESSONS:
        await app.bot.send_message(chat_id, "Module not found.")
        return
    lessons = LESSONS[module]
    if index < 0 or index >= len(lessons):
        await app.bot.send_message(chat_id, "No more lessons in this module.")
        return
    lesson = lessons[index]
    user = await get_user(tg_id)
    is_premium_user = bool(user and user["is_premium"])
    if lesson.get("premium") and not is_premium_user:
        text = f"💎 *Locked Premium Lesson*\\n\\nThis lesson (`{lesson['title']}`) is premium-only. Contact admin to unlock."
        await app.bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Contact Admin", url=ADMIN_CONTACT)]]), parse_mode="Markdown")
        return
    lang = "html"
    if module == "js":
        lang = "javascript"
    text_lines = [
        f"📘 {module.upper()} — {lesson['title']} (Lesson {index+1}/{len(lessons)})",
        "",
        lesson["content"],
        "",
        "```" + lang + "\n" + lesson["code"] + "\n```"
    ]
    text = "\n".join(text_lines)
    await app.bot.send_message(chat_id, text, reply_markup=lesson_nav_kb(module,index, has_quiz=bool(lesson.get("quiz")), is_premium_user=is_premium_user), parse_mode="Markdown")
    # record viewed
    prog = await get_progress(tg_id)
    mod = prog["modules"].setdefault(module, {})
    mod[str(index)] = mod.get(str(index), "viewed")
    await set_progress(tg_id, prog)

# === Handlers ===
async def start(update, context):
    u = update.effective_user
    await upsert_user(u.id, u.first_name or "", u.username or "")
    await reset_daily_counts_if_needed(u.id)
    await update.message.reply_text("Welcome to WebDev Tutor Bot!\\nChoose a topic:", reply_markup=main_menu_kb())

async def on_callback(update, context):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    tg_id = q.from_user.id
    app = context.application

    await upsert_user(tg_id, q.from_user.first_name or "", q.from_user.username or "")
    await reset_daily_counts_if_needed(tg_id)
    user = await get_user(tg_id)
    is_premium_user = bool(user and user["is_premium"])

    if data == "menu:home":
        await q.message.edit_text("Main Menu:", reply_markup=main_menu_kb()); return
    if data.startswith("mod:"):
        module = data.split(":",1)[1]; await send_lesson(app, q.message.chat.id, tg_id, module, 0); return
    if data.startswith("nav:"):
        _, module, idx_s, action = data.split(":",3)
        idx = int(idx_s)
        if action == "next":
            await send_lesson(app, q.message.chat.id, tg_id, module, idx+1); return
        if action == "repeat":
            await send_lesson(app, q.message.chat.id, tg_id, module, idx); return
    if data.startswith("quiz:"):
        _, module, idx_s = data.split(":",2)
        idx = int(idx_s)
        lesson = LESSONS.get(module,[])[idx]
        qobj = lesson.get("quiz")
        if not qobj:
            await q.message.reply_text("No quiz for this lesson.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")]]))
            return
        await context.application.bot.send_message(q.message.chat.id, f"❓ {qobj['q']}", reply_markup=quiz_kb(module, idx))
        return
    if data.startswith("ans:"):
        _, module, idx_s, choice_s = data.split(":",3)
        idx = int(idx_s); choice = int(choice_s)
        lesson = LESSONS.get(module,[])[idx]
        qobj = lesson.get("quiz")
        if not qobj:
            await q.message.reply_text("Quiz data missing."); return
        await reset_daily_counts_if_needed(tg_id)
        user = await get_user(tg_id)
        used = int(user["quizzes_used_today"] or 0)
        if not is_premium_user and used >= FREE_DAILY_QUIZZES:
            await q.message.reply_text(f"❗ Free daily quiz limit reached ({FREE_DAILY_QUIZZES}). Unlock Premium to continue.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 Unlock", url=ADMIN_CONTACT)]]))
            return
        await set_user_field(tg_id, "quizzes_used_today", used+1)
        prog = await get_progress(tg_id)
        correct = (choice == qobj["a"])
        prog["quizzes"].append({"module":module, "index":idx, "choice":choice, "correct":bool(correct), "time": datetime.utcnow().isoformat()})
        if correct:
            mod = prog["modules"].setdefault(module, {})
            mod[str(idx)] = "completed"
            lessons = LESSONS.get(module,[])
            all_done = all(str(i) in mod and mod[str(i)]=="completed" for i in range(len(lessons)) if not lessons[i].get("premium") or is_premium_user)
            if all_done and module not in prog["completed"]:
                prog["completed"].append(module)
                await context.application.bot.send_message(update.effective_chat.id, f"🎉 Congratulations — you completed the {module.upper()} module!")
            await set_progress(tg_id, prog)
            explanation = f"✅ Correct! `{qobj['opts'][choice]}` is right."
            if is_premium_user:
                explanation += "\n\n📘 Bonus: " + (lesson.get("content") or "")
            await context.application.bot.send_message(update.effective_chat.id, explanation, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➡️ Next Lesson", callback_data=f"nav:{module}:{idx}:next"), InlineKeyboardButton("🏠 Menu", callback_data="menu:home")]]), parse_mode="Markdown")
        else:
            await context.application.bot.send_message(update.effective_chat.id, "❌ Not quite. Try again or review the lesson.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔁 Repeat Lesson", callback_data=f"nav:{module}:{idx}:repeat"), InlineKeyboardButton("🏠 Menu", callback_data="menu:home")]]))
            await set_progress(tg_id, prog)
        return
    if data == "menu:quizzes":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("HTML", callback_data="mod:html")],[InlineKeyboardButton("CSS", callback_data="mod:css")],[InlineKeyboardButton("JavaScript", callback_data="mod:js")],[InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")]])
        await q.message.edit_text("Pick a module to practice:", reply_markup=kb); return
    if data == "menu:progress":
        prog = await get_progress(tg_id)
        lines = ["📊 Progress:"]
        for m in ("html","css","js"):
            mod = prog["modules"].get(m,{})
            total = len(LESSONS.get(m,[]))
            done = sum(1 for v in mod.values() if v=="completed")
            lines.append(f"{m.upper()}: {done}/{total} lessons completed")
        lines.append("Quizzes taken: " + str(len(prog["quizzes"])))
        await q.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")]])); return
    await q.answer("Unknown command")

async def on_text(update, context):
    if not update.message: return
    txt = (update.message.text or "").strip()
    if txt.startswith("/start"):
        await start(update, context)
    else:
        await update.message.reply_text("Use the buttons to navigate. Press /start to open the menu.", reply_markup=main_menu_kb())

async def post_init(app):
    await get_db()
    log.info("Bot initialized and post_init complete.")

def build_app():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is required in environment")
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app

def main():
    app = build_app()
    log.info("WebDev Tutor Bot starting (long polling)…")
    app.run_polling(allowed_updates=None)

if __name__ == '__main__':
    main()
