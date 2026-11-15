"""Local SQLite and persistent PostgreSQL storage for serverless deployments."""
import re
import sqlite3
import os
import threading
from pathlib import Path


_initialized = set()
_schema_lock = threading.Lock()


def database_url():
    # Vercel Marketplace integrations inject these automatically.
    return next((os.environ[key] for key in (
        'DATABASE_URL', 'POSTGRES_URL', 'POSTGRES_PRISMA_URL',
        'POSTGRES_URL_NON_POOLING', 'DATABASE_URL_UNPOOLED'
    ) if os.environ.get(key)), None)


class PostgresConnection:
    def __init__(self, url):
        import psycopg
        from psycopg.rows import dict_row
        self.connection = psycopg.connect(url, row_factory=dict_row, connect_timeout=10)
        try:
            with _schema_lock:
                if url not in _initialized:
                    # Serialize first startup across separate serverless instances.
                    self.connection.execute('SELECT pg_advisory_xact_lock(734624890)')
                    schema = Path(__file__).with_name('schema.sql').read_text()
                    statements = '\n'.join(line for line in schema.splitlines()
                                           if not line.lstrip().startswith('--'))
                    for statement in statements.split(';'):
                        statement = statement.strip()
                        if statement and statement not in ('BEGIN', 'COMMIT'):
                            self.connection.execute(statement)
                    self.connection.commit()
                    _initialized.add(url)
        except Exception:
            self.connection.close()
            raise

    def execute(self, sql, params=()):
        import psycopg
        # Keep the application's existing SQLite queries in one place.
        sql = sql.replace('BEGIN IMMEDIATE', 'BEGIN')
        sql = re.sub(r'\buser\b', '"user"', sql).replace('?', '%s')
        # Serialize changes for an account before reading its tournament/revision.
        if sql == 'SELECT * FROM users WHERE id=%s':
            sql += ' FOR UPDATE'
        try:
            return self.connection.execute(sql, params)
        except psycopg.IntegrityError as exc:
            raise sqlite3.IntegrityError(str(exc)) from exc

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()
