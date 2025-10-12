import os
import logging
import requests
from dotenv import load_dotenv
from supabase import create_client, Client
from fastapi import APIRouter, HTTPException
from email_search_sync.gmail_client_service import GmailClient


load_dotenv()

url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(url, key)

RECEIPTDROP_INBOX = os.getenv("RECEIPTDROP_INBOX")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gmail-forward", tags=["批量转发 Gmail 邮件到虚拟邮箱"])

@router.post("")
async def forward_emails(user_id: str, message_ids: list[str]):
    """批量转发 Gmail 邮件到虚拟邮箱"""
    gmail = GmailClient(user_id)
    results = []

    for mid in message_ids:
        try:
            # 去重
            exists = supabase.table("imported_emails").select("message_id").eq("user_id", user_id).eq("message_id", mid).execute()
            if exists.data:
                results.append({"message_id": mid, "status": "skipped"})
                continue

            msg = gmail.service.users().messages().get(userId="me", id=mid, format="raw").execute()
            raw_eml = msg["raw"]

            inbox_url = f"{RECEIPTDROP_INBOX}/{user_id}/upload-eml"
            res = requests.post(inbox_url, json={"message_id": mid, "raw_eml_base64url": raw_eml})
            if res.status_code not in (200, 201):
                logger.error(f"Upload failed {mid}: {res.text}")
                results.append({"message_id": mid, "status": "failed"})
                continue

            supabase.table("imported_emails").insert({
                "user_id": user_id,
                "message_id": mid,
                "attachment_id": "WHOLE_MESSAGE"
            }).execute()

            logger.info(f"Forwarded message {mid} for user {user_id}")
            results.append({"message_id": mid, "status": "forwarded"})
        except Exception as e:
            logger.exception("Forward error")
            results.append({"message_id": mid, "status": f"error: {str(e)}"})

    summary = {
        "forwarded": len([r for r in results if r["status"] == "forwarded"]),
        "skipped": len([r for r in results if r["status"] == "skipped"]),
        "failed": len([r for r in results if r["status"] == "failed"]),
        "errors": len([r for r in results if "error" in r["status"]])
    }
    return {"summary": summary, "details": results}
