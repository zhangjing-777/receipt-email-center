import os
import logging
from dotenv import load_dotenv
from supabase import create_client, Client
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from core.encryption import encrypt_value, decrypt_value


load_dotenv()

url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(url, key)

logger = logging.getLogger(__name__)


class GmailClient:
    def __init__(self, user_id: str):
        data = supabase.table("user_email_tokens").select("*").eq("user_id", user_id).execute().data
        if not data:
            raise Exception(f"No Gmail token found for user {user_id}")

        token = data[0]
        creds = Credentials(
            token=decrypt_value(token["access_token"]),
            refresh_token=decrypt_value(token["refresh_token"]),
            token_uri=decrypt_value(token["token_uri"]),
            client_id=token["client_id"],
            client_secret=decrypt_value(token["client_secret"]),
        )
        if not creds.valid:
            logger.info(f"Refreshing Gmail token for user {user_id}")
            creds.refresh(Request())
            new_token = encrypt_value(creds.token)
            supabase.table("user_email_tokens").update({"access_token": new_token}).eq("user_id", user_id).execute()

        self.service = build("gmail", "v1", credentials=creds)
        self.user_id = user_id
