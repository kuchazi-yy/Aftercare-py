"""创建异步数据库引擎、会话工厂并管理表结构初始化。"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncAttrs, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from ac_py.config import Settings


class Base(AsyncAttrs, DeclarativeBase):
    """作为所有 SQLAlchemy 数据表模型的声明基类。"""


class Database:
    """封装数据库引擎与会话生命周期，便于测试时替换连接。"""

    def __init__(self, settings: Settings) -> None:
        """根据配置创建异步引擎和会话工厂。"""

        self.engine = create_async_engine(settings.mysql_dsn, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_schema(self) -> None:
        """创建当前版本所需的数据表，开发环境用于快速启动。"""

        from ac_py.db import models as _models  # noqa: F401

        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        """释放数据库连接池持有的资源。"""

        await self.engine.dispose()

    async def session(self) -> AsyncIterator[AsyncSession]:
        """生成一个请求级数据库会话并在结束时自动关闭。"""

        async with self.session_factory() as session:
            yield session
