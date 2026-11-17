"""Local SQLite and persistent PostgreSQL storage for serverless deployments."""
import re
import sqlite3
import os
import threading
from pathlib import Path
from urllib.parse import urlsplit


def report_database_error(exc, stage):
    """Log only fixed stage names, exception classes and SQLSTATE, never values."""
    state = getattr(exc, 'sqlstate', None)
    if not isinstance(state, str) or not re.fullmatch(r'[A-Z0-9]{5}', state):
        state = 'none'
    print(f'DB_ERROR stage={stage} type={type(exc).__name__} sqlstate={state}', flush=True)


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
        try:
            self.connection = psycopg.connect(url, row_factory=dict_row, connect_timeout=10)
        except Exception as exc:
            report_database_error(exc, 'connect')
            # Classify common setup mistakes without printing any connection data.
            try:
                parsed = urlsplit(url)
                host = parsed.hostname or ''
                placeholder = host == 'example.com' or host.endswith('.example.com')
                shape = 'placeholder' if placeholder else ('postgres_uri' if parsed.scheme in ('postgres', 'postgresql') else 'other')
            except ValueError:
                shape = 'invalid_uri'
            print(f'DB_CONFIG format={shape}', flush=True)
            raise
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
        except Exception as exc:
            report_database_error(exc, 'schema')
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
        except Exception as exc:
            report_database_error(exc, 'query')
            raise

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()
