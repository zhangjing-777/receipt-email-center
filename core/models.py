from sqlalchemy import Column, Text, DateTime as SQLDateTime, TypeDecorator, Date as SQLDate
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, date
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
    __tablename__ = "gmail_confirm_link_en"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    email = Column(Text)
    confirm_link = Column(Text)
    cancel_link = Column(Text)
    created_at = Column(AutoConvertDateTime, default=datetime.utcnow, index=True)