import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from server.config import (
    CREATE_DEFAULT_ADMIN,
    DATABASE_PATH,
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_USERNAME,
    SESSION_TTL_SECONDS,
)


def _utc_now():
    return datetime.now(timezone.utc)


def _utc_iso():
    return _utc_now().isoformat().replace("+00:00", "Z")


def _parse_utc(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def get_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(get_connection()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (username) REFERENCES users(username)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_history (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                action TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS column_metadata (
                username TEXT NOT NULL,
                column_name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                semantic_role TEXT NOT NULL DEFAULT 'unspecified',
                class_descriptions_json TEXT NOT NULL DEFAULT '{}',
                source_column TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (username, column_name),
                FOREIGN KEY (username) REFERENCES users(username)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_state (
                username TEXT NOT NULL,
                state_key TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (username, state_key),
                FOREIGN KEY (username) REFERENCES users(username)
            )
            """
        )
        column_info = conn.execute("PRAGMA table_info(column_metadata)").fetchall()
        existing_columns = {row["name"] for row in column_info}
        if "source_column" not in existing_columns:
            conn.execute("ALTER TABLE column_metadata ADD COLUMN source_column TEXT NOT NULL DEFAULT ''")
        conn.commit()

    if CREATE_DEFAULT_ADMIN and DEFAULT_ADMIN_PASSWORD:
        create_user(DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD, allow_existing=True)


def create_user(username, password, allow_existing=False):
    username = username.strip().lower()
    now = _utc_iso()
    password_hash = generate_password_hash(password)
    try:
        with closing(get_connection()) as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, password_hash, now),
            )
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        if allow_existing:
            return False
        raise


def get_user(username):
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT username, password_hash FROM users WHERE username = ?",
            (username.strip().lower(),),
        ).fetchone()
    return row


def validate_user(username, password):
    user = get_user(username)
    if not user:
        return False
    return check_password_hash(user["password_hash"], password)


def save_session(token, username):
    now = _utc_iso()
    with closing(get_connection()) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO sessions (token, username, created_at) VALUES (?, ?, ?)",
            (token, username.strip().lower(), now),
        )
        conn.commit()


def get_session_username(token):
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT username, created_at FROM sessions WHERE token = ?",
            (token,),
        ).fetchone()
    if not row:
        return None
    created_at = _parse_utc(row["created_at"])
    if SESSION_TTL_SECONDS > 0 and _utc_now() - created_at > timedelta(seconds=SESSION_TTL_SECONDS):
        delete_session(token)
        return None
    return row["username"]


def delete_session(token):
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()


def save_history(history_id, username, action, payload, created_at):
    with closing(get_connection()) as conn:
        conn.execute(
            """
            INSERT INTO analysis_history (id, username, action, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (history_id, username, action, json.dumps(payload), created_at),
        )
        conn.commit()


def get_history(username, limit=100):
    with closing(get_connection()) as conn:
        rows = conn.execute(
            """
            SELECT id, username, action, payload_json, created_at
            FROM analysis_history
            WHERE username = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (username, int(limit)),
        ).fetchall()

    items = []
    for row in rows:
        items.append(
            {
                "id": row["id"],
                "username": row["username"],
                "action": row["action"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
        )
    return items


def save_column_metadata(
    username,
    column_name,
    description,
    semantic_role,
    class_descriptions,
    source_column="",
):
    now = _utc_iso()
    payload = json.dumps(class_descriptions, ensure_ascii=False)
    with closing(get_connection()) as conn:
        conn.execute(
            """
            INSERT INTO column_metadata (
                username, column_name, description, semantic_role,
                class_descriptions_json, source_column, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(username, column_name) DO UPDATE SET
                description = excluded.description,
                semantic_role = excluded.semantic_role,
                class_descriptions_json = excluded.class_descriptions_json,
                source_column = excluded.source_column,
                updated_at = excluded.updated_at
            """,
            (
                username.strip().lower(),
                column_name,
                description,
                semantic_role,
                payload,
                str(source_column or "").strip(),
                now,
            ),
        )
        conn.commit()


def get_column_metadata(username, column_name):
    with closing(get_connection()) as conn:
        row = conn.execute(
            """
            SELECT column_name, description, semantic_role, class_descriptions_json, source_column, updated_at
            FROM column_metadata
            WHERE username = ? AND column_name = ?
            """,
            (username.strip().lower(), column_name),
        ).fetchone()
    if not row:
        return None
    return {
        "column": row["column_name"],
        "description": row["description"],
        "semantic_role": row["semantic_role"],
        "class_descriptions": json.loads(row["class_descriptions_json"]),
        "source_column": row["source_column"],
        "updated_at": row["updated_at"],
    }


def get_all_column_metadata(username):
    with closing(get_connection()) as conn:
        rows = conn.execute(
            """
            SELECT column_name, description, semantic_role, class_descriptions_json, source_column, updated_at
            FROM column_metadata
            WHERE username = ?
            ORDER BY column_name ASC
            """,
            (username.strip().lower(),),
        ).fetchall()
    return {
        row["column_name"]: {
            "column": row["column_name"],
            "description": row["description"],
            "semantic_role": row["semantic_role"],
            "class_descriptions": json.loads(row["class_descriptions_json"]),
            "source_column": row["source_column"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    }


def prune_column_metadata(username, valid_columns):
    placeholders = ",".join("?" for _ in valid_columns)
    with closing(get_connection()) as conn:
        if valid_columns:
            conn.execute(
                f"""
                DELETE FROM column_metadata
                WHERE username = ? AND column_name NOT IN ({placeholders})
                """,
                (username.strip().lower(), *valid_columns),
            )
        else:
            conn.execute(
                "DELETE FROM column_metadata WHERE username = ?",
                (username.strip().lower(),),
            )
        conn.commit()


def save_analysis_state(username, state_key, payload):
    now = _utc_iso()
    payload_json = json.dumps(payload, ensure_ascii=False)
    with closing(get_connection()) as conn:
        conn.execute(
            """
            INSERT INTO analysis_state (username, state_key, payload_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(username, state_key) DO UPDATE SET
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (username.strip().lower(), state_key, payload_json, now),
        )
        conn.commit()


def get_analysis_state(username, state_key):
    with closing(get_connection()) as conn:
        row = conn.execute(
            """
            SELECT payload_json, updated_at
            FROM analysis_state
            WHERE username = ? AND state_key = ?
            """,
            (username.strip().lower(), state_key),
        ).fetchone()
    if not row:
        return None
    return {
        "payload": json.loads(row["payload_json"]),
        "updated_at": row["updated_at"],
    }


def delete_analysis_states(username, state_keys=None):
    username = username.strip().lower()
    with closing(get_connection()) as conn:
        if state_keys:
            placeholders = ",".join("?" for _ in state_keys)
            conn.execute(
                f"DELETE FROM analysis_state WHERE username = ? AND state_key IN ({placeholders})",
                (username, *state_keys),
            )
        else:
            conn.execute("DELETE FROM analysis_state WHERE username = ?", (username,))
        conn.commit()
