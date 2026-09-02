"""SQLAlchemy 2.0 声明式基类。

所有 ORM 模型都继承 Base；alembic 通过 Base.metadata 做自动迁移检测。
后续章节新增模型时，须在 app/db/models/ 中定义并被 import 到此模块或 alembic env.py，
否则 autogenerate 检测不到。
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
