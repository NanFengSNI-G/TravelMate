"""保留旧文件名，现仅检查连接和补建缺失表，不删除任何表或数据。"""
from sqlalchemy import text
from app.db import engine
from app.models import Base

Base.metadata.create_all(engine())
with engine().connect() as connection:
    print("当前数据库：", connection.scalar(text("SELECT DATABASE()")))
print("缺失表已补建；已有数据保留。")
