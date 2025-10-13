import os
import logging
import base64
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import List
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from core.database import AsyncSessionLocal
from core.models import ImportedEmail
from email_search_sync.gmail_client_service import GmailClient  # ✅ 只导入 GmailClient


load_dotenv()

# 从环境变量读取配置
RECEIPTDROP_INBOX = os.getenv("RECEIPTDROP_INBOX")
AWS_SMTP_USER = os.getenv("AWS_SMTP_USER")
AWS_SMTP_PASS = os.getenv("AWS_SMTP_PASS")
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gmail-forward", tags=["批量转发 Gmail 邮件到虚拟邮箱"])


# 重试配置
MAX_RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 2


class EmailForwardError(Exception):
    """邮件转发错误"""
    pass


def send_email_via_smtp(
    from_email: str,
    to_email: str,
    raw_eml_data: bytes,
    message_id: str,
    retry_count: int = 0
) -> bool:
    """
    通过 AWS SMTP 转发原始邮件（带重试机制）
    
    Args:
        from_email: 发件人邮箱
        to_email: 收件人邮箱（虚拟邮箱）
        raw_eml_data: 原始邮件的 RFC822 格式数据
        message_id: Gmail message ID（用于追踪）
        retry_count: 当前重试次数
    
    Returns:
        bool: 发送是否成功
    
    Raises:
        EmailForwardError: 发送失败且超过最大重试次数
    """
    try:
        # 创建 SMTP 连接
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()  # 启用 TLS
            server.login(AWS_SMTP_USER, AWS_SMTP_PASS)
            
            # 创建邮件容器
            msg = MIMEMultipart()
            msg['From'] = from_email
            msg['To'] = to_email
            msg['Subject'] = f"Forwarded Email from Gmail (ID: {message_id[:8]}...)"
            msg['X-Gmail-Message-ID'] = message_id  # 用于追踪
            msg['X-Forwarded-By'] = 'ReceiptDrop'
            
            # 将原始邮件作为附件添加
            part = MIMEBase('message', 'rfc822')
            part.set_payload(raw_eml_data)
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename="forwarded_{message_id[:8]}.eml"'
            )
            msg.attach(part)
            
            # 发送邮件
            server.send_message(msg)
            logger.info(f"✅ Email sent via SMTP: message_id={message_id}, to={to_email}")
            return True
            
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"❌ SMTP authentication failed: {str(e)}")
        raise EmailForwardError(f"SMTP authentication failed: {str(e)}")
    
    except smtplib.SMTPException as e:
        logger.warning(f"⚠️ SMTP error for message {message_id} (attempt {retry_count + 1}): {str(e)}")
        
        # 如果未超过最大重试次数，进行重试
        if retry_count < MAX_RETRY_ATTEMPTS:
            time.sleep(RETRY_DELAY_SECONDS * (retry_count + 1))  # 指数退避
            logger.info(f"🔄 Retrying email {message_id}, attempt {retry_count + 2}/{MAX_RETRY_ATTEMPTS + 1}")
            return send_email_via_smtp(from_email, to_email, raw_eml_data, message_id, retry_count + 1)
        else:
            raise EmailForwardError(f"SMTP error after {MAX_RETRY_ATTEMPTS} retries: {str(e)}")
    
    except Exception as e:
        logger.error(f"❌ Unexpected error sending email {message_id}: {str(e)}")
        raise EmailForwardError(f"Unexpected error: {str(e)}")


async def check_already_imported(user_id: str, message_ids: List[str]) -> dict:
    """
    批量检查邮件是否已导入
    
    Returns:
        Dict[message_id, is_imported]
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ImportedEmail.message_id)
            .where(ImportedEmail.user_id == user_id)
            .where(ImportedEmail.message_id.in_(message_ids))
        )
        imported_ids = {row[0] for row in result.fetchall()}
    
    return {mid: (mid in imported_ids) for mid in message_ids}


async def mark_as_imported(user_id: str, message_id: str):
    """标记邮件为已导入"""
    async with AsyncSessionLocal() as session:
        stmt = pg_insert(ImportedEmail).values({
            "user_id": user_id,
            "message_id": message_id,
            "attachment_id": "WHOLE_MESSAGE"
        }).on_conflict_do_nothing(
            index_elements=['user_id', 'message_id']
        )
        await session.execute(stmt)
        await session.commit()


@router.post("")
async def forward_emails(
    user_id: str,
    email: str = Query(..., description="要转发的 Gmail 邮箱地址"),
    message_ids: List[str] = Query(..., description="要转发的邮件 ID 列表")
):
    """
    批量转发 Gmail 邮件到虚拟邮箱（通过 AWS SMTP）
    
    - **user_id**: Receiptdrop 用户 ID
    - **email**: 要转发的 Gmail 邮箱地址
    - **message_ids**: Gmail 邮件 ID 列表
    
    返回转发结果统计和详细信息
    """
    logger.info(f"📨 Forward request: user_id={user_id}, email={email}, total_emails={len(message_ids)}")
    
    # 验证配置
    if not all([RECEIPTDROP_INBOX, AWS_SMTP_USER, AWS_SMTP_PASS, SMTP_HOST]):
        logger.error("❌ SMTP configuration is incomplete")
        raise HTTPException(status_code=500, detail="SMTP configuration error")
    
    try:
        gmail = await GmailClient.create(user_id, email)  # ✅ 使用异步创建
        user_email = gmail.user_email or "noreply@receiptdrop.dev"
    except Exception as e:
        logger.exception(f"❌ Failed to initialize Gmail client for user {user_id}, email {email}")
        raise HTTPException(status_code=500, detail=f"Gmail client initialization failed: {str(e)}")
    
    # 虚拟邮箱地址
    virtual_inbox = f"{user_id}@{RECEIPTDROP_INBOX}"
    
    # 批量检查已导入的邮件
    imported_status = await check_already_imported(user_id, message_ids)
    
    results = []
    start_time = time.time()

    for idx, mid in enumerate(message_ids, 1):
        logger.info(f"📧 Processing {idx}/{len(message_ids)}: message_id={mid}")
        
        try:
            # 去重检查
            if imported_status.get(mid, False):
                logger.info(f"⏭️ Message {mid} already imported, skipping")
                results.append({
                    "message_id": mid,
                    "status": "skipped",
                    "reason": "already_imported"
                })
                continue

            # 获取原始邮件（RFC822 格式）
            msg = gmail.service.users().messages().get(
                userId="me",
                id=mid,
                format="raw"
            ).execute()
            
            raw_eml_base64url = msg.get("raw")
            
            if not raw_eml_base64url:
                logger.error(f"❌ No raw content for message {mid}")
                results.append({
                    "message_id": mid,
                    "status": "failed",
                    "reason": "no_raw_content"
                })
                continue
            
            # Base64url 解码（Gmail API 使用 base64url 编码）
            raw_eml_base64 = raw_eml_base64url.replace('-', '+').replace('_', '/')
            # 添加填充
            padding = len(raw_eml_base64) % 4
            if padding:
                raw_eml_base64 += '=' * (4 - padding)
            
            raw_eml_bytes = base64.b64decode(raw_eml_base64)
            
            # 记录邮件大小
            email_size_kb = len(raw_eml_bytes) / 1024
            logger.info(f"📦 Email size: {email_size_kb:.2f} KB")

            # 通过 AWS SMTP 转发邮件
            forward_start = time.time()
            send_email_via_smtp(
                from_email=user_email,
                to_email=virtual_inbox,
                raw_eml_data=raw_eml_bytes,
                message_id=mid
            )
            forward_duration = time.time() - forward_start

            # 标记为已导入
            await mark_as_imported(user_id, mid)

            logger.info(f"✅ Forwarded message {mid} in {forward_duration:.2f}s")
            results.append({
                "message_id": mid,
                "status": "forwarded",
                "size_kb": round(email_size_kb, 2),
                "duration_seconds": round(forward_duration, 2)
            })
            
        except EmailForwardError as e:
            logger.error(f"❌ Forward failed for {mid}: {str(e)}")
            results.append({
                "message_id": mid,
                "status": "failed",
                "reason": str(e)
            })
        except Exception as e:
            logger.exception(f"❌ Unexpected error for {mid}")
            results.append({
                "message_id": mid,
                "status": "failed",
                "reason": f"unexpected_error: {str(e)}"
            })

    # 统计结果
    total_duration = time.time() - start_time
    summary = {
        "total": len(message_ids),
        "forwarded": len([r for r in results if r["status"] == "forwarded"]),
        "skipped": len([r for r in results if r["status"] == "skipped"]),
        "failed": len([r for r in results if r["status"] == "failed"]),
        "total_duration_seconds": round(total_duration, 2),
        "average_duration_seconds": round(total_duration / len(message_ids), 2) if message_ids else 0
    }
    
    logger.info(f"📊 Forward summary for user {user_id}, email {email}: {summary}")
    return {
        "summary": summary,
        "details": results,
        "virtual_inbox": virtual_inbox,
        "source_email": email
    }


@router.get("/test-smtp")
async def test_smtp_connection():
    """测试 AWS SMTP 连接"""
    logger.info("🔍 Testing SMTP connection...")
    
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(AWS_SMTP_USER, AWS_SMTP_PASS)
            logger.info("✅ SMTP connection test successful")
            return {
                "status": "success",
                "message": "SMTP connection is working",
                "smtp_host": SMTP_HOST,
                "smtp_port": SMTP_PORT,
                "smtp_user": AWS_SMTP_USER[:4] + "***"  # 隐藏敏感信息
            }
    except Exception as e:
        logger.exception("❌ SMTP connection test failed")
        raise HTTPException(status_code=500, detail=f"SMTP test failed: {str(e)}")


@router.get("/imported-count")
async def get_imported_count(user_id: str):
    """获取用户已导入的邮件数量"""
    logger.info(f"📊 Getting imported count for user {user_id}")
    
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ImportedEmail)
                .where(ImportedEmail.user_id == user_id)
            )
            count = len(result.scalars().all())
        
        return {
            "user_id": user_id,
            "imported_count": count
        }
    except Exception as e:
        logger.exception(f"❌ Failed to get imported count for user {user_id}")
        raise HTTPException(status_code=500, detail=f"Database query failed: {str(e)}")


@router.delete("/clear-imported")
async def clear_imported_records(
    user_id: str,
    confirm: bool = Query(False, description="确认删除操作")
):
    """清空用户的已导入邮件记录（谨慎使用）"""
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Please set confirm=true to proceed with deletion"
        )
    
    logger.warning(f"⚠️ Clearing imported records for user {user_id}")
    
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ImportedEmail)
                .where(ImportedEmail.user_id == user_id)
            )
            records = result.scalars().all()
            
            for record in records:
                await session.delete(record)
            
            await session.commit()
            
            deleted_count = len(records)
            logger.info(f"🗑️ Cleared {deleted_count} imported records for user {user_id}")
            
            return {
                "message": "Imported records cleared successfully",
                "deleted_count": deleted_count
            }
    except Exception as e:
        logger.exception(f"❌ Failed to clear imported records for user {user_id}")
        raise HTTPException(status_code=500, detail=f"Database operation failed: {str(e)}")