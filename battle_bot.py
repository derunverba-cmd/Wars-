# -*- coding: utf-8 -*-
# Бот для війнушок — оновлення 1.1
# Змінні Railway: BOT_TOKEN (обов'язково), DB_PATH (необов'язково)
import html
import itertools
import os
import random
import sqlite3
import threading
import time

import telebot
from telebot import types

TOKEN = os.environ["BOT_TOKEN"]
DB_PATH = os.environ.get("DB_PATH", "bot.db")
ADMINS = {7660211311, 1642108682}

GIFT_COOLDOWN = 2 * 60 * 60   # подарунок раз на 2 години
BATTLE_COOLDOWN = 60          # новий виклик на битву раз на 60 секунд
CHALLENGE_TTL = 120           # скільки секунд діє виклик на битву
STEAL_MIN, STEAL_MAX = 1, 3   # скільки сили забирає переможець

REF_POWER = 5                 # сила за запрошену людину
REF_POWER_PREMIUM = 20        # сила за запрошену людину з Telegram Premium

# рівень: скільки сили потрібно
LEVELS = [(5, 200), (4, 100), (3, 50), (2, 25), (1, 10)]

# рівень: (мін, макс) подарунка
GIFTS = {
    0: (1, 5),
    1: (1, 5),
    2: (3, 7),
    3: (5, 10),
    4: (7, 13),
    5: (1, 20),
}

# промокоди (пишуться маленькими літерами, без #)
# щоб додати новий — просто додай рядок
PROMOS = {
    "winter": {"coins": 12, "power": 0},
    "christmas": {"coins": 12, "power": 0},
}

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
BOT_USERNAME = bot.get_me().username

db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
lock = threading.Lock()

with lock:
    db.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY,
        username TEXT,
        name TEXT,
        power INTEGER DEFAULT 0,
        last_gift REAL DEFAULT 0,
        last_battle REAL DEFAULT 0,
        battles INTEGER DEFAULT 0,
        coins INTEGER DEFAULT 0,
        referred_by INTEGER DEFAULT 0)""")
    # якщо база вже була зі старої версії — додаємо нові колонки
    for col in ("battles INTEGER DEFAULT 0",
                "coins INTEGER DEFAULT 0",
                "referred_by INTEGER DEFAULT 0"):
        try:
            db.execute("ALTER TABLE users ADD COLUMN " + col)
        except sqlite3.OperationalError:
            pass
    db.execute("CREATE TABLE IF NOT EXISTS chats(id INTEGER PRIMARY KEY)")
    db.execute("""CREATE TABLE IF NOT EXISTS promo_uses(
        user_id INTEGER, code TEXT, PRIMARY KEY(user_id, code))""")
    db.commit()

awaiting_promo = set()   # хто зараз вводить промокод
challenges = {}          # активні виклики на битву
_ids = itertools.count(1)


# ---------- допоміжне ----------

def get_level(power):
    for lvl, need in LEVELS:
        if power >= need:
            return lvl
    return 0


def next_level_info(power):
    """(наступний рівень, скільки сили треба) або None, якщо максимум"""
    for lvl, need in sorted(LEVELS):
        if power < need:
            return lvl, need
    return None


def save_user(u):
    uname = (u.username or "").lower()
    with lock:
        db.execute("INSERT OR IGNORE INTO users(id, username, name) VALUES(?,?,?)",
                   (u.id, uname, u.first_name or ""))
        db.execute("UPDATE users SET username=?, name=? WHERE id=?",
                   (uname, u.first_name or "", u.id))
        db.commit()


def get_user(uid):
    with lock:
        return db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def find_by_username(username):
    with lock:
        return db.execute("SELECT * FROM users WHERE username=?",
                          (username.lower().lstrip("@"),)).fetchone()


def set_power(uid, power):
    with lock:
        db.execute("UPDATE users SET power=? WHERE id=?", (max(0, power), uid))
        db.commit()


def fmt_time(sec):
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h} год")
    if m:
        parts.append(f"{m} хв")
    if s and not h:
        parts.append(f"{s} с")
    return " ".join(parts) or "0 с"


def mention(row):
    return f'<a href="tg://user?id={row["id"]}">{html.escape(row["name"] or "Гравець")}</a>'


def main_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("Сила", "Рівень")
    kb.row("Профіль", "Promo")
    return kb


def say(message, text):
    """Відповідь; в особистому чаті одразу показуємо меню внизу"""
    markup = main_menu() if message.chat.type == "private" else None
    bot.reply_to(message, text, reply_markup=markup)


KNOWN = {
    "/start", "/news", "/menu", "меню",
    "сила", "/power", "/sila",
    "рівень", "/level",
    "профіль", "/profile",
    "promo", "/promo", "промо",
    "битва", "/battle",
}


# ---------- головний обробник тексту ----------

@bot.message_handler(func=lambda m: True, content_types=["text"])
def on_text(message):
    u = message.from_user
    if u.is_bot:
        return

    is_new = get_user(u.id) is None
    save_user(u)

    if message.chat.type in ("group", "supergroup"):
        with lock:
            db.execute("INSERT OR IGNORE INTO chats(id) VALUES(?)", (message.chat.id,))
            db.commit()

    text = (message.text or "").strip()
    low = text.lower()
    first = low.split()[0] if low else ""
    first = first.split("@")[0]  # /news@botname -> /news
    private = message.chat.type == "private"

    # людина натиснула Promo і тепер пише код
    if private and u.id in awaiting_promo:
        awaiting_promo.discard(u.id)
        if first not in KNOWN:
            return activate_promo(message, text)

    if first == "/start":
        return cmd_start(message, is_new)
    if first in ("/menu", "меню"):
        return bot.reply_to(message, "📋 Меню", reply_markup=main_menu())
    if first == "/news":
        return cmd_news(message)
    if first in ("сила", "/power", "/sila"):
        return cmd_gift(message)
    if first in ("рівень", "/level"):
        return cmd_level(message)
    if first in ("профіль", "/profile"):
        return cmd_profile(message)
    if first in ("promo", "/promo", "промо"):
        return cmd_promo(message)
    if first in ("битва", "/battle"):
        return cmd_battle(message)


# ---------- /start і реферали ----------

def cmd_start(message, is_new):
    u = message.from_user
    parts = message.text.split()

    if is_new and message.chat.type == "private" and len(parts) > 1 \
            and parts[1].startswith("ref_"):
        try:
            ref_id = int(parts[1][4:])
        except ValueError:
            ref_id = 0
        if ref_id and ref_id != u.id and get_user(ref_id):
            premium = bool(getattr(u, "is_premium", False))
            bonus = REF_POWER_PREMIUM if premium else REF_POWER
            with lock:
                db.execute("UPDATE users SET power=power+? WHERE id=?", (bonus, ref_id))
                db.execute("UPDATE users SET referred_by=? WHERE id=?", (ref_id, u.id))
                db.commit()
            try:
                extra = " (з Telegram Premium 🌟)" if premium else ""
                bot.send_message(
                    ref_id,
                    f"🎉 За твоїм посиланням зайшов {html.escape(u.first_name or 'гравець')}"
                    f"{extra}!\n💪 Ти отримав <b>+{bonus}</b> сили")
            except Exception:
                pass

    say(message,
        "⚔️ <b>Привіт! Це бот для війнушок.</b>\n\n"
        "Додай мене в чат і пиши:\n"
        "• <b>Сила</b> — отримати подарунок (раз на 2 години)\n"
        "• <b>Рівень</b> — твій рівень\n"
        "• <b>Профіль</b> — твоя статистика і реферальне посилання\n"
        "• <b>Promo</b> — активувати промокод\n"
        "• <b>Битва</b> — відповідай цим словом на повідомлення "
        "суперника (або <b>Битва @username</b>). Битва починається, "
        "коли суперник прийме виклик.\n\n"
        "Чим більше сили — тим вищий рівень і більше шансів на перемогу!")


# ---------- сила / рівень / профіль ----------

def cmd_gift(message):
    u = message.from_user
    row = get_user(u.id)
    now = time.time()
    left = row["last_gift"] + GIFT_COOLDOWN - now
    if left > 0:
        say(message, f"⏳ Наступний подарунок через <b>{fmt_time(left)}</b>")
        return

    old_power = row["power"]
    old_lvl = get_level(old_power)
    lo, hi = GIFTS[old_lvl]
    gift = random.randint(lo, hi)
    new_power = old_power + gift
    new_lvl = get_level(new_power)

    with lock:
        db.execute("UPDATE users SET power=?, last_gift=? WHERE id=?",
                   (new_power, now, u.id))
        db.commit()

    msg = f"🎁 Ти отримав <b>+{gift}</b> сили!\n💪 Всього сили: <b>{new_power}</b>"
    if new_lvl > old_lvl:
        msg += f"\n🔥 Новий рівень: <b>{new_lvl}</b>!"
    say(message, msg)


def cmd_level(message):
    row = get_user(message.from_user.id)
    power = row["power"]
    lvl = get_level(power)
    msg = f"🏅 Ваш рівень: <b>{lvl}</b>\n"
    info = next_level_info(power)
    if info:
        nxt, need = info
        msg += f"📈 Залишилось до <b>{nxt}</b> рівня: <b>{need - power}</b> сили"
    else:
        msg += "👑 У вас максимальний рівень!"
    say(message, msg)


def cmd_profile(message):
    row = get_user(message.from_user.id)
    lvl = get_level(row["power"])
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{row['id']}"
    say(message,
        f"👤 <b>Профіль</b>\n\n"
        f"🆔 Айді гравця: <code>{row['id']}</code>\n"
        f"⚔️ Всього битв: <b>{row['battles']}</b>\n"
        f"🏅 Рівень: <b>{lvl}</b>\n"
        f"💎 W coins: <b>{row['coins']}</b>\n\n"
        f"🔗 Реферальне посилання:\n{link}\n\n"
        f"За кожного запрошеного: +{REF_POWER} сили, "
        f"а якщо в нього Telegram Premium — +{REF_POWER_PREMIUM} сили.")


# ---------- промокоди ----------

def cmd_promo(message):
    if message.chat.type != "private":
        bot.reply_to(message, "🎟 Промокоди активуються в особистих повідомленнях з ботом.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip():
        return activate_promo(message, parts[1])
    awaiting_promo.add(message.from_user.id)
    say(message, "🎟 Введи промокод (наприклад, <code>#winter</code>):")


def activate_promo(message, raw):
    uid = message.from_user.id
    code = raw.strip().lstrip("#").lower()
    promo = PROMOS.get(code)
    if not promo:
        say(message, "❌ Такого промокоду не існує.")
        return

    with lock:
        used = db.execute("SELECT 1 FROM promo_uses WHERE user_id=? AND code=?",
                          (uid, code)).fetchone()
        if not used:
            db.execute("INSERT INTO promo_uses(user_id, code) VALUES(?,?)", (uid, code))
            db.execute("UPDATE users SET coins=coins+?, power=power+? WHERE id=?",
                       (promo["coins"], promo["power"], uid))
            db.commit()
    if used:
        say(message, "⚠️ Ти вже активував цей промокод.")
        return

    rewards = []
    if promo["coins"]:
        rewards.append(f"💎 <b>{promo['coins']}</b> W coins")
    if promo["power"]:
        rewards.append(f"💪 <b>{promo['power']}</b> сили")
    say(message, "✅ Промокод активовано!\nТи отримав: " + " і ".join(rewards))


# ---------- битви з підтвердженням ----------

def cmd_battle(message):
    if message.chat.type == "private":
        bot.reply_to(message, "⚔️ Битви працюють тільки в груповому чаті.")
        return

    me = get_user(message.from_user.id)
    now = time.time()
    left = me["last_battle"] + BATTLE_COOLDOWN - now
    if left > 0:
        bot.reply_to(message, f"⏳ Новий виклик можна кинути через <b>{fmt_time(left)}</b>")
        return

    enemy = None
    if message.reply_to_message and message.reply_to_message.from_user:
        eu = message.reply_to_message.from_user
        if eu.is_bot:
            bot.reply_to(message, "🤖 З ботами битись не можна.")
            return
        save_user(eu)
        enemy = get_user(eu.id)
    else:
        parts = message.text.split()
        if len(parts) > 1 and parts[1].startswith("@"):
            enemy = find_by_username(parts[1])

    if not enemy:
        bot.reply_to(
            message,
            "Відповідай словом <b>Битва</b> на повідомлення суперника "
            "або напиши <b>Битва @username</b>")
        return
    if enemy["id"] == me["id"]:
        bot.reply_to(message, "Сам з собою битись не можна 😄")
        return

    cid = next(_ids)
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("✅ Прийняти", callback_data=f"bt:y:{cid}"),
        types.InlineKeyboardButton("❌ Відмовитись", callback_data=f"bt:n:{cid}"))

    sent = bot.reply_to(
        message,
        f"⚔️ {mention(me)} (💪{me['power']}) викликає на битву "
        f"{mention(enemy)} (💪{enemy['power']})!\n\n"
        f"{mention(enemy)}, приймаєш виклик? (діє {CHALLENGE_TTL // 60} хв)",
        reply_markup=kb)

    challenges[cid] = {"a": me["id"], "b": enemy["id"],
                       "chat": message.chat.id, "msg": sent.message_id, "t": now}
    with lock:
        db.execute("UPDATE users SET last_battle=? WHERE id=?", (now, me["id"]))
        db.commit()


def resolve_battle(a_id, b_id):
    a, b = get_user(a_id), get_user(b_id)
    p1, p2 = a["power"], b["power"]
    chance = 0.5 if p1 + p2 == 0 else p1 / (p1 + p2)
    win = random.random() < chance

    winner, loser = (a, b) if win else (b, a)
    steal = min(random.randint(STEAL_MIN, STEAL_MAX), loser["power"])
    with lock:
        db.execute("UPDATE users SET power=power+? WHERE id=?", (steal, winner["id"]))
        db.execute("UPDATE users SET power=power-? WHERE id=?", (steal, loser["id"]))
        db.execute("UPDATE users SET battles=battles+1 WHERE id IN (?, ?)", (a_id, b_id))
        db.commit()

    return (f"⚔️ <b>БИТВА!</b>\n"
            f"{mention(a)} (💪{p1}, шанс {chance * 100:.0f}%) VS "
            f"{mention(b)} (💪{p2}, шанс {(1 - chance) * 100:.0f}%)\n\n"
            f"🏆 Перемагає {mention(winner)} і забирає <b>{steal}</b> сили!")


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("bt:"))
def on_battle_button(call):
    try:
        _, action, cid = call.data.split(":")
        cid = int(cid)
    except ValueError:
        return

    ch = challenges.get(cid)
    if not ch:
        bot.answer_callback_query(call.id, "Цей виклик вже неактуальний")
        return

    uid = call.from_user.id

    if time.time() - ch["t"] > CHALLENGE_TTL:
        challenges.pop(cid, None)
        bot.answer_callback_query(call.id, "Час виклику вийшов")
        try:
            bot.edit_message_text("⌛ Виклик на битву закінчився.", ch["chat"], ch["msg"])
        except Exception:
            pass
        return

    # виклик може скасувати той, хто кинув
    if uid == ch["a"] and action == "n":
        challenges.pop(cid, None)
        bot.answer_callback_query(call.id, "Виклик скасовано")
        try:
            bot.edit_message_text("🚫 Виклик на битву скасовано.", ch["chat"], ch["msg"])
        except Exception:
            pass
        return

    if uid != ch["b"]:
        bot.answer_callback_query(call.id, "Ця кнопка не для тебе")
        return

    challenges.pop(cid, None)
    if action == "n":
        bot.answer_callback_query(call.id, "Ти відмовився")
        b = get_user(ch["b"])
        try:
            bot.edit_message_text(f"❌ {mention(b)} відмовився від битви.",
                                  ch["chat"], ch["msg"])
        except Exception:
            pass
        return

    bot.answer_callback_query(call.id, "Битва почалась!")
    result = resolve_battle(ch["a"], ch["b"])
    try:
        bot.edit_message_text(result, ch["chat"], ch["msg"])
    except Exception:
        bot.send_message(ch["chat"], result)


# ---------- новини для адмінів ----------

def cmd_news(message):
    uid = message.from_user.id
    if uid not in ADMINS:
        return  # тільки ці два адміни
    if message.chat.type != "private":
        bot.reply_to(message, "Використовуй /news в особистих повідомленнях з ботом.")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(message, "Напиши так: <code>/news текст новини</code>")
        return

    news = "📰 <b>Новини бота</b>\n\n" + parts[1].strip()

    with lock:
        user_ids = [r["id"] for r in db.execute("SELECT id FROM users").fetchall()]
        chat_ids = [r["id"] for r in db.execute("SELECT id FROM chats").fetchall()]

    ok, fail = 0, 0
    for target in set(user_ids + chat_ids):
        try:
            bot.send_message(target, news)
            ok += 1
        except Exception:
            fail += 1
        time.sleep(0.05)

    bot.reply_to(message, f"✅ Надіслано: {ok}\n❌ Не вдалось: {fail}")


if __name__ == "__main__":
    print("Бот запущено...")
    bot.infinity_polling(skip_pending=True)
