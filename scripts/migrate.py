from sqlalchemy import inspect, text
from app.db import engine


COLUMNS = {
    "title": "VARCHAR(64) NOT NULL DEFAULT '' COMMENT '自定义会话标题；为空时从首条用户消息生成'",
    "deleted": "INTEGER NOT NULL DEFAULT 0 COMMENT '会话移除标记；业务记录保留'",
    "created_at": "INTEGER NOT NULL DEFAULT 0 COMMENT '会话创建时间，Unix 秒'",
}


def migrate():
    with engine().connect() as connection:
        locked = connection.scalar(
            text("SELECT GET_LOCK('travelmate_schema_upgrade', 30)")
        )
        if locked != 1:
            raise RuntimeError("数据库升级锁获取失败，请稍后重试")
        try:
            columns = {
                column["name"]
                for column in inspect(connection).get_columns("conversations")
            }
            for name, definition in COLUMNS.items():
                if name not in columns:
                    connection.execute(
                        text(
                            f"ALTER TABLE conversations ADD COLUMN `{name}` {definition}"
                        )
                    )
            connection.commit()
        finally:
            connection.execute(text("SELECT RELEASE_LOCK('travelmate_schema_upgrade')"))
    print("会话管理表结构已就绪，现有记录保留")


if __name__ == "__main__":
    migrate()
