import logging
from fastapi import APIRouter, HTTPException
from sqlalchemy import select, delete, and_, insert
from core.database import AsyncSessionLocal
from core.models import GmailConfirmLinkEN
from core.encryption import encrypt_value, decrypt_data
from email_confirm_click.eml_parser import load_s3, mail_parser
from email_confirm_click.utils import extract_gmail_forwarding_links, confirm_gmail_forwarding_link


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gmail-confirm-click", tags=["gmail-confirm-click相关操作"])


# 拉取 S3 并转发给supabase且完成click
@router.post("")
async def gmail_confirm_click(bucket, key, user_id):
    logger.info(f"Received webhook request: bucket={bucket}, key={key}, user_id={user_id}")
    bucket = str(bucket)
    key = str(key)
    user_id = str(user_id)
    try:
        eml_bytes = load_s3(bucket, key)
        logger.info("Loaded EML bytes from S3.")
        raw_eml = mail_parser(eml_bytes)
        logger.info(f"Parsed EML: to_email={raw_eml.get('to_email')}, subject={raw_eml.get('subject')}")
        email_body = raw_eml['body']
        links = extract_gmail_forwarding_links(email_body)
        logger.info(f"Extracted links: {links}")
        
        # 加密敏感数据
        encrypted_email = encrypt_value(raw_eml['to_email'])
        encrypted_confirm_link = encrypt_value(links['confirm']) if links['confirm'] else None
        encrypted_cancel_link = encrypt_value(links['cancel']) if links['cancel'] else None
        
        insert_data = {
            "user_id": user_id,
            "email": encrypted_email,
            "confirm_link": encrypted_confirm_link,
            "cancel_link": encrypted_cancel_link
        }
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                insert(GmailConfirmLinkEN).values([insert_data]).returning(GmailConfirmLinkEN)
            )
            await session.commit()
            inserted_records = result.scalars().all()
        
        logger.info(f"Inserted into gmail_confirm_link_en table, inserted {len(inserted_records)} record(s)")

        confirm_link = links['confirm']
        await confirm_gmail_forwarding_link(confirm_link)
        logger.info(f"Successfully processed Gmail click for link: {confirm_link}")
        return {"status": "success"}
    except Exception as e:
        logger.exception(f"Error in gmail_confirm_click: {str(e)}")
        raise


@router.get("/get-confirm-item")  
async def get_gmail_confirm(confirm_id: str, user_id: str):
    """根据ID和用户ID获取Gmail确认链接"""
    logger.info(f"GET request for gmail_confirm: id={confirm_id}, user_id={user_id}")

    try:
        # 从数据库查询
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(GmailConfirmLinkEN)
                .where(and_(GmailConfirmLinkEN.id == confirm_id, GmailConfirmLinkEN.user_id == user_id))
            )
            records = result.scalars().all()
        
        logger.info(f"Query result: found {len(records)} record(s)")
        
        if not records:
            logger.warning(f"Gmail confirm link not found: id={confirm_id}, user_id={user_id}")
            raise HTTPException(status_code=404, detail="Gmail confirm link not found")
        
        # 解密敏感数据
        decrypted_result = []
        for record in records:
            record_dict = {c.name: getattr(record, c.name) for c in record.__table__.columns}
            # 转换类型
            if record_dict.get('id'):
                record_dict['id'] = str(record_dict['id'])
            if record_dict.get('user_id'):
                record_dict['user_id'] = str(record_dict['user_id'])
            if record_dict.get('created_at'):
                record_dict['created_at'] = record_dict['created_at'].isoformat()
            
            decrypted = decrypt_data("gmail_confirm_link_en", record_dict)
            decrypted_result.append(decrypted)
        
        logger.info(f"Successfully retrieved and decrypted gmail_confirm: id={confirm_id}")
        return decrypted_result

    except Exception as e:
        logger.exception(f"Failed to get gmail_confirm: id={confirm_id}, user_id={user_id}, error={str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/delete-confirm-item")
async def delete_gmail_confirm(confirm_id: str, user_id: str):
    """根据ID和用户ID删除Gmail确认链接"""
    logger.info(f"DELETE request for gmail_confirm: id={confirm_id}, user_id={user_id}")
    try:
        # 先检查记录是否存在
        async with AsyncSessionLocal() as session:
            check_result = await session.execute(
                select(GmailConfirmLinkEN.id)
                .where(and_(GmailConfirmLinkEN.id == confirm_id, GmailConfirmLinkEN.user_id == user_id))
            )
            existing_record = check_result.scalar_one_or_none()
        
        logger.info(f"Check existence result: {'found' if existing_record else 'not found'}")
        
        if not existing_record:
            logger.warning(f"Gmail confirm link not found for deletion: id={confirm_id}, user_id={user_id}")
            raise HTTPException(status_code=404, detail="Gmail confirm link not found")
        
        # 删除记录
        async with AsyncSessionLocal() as session:
            delete_result = await session.execute(
                delete(GmailConfirmLinkEN)
                .where(and_(GmailConfirmLinkEN.id == confirm_id, GmailConfirmLinkEN.user_id == user_id))
                .returning(GmailConfirmLinkEN)
            )
            await session.commit()
            deleted_records = delete_result.scalars().all()
        
        logger.info(f"Delete result: deleted {len(deleted_records)} record(s)")
        
        logger.info(f"Successfully deleted gmail_confirm: id={confirm_id}, user_id={user_id}")
        return {
            "message": "Gmail confirm link deleted successfully",
            "status": "success",
            "deleted_id": confirm_id
        }
    except Exception as e:
        logger.exception(f"Failed to delete gmail_confirm: id={confirm_id}, user_id={user_id}, error={str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
