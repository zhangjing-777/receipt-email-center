import logging
import hashlib
import asyncio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from core.database import AsyncSessionLocal
from core.models import UserEmailToken
from core.encryption import encrypt_value, decrypt_value


logger = logging.getLogger(__name__)


def generate_email_hash(email: str) -> str:
    """生成邮箱的 SHA256 哈希值"""
    return hashlib.sha256(email.lower().encode('utf-8')).hexdigest()


class GmailClient:
    """Gmail API 客户端（使用 SQLAlchemy 管理 token）"""
    
    def __init__(self, user_id: str, email: str = None):
        """
        初始化 Gmail 客户端
        
        Args:
            user_id: 用户ID
            email: Gmail 邮箱地址（可选）。如果不指定且用户有多个邮箱，会抛出异常
        """
        self.user_id = user_id
        self.email = email
        self.service = None
        self.user_email = None
        # ✅ 不在 __init__ 中初始化，而是延迟到第一次使用
        self._initialized = False
    
    def _ensure_initialized(self):
        """确保服务已初始化（同步方法）"""
        if self._initialized:
            return
        
        # ✅ 使用 asyncio.run() 来处理异步初始化
        try:
            # 检查是否已经有运行中的事件循环
            loop = asyncio.get_running_loop()
            # 如果有运行中的循环，使用 nest_asyncio 或直接抛出错误
            raise RuntimeError(
                "Cannot initialize GmailClient synchronously in an async context. "
                "Please use 'await GmailClient.create(user_id, email)' instead."
            )
        except RuntimeError:
            # 没有运行中的事件循环，可以使用 asyncio.run()
            asyncio.run(self._async_initialize())
            self._initialized = True
    
    async def _async_initialize(self):
        """异步初始化 Gmail 服务"""
        token_data = await self._get_token_data()
        
        if not token_data:
            error_msg = f"No Gmail token found for user {self.user_id}"
            if self.email:
                error_msg += f" with email {self.email}"
            raise Exception(error_msg)
        
        # 解密 token 数据
        creds = Credentials(
            token=decrypt_value(token_data["access_token"]),
            refresh_token=decrypt_value(token_data["refresh_token"]),
            token_uri=decrypt_value(token_data["token_uri"]),
            client_id=token_data["client_id"],
            client_secret=decrypt_value(token_data["client_secret"]),
        )
        
        # 如果 token 过期，刷新它
        if not creds.valid:
            logger.info(f"Refreshing Gmail token for user {self.user_id}")
            creds.refresh(Request())
            
            # 更新数据库中的 access_token
            await self._update_access_token(creds.token, token_data["email_hash"])
        
        self.service = build("gmail", "v1", credentials=creds)
        self.user_email = decrypt_value(token_data["email"])
        logger.info(f"Gmail service initialized for user {self.user_id}, email {self.user_email}")
    
    @classmethod
    async def create(cls, user_id: str, email: str = None):
        """
        ✅ 异步工厂方法，用于在异步上下文中创建 GmailClient
        
        使用方式：
            gmail = await GmailClient.create(user_id, email)
        """
        instance = cls(user_id, email)
        await instance._async_initialize()
        instance._initialized = True
        return instance
    
    async def _get_token_data(self):
        """从数据库获取 token 数据"""
        async with AsyncSessionLocal() as session:
            query = select(UserEmailToken).where(
                UserEmailToken.user_id == self.user_id,
                UserEmailToken.email_provider == 'gmail'
            )
            
            # 如果指定了邮箱，添加邮箱过滤
            if self.email:
                email_hash = generate_email_hash(self.email)
                query = query.where(UserEmailToken.email_hash == email_hash)
            
            result = await session.execute(query)
            tokens = result.scalars().all()
            
            if not tokens:
                return None
            
            if len(tokens) > 1 and not self.email:
                # 如果有多个邮箱但没有指定，抛出错误
                decrypted_emails = [decrypt_value(t.email) for t in tokens]
                error_msg = (
                    f"User {self.user_id} has {len(tokens)} Gmail accounts linked. "
                    f"Please specify which email to use: {', '.join(decrypted_emails)}"
                )
                logger.error(error_msg)
                raise Exception(error_msg)
            
            token = tokens[0]
            
            return {
                "email": token.email,
                "email_hash": token.email_hash,
                "access_token": token.access_token,
                "refresh_token": token.refresh_token,
                "token_uri": token.token_uri,
                "client_id": token.client_id,
                "client_secret": token.client_secret
            }
    
    async def _update_access_token(self, new_token: str, email_hash: str):
        """更新数据库中的 access_token"""
        encrypted_token = encrypt_value(new_token)
        
        async with AsyncSessionLocal() as session:
            await session.execute(
                pg_insert(UserEmailToken)
                .values(
                    user_id=self.user_id,
                    email_provider='gmail',
                    email_hash=email_hash,
                    access_token=encrypted_token
                )
                .on_conflict_do_update(
                    index_elements=['user_id', 'email_provider', 'email_hash'],
                    set_={'access_token': encrypted_token}
                )
            )
            await session.commit()
        
        logger.info(f"Access token updated for user {self.user_id}, email_hash {email_hash[:8]}...")