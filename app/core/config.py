from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "Centralized Authentication Service"
    API_V1_STR: str = "/api/v1"
    
    # CORS
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://student.platform.local",
        "https://student.platform.local",
        "http://teacher.platform.local",
        "https://teacher.platform.local",
        "http://localhost:3000",
        "http://localhost:7000",
        "http://localhost:8000",
        "http://localhost:9000",
        "http://localhost:5173",
        "http://localhost:5174"
    ]
    
    # Database Provider Configuration: 'sqlite' (local file) or 'turso' (remote cloud)
    DB_PROVIDER: str = "sqlite"
    USE_TURSO_DB: bool = False
    
    TURSO_DATABASE_URL: str = ""
    TURSO_AUTH_TOKEN: str = ""
    SQLITE_DB_PATH: str = "../parse-forge/data/db/mock_pariksha.db"
    
    DATABASE_URL: Optional[str] = None
    
    @property
    def RESOLVED_DATABASE_URL(self) -> str:
        if self.DATABASE_URL and not self.USE_TURSO_DB and self.DB_PROVIDER != "turso":
            url = self.DATABASE_URL.strip().strip("'").strip('"')
            if url.startswith("libsql://"):
                url = url.replace("libsql://", "sqlite+https://")
                if "secure=" not in url:
                    sep = "&" if "?" in url else "?"
                    url = f"{url}{sep}secure=true"
            return url

        if (self.DB_PROVIDER == "turso" or self.USE_TURSO_DB) and self.TURSO_DATABASE_URL:
            raw_url = self.TURSO_DATABASE_URL.strip().strip("'").strip('"').rstrip('/')
            url = raw_url.replace("libsql://", "sqlite+https://")
            
            # Append secure=true
            if "secure=" not in url:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}secure=true"
                
            return url

        # Default: Local SQLite Database
        if self.SQLITE_DB_PATH.startswith("sqlite+aiosqlite://"):
            return self.SQLITE_DB_PATH
        return f"sqlite+aiosqlite:///{self.SQLITE_DB_PATH}"

    # JWT Auth
    SECRET_KEY: str = "your-super-secret-key-that-should-be-changed"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
