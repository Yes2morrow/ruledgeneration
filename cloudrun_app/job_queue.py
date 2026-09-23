"""Transactional, leased queue for one container (shared by its Uvicorn workers).

Use a persistent LOCAL block volume for restart durability. SQLite WAL is not a
multi-container/network-filesystem queue; production scale-out needs a DB broker.
"""
import json
import sqlite3
import time
import uuid
import os
import re
from contextlib import contextmanager
from pathlib import Path


class JobQueue:
    def __init__(self, path, max_pending=8, lease_seconds=60, max_attempts=3):
        self.path = str(path)
        self.max_pending = max_pending
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            # SQLite's journal-mode transition can ignore busy_timeout when two
            # fresh Uvicorn processes initialize the same new file simultaneously.
            deadline = time.monotonic() + 10
            while True:
                try:
                    db.execute('PRAGMA journal_mode=WAL')
                    break
                except sqlite3.OperationalError as exc:
                    if 'locked' not in str(exc) or time.monotonic() >= deadline:
                        raise
                    time.sleep(.05)
            db.execute('''CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, owner TEXT NOT NULL,
                kind TEXT NOT NULL, payload TEXT NOT NULL, tenant TEXT NOT NULL,
                status TEXT NOT NULL, result TEXT, error TEXT,
                created REAL NOT NULL, updated REAL NOT NULL, lease REAL NOT NULL DEFAULT 0,
                token TEXT, attempts INTEGER NOT NULL DEFAULT 0)''')
            db.execute('CREATE INDEX IF NOT EXISTS job_fingerprint ON jobs(fingerprint, created)')
            db.execute('CREATE INDEX IF NOT EXISTS job_status ON jobs(status, created)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def submit(self, run_id, fingerprint, owner, kind, payload, tenant, ttl=600):
        now = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            hit = db.execute('''SELECT id FROM jobs WHERE fingerprint=? AND owner=?
                AND (status IN ('queued','running') OR (status='succeeded' AND updated>?))
                ORDER BY created DESC LIMIT 1''', (fingerprint, owner, now-ttl)).fetchone()
            if hit:
                return hit['id']
            pending = db.execute("SELECT count(*) AS total FROM jobs WHERE status IN ('queued','running')").fetchone()['total']
            if pending >= self.max_pending:
                raise OverflowError('任务队列已满，请稍后重试')
            db.execute('''INSERT INTO jobs
                (id,fingerprint,owner,kind,payload,tenant,status,created,updated)
                VALUES (?,?,?,?,?,?,'queued',?,?)''',
                (run_id, fingerprint, owner, kind, json.dumps(payload), json.dumps(tenant), now, now))
            # Keep bounded history; never discard pending work.
            db.execute("DELETE FROM jobs WHERE status IN ('succeeded','failed') AND updated<?", (now-7*86400,))
        return run_id

    def claim(self):
        now = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("""UPDATE jobs SET status='failed', error=?, updated=?
                WHERE status='running' AND lease<? AND attempts>=?""",
                ('任务多次中断，请重新提交', now, now, self.max_attempts))
            row = db.execute("""SELECT * FROM jobs WHERE status='queued'
                OR (status='running' AND lease<?) ORDER BY created LIMIT 1""", (now,)).fetchone()
            if row is None:
                return None
            job = dict(row)
            token = uuid.uuid4().hex
            db.execute("""UPDATE jobs SET status='running', token=?, lease=?,
                attempts=attempts+1, updated=? WHERE id=?""", (token, now+self.lease_seconds, now, job['id']))
            job.update(token=token, payload=json.loads(job['payload']), tenant=json.loads(job['tenant']))
            return job

    def heartbeat(self, job):
        with self.connect() as db:
            db.execute("UPDATE jobs SET lease=? WHERE id=? AND token=? AND status='running'",
                       (time.time()+self.lease_seconds, job['id'], job['token']))

    def finish(self, job, result=None, error=None):
        with self.connect() as db:
            changed = db.execute('''UPDATE jobs SET status=?, result=?, error=?, updated=?, lease=0
                WHERE id=? AND token=? AND status='running' ''',
                ('failed' if error else 'succeeded', json.dumps(result) if result is not None else None,
                 error, time.time(), job['id'], job['token']))
            return changed.rowcount == 1

    def get(self, run_id, owner):
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=? AND owner=?', (run_id, owner)).fetchone()
        if row is None:
            return None
        messages = {'queued': '已排队', 'running': '正在计算布局与道路',
                    'succeeded': '生成完成', 'failed': '任务失败'}
        return {'runId': row['id'], 'status': row['status'],
                'progress': [messages[row['status']]],
                'createdAt': row['created'], 'updatedAt': row['updated'],
                'result': json.loads(row['result']) if row['result'] else None,
                'error': row['error'], 'done': row['status'] in ('succeeded', 'failed')}

    def pending_count(self):
        with self.connect() as db:
            return db.execute("SELECT count(*) AS total FROM jobs WHERE status IN ('queued','running')").fetchone()['total']


class _MySQLConnection:
    def __init__(self, connection):
        self.connection = connection
        self.locked = False
        self.cursors = []

    def execute(self, sql, params=()):
        cursor = self.connection.cursor()
        self.cursors.append(cursor)
        if sql == 'BEGIN IMMEDIATE':
            # Serialize admission/deduplication/claim across replicas. Named locks
            # are connection-scoped and released even when a worker is killed.
            cursor.execute("SELECT GET_LOCK('layout_jobs_transaction', 10) AS acquired")
            if cursor.fetchone()['acquired'] != 1:
                raise TimeoutError('任务队列暂时繁忙')
            self.locked = True
        else:
            cursor.execute(re.sub(r'\bjobs\b', 'layout_jobs', sql).replace('?', '%s'), params)
        return cursor


class MySQLJobQueue(JobQueue):
    """Shared persistent queue. Same leased state machine as the local queue."""
    def __init__(self, max_pending=8, lease_seconds=60, max_attempts=3):
        self.max_pending, self.lease_seconds, self.max_attempts = max_pending, lease_seconds, max_attempts
        import pymysql
        self.driver = pymysql
        required = ('JOB_DB_HOST', 'JOB_DB_USER', 'JOB_DB_PASSWORD', 'JOB_DB_NAME')
        missing = [key for key in required if not os.environ.get(key)]
        if missing:
            raise RuntimeError('MySQL 任务队列配置缺少: ' + ', '.join(missing))
        self.config = dict(host=os.environ['JOB_DB_HOST'], port=int(os.environ.get('JOB_DB_PORT', '3306')),
                           user=os.environ['JOB_DB_USER'], password=os.environ['JOB_DB_PASSWORD'],
                           database=os.environ['JOB_DB_NAME'], charset='utf8mb4', autocommit=False,
                           cursorclass=pymysql.cursors.DictCursor, connect_timeout=5,
                           read_timeout=15, write_timeout=15)
        if os.environ.get('JOB_DB_SSL_CA'):
            self.config.update(ssl_ca=os.environ['JOB_DB_SSL_CA'], ssl_verify_cert=True,
                               ssl_verify_identity=True)
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS layout_jobs (
                id VARCHAR(64) PRIMARY KEY, fingerprint CHAR(64) NOT NULL, owner CHAR(64) NOT NULL,
                kind VARCHAR(16) NOT NULL, payload MEDIUMTEXT NOT NULL, tenant TEXT NOT NULL,
                status VARCHAR(16) NOT NULL, result LONGTEXT, error TEXT,
                created DOUBLE NOT NULL, updated DOUBLE NOT NULL, lease DOUBLE NOT NULL DEFAULT 0,
                token CHAR(32), attempts INT NOT NULL DEFAULT 0,
                INDEX job_fingerprint(fingerprint,created), INDEX job_status(status,created)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')

    @contextmanager
    def connect(self):
        connection = self.driver.connect(**self.config)
        adapter = _MySQLConnection(connection)
        try:
            yield adapter
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            if adapter.locked:
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT RELEASE_LOCK('layout_jobs_transaction')")
                finally:
                    connection.close()
            else:
                connection.close()


def build_job_queue(local_path, max_pending):
    backend = os.environ.get('JOB_QUEUE_BACKEND', 'sqlite')
    if backend == 'mysql':
        return MySQLJobQueue(max_pending=max_pending)
    if backend != 'sqlite':
        raise RuntimeError('JOB_QUEUE_BACKEND 只支持 sqlite / mysql')
    return JobQueue(local_path, max_pending=max_pending)
