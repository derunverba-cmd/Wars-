# -*- coding: utf-8 -*-
# Бот для війнушок в чаті
# Запуск на Railway: змінні BOT_TOKEN і DB_PATH (див. README)
import os
import random
import sqlite3
import threading
import time
import html

import telebot

TOKEN = os.environ["BOT_TOKEN"]  # токен беремо зі змінних Railway, не з коду
DB_PATH = os.environ.get("DB_PATH", "bot.db")  # на Railway: /data/bot.db (Volume)
ADMINS = {7660211311, 1642108682}

GIFT_COOLDOWN = 2 * 60 * 60   # подарунок раз на 2 години
BATTLE_COOLDOWN = 60          # битва раз на 60 секунд
STEAL_MIN, STEAL_MAX = 1, 3   # скільки сили забирає переможець

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

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
db = sqlite3.connect(DB_PATH, check_same_thread=False)
lock = threading.Lock()

with lock:
    db.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY,
        username TEXT,
        name TEXT,
        power INTEGER DEFAULT 0,
        last_gift REAL DEFAULT 0,
        last_battle REAL DEFAULT 0)""")
    db.execute("CREATE TABLE IF NOT EXISTS chats(id INTEGER PRIMARY KEY)")
    db.commit()


def get_level(power):
    for lvl, need in LEVELS:
        if power >= need:
            return lvl
    return 0


def next_need(power):
    for lvl, need in sorted(LEVELS, key=lambda x: x[1]):
        if power < need:
            return need
    return None


def save_user(u):
    with lock:
        db.execute(
            "INSERT OR IGNORE INTO users(id, username, name) VALUES(?,?,?)",
            (u.id, (u.username or "").lower(), u.first_name or ""))
        db.execute("UPDATE users SET username=?, name=? WHERE id=?",
                   ((u.username or "").lower(), u.first_name or "", u.id))
        db.commit()


def get_user(uid):
    with lock:
        return db.execute(
            "SELECT id, username, name, power, last_gift, last_battle FROM users WHERE id=?",
            (uid,)).fetchone()


def find_by_username(username):
    with lock:
        return db.execute(
            "SELECT id, username, name, power, last_gift, last_battle FROM users WHERE username=?",
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
    uid, username, name = row[0], row[1], row[2]
    return f'<a href="tg://user?id={uid}">{html.escape(name or "Гравець")}</a>'


@bot.message_handler(func=lambda m: True, content_types=["text"])
def on_text(message):
    u = message.from_user
    if u.is_bot:
        return
    save_user(u)

    if message.chat.type in ("group", "supergroup"):
        with lock:
            db.execute("INSERT OR IGNORE INTO chats(id) VALUES(?)", (message.chat.id,))
            db.commit()

    text = (message.text or "").strip()
    low = text.lower()
    first = low.split()[0] if low else ""
    first = first.split("@")[0]  # /news@botname -> /news

    if first in ("/start",):
        return cmd_start(message)
    if first == "/news":
        return cmd_news(message)
    if first in ("сила", "/power", "/sila"):
        return cmd_gift(message)
    if first in ("рівень", "рівень", "уровень", "/level", "/riven"):
        return cmd_level(message)
    if first in ("битва", "/battle", "/bytva"):
        return cmd_battle(message)


def cmd_start(message):
    bot.reply_to(
        message,
        "⚔️ <b>Привіт! Це бот для війнушок.</b>\n\n"
        "Додай мене в чат і пиши:\n"
        "• <b>Сила</b> — отримати подарунок (раз на 2 години)\n"
        "• <b>Рівень</b> — дізнатись свій рівень\n"
        "• <b>Битва</b> — відповідай цим словом на повідомлення "
        "суперника (або <b>Битва @username</b>)\n\n"
        "Чим більше сили — тим вищий рівень і більше шансів на перемогу!")


def cmd_gift(message):
    u = message.from_user
    row = get_user(u.id)
    now = time.time()
    left = row[4] + GIFT_COOLDOWN - now
    if left > 0:
        bot.reply_to(message, f"⏳ Наступний подарунок через <b>{fmt_time(left)}</b>")
        return

    old_power = row[3]
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
    bot.reply_to(message, msg)


def cmd_level(message):
    row = get_user(message.from_user.id)
    power = row[3]
    lvl = get_level(power)
    msg = f"🏅 Твій рівень: <b>{lvl}</b>\n💪 Сила: <b>{power}</b>"
    need = next_need(power)
    if need:
        msg += f"\n📈 До наступного рівня: ще <b>{need - power}</b> сили"
    else:
        msg += "\n👑 Максимальний рівень!"
    bot.reply_to(message, msg)


def cmd_battle(message):
    if message.chat.type == "private":
        bot.reply_to(message, "⚔️ Битви працюють тільки в груповому чаті.")
        return

    me = get_user(message.from_user.id)
    now = time.time()
    left = me[5] + BATTLE_COOLDOWN - now
    if left > 0:
        bot.reply_to(message, f"⏳ Відпочинь ще <b>{fmt_time(left)}</b> перед новою битвою")
        return

    # шукаємо суперника: через відповідь або @username
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
    if enemy[0] == me[0]:
        bot.reply_to(message, "Сам з собою битись не можна 😄")
        return

    p1, p2 = me[3], enemy[3]
    chance = 0.5 if p1 + p2 == 0 else p1 / (p1 + p2)
    win = random.random() < chance

    winner, loser = (me, enemy) if win else (enemy, me)
    steal = min(random.randint(STEAL_MIN, STEAL_MAX), loser[3])
    set_power(winner[0], winner[3] + steal)
    set_power(loser[0], loser[3] - steal)
    with lock:
        db.execute("UPDATE users SET last_battle=? WHERE id=?", (now, me[0]))
        db.commit()

    bot.reply_to(
        message,
        f"⚔️ <b>БИТВА!</b>\n"
        f"{mention(me)} (💪{p1}, шанс {chance * 100:.0f}%) VS "
        f"{mention(enemy)} (💪{p2}, шанс {(1 - chance) * 100:.0f}%)\n\n"
        f"🏆 Перемагає {mention(winner)} і забирає <b>{steal}</b> сили!")


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
        user_ids = [r[0] for r in db.execute("SELECT id FROM users").fetchall()]
        chat_ids = [r[0] for r in db.execute("SELECT id FROM chats").fetchall()]

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
