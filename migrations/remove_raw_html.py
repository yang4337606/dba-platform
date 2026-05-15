"""
Migration script: Remove raw_html column from awr_reports table.

Usage:
    python migrations/remove_raw_html.py

This drops the raw_html TEXT column that stored full AWR HTML content (up to 50MB per row).
Reports now read HTML from the file_path on disk when re-parsing is needed.

Note: SQLite does not support DROP COLUMN directly (before 3.35.0).
For older SQLite, this script recreates the table without the column.
"""
import sqlite3
import os
import sys

# Resolve database path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'app', 'instance', 'app.db')

if not os.path.exists(DB_PATH):
    print(f"Database not found at {DB_PATH}, skipping migration.")
    sys.exit(0)

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Check if raw_html column exists
cursor.execute("PRAGMA table_info(awr_reports)")
columns = [row[1] for row in cursor.fetchall()]

if 'raw_html' not in columns:
    print("Column 'raw_html' does not exist in awr_reports. Nothing to do.")
    conn.close()
    sys.exit(0)

# Check SQLite version for DROP COLUMN support
sqlite_version = sqlite3.sqlite_version_info
if sqlite_version >= (3, 35, 0):
    print("Using ALTER TABLE DROP COLUMN (SQLite >= 3.35.0)")
    cursor.execute("ALTER TABLE awr_reports DROP COLUMN raw_html")
else:
    print(f"SQLite {sqlite3.sqlite_version} < 3.35.0, recreating table without raw_html")
    # Get current CREATE TABLE statement
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='awr_reports'")
    create_sql = cursor.fetchone()[0]

    # Build column list without raw_html
    cols_without = [c for c in columns if c != 'raw_html']
    cols_str = ', '.join(cols_without)

    cursor.execute("BEGIN TRANSACTION")
    cursor.execute(f"CREATE TABLE awr_reports_backup AS SELECT {cols_str} FROM awr_reports")
    cursor.execute("DROP TABLE awr_reports")
    cursor.execute(f"ALTER TABLE awr_reports_backup RENAME TO awr_reports")
    cursor.execute("COMMIT")

conn.commit()
conn.close()
print("Migration complete: raw_html column removed from awr_reports.")
