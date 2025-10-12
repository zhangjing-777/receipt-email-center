import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from core.config import settings


logger = logging.getLogger(__name__)

# 创建异步引擎
engine = create_async_engine(
    settings.database_url,
    pool_size=50,              # 连接池大小
    max_overflow=20,           # 超出后最多再创建
    pool_pre_ping=True,        # 自动检测失效连接
    pool_recycle=3600,         # 1小时回收连接
    echo=False,
    connect_args={
        #"statement_cache_size": 0,  # 🔥 禁用预处理语句缓存
        "server_settings": {
            "application_name": "receipt_processing_center"
        }
    }
)

# 创建异步 Session 工厂
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

Base = declarative_base()

async def get_db():
    """获取数据库会话（依赖注入）"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

async def init_db():
    """初始化数据库（可选）"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)