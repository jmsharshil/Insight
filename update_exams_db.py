import sqlite3
import sys

try:
    conn = sqlite3.connect('db.sqlite3')
    conn.execute('ALTER TABLE exams ADD COLUMN reminder_1d_sent boolean NOT NULL DEFAULT 0;')
    conn.execute('ALTER TABLE exams ADD COLUMN reminder_1h_sent boolean NOT NULL DEFAULT 0;')
    conn.commit()
    print("Success")
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
