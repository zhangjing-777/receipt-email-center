import logging
import hashlib
from fastapi import APIRouter, HTTPException
from sqlalchemy import select, insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from core.database import AsyncSessionLocal
from core.models import UserEmailToken
from core.encryption import encrypt_value, decrypt_value
from core.config import settings


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gmail-auth", tags=["gmail授权相关操作"])


def generate_email_hash(email: str) -> str:
    """生成邮箱的 SHA256 哈希值（用于去重）"""
    return hashlib.sha256(email.lower().encode('utf-8')).hexdigest()


@router.get("/get-auth-url")
async def gmail_login():
    """生成 Gmail 授权链接"""
    try:
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uris": [settings.google_redirect_uri],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=[
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/userinfo.email",
                "https://www.googleapis.com/auth/userinfo.profile",
                "openid",
            ]
        )
        flow.redirect_uri = settings.google_redirect_uri
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent"  # 强制显示授权页面，确保获得 refresh_token
        )
        logger.info("Gmail OAuth URL generated successfully")
        return {"auth_url": auth_url}
    except Exception as e:
        logger.exception("Failed to generate Gmail OAuth URL")
        raise HTTPException(status_code=500, detail=f"Failed to generate auth URL: {str(e)}")


@router.get("/callback")
async def gmail_callback(user_id: str, code: str):
    """授权成功后保存 Token（加密存储到数据库）"""
    logger.info(f"Gmail OAuth callback received for user_id={user_id}")
    
    try:
        # 1. 获取 OAuth token
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uris": [settings.google_redirect_uri],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=[
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/userinfo.email",
                "https://www.googleapis.com/auth/userinfo.profile",
                "openid",
            ]
        )
        flow.redirect_uri = settings.google_redirect_uri
        flow.fetch_token(code=code)
        creds = flow.credentials

        # 2. 获取用户邮箱地址
        gmail_service = build("gmail", "v1", credentials=creds)
        profile = gmail_service.users().getProfile(userId="me").execute()
        email = profile["emailAddress"]
        
        logger.info(f"Successfully retrieved Gmail profile for {email}")

        # 3. 准备加密数据
        email_hash = generate_email_hash(email)
        
        token_data = {
            "user_id": user_id,
            "email_provider": "gmail",
            "email": encrypt_value(email),
            "email_hash": email_hash,
            "access_token": encrypt_value(creds.token),
            "refresh_token": encrypt_value(creds.refresh_token) if creds.refresh_token else None,
            "token_uri": encrypt_value(creds.token_uri) if creds.token_uri else None,
            "client_id": settings.google_client_id,
            "client_secret": encrypt_value(settings.google_client_secret),
            "expiry": creds.expiry.isoformat() if creds.expiry else None
        }

        # 4. Upsert 到数据库（使用 PostgreSQL 的 ON CONFLICT）
        async with AsyncSessionLocal() as session:
            stmt = pg_insert(UserEmailToken).values(token_data)
            stmt = stmt.on_conflict_do_update(
                index_elements=['user_id', 'email_provider', 'email_hash'],
                set_={
                    'access_token': stmt.excluded.access_token,
                    'refresh_token': stmt.excluded.refresh_token,
                    'token_uri': stmt.excluded.token_uri,
                    'expiry': stmt.excluded.expiry,
                    'updated_at': stmt.excluded.updated_at
                }
            )
            await session.execute(stmt)
            await session.commit()
        
        logger.info(f"Gmail account linked successfully for user {user_id}, email={email}")
        
        return {
            "message": "Gmail linked successfully",
            "email": email,
            "status": "success"
        }
        
    except Exception as e:
        logger.exception(f"Gmail OAuth callback failed for user_id={user_id}")
        raise HTTPException(status_code=500, detail=f"OAuth callback failed: {str(e)}")


@router.get("/check-token")
async def check_gmail_token(user_id: str):
    """
    检查用户是否已授权 Gmail，并返回完整的 token 信息（含解密字段）
    """
    logger.info(f"Checking Gmail token for user_id={user_id}")
    
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserEmailToken)
                .where(UserEmailToken.user_id == user_id)
                .where(UserEmailToken.email_provider == 'gmail')
            )
            token = result.scalar_one_or_none()

        if not token:
            return {
                "authorized": False,
                "message": "No Gmail token found"
            }

        # 构造完整返回字典
        token_data = {
            "id": token.id,
            "user_id": str(token.user_id),
            "email_provider": token.email_provider,
            "email": decrypt_value(token.email),
            "email_hash": token.email_hash,
            "access_token": decrypt_value(token.access_token),
            "refresh_token": decrypt_value(token.refresh_token),
            "token_uri": token.token_uri,
            "client_id": token.client_id,
            "client_secret": decrypt_value(token.client_secret),
            "expiry": token.expiry.isoformat() if token.expiry else None,
            "created_at": token.created_at.isoformat() if token.created_at else None,
            "updated_at": token.updated_at.isoformat() if token.updated_at else None,
        }

        logger.info(f"Gmail token found for user_id={user_id}, email={token_data['email']}")
        return {
            "authorized": True,
            "data": token_data
        }

    except Exception as e:
        logger.exception(f"Failed to check Gmail token for user_id={user_id}")
        raise HTTPException(status_code=500, detail=f"Token check failed: {str(e)}")
    

@router.delete("/revoke")
async def revoke_gmail_token(user_id: str):
    """撤销用户的 Gmail 授权"""
    logger.info(f"Revoking Gmail token for user_id={user_id}")
    
    try:
        async with AsyncSessionLocal() as session:
            # 删除 token 记录
            result = await session.execute(
                select(UserEmailToken)
                .where(UserEmailToken.user_id == user_id)
                .where(UserEmailToken.email_provider == 'gmail')
            )
            token = result.scalar_one_or_none()
            
            if not token:
                raise HTTPException(status_code=404, detail="Gmail token not found")
            
            await session.delete(token)
            await session.commit()
        
        logger.info(f"Gmail token revoked successfully for user_id={user_id}")
        return {
            "message": "Gmail authorization revoked successfully",
            "status": "success"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to revoke Gmail token for user_id={user_id}")
        raise HTTPException(status_code=500, detail=f"Token revocation failed: {str(e)}")
