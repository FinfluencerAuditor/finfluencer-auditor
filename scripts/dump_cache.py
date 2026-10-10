"""Utility script to dump the SQLite api_cache table into fixtures/serp_cache.json."""

import json
import os
import sqlite3
from pathlib import Path

DB_PATH = os.getenv("AUDITOR_DB_PATH", "data/auditor.sqlite3")
FIXTURES_PATH = Path("fixtures/serp_cache.json")


def dump_cache():
    if not Path(DB_PATH).exists():
        print(f"Database {DB_PATH} does not exist.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        rows = cursor.execute("SELECT cache_key, response_json FROM api_cache").fetchall()
        cache_data = {}
        for k, v in rows:
            try:
                cache_data[k] = json.loads(v)
            except Exception:
                cache_data[k] = v

        FIXTURES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(FIXTURES_PATH, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2, ensure_ascii=False)
        print(f"Successfully exported {len(cache_data)} cached SerpApi entries to {FIXTURES_PATH}")
    finally:
        conn.close()


if __name__ == "__main__":
    dump_cache()
