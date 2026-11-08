"""Publishing queue (SQLite, local file publish.db, never committed).

One row = one video on one channel. Status flow:
  needs_review -> (approve) -> queued -> sent        (sent = handed to Postiz with a schedule date)
  failed / skipped are terminal until you re-enqueue or approve again.
"""
import os
import json
import sqlite3
import datetime
import contextlib

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get('PUBLISH_DB') or os.path.join(HERE, 'publish.db')

SCHEMA = '''CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT NOT NULL, channel TEXT NOT NULL, file TEXT NOT NULL,
  title TEXT, caption TEXT, status TEXT NOT NULL, scheduled_at TEXT, postiz_id TEXT, error TEXT, verify TEXT,
  created TEXT, updated TEXT, UNIQUE(video_id, channel))'''


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


@contextlib.contextmanager
def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    try:
        c.execute(SCHEMA)
        yield c
        c.commit()
    finally:
        c.close()


def insert(video_id, channel, file, title, caption, status, verify):
    with conn() as c:
        try:
            c.execute('INSERT INTO posts(video_id,channel,file,title,caption,status,verify,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                      (video_id, channel, file, title, caption, status, json.dumps(verify, ensure_ascii=False), now_iso(), now_iso()))
            return True
        except sqlite3.IntegrityError:
            return False


def update(row_id, **kw):
    kw['updated'] = now_iso()
    sets = ','.join(f'{k}=?' for k in kw)
    with conn() as c:
        c.execute(f'UPDATE posts SET {sets} WHERE id=?', (*kw.values(), row_id))


def rows(where='1=1', args=()):
    with conn() as c:
        return [dict(r) for r in c.execute(f'SELECT * FROM posts WHERE {where} ORDER BY id', args).fetchall()]
