import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from email_search_sync.gmail_client_service import GmailClient


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gmail-search", tags=["根据关键词搜索发票邮件"])


def build_gmail_query(
    keywords: str,
    after_date: Optional[str] = None,
    before_date: Optional[str] = None,
    has_attachment: bool = False,
    from_address: Optional[str] = None
) -> str:
    """
    构建 Gmail 搜索查询字符串
    
    Args:
        keywords: 搜索关键词
        after_date: 开始日期 (YYYY/MM/DD 格式)
        before_date: 结束日期 (YYYY/MM/DD 格式)
        has_attachment: 是否必须有附件
        from_address: 发件人地址
    
    Returns:
        完整的 Gmail 查询字符串
    """
    query_parts = [f"({keywords})"]
    
    if after_date:
        query_parts.append(f"after:{after_date}")
    
    if before_date:
        query_parts.append(f"before:{before_date}")
    
    if has_attachment:
        query_parts.append("has:attachment")
    
    if from_address:
        query_parts.append(f"from:{from_address}")
    
    return " ".join(query_parts)


@router.get("")
async def search_gmail(
    user_id: str,
    email: str = Query(..., description="要搜索的 Gmail 邮箱地址"),
    keywords: str = Query(default="invoice OR receipt OR 发票", description="搜索关键词"),
    limit: int = Query(default=10, ge=1, le=100, description="返回结果数量（1-100）"),
    page_token: Optional[str] = Query(default=None, description="分页 token"),
    days_back: Optional[int] = Query(default=None, ge=1, le=365, description="搜索最近 N 天的邮件"),
    after_date: Optional[str] = Query(default=None, description="开始日期 (YYYY/MM/DD)"),
    before_date: Optional[str] = Query(default=None, description="结束日期 (YYYY/MM/DD)"),
    has_attachment: bool = Query(default=False, description="是否必须有附件"),
    from_address: Optional[str] = Query(default=None, description="发件人邮箱地址")
):
    """
    搜索 Gmail 邮件（支持分页和日期过滤）
    
    - **user_id**: Receiptdrop 用户 ID
    - **email**: 要搜索的 Gmail 邮箱地址
    - **keywords**: 搜索关键词（默认：invoice OR receipt OR 发票）
    - **limit**: 返回结果数量（1-100，默认 10）
    - **page_token**: 分页 token（从上一次响应中获取）
    - **days_back**: 搜索最近 N 天的邮件（1-365）
    - **after_date**: 开始日期，格式 YYYY/MM/DD
    - **before_date**: 结束日期，格式 YYYY/MM/DD
    - **has_attachment**: 是否必须有附件
    - **from_address**: 发件人邮箱地址
    """
    logger.info(f"Gmail search requested: user_id={user_id}, email={email}, keywords={keywords}, limit={limit}")
    
    try:
        gmail = GmailClient(user_id, email)
        
        # 如果指定了 days_back，自动计算 after_date
        if days_back and not after_date:
            date_threshold = datetime.now() - timedelta(days=days_back)
            after_date = date_threshold.strftime("%Y/%m/%d")
        
        # 构建查询字符串
        query = build_gmail_query(
            keywords=keywords,
            after_date=after_date,
            before_date=before_date,
            has_attachment=has_attachment,
            from_address=from_address
        )
        
        logger.info(f"Gmail query: {query}")
        
        # 执行搜索
        search_params = {
            "userId": "me",
            "q": query,
            "maxResults": limit
        }
        
        if page_token:
            search_params["pageToken"] = page_token
        
        results = gmail.service.users().messages().list(**search_params).execute()
        
        messages = []
        for msg in results.get("messages", []):
            try:
                # 获取邮件元数据
                meta = gmail.service.users().messages().get(
                    userId="me",
                    id=msg["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"]
                ).execute()
                
                headers = meta.get("payload", {}).get("headers", [])
                
                # 提取邮件头信息
                subject = next((h["value"] for h in headers if h["name"].lower() == "subject"), "(no subject)")
                from_email = next((h["value"] for h in headers if h["name"].lower() == "from"), "")
                date_str = next((h["value"] for h in headers if h["name"].lower() == "date"), "")
                
                snippet = meta.get("snippet", "")
                
                # 检查是否有附件
                has_attachments = False
                payload = meta.get("payload", {})
                if "parts" in payload:
                    has_attachments = any(
                        "attachmentId" in part.get("body", {})
                        for part in payload.get("parts", [])
                    )
                
                messages.append({
                    "message_id": msg["id"],
                    "subject": subject,
                    "from": from_email,
                    "date": date_str,
                    "snippet": snippet,
                    "has_attachments": has_attachments
                })
            except Exception as e:
                logger.warning(f"Failed to fetch metadata for message {msg['id']}: {str(e)}")
                continue
        
        response = {
            "total_found": len(messages),
            "messages": messages,
            "query": query,
            "searched_email": email
        }
        
        # 如果有下一页，添加 next_page_token
        if "nextPageToken" in results:
            response["next_page_token"] = results["nextPageToken"]
        
        logger.info(f"Gmail search completed: found {len(messages)} messages for user {user_id}, email {email}")
        return response
        
    except Exception as e:
        logger.exception(f"Gmail search failed for user_id={user_id}, email={email}")
        raise HTTPException(status_code=500, detail=f"Gmail search failed: {str(e)}")


@router.get("/count")
async def count_gmail_messages(
    user_id: str,
    email: str = Query(..., description="要统计的 Gmail 邮箱地址"),
    keywords: str = Query(default="invoice OR receipt OR 发票", description="搜索关键词"),
    days_back: Optional[int] = Query(default=None, ge=1, le=365, description="统计最近 N 天的邮件")
):
    """
    统计符合条件的邮件数量（不返回具体邮件内容）
    """
    logger.info(f"Gmail count requested: user_id={user_id}, email={email}, keywords={keywords}")
    
    try:
        gmail = GmailClient(user_id, email)
        
        # 如果指定了 days_back，自动计算 after_date
        after_date = None
        if days_back:
            date_threshold = datetime.now() - timedelta(days=days_back)
            after_date = date_threshold.strftime("%Y/%m/%d")
        
        query = build_gmail_query(keywords=keywords, after_date=after_date)
        
        # 只获取 ID 列表，不获取完整内容
        results = gmail.service.users().messages().list(
            userId="me",
            q=query,
            maxResults=500  # Gmail API 单次最多返回 500
        ).execute()
        
        total_count = results.get("resultSizeEstimate", 0)
        
        logger.info(f"Gmail count completed: found ~{total_count} messages for user {user_id}, email {email}")
        return {
            "count": total_count,
            "query": query,
            "email": email,
            "note": "This is an estimate from Gmail API"
        }
        
    except Exception as e:
        logger.exception(f"Gmail count failed for user_id={user_id}, email={email}")
        raise HTTPException(status_code=500, detail=f"Gmail count failed: {str(e)}")