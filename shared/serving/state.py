"""Private durable policy and operation records; live task handles are never persisted."""
import json
import os
from pathlib import Path
import sqlite3
import time


def state_directory(reg):
    mount = '/mnt/AI_Models' if reg['aliases'][0] == 'geekom' else '/mnt/xfs/AI_Models'
    return Path(os.getenv('LARIO_CONTROL_STATE', mount+'/control'))/reg['aliases'][0]


def off_marker(reg):
    return state_directory(reg)/'off'


class Store:
    def __init__(self, directory, legacy):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        path = self.directory/'state.sqlite3'
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, request TEXT, result TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS cancelled (id TEXT PRIMARY KEY, created REAL)')
        if self.get('policy') is None:
            self.put('policy', {'revision': 1, 'paused': False, 'disabled': [], 'legacy': legacy})

    def get(self, key):
        row = self.db.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO kv VALUES (?,?)', (key, json.dumps(value)))

    def change(self, **updates):
        policy = self.get('policy')
        policy.update(updates)
        policy['revision'] += 1
        self.put('policy', policy)
        return policy

    def tombstone(self, run):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO cancelled VALUES (?,?)', (run, time.time()))

    def cancelled(self, run):
        return bool(self.db.execute('SELECT 1 FROM cancelled WHERE id=?', (run,)).fetchone())

    def close(self):
        self.db.close()
