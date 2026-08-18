from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Arya Noble Chatbot API"
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/arya_noble"
    SECRET_KEY: str = "supersecretkey" # Replace in production
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    CIS_RSA_PUBLIC_KEY: Optional[str] = None
    CIS_RSA_PUBLIC_KEY_PATH: Optional[str] = None
    UPLOAD_DIR: str = "data/uploads"
    SECRET_ENCRYPTION_KEY: str = "HD77PDBToZJLKpGJlUKP1HKLH3LcwUe1TUl1ZrTl6MU="
    ENVIRONMENT: str = "development" # "development" | "staging" | "production"

    # RAG & LLM Settings
    EMBEDDING_PROVIDER: str = "huggingface"
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-m3"
    LLM_MODEL_NAME: str = "gpt-4o-mini"
    OPENAI_API_KEY: Optional[str] = None

    # MinIO / S3 Object Storage Settings
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET: str = "erha-knowledge-assets"
    S3_REGION: str = "us-east-1"
    S3_USE_PATH_STYLE: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    def validate_security(self):
        """Validates production environment security settings."""
        if self.ENVIRONMENT.lower() in ("production", "prod"):
            if "supersecretkey" in self.SECRET_KEY.lower():
                raise ValueError("SECURITY ALERT: Cannot run in production with default 'supersecretkey'! Set a secure random SECRET_KEY in .env.")
            if not self.OPENAI_API_KEY or "your-key" in self.OPENAI_API_KEY.lower():
                raise ValueError("SECURITY ALERT: Valid OPENAI_API_KEY is required for production deployment!")
        elif "supersecretkey" in self.SECRET_KEY.lower():
            import warnings
            warnings.warn("SECURITY WARNING: Using default 'supersecretkey'. Change SECRET_KEY before deploying to production.")

settings = Settings()
settings.validate_security()
