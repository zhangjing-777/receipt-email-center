import boto3
import mailparser
import logging
from core.config import settings


logger = logging.getLogger(__name__)


def load_s3(bucket, key):
    logger.info(f"Loading object from S3: bucket={bucket}, key={key}")
    try:
        s3 = boto3.client(
            "s3",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key
        )
        response = s3.get_object(Bucket=bucket, Key=key)
        logger.info("S3 object loaded successfully.")
        return response["Body"].read()
    except Exception as e:
        logger.exception(f"Failed to load object from S3: bucket={bucket}, key={key}, error={str(e)}")
        raise


def mail_parser(eml_bytes):
    logger.info("Parsing EML bytes.")
    try:
        mail = mailparser.parse_from_bytes(eml_bytes)

        # 基本字段提取
        from_email = mail.from_[0][1] if mail.from_ else ""
        to_email = mail.to[0][1] if mail.to else ""
        subject = mail.subject or ""
        body = mail.text_plain[0] if mail.text_plain else mail.text_html[0] if mail.text_html else ""

        # 原始附件提取
        raw_attachments = []
        for att in mail.attachments:
            filename = att.get("filename", "unknown")
            content_type = att.get("mail_content_type", "application/octet-stream")
            payload = att.get("payload", b"")
            if isinstance(payload, str):
                payload = payload.encode("utf-8")

            raw_attachments.append({
                "filename": filename,
                "content_type": content_type,
                "binary": payload,  # 这是原始文件二进制，不 base64 编码
            })
        
        logger.info(f"Parsed {len(raw_attachments)} attachments from EML.")
        return dict(
                from_email=from_email,
                to_email=to_email,
                subject=subject,
                body=body,
                attachments=raw_attachments
            )
    except Exception as e:
        logger.exception(f"Failed to parse EML bytes: error={str(e)}")
        raise

