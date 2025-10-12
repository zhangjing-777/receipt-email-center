import logging
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from core.database import AsyncSessionLocal
from core.models import UserEmailToken
from core.encryption import encrypt_value, decrypt_value


logger = logging.getLogger(__name__)


class GmailClient:
    """Gmail API 客户端（使用 SQLAlchemy 管理 token）"""
    
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.service = None
        self.user_email = None
        self._initialize_service()
    
    def _initialize_service(self):
        """初始化 Gmail 服务（同步方法，在构造函数中调用）"""
        import asyncio
        
        # 如果已经在事件循环中，直接运行
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 没有运行的事件循环，创建一个新的
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            token_data = loop.run_until_complete(self._get_token_data())
            loop.close()
        else:
            # 已经在事件循环中，使用 run_until_complete
            token_data = loop.run_until_complete(self._get_token_data())
        
        if not token_data:
            raise Exception(f"No Gmail token found for user {self.user_id}")
        
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
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._update_access_token(creds.token))
                loop.close()
            else:
                loop.run_until_complete(self._update_access_token(creds.token))
        
        self.service = build("gmail", "v1", credentials=creds)
        self.user_email = decrypt_value(token_data["email"])
        logger.info(f"Gmail service initialized for user {self.user_id}")
    
    async def _get_token_data(self):
        """从数据库获取 token 数据"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserEmailToken)
                .where(UserEmailToken.user_id == self.user_id)
                .where(UserEmailToken.email_provider == 'gmail')
            )
            token = result.scalar_one_or_none()
            
            if not token:
                return None
            
            return {
                "email": token.email,
                "access_token": token.access_token,
                "refresh_token": token.refresh_token,
                "token_uri": token.token_uri,
                "client_id": token.client_id,
                "client_secret": token.client_secret
            }
    
    async def _update_access_token(self, new_token: str):
        """更新数据库中的 access_token"""
        encrypted_token = encrypt_value(new_token)
        
        async with AsyncSessionLocal() as session:
            await session.execute(
                pg_insert(UserEmailToken)
                .values(
                    user_id=self.user_id,
                    email_provider='gmail',
                    access_token=encrypted_token
                )
                .on_conflict_do_update(
                    index_elements=['user_id', 'email_provider'],
                    set_={'access_token': encrypted_token}
                )
            )
            await session.commit()
        
        logger.info(f"Access token updated for user {self.user_id}")


