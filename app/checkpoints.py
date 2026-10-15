from contextlib import contextmanager
from langgraph.checkpoint.mysql.pymysql import PyMySQLSaver


def compatible_sql(sql: str):
    # MySQL 9.6 已移除 MD5；使用 SHA-256 的前 16 字节作为 namespace 索引。
    for expression in ("%s", "%(checkpoint_ns)s", "checkpoint_ns"):
        sql = sql.replace(
            f"UNHEX(MD5({expression}))", f"UNHEX(LEFT(SHA2({expression},256),32))"
        )
    return sql


class HashCursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, sql, args=None):
        return self.cursor.execute(compatible_sql(sql), args)

    def executemany(self, sql, args):
        return self.cursor.executemany(compatible_sql(sql), args)

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class TutorialMySQLSaver(PyMySQLSaver):
    # 仅用于全新的教学 checkpoint 库；不迁移已有 MD5 namespace 数据。
    # 社区库最终也使用普通列，但其旧建表步骤包含生成列。
    MIGRATIONS = [
        sql.replace("BINARY(16) AS (UNHEX(MD5(checkpoint_ns))) STORED", "BINARY(16)")
        for sql in PyMySQLSaver.MIGRATIONS
    ]

    @contextmanager
    def _cursor(self, *, pipeline=False):
        with super()._cursor(pipeline=pipeline) as cursor:
            yield HashCursor(cursor)
