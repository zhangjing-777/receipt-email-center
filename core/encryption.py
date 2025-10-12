import base64
import logging
from cryptography.fernet import Fernet
from core.config import settings

logger = logging.getLogger(__name__)

# 获取加密密钥
ENCRYPTION_KEY = settings.encryption_key_bytes

fernet = Fernet(ENCRYPTION_KEY.encode() if isinstance(ENCRYPTION_KEY, str) else ENCRYPTION_KEY)


# 需要加密的敏感字段
SENSITIVE_FIELDS = {
    'gmail_confirm_link_en': ['email', 'confirm_link', 'cancel_link'],
    'subscription_records': ['seller_name', 'plan_name', 'note']
}

def encrypt_value(value):
    """加密单个值"""
    if value is None or value == "":
        return value
    
    try:
        if isinstance(value, (int, float)):
            value = str(value)
        encrypted = fernet.encrypt(value.encode('utf-8'))
        return base64.b64encode(encrypted).decode('utf-8')
    except Exception as e:
        logger.error(f"Encryption failed for value: {str(e)}")
        return value

def decrypt_value(encrypted_value):
    """解密单个值"""
    if encrypted_value is None or encrypted_value == "":
        return encrypted_value
    
    try:
        encrypted_bytes = base64.b64decode(encrypted_value.encode('utf-8'))
        decrypted = fernet.decrypt(encrypted_bytes)
        return decrypted.decode('utf-8')
    except Exception as e:
        logger.error(f"Decryption failed for value: {str(e)}")
        return encrypted_value

def encrypt_data(table_name, data_dict):
    """对指定表的敏感字段进行加密"""
    if table_name not in SENSITIVE_FIELDS:
        return data_dict
    
    encrypted_data = data_dict.copy()
    sensitive_fields = SENSITIVE_FIELDS[table_name]
    
    for field in sensitive_fields:
        if field in encrypted_data and encrypted_data[field]:
            encrypted_data[field] = encrypt_value(encrypted_data[field])
    
    logger.info(f"Encrypted {len(sensitive_fields)} sensitive fields for table {table_name}")
    return encrypted_data

def decrypt_data(table_name, data_dict):
    """对指定表的敏感字段进行解密"""
    if table_name not in SENSITIVE_FIELDS:
        return data_dict
    
    decrypted_data = data_dict.copy()
    sensitive_fields = SENSITIVE_FIELDS[table_name]
    
    for field in sensitive_fields:
        if field in decrypted_data and decrypted_data[field]:
            decrypted_data[field] = decrypt_value(decrypted_data[field])
    
    logger.info(f"Decrypted {len(sensitive_fields)} sensitive fields for table {table_name}")
    return decrypted_data