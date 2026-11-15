"""Local SQLite and persistent PostgreSQL storage for serverless deployments."""
import re
import sqlite3


class PostgresConnection:
    def __init__(self, url):
        import psycopg
        from psycopg.rows import dict_row
        self.connection = psycopg.connect(url, row_factory=dict_row, connect_timeout=10)

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
