#!/usr/bin/env python3
"""Small Kaizen web server: static files, account sessions, and SQLite storage."""

import argparse
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "public"
DB_PATH = Path(os.environ.get("KAIZEN_DB", ROOT / "data" / "kaizen.db"))
DATABASE_URL = os.environ.get("DATABASE_URL", "")
SESSION_SECONDS = 60 * 60 * 24 * 30
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FAKE_SALT = bytes.fromhex("8fce59d75a7e2f31a512b96f015ffd8d")
_db_ready = False
_db_lock = threading.Lock()


class Database:
    def __init__(self):
        self.postgres = bool(DATABASE_URL)
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row
            self.connection = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        else:
            self.connection = sqlite3.connect(DB_PATH, timeout=10)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys = ON")

    def execute(self, query, parameters=()):
        if self.postgres:
            query = query.replace("?", "%s")
        return self.connection.execute(query, parameters)

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, *args):
        return self.connection.__exit__(*args)


def connect():
    return Database()


def init_db():
    global _db_ready
    with _db_lock:
        if _db_ready:
            return
        if not DATABASE_URL:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        primary_key = "BIGSERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY"
        binary = "BYTEA" if DATABASE_URL else "BLOB"
        email = "TEXT NOT NULL UNIQUE" if DATABASE_URL else "TEXT NOT NULL UNIQUE COLLATE NOCASE"
        statements = [
            f"CREATE TABLE IF NOT EXISTS users (id {primary_key}, email {email}, password_hash {binary} NOT NULL, password_salt {binary} NOT NULL, created_at BIGINT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS user_data (user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, data TEXT NOT NULL, updated_at BIGINT NOT NULL)",
            f"CREATE TABLE IF NOT EXISTS sessions (token_hash {binary} PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, csrf_token TEXT NOT NULL, expires_at BIGINT NOT NULL)",
            "CREATE INDEX IF NOT EXISTS sessions_user_id ON sessions(user_id)",
        ]
        with connect() as db:
            for statement in statements:
                db.execute(statement)
        _db_ready = True


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)


def empty_data():
    return {"habits": [], "days": {}, "settings": {"theme": "light"}}


def validate_data(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid data.")
    habits = value.get("habits")
    days = value.get("days")
    settings = value.get("settings")
    if not isinstance(habits, list) or len(habits) > 200 or not isinstance(days, dict) or len(days) > 4000:
        raise ValueError("Invalid data.")

    clean_habits = []
    for habit in habits:
        if not isinstance(habit, dict):
            raise ValueError("Invalid habit.")
        habit_id, name, created = habit.get("id"), habit.get("name"), habit.get("createdAt")
        if not isinstance(habit_id, str) or not 1 <= len(habit_id) <= 64:
            raise ValueError("Invalid habit ID.")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ValueError("Habit names must contain 1–80 characters.")
        if not isinstance(created, str) or not DATE_RE.fullmatch(created):
            raise ValueError("Invalid creation date.")
        clean_habits.append({"id": habit_id, "name": name.strip(), "createdAt": created})

    clean_days = {}
    for date, day in days.items():
        if not isinstance(date, str) or not DATE_RE.fullmatch(date) or not isinstance(day, dict):
            raise ValueError("Invalid daily record.")
        completed, reflection, total = day.get("completed", []), day.get("reflection", ""), day.get("total", 0)
        if not isinstance(completed, list) or len(completed) > 200 or not all(isinstance(item, str) and len(item) <= 64 for item in completed):
            raise ValueError("Invalid completed habits.")
        if not isinstance(reflection, str) or len(reflection) > 500:
            raise ValueError("Reflections can contain at most 500 characters.")
        if not isinstance(total, int) or isinstance(total, bool) or not 0 <= total <= 200:
            raise ValueError("Invalid daily total.")
        clean_days[date] = {"completed": list(dict.fromkeys(completed)), "reflection": reflection, "total": total}

    theme = settings.get("theme") if isinstance(settings, dict) else None
    if theme not in ("light", "dark"):
        raise ValueError("Invalid theme.")
    return {"habits": clean_habits, "days": clean_days, "settings": {"theme": theme}}


class KaizenHandler(BaseHTTPRequestHandler):
    server_version = "Kaizen/1.0"

    def route(self):
        return getattr(self, "route_path", urlparse(self.path).path)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        super().end_headers()

    def json_response(self, status, payload, cookie=None):
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("Invalid request.") from error
        if length < 2 or length > 1_000_000:
            raise ValueError("Invalid request size.")
        try:
            return json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Invalid JSON.") from error

    def current_session(self):
        cookies = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookies.get("kaizen_session")
        if not morsel:
            return None
        token_hash = hashlib.sha256(morsel.value.encode()).digest()
        with connect() as db:
            return db.execute("""
                SELECT sessions.token_hash, sessions.user_id, sessions.csrf_token, users.email
                FROM sessions JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ? AND sessions.expires_at > ?
            """, (token_hash, int(time.time()))).fetchone()

    def require_session(self, csrf=False):
        session = self.current_session()
        if not session:
            self.json_response(401, {"error": "Please log in."})
            return None
        if csrf and not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), session["csrf_token"]):
            self.json_response(403, {"error": "Invalid security token."})
            return None
        return session

    def create_session(self, user_id, email):
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        expires = int(time.time()) + SESSION_SECONDS
        with connect() as db:
            db.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
            db.execute("INSERT INTO sessions (token_hash, user_id, csrf_token, expires_at) VALUES (?, ?, ?, ?)",
                       (hashlib.sha256(token.encode()).digest(), user_id, csrf, expires))
        secure = "; Secure" if os.environ.get("KAIZEN_SECURE_COOKIE") == "1" or os.environ.get("VERCEL") else ""
        cookie = f"kaizen_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_SECONDS}{secure}"
        self.json_response(200, {"email": email, "csrfToken": csrf}, cookie)

    def do_GET(self):
        init_db()
        path = self.route()
        if path == "/api/session":
            session = self.require_session()
            if session:
                self.json_response(200, {"email": session["email"], "csrfToken": session["csrf_token"]})
            return
        if path == "/api/data":
            session = self.require_session()
            if not session:
                return
            with connect() as db:
                row = db.execute("SELECT data FROM user_data WHERE user_id = ?", (session["user_id"],)).fetchone()
            self.json_response(200, {"data": json.loads(row["data"]) if row else empty_data()})
            return
        self.serve_static(path)

    def do_POST(self):
        init_db()
        path = self.route()
        try:
            if path in ("/api/register", "/api/login"):
                payload = self.read_json()
                self.authenticate(path, payload)
                return
            if path == "/api/logout":
                session = self.require_session(csrf=True)
                if not session:
                    return
                with connect() as db:
                    db.execute("DELETE FROM sessions WHERE token_hash = ?", (session["token_hash"],))
                self.json_response(200, {"ok": True}, "kaizen_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0")
                return
            self.json_response(404, {"error": "Not found."})
        except ValueError as error:
            self.json_response(400, {"error": str(error)})

    def authenticate(self, path, payload):
        email = payload.get("email", "").strip().lower() if isinstance(payload, dict) else ""
        password = payload.get("password", "") if isinstance(payload, dict) else ""
        if len(email) > 254 or not EMAIL_RE.fullmatch(email):
            raise ValueError("Enter a valid email address.")
        if not isinstance(password, str) or not 8 <= len(password) <= 128:
            raise ValueError("Password must contain 8–128 characters.")

        if path == "/api/register":
            salt = secrets.token_bytes(16)
            try:
                with connect() as db:
                    cursor = db.execute("INSERT INTO users (email, password_hash, password_salt, created_at) VALUES (?, ?, ?, ?) RETURNING id",
                                        (email, password_hash(password, salt), salt, int(time.time())))
                    user_id = cursor.fetchone()["id"]
                    db.execute("INSERT INTO user_data (user_id, data, updated_at) VALUES (?, ?, ?)",
                               (user_id, json.dumps(empty_data()), int(time.time())))
            except Exception as error:
                if error.__class__.__name__ not in ("IntegrityError", "UniqueViolation"):
                    raise
                self.json_response(409, {"error": "An account with that email already exists."})
                return
            self.create_session(user_id, email)
            return

        with connect() as db:
            user = db.execute("SELECT id, email, password_hash, password_salt FROM users WHERE email = ?", (email,)).fetchone()
        candidate = password_hash(password, user["password_salt"] if user else FAKE_SALT)
        if not user or not hmac.compare_digest(candidate, user["password_hash"]):
            self.json_response(401, {"error": "Invalid email or password."})
            return
        self.create_session(user["id"], user["email"])

    def do_PUT(self):
        init_db()
        if self.route() != "/api/data":
            self.json_response(404, {"error": "Not found."})
            return
        session = self.require_session(csrf=True)
        if not session:
            return
        try:
            payload = self.read_json()
            data = validate_data(payload.get("data") if isinstance(payload, dict) else None)
        except ValueError as error:
            self.json_response(400, {"error": str(error)})
            return
        with connect() as db:
            db.execute("UPDATE user_data SET data = ?, updated_at = ? WHERE user_id = ?",
                       (json.dumps(data, separators=(",", ":")), int(time.time()), session["user_id"]))
        self.json_response(200, {"ok": True})

    def serve_static(self, request_path):
        relative = "index.html" if request_path == "/" else request_path.lstrip("/")
        target = (STATIC_ROOT / relative).resolve()
        public = relative == "index.html" or relative.startswith(("css/", "js/", "assets/"))
        if not public or not target.is_relative_to(STATIC_ROOT) or not target.is_file():
            self.json_response(404, {"error": "Not found."})
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Kaizen web application.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    init_db()
    print(f"Kaizen is running at http://{args.host}:{args.port}")
    ThreadingHTTPServer((args.host, args.port), KaizenHandler).serve_forever()
