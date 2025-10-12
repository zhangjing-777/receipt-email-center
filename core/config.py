from pydantic_settings import BaseSettings
import base64


class Settings(BaseSettings):
    # 数据库连接参数
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str
    db_user: str
    db_password: str

    aws_region: str
    aws_access_key_id: str
    aws_secret_access_key: str

    supabase_url: str
    supabase_service_role_key: str

    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str

    receiptdrop_inbox: str

    aws_smtp_user: str
    aws_smtp_pass: str
    smtp_host: str
    smtp_port: str
  
    # 其他配置
    encryption_key: str
    
    class Config:
        env_file = ".env"
    
    @property
    def encryption_key_bytes(self) -> bytes:
        """Convert base64 encoded key to bytes"""
        return base64.b64decode(self.encryption_key)
    
    @property
    def database_url(self) -> str:
        """Construct database URL from individual components"""
        import urllib.parse
        password = urllib.parse.quote_plus(self.db_password)
        return f"postgresql+asyncpg://{self.db_user}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"


settings = Settings()