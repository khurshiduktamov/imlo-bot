"""SQLite storage for users, chats, per-user settings and activity events.

Tables
  users  - one row per Telegram user (ids, names, settings, counters)
  chats  - one row per chat the bot was used in (private chats and groups)
  events - one row per interaction, used for active-user statistics
"""
import csv
import io
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

DB_PATH = os.getenv("DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "bot.db")
TASHKENT = timezone(timedelta(hours=5))
DAY = 86400

_conn = None


def conn():
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, isolation_level=None)  # autocommit
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id       INTEGER PRIMARY KEY,
                username      TEXT,
                first_name    TEXT,
                last_name     TEXT,
                language_code TEXT,
                is_premium    INTEGER DEFAULT 0,
                latin_variant TEXT    DEFAULT 'new',
                first_seen    INTEGER NOT NULL,
                last_seen     INTEGER NOT NULL,
                blocked       INTEGER DEFAULT 0,
                texts         INTEGER DEFAULT 0,
                files         INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS chats (
                chat_id    INTEGER PRIMARY KEY,
                type       TEXT,
                title      TEXT,
                first_seen INTEGER NOT NULL,
                last_seen  INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                ts      INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                chat_id INTEGER,
                kind    TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
            CREATE INDEX IF NOT EXISTS events_user_ts ON events(user_id, ts);
        """)
        # columns added after the first release
        existing = {r["name"] for r in _conn.execute("PRAGMA table_info(users)")}
        if "mode" not in existing:
            _conn.execute("ALTER TABLE users ADD COLUMN mode TEXT DEFAULT 'check'")
    return _conn


def track(user, chat, kind):
    """Record an interaction. user/chat are aiogram User/Chat objects (chat may be None)."""
    now = int(time.time())
    c = conn()
    c.execute("""
        INSERT INTO users (user_id, username, first_name, last_name, language_code, is_premium,
                           first_seen, last_seen, texts, files)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username, first_name=excluded.first_name,
            last_name=excluded.last_name, language_code=excluded.language_code,
            is_premium=excluded.is_premium, last_seen=excluded.last_seen, blocked=0,
            texts=texts + excluded.texts, files=files + excluded.files
    """, (user.id, user.username, user.first_name, user.last_name, user.language_code,
          int(bool(user.is_premium)), now, now, int(kind == "text"), int(kind == "file")))
    if chat is not None:
        c.execute("""
            INSERT INTO chats (chat_id, type, title, first_seen, last_seen) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET type=excluded.type, title=excluded.title,
                                               last_seen=excluded.last_seen
        """, (chat.id, chat.type, chat.title, now, now))
    c.execute("INSERT INTO events (ts, user_id, chat_id, kind) VALUES (?, ?, ?, ?)",
              (now, user.id, chat.id if chat else None, kind))


def set_blocked(user_id, blocked):
    conn().execute("UPDATE users SET blocked=? WHERE user_id=?", (int(blocked), user_id))


def get_latin_variant(user_id):
    row = conn().execute("SELECT latin_variant FROM users WHERE user_id=?", (user_id,)).fetchone()
    return row["latin_variant"] if row and row["latin_variant"] in ("new", "old") else "new"


def set_latin_variant(user_id, variant):
    conn().execute("UPDATE users SET latin_variant=? WHERE user_id=?", (variant, user_id))


def get_mode(user_id):
    """What plain text messages do: 'check' (spell check) or 'convert' (change alphabet)."""
    row = conn().execute("SELECT mode FROM users WHERE user_id=?", (user_id,)).fetchone()
    return row["mode"] if row and row["mode"] in ("check", "convert") else "check"


def set_mode(user_id, mode):
    conn().execute("UPDATE users SET mode=? WHERE user_id=?", (mode, user_id))


def _one(sql, *args):
    return conn().execute(sql, args).fetchone()[0]


def stats():
    now = int(time.time())
    c = conn()
    s = {
        "users": _one("SELECT COUNT(*) FROM users"),
        "blocked": _one("SELECT COUNT(*) FROM users WHERE blocked=1"),
        "groups": _one("SELECT COUNT(*) FROM chats WHERE type IN ('group', 'supergroup')"),
        "latin_old": _one("SELECT COUNT(*) FROM users WHERE latin_variant='old'"),
    }
    for label, days in (("1d", 1), ("7d", 7), ("30d", 30)):
        since = now - days * DAY
        s[f"active_{label}"] = _one("SELECT COUNT(DISTINCT user_id) FROM events WHERE ts>=?", since)
        s[f"new_{label}"] = _one("SELECT COUNT(*) FROM users WHERE first_seen>=?", since)
        s[f"texts_{label}"] = _one("SELECT COUNT(*) FROM events WHERE ts>=? AND kind='text'", since)
        s[f"files_{label}"] = _one("SELECT COUNT(*) FROM events WHERE ts>=? AND kind='file'", since)

    # daily active users for the last 14 days (Tashkent time)
    today = datetime.now(TASHKENT).date()
    start = datetime.combine(today - timedelta(days=13), datetime.min.time(), TASHKENT)
    rows = c.execute("""
        SELECT date(ts + 5*3600, 'unixepoch') AS day, COUNT(DISTINCT user_id) AS dau
        FROM events WHERE ts>=? GROUP BY day
    """, (int(start.timestamp()),)).fetchall()
    by_day = {r["day"]: r["dau"] for r in rows}
    s["daily"] = [((today - timedelta(days=i)).isoformat(), by_day.get((today - timedelta(days=i)).isoformat(), 0))
                  for i in range(13, -1, -1)]
    s["tracking_since"] = _one("SELECT MIN(ts) FROM events")
    return s


def export_users_csv():
    rows = conn().execute("SELECT * FROM users ORDER BY last_seen DESC").fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    if rows:
        w.writerow(rows[0].keys())
    for r in rows:
        r = dict(r)
        for k in ("first_seen", "last_seen"):
            r[k] = datetime.fromtimestamp(r[k], TASHKENT).strftime("%Y-%m-%d %H:%M")
        w.writerow(r.values())
    return buf.getvalue().encode("utf-8-sig")  # BOM so Excel shows Cyrillic/Uzbek letters correctly
