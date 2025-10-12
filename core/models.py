from sqlalchemy import Column, Text, DateTime as SQLDateTime, TypeDecorator, BigInteger, Index
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from core.database import Base


# 自定义 DateTime 类型，自动转换字符串
class AutoConvertDateTime(TypeDecorator):
    """自动将字符串转换为 datetime 对象的类型"""
    impl = SQLDateTime(timezone=True)
    cache_ok = True
    
    def process_bind_param(self, value, dialect):
        """插入数据库前处理（Python → DB）"""
        if value is None:
            return None
        if isinstance(value, str):
            try:
                # 处理 ISO 格式：2025-10-10T18:25:47.233500
                if 'T' in value:
                    return datetime.fromisoformat(value.replace('Z', '+00:00'))
                else:
                    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
        if isinstance(value, datetime):
            return value
        return None
    
    def process_result_value(self, value, dialect):
        """从数据库读取后处理（DB → Python）"""
        return value


class GmailConfirmLinkEN(Base):
    """Gmail 确认链接表"""
    __tablename__ = "gmail_confirm_link_en"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    email = Column(Text)
    confirm_link = Column(Text)
    cancel_link = Column(Text)
    created_at = Column(AutoConvertDateTime, default=datetime.utcnow, index=True)


class UserEmailToken(Base):
    """用户邮箱授权令牌表"""
    __tablename__ = "user_email_tokens"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    email_provider = Column(Text, default='gmail', nullable=False)
    email = Column(Text, nullable=False)  # 加密存储
    email_hash = Column(Text, nullable=False)  # sha256(email.lower())
    access_token = Column(Text, nullable=False)  # 加密存储
    refresh_token = Column(Text, nullable=False)  # 加密存储
    token_uri = Column(Text)
    client_id = Column(Text)
    client_secret = Column(Text)  # 加密存储
    expiry = Column(AutoConvertDateTime)
    created_at = Column(AutoConvertDateTime, default=datetime.utcnow)
    updated_at = Column(AutoConvertDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_user_provider_hash', 'user_id', 'email_provider', 'email_hash', unique=True),
    )


class ImportedEmail(Base):
    """已导入邮件记录表（用于去重）"""
    __tablename__ = "imported_emails"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    message_id = Column(Text, nullable=False, index=True)
    attachment_id = Column(Text)
    imported_at = Column(AutoConvertDateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_user_message', 'user_id', 'message_id', unique=True),
    )