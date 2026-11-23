"""Lớp 1 — cấu hình hạ tầng lõi (bootstrap).

DevOps đặt các giá trị này qua biến môi trường / IaC lúc deploy. Secret (mật khẩu DB, API key,
JWT secret...) có nguồn gốc ở Key Vault / Secrets Manager và được nền tảng đưa vào env
(tham chiếu Key Vault của Container Apps, `secrets` của ECS task definition). Ở local thì lấy từ `.env`.

Admin UI chỉ xem lớp này (xem `public_summary`), không sửa được.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


def load_dotenv(path: Path = Path(".env")) -> None:
    """Đọc .env đơn giản (KEY=VALUE). Không ghi đè biến đã có trong môi trường."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


PARSER_TYPES = ("docling", "paddleocr")


@dataclass(frozen=True)
class BootstrapSettings:
    app_env: str = "dev"  # dev | prod
    public_base_url: str = "http://localhost:5173"
    cors_origins: tuple[str, ...] = ()

    # DB: postgres | cosmos | dynamodb | memory (chỉ dùng cho test)
    db_type: str = "postgres"
    database_url: str = field(default="", repr=False)
    cosmos_endpoint: str = ""
    cosmos_database: str = "hoken"
    cosmos_key: str = field(default="", repr=False)  # trống → Managed Identity
    dynamodb_table: str = "hoken"
    aws_region: str = "ap-northeast-1"

    # Lưu file: local | azure | s3
    blob_type: str = "local"
    blob_local_dir: str = "out/blob"
    azure_blob_account_url: str = ""
    azure_blob_container: str = "hoken"
    azure_storage_connection_string: str = field(default="", repr=False)
    s3_bucket: str = ""

    # Hàng đợi: postgres | azure | sqs | memory
    queue_type: str = "postgres"
    azure_queue_account_url: str = ""
    queue_prefix: str = "hoken"
    sqs_queue_url_prefix: str = ""  # vd https://sqs.ap-northeast-1.amazonaws.com/123456789012/hoken-

    jwt_secret: str = field(default="", repr=False)
    session_hours: int = 12

    # Parser (標準解析) chạy trong worker hàng đợi "docling": docling | paddleocr. Thư viện tương ứng chỉ có
    # trong image worker parser (docker/app.Dockerfile target docling / paddleocr) hoặc .venv-parser.
    parser_type: str = "docling"

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"

    def public_summary(self) -> dict:
        """Thông tin chỉ đọc cho Admin UI. Không có secret."""
        return {
            "app_env": self.app_env,
            "db_type": self.db_type,
            "blob_type": self.blob_type,
            "queue_type": self.queue_type,
            "parser_type": self.parser_type,
            "aws_region": self.aws_region,
            "cosmos_endpoint": self.cosmos_endpoint,
            "s3_bucket": self.s3_bucket,
            "azure_blob_account_url": self.azure_blob_account_url,
        }

    def validate(self) -> None:
        problems = []
        if not self.jwt_secret or len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET phải có ít nhất 32 ký tự")
        if self.is_prod and self.blob_type == "local":
            problems.append("APP_ENV=prod không dùng adapter local cho blob")
        if self.is_prod and self.db_type in ("memory",):
            problems.append("APP_ENV=prod không dùng DB memory")
        if self.parser_type not in PARSER_TYPES:
            problems.append(f"PARSER_TYPE phải là một trong {', '.join(PARSER_TYPES)}")
        if problems:
            raise RuntimeError("Cấu hình bootstrap không hợp lệ: " + "; ".join(problems))


def settings_from_env() -> BootstrapSettings:
    origins = tuple(o.strip() for o in _env("CORS_ORIGINS").split(",") if o.strip())
    return BootstrapSettings(
        app_env=_env("APP_ENV", "dev"),
        public_base_url=_env("PUBLIC_BASE_URL", "http://localhost:5173").rstrip("/"),
        cors_origins=origins,
        db_type=_env("DB_TYPE", "postgres"),
        database_url=_env("DATABASE_URL", "postgresql://hoken:hoken@localhost:5432/hoken"),
        cosmos_endpoint=_env("COSMOS_ENDPOINT"),
        cosmos_database=_env("COSMOS_DATABASE", "hoken"),
        cosmos_key=_env("COSMOS_KEY"),
        dynamodb_table=_env("DYNAMODB_TABLE", "hoken"),
        aws_region=_env("AWS_REGION", "ap-northeast-1"),
        blob_type=_env("BLOB_TYPE", "local"),
        blob_local_dir=_env("BLOB_LOCAL_DIR", "out/blob"),
        azure_blob_account_url=_env("AZURE_BLOB_ACCOUNT_URL"),
        azure_blob_container=_env("AZURE_BLOB_CONTAINER", "hoken"),
        azure_storage_connection_string=_env("AZURE_STORAGE_CONNECTION_STRING"),
        s3_bucket=_env("S3_BUCKET"),
        queue_type=_env("QUEUE_TYPE", "postgres"),
        azure_queue_account_url=_env("AZURE_QUEUE_ACCOUNT_URL"),
        queue_prefix=_env("QUEUE_PREFIX", "hoken"),
        sqs_queue_url_prefix=_env("SQS_QUEUE_URL_PREFIX"),
        jwt_secret=_env("JWT_SECRET"),
        session_hours=int(_env("SESSION_HOURS", "12") or 12),
        parser_type=_env("PARSER_TYPE", "docling").strip().lower(),
    )


@lru_cache(maxsize=1)
def get_settings() -> BootstrapSettings:
    load_dotenv()
    s = settings_from_env()
    s.validate()
    return s
