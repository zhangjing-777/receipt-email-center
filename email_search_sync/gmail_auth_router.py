import os
import logging
from dotenv import load_dotenv
from supabase import create_client, Client
from fastapi import APIRouter, HTTPException
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from core.encryption import encrypt_value


load_dotenv()

url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(url, key)

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gmail-auth", tags=["gmail授权相关操作"])

@router.get("/get-auth-url")
async def gmail_login():
    """生成 Gmail 授权链接"""
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "redirect_uris": [REDIRECT_URI],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    flow.redirect_uri = REDIRECT_URI
    auth_url, _ = flow.authorization_url(access_type="offline", include_granted_scopes="true")
    logger.info(f"Gmail OAuth URL generated")
    return {"auth_url": auth_url}

@router.get("/callback")
async def gmail_callback(user_id: str, code: str):
    """授权成功后保存 Token（加密存储）"""
    try:
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "redirect_uris": [REDIRECT_URI],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        )
        flow.redirect_uri = REDIRECT_URI
        flow.fetch_token(code=code)
        creds = flow.credentials

        gmail_service = build("gmail", "v1", credentials=creds)
        profile = gmail_service.users().getProfile(userId="me").execute()
        email = profile["emailAddress"]

        data = {
            "user_id": user_id,
            "email_provider": "gmail",
            "user_email": encrypt_value(email),
            "access_token": encrypt_value(creds.token),
            "refresh_token": encrypt_value(creds.refresh_token),
            "token_uri": encrypt_value(creds.token_uri),
            "client_id": CLIENT_ID,
            "client_secret": encrypt_value(CLIENT_SECRET),
            "expiry": creds.expiry.isoformat()
        }

        supabase.table("user_email_tokens").upsert(data).execute()
        logger.info(f"Gmail account linked for {email}")

        return {"message": "Gmail linked successfully", "email": email}
    except Exception as e:
        logger.exception("Gmail OAuth callback failed")
        raise HTTPException(status_code=500, detail=str(e))
