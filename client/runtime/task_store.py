"""SQLite scheduling ledger; committed intent is not proof of business execution."""
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from shared.scheduling import validate_trigger, next_fire, due_occurrence, latest_fire

UTC = timezone.utc
TERMINAL = {'success', 'failed', 'cancelled', 'unknown', 'skipped'}


class TaskStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                enabled INTEGER NOT NULL, body TEXT NOT NULL, next_fire TEXT);
            CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, task_id TEXT, revision INTEGER,
                scheduled_for TEXT, request_id TEXT, state TEXT NOT NULL, body TEXT NOT NULL,
                error_msg TEXT, created_at TEXT NOT NULL,
                UNIQUE(task_id, revision, scheduled_for), UNIQUE(task_id, request_id));
            CREATE TABLE IF NOT EXISTS attempts(execution_id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL,
                state TEXT NOT NULL, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS outbox(key TEXT PRIMARY KEY, route TEXT NOT NULL, body TEXT NOT NULL);
        ''')
        self.db.execute('CREATE INDEX IF NOT EXISTS tasks_due ON tasks(enabled,next_fire)')
        self.db.commit()

    def tasks(self):
        with self.lock:
            return [dict(json.loads(r['body']), id=r['id'], revision=r['revision'],
                         enabled=bool(r['enabled']), next_fire_at=r['next_fire'])
                    for r in self.db.execute('SELECT * FROM tasks ORDER BY rowid DESC')]

    def events(self):
        with self.lock:
            return [dict(r, body=json.loads(r['body'])) for r in self.db.execute(
                'SELECT * FROM events ORDER BY created_at DESC LIMIT 500')]

    def create(self, body, now=None):
        now = now or datetime.now(UTC)
        body = dict(body)
        body['trigger'] = validate_trigger(body['trigger'])
        ident = str(uuid.uuid4())
        trigger = body['trigger']
        fire = next_fire(trigger, now)
        # once in the past still produces a visible skipped/run_once occurrence.
        if trigger['kind'] == 'once':
            fire = datetime.fromisoformat(trigger['start_at']).astimezone(UTC)
        with self.lock, self.db:
            self.db.execute('INSERT INTO tasks VALUES(?,1,1,?,?)',
                            (ident, json.dumps(body), fire.astimezone(UTC).isoformat() if fire else None))
        return next(t for t in self.tasks() if t['id'] == ident)

    def action(self, ident, body, now=None):
        now = now or datetime.now(UTC)
        with self.lock, self.db:
            row = self.db.execute('SELECT * FROM tasks WHERE id=?', (ident,)).fetchone()
            if row is None:
                raise ValueError('本机任务不存在')
            action = body.get('action')
            if action == 'run':
                if not row['enabled']:
                    raise ValueError('任务已暂停，请核对设备状态并恢复后再运行')
                request_id = str(uuid.UUID(str(body.get('request_id', ''))))
                return self._event(row, None, now, request_id)
            if action not in ('pause', 'resume', 'delete'):
                raise ValueError('无效任务操作')
            if action in ('pause', 'delete'):
                self.db.execute("UPDATE events SET state='cancelled' WHERE task_id=? AND state='queued'", (ident,))
                self.db.execute("UPDATE events SET state='cancel_requested' WHERE task_id=? AND state IN ('preparing','running')", (ident,))
            if action == 'resume':
                trigger = json.loads(row['body'])['trigger']
                fire = next_fire(trigger, now)
                self.db.execute('UPDATE tasks SET next_fire=? WHERE id=?',
                                (fire.astimezone(UTC).isoformat() if fire else None, ident))
            if action == 'delete':
                self.db.execute('DELETE FROM tasks WHERE id=?', (ident,))
            else:
                self.db.execute('UPDATE tasks SET enabled=? WHERE id=?', (action == 'resume', ident))
            return {'id': ident, 'action': action}

    def _event(self, row, fire, now, request_id=None, state='queued'):
        ident = 'S' + str(uuid.uuid4())
        stamp = fire.astimezone(UTC).isoformat() if fire else None
        self.db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?,?,?)',
                        (ident, row['id'], row['revision'], stamp, request_id, state,
                         row['body'], '错过触发窗口；不会唤醒休眠机' if state == 'skipped' else None, now.isoformat()))
        result = self.db.execute('SELECT * FROM events WHERE task_id=? AND '
                                 + ('request_id=?' if request_id else 'revision=? AND scheduled_for=?'),
                                 (row['id'], request_id) if request_id else (row['id'], row['revision'], stamp)).fetchone()
        return dict(result)

    def tick(self, now=None):
        now = now or datetime.now(UTC)
        with self.lock, self.db:
            rows = self.db.execute('SELECT * FROM tasks WHERE enabled=1 AND next_fire<=?',
                                   (now.astimezone(UTC).isoformat(),)).fetchall()
            for row in rows:
                fire = datetime.fromisoformat(row['next_fire'])
                if fire > now:
                    continue
                trigger = json.loads(row['body'])['trigger']
                if trigger['kind'] in ('daily', 'weekly'):
                    candidate = latest_fire(trigger, now)
                    if candidate and candidate > fire:
                        fire = candidate
                self._event(row, fire, now, state='queued' if due_occurrence(trigger, fire, now) else 'skipped')
                future = next_fire(trigger, now)
                self.db.execute('UPDATE tasks SET next_fire=? WHERE id=?',
                                (future.astimezone(UTC).isoformat() if future else None, row['id']))

    def queued(self):
        with self.lock:
            return [dict(r, body=json.loads(r['body'])) for r in self.db.execute(
                "SELECT * FROM events WHERE state='queued' ORDER BY created_at LIMIT 1")]

    def close(self):
        with self.lock:
            self.db.close()

    def attempts(self):
        with self.lock:
            return [dict(r, body=json.loads(r['body'])) for r in self.db.execute('SELECT * FROM attempts')]

    def intent(self, ident, body):
        with self.lock, self.db:
            existing = self.db.execute('SELECT state FROM events WHERE id=?', (ident,)).fetchone()
            if existing and existing['state'] != 'queued':
                raise ValueError('执行意图已存在，禁止重复启动')
            event = self.db.execute('SELECT * FROM events WHERE id=?', (ident,)).fetchone()
            if event and event['task_id']:
                task = self.db.execute('SELECT * FROM tasks WHERE id=?', (event['task_id'],)).fetchone()
                if task is None or not task['enabled']:
                    raise ValueError('本机任务已删除或暂停')
                now = datetime.now(UTC)
                if event['scheduled_for'] and not due_occurrence(json.loads(event['body'])['trigger'],
                        datetime.fromisoformat(event['scheduled_for']), now):
                    raise ValueError('发生项已超出宽限窗口')
                if event['request_id'] and (now - datetime.fromisoformat(event['created_at'])).total_seconds() > 300:
                    raise ValueError('手动发生项已超出 300 秒宽限窗口')
            self.db.execute('INSERT OR IGNORE INTO events VALUES(?,NULL,0,NULL,NULL,?,?,NULL,?)',
                            (ident, 'preparing', json.dumps(body), datetime.now(UTC).isoformat()))
            self.db.execute("UPDATE events SET state='preparing' WHERE id=? AND state='queued'", (ident,))

    def fail_queued(self, ident, error):
        with self.lock, self.db:
            self.db.execute("UPDATE events SET state=?,error_msg=? WHERE id=? AND state='queued'",
                            ('skipped' if '宽限窗口' in error else 'failed', error, ident))

    def state(self, ident, state, error=None):
        with self.lock, self.db:
            self.db.execute('UPDATE events SET state=?, error_msg=? WHERE id=?', (state, error, ident))
            if state == 'unknown':
                self.db.execute('UPDATE tasks SET enabled=0 WHERE id=(SELECT task_id FROM events WHERE id=?)', (ident,))
                self.db.execute("UPDATE events SET state='cancelled' WHERE state='queued' AND task_id=(SELECT task_id FROM events WHERE id=?)", (ident,))

    def attempt(self, execution_id, body):
        with self.lock, self.db:
            old = self.db.execute('SELECT * FROM attempts WHERE execution_id=?', (str(execution_id),)).fetchone()
            if old:
                return old['attempt_id']  # Claim only is idempotent; start must never be replayed.
            attempt = str(uuid.uuid4())
            self.db.execute('INSERT INTO attempts VALUES(?,?,?,?)',
                            (str(execution_id), attempt, 'claim_intent', json.dumps(body)))
            return attempt

    def attempt_state(self, ident, state, body=None):
        with self.lock, self.db:
            if body is None:
                self.db.execute('UPDATE attempts SET state=? WHERE execution_id=?', (state, str(ident)))
            else:
                self.db.execute('UPDATE attempts SET state=?,body=? WHERE execution_id=?',
                                (state, json.dumps(body), str(ident)))

    def finish_attempt(self, ident, body, payload):
        with self.lock, self.db:
            self.db.execute('UPDATE attempts SET state=?,body=? WHERE execution_id=?',
                            (payload['state'], json.dumps(body), str(ident)))
            self.db.execute('INSERT OR REPLACE INTO outbox VALUES(?,?,?)',
                            ('remote:' + str(ident), '/executions/' + str(ident) + '/report', json.dumps(payload)))

    def enqueue_report(self, key, route, body):
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO outbox VALUES(?,?,?)', (key, route, json.dumps(body)))

    def flush(self, send):
        with self.lock:
            items = list(self.db.execute('SELECT * FROM outbox ORDER BY rowid LIMIT 1'))
        for item in items:
            if send(item['route'], json.loads(item['body'])):
                with self.lock, self.db:
                    self.db.execute('DELETE FROM outbox WHERE key=?', (item['key'],))
            else:
                # A revoked/conflicting report must not starve other completed work.
                with self.lock, self.db:
                    self.db.execute('UPDATE outbox SET rowid=(SELECT COALESCE(MAX(rowid),0)+1 FROM outbox) WHERE key=?', (item['key'],))

    def recover(self):
        # Caller must hold the lifetime interprocess gate first: previous Agent is gone,
        # and Windows kill-on-close has stopped its contained child processes.
        with self.lock, self.db:
            self.db.execute("UPDATE events SET state='unknown', error_msg='Agent 重启，业务结果不确定；不自动重试' WHERE state IN ('preparing','running','cancel_requested')")
            self.db.execute("UPDATE tasks SET enabled=0 WHERE id IN (SELECT task_id FROM events WHERE state='unknown')")
            self.db.execute("UPDATE events SET state='cancelled' WHERE state='queued' AND task_id IN (SELECT task_id FROM events WHERE state='unknown')")
            return [dict(r, body=json.loads(r['body'])) for r in self.db.execute(
                "SELECT * FROM attempts WHERE state NOT IN ('reported', 'rejected') AND NOT EXISTS "
                "(SELECT 1 FROM outbox WHERE key = 'remote:' || attempts.execution_id)")]
