import logging
import os
import sqlite3
from typing import Any, Dict, Iterable, Optional

from qdp.color import RED, YELLOW

logger = logging.getLogger(__name__)

DOWNLOAD_COLUMNS = {
    "id": "TEXT UNIQUE NOT NULL",
    "item_type": "TEXT DEFAULT 'album'",
    "album_id": "TEXT",
    "local_path": "TEXT",
    "expected_tracks": "INTEGER",
    "matched_tracks": "INTEGER",
    "last_checked": "TEXT",
    "integrity_status": "TEXT DEFAULT 'unknown'",
    "folder_format": "TEXT",
    "track_format": "TEXT",
    "source_quality": "TEXT",
    "actual_quality": "TEXT",
    "bit_depth": "INTEGER",
    "sampling_rate": "REAL",
    "sidecar_path": "TEXT",
}


def _connect(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return sqlite3.connect(db_path)


def _ensure_schema(conn):
    try:
        conn.execute("CREATE TABLE downloads (id TEXT UNIQUE NOT NULL);")
        logger.info(f"{YELLOW}Download-IDs database created")
    except sqlite3.OperationalError:
        pass

    existing = {
        row[1] for row in conn.execute("PRAGMA table_info(downloads)").fetchall()
    }
    for column, column_def in DOWNLOAD_COLUMNS.items():
        if column in existing:
            continue
        if column == "id":
            continue
        conn.execute(f"ALTER TABLE downloads ADD COLUMN {column} {column_def}")
    conn.commit()


def create_db(db_path):
    with _connect(db_path) as conn:
        _ensure_schema(conn)
        return db_path


def _normalize_payload(item_id: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    normalized = {"id": str(item_id)}
    if payload:
        normalized.update({k: v for k, v in payload.items() if k in DOWNLOAD_COLUMNS and k != "id"})
    if not normalized.get("album_id"):
        normalized["album_id"] = str(item_id)
    return normalized


def upsert_download_entry(db_path: str, item_id: str, payload: Optional[Dict[str, Any]] = None):
    if not db_path:
        return
    normalized = _normalize_payload(item_id, payload)
    columns = list(normalized.keys())
    values = [normalized[column] for column in columns]
    placeholders = ", ".join("?" for _ in columns)
    update_clause = ", ".join(f"{column}=excluded.{column}" for column in columns if column != "id")
    sql = (
        f"INSERT INTO downloads ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {update_clause or 'id=excluded.id'}"
    )
    with _connect(db_path) as conn:
        _ensure_schema(conn)
        try:
            conn.execute(sql, values)
            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"{RED}Unexpected DB error: {e}")


def handle_download_id(db_path, item_id, add_id=False):
    if not db_path:
        return

    with _connect(db_path) as conn:
        _ensure_schema(conn)
        if add_id:
            upsert_download_entry(db_path, item_id)
        else:
            row = conn.execute(
                "SELECT * FROM downloads WHERE id=?",
                (str(item_id),),
            ).fetchone()
            return row


def get_download_entry(db_path: str, item_id: str) -> Optional[Dict[str, Any]]:
    if not db_path:
        return None
    with _connect(db_path) as conn:
        _ensure_schema(conn)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM downloads WHERE id=?", (str(item_id),)).fetchone()
        return dict(row) if row else None


def iter_download_entries(db_path: str) -> Iterable[Dict[str, Any]]:
    if not db_path or not os.path.exists(db_path):
        return []
    with _connect(db_path) as conn:
        _ensure_schema(conn)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM downloads ORDER BY COALESCE(last_checked, '') DESC, id ASC").fetchall()
        return [dict(row) for row in rows]


def remove_download_id(db_path, item_id):
    if not db_path:
        return False

    with _connect(db_path) as conn:
        _ensure_schema(conn)
        try:
            cursor = conn.execute("DELETE FROM downloads WHERE id=?", (str(item_id),))
            conn.commit()
            if cursor.rowcount:
                logger.info("Reset stale DB record: %s", item_id)
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.warning("Failed to remove download id %s: %s", item_id, e)
            return False
