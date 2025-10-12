import logging
from fastapi import APIRouter, HTTPException
from email_search_sync.gmail_client_service import GmailClient


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gmail-search", tags=["根据关键词搜索发票邮件"])

@router.get("")
async def search_gmail(user_id: str, keywords: str = "invoice OR receipt OR 发票", limit: int = 10):
    """搜索发票邮件"""
    try:
        gmail = GmailClient(user_id)
        q = f"({keywords})"
        results = gmail.service.users().messages().list(userId="me", q=q, maxResults=limit).execute()
        messages = []
        for msg in results.get("messages", []):
            meta = gmail.service.users().messages().get(userId="me", id=msg["id"], format="metadata").execute()
            headers = meta.get("payload", {}).get("headers", [])
            subject = next((h["value"] for h in headers if h["name"] == "Subject"), "(no subject)")
            snippet = meta.get("snippet", "")
            has_attachments = any("attachmentId" in p.get("body", {}) for p in meta.get("payload", {}).get("parts", []))
            messages.append({
                "message_id": msg["id"],
                "subject": subject,
                "snippet": snippet,
                "has_attachments": has_attachments
            })
        logger.info(f"Found {len(messages)} messages for user {user_id}")
        return {"results": messages}
    except Exception as e:
        logger.exception("Gmail search failed")
        raise HTTPException(status_code=500, detail=str(e))
