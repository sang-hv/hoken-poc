"""Danh mục adapter.

- Lớp 1 (hạ tầng lõi: DB, blob, queue) chọn theo biến môi trường → `make_*`.
- Lớp 2 (dịch vụ AI & search) cũng chọn theo biến môi trường → `CATALOG`. Mỗi adapter khai báo các trường;
  biến môi trường là `<COMPONENT>_TYPE` + `<COMPONENT>_<FIELD>` (xem `ConfigService`). Trường kind="secret"
  không bao giờ trả ra API; prod lấy từ Key Vault / Secrets Manager qua tham chiếu secret của nền tảng.
"""

from __future__ import annotations

import importlib
from dataclasses import asdict, dataclass, field
from typing import Any

from app.core.settings import BootstrapSettings


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: str = "text"  # text | secret | number | select | bool | textarea
    required: bool = False
    default: Any = None
    options: tuple[str, ...] = ()
    show_if: dict[str, Any] = field(default_factory=dict)  # vd {"auth": "key"}


@dataclass(frozen=True)
class AdapterSpec:
    component: str
    type: str  # local | azure | aws
    service: str  # tên dịch vụ hiển thị
    target: str  # "module:Class" có classmethod from_config(cfg, secrets)
    fields: tuple[FieldSpec, ...]

    def load(self, cfg: dict, secrets: dict) -> Any:
        mod, cls = self.target.split(":")
        return getattr(importlib.import_module(mod), cls).from_config(cfg, secrets)

    def public(self) -> dict:
        d = asdict(self)
        d.pop("target")
        return d


AZ_AUTH = FieldSpec("auth", "select", True, "managed_identity", ("managed_identity", "key"))
AWS_AUTH = FieldSpec("auth", "select", True, "iam_role", ("iam_role", "access_key"))
AWS_KEYS = (
    FieldSpec("access_key_id", "secret", show_if={"auth": "access_key"}),
    FieldSpec("secret_access_key", "secret", show_if={"auth": "access_key"}),
)

COMPONENTS = ("llm", "embedding", "cu", "search")

CATALOG: tuple[AdapterSpec, ...] = (
    # ---------------------------------------------------------------- LLM (chat + vision + mini)
    AdapterSpec(
        "llm",
        "local",
        "OpenAI-compatible (Ollama / vLLM / LM Studio)",
        "app.adapters.local.openai_compat:OpenAICompatLLM",
        (
            FieldSpec("base_url", required=True, default="http://localhost:11434/v1"),
            FieldSpec("model", required=True),
            FieldSpec("mini_model"),
            FieldSpec("vision_model"),
            FieldSpec("api_key", "secret"),
        ),
    ),
    AdapterSpec(
        "llm",
        "azure",
        "Azure OpenAI",
        "app.adapters.azure.openai:AzureOpenAILLM",
        (
            FieldSpec("endpoint", required=True, default="https://<resource>.openai.azure.com"),
            FieldSpec("deployment", required=True),
            FieldSpec("mini_deployment"),
            FieldSpec("vision_deployment"),
            FieldSpec("api_version", default="2024-10-21"),
            FieldSpec("temperature", "number"),
            FieldSpec("seed", "number"),
            AZ_AUTH,
            FieldSpec("api_key", "secret", show_if={"auth": "key"}),
        ),
    ),
    AdapterSpec(
        "llm",
        "aws",
        "Amazon Bedrock",
        "app.adapters.aws.bedrock:BedrockLLM",
        (
            FieldSpec("region", required=True, default="ap-northeast-1"),
            FieldSpec("model_id", required=True, default="jp.anthropic.claude-sonnet-4-5-20250929-v1:0"),
            FieldSpec("mini_model_id"),
            FieldSpec("vision_model_id"),
            FieldSpec("temperature", "number"),
            AWS_AUTH,
            *AWS_KEYS,
        ),
    ),
    # ---------------------------------------------------------------- embedding
    AdapterSpec(
        "embedding",
        "local",
        "OpenAI-compatible embeddings",
        "app.adapters.local.openai_compat:OpenAICompatEmbedder",
        (
            FieldSpec("base_url", required=True, default="http://localhost:11434/v1"),
            FieldSpec("model", required=True),
            FieldSpec("dims", "number", True, 1024),
            FieldSpec("api_key", "secret"),
        ),
    ),
    AdapterSpec(
        "embedding",
        "azure",
        "Azure OpenAI embeddings",
        "app.adapters.azure.openai:AzureOpenAIEmbedder",
        (
            FieldSpec("endpoint", required=True, default="https://<resource>.openai.azure.com"),
            FieldSpec("deployment", required=True, default="text-embedding-3-large"),
            FieldSpec("dims", "number", True, 1536),
            FieldSpec("api_version", default="2024-10-21"),
            AZ_AUTH,
            FieldSpec("api_key", "secret", show_if={"auth": "key"}),
        ),
    ),
    AdapterSpec(
        "embedding",
        "aws",
        "Amazon Bedrock embeddings",
        "app.adapters.aws.bedrock:BedrockEmbedder",
        (
            FieldSpec("region", required=True, default="ap-northeast-1"),
            FieldSpec("model_id", required=True, default="cohere.embed-multilingual-v3"),
            FieldSpec("dims", "number", True, 1024),
            AWS_AUTH,
            *AWS_KEYS,
        ),
    ),
    # ---------------------------------------------------------------- Content Understanding (chỉ Azure)
    AdapterSpec(
        "cu",
        "azure",
        "Azure AI Content Understanding",
        "app.adapters.azure.cu:ContentUnderstanding",
        (
            FieldSpec("endpoint", required=True, default="https://<resource>.services.ai.azure.com"),
            FieldSpec("analyzer_id", required=True, default="prebuilt-layout"),
            FieldSpec("api_version", default="2025-11-01"),
            AZ_AUTH,
            FieldSpec("api_key", "secret", show_if={"auth": "key"}),
        ),
    ),
    # ---------------------------------------------------------------- search hybrid
    AdapterSpec(
        "search",
        "local",
        "PostgreSQL + pgvector + pg_bigm",
        "app.adapters.local.pg_search:PgSearch",
        (
            FieldSpec("dsn", "secret"),  # trống → dùng DATABASE_URL của hệ thống
            FieldSpec("index", required=True, default="hoken_chunks"),
        ),
    ),
    AdapterSpec(
        "search",
        "azure",
        "Azure AI Search",
        "app.adapters.azure.ai_search:AzureAISearch",
        (
            FieldSpec("endpoint", required=True, default="https://<search>.search.windows.net"),
            FieldSpec("index", required=True, default="hoken-chunks"),
            FieldSpec("semantic", "bool", default=True),
            FieldSpec("api_version", default="2024-07-01"),
            AZ_AUTH,
            FieldSpec("api_key", "secret", show_if={"auth": "key"}),
        ),
    ),
    AdapterSpec(
        "search",
        "aws",
        "Amazon OpenSearch",
        "app.adapters.aws.opensearch:OpenSearchIndex",
        (
            FieldSpec("endpoint", required=True, default="https://<domain>.ap-northeast-1.es.amazonaws.com"),
            FieldSpec("index", required=True, default="hoken-chunks"),
            FieldSpec("region", default="ap-northeast-1"),
            FieldSpec("auth", "select", True, "iam_role", ("iam_role", "access_key", "basic")),
            *AWS_KEYS,
            FieldSpec("username", show_if={"auth": "basic"}),
            FieldSpec("password", "secret", show_if={"auth": "basic"}),
        ),
    ),
)


def specs_for(component: str, app_env: str) -> list[AdapterSpec]:
    """Prod không có lựa chọn Local. CU chỉ có Azure."""
    return [s for s in CATALOG if s.component == component and not (app_env == "prod" and s.type == "local")]


def find_spec(component: str, type_: str, app_env: str) -> AdapterSpec:
    for s in specs_for(component, app_env):
        if s.type == type_:
            return s
    raise KeyError(f"{component}:{type_}")


# ------------------------------------------------------------------ lớp 1: theo biến môi trường
def make_store(s: BootstrapSettings):
    if s.db_type == "postgres":
        from app.adapters.local.pg_store import PgStore

        return PgStore(s.database_url)
    if s.db_type == "cosmos":
        from app.adapters.azure.cosmos import CosmosStore

        return CosmosStore(s.cosmos_endpoint, s.cosmos_database, s.cosmos_key)
    if s.db_type == "dynamodb":
        from app.adapters.aws.dynamodb import DynamoStore

        return DynamoStore(s.dynamodb_table, s.aws_region)
    if s.db_type == "memory":
        from app.adapters.memory import MemoryStore

        return MemoryStore()
    raise ValueError(f"DB_TYPE không hỗ trợ: {s.db_type}")


def make_queue(s: BootstrapSettings, store=None):
    if s.queue_type == "postgres":
        from app.adapters.local.pg_queue import PgQueue

        return PgQueue(s.database_url, s.queue_prefix)
    if s.queue_type == "azure":
        from app.adapters.azure.storage_queue import AzureStorageQueue

        return AzureStorageQueue(s.azure_queue_account_url, s.azure_storage_connection_string, s.queue_prefix)
    if s.queue_type == "sqs":
        from app.adapters.aws.sqs import SqsQueue

        return SqsQueue(s.sqs_queue_url_prefix, s.aws_region)
    if s.queue_type == "memory":
        from app.adapters.memory import MemoryQueue

        return MemoryQueue()
    raise ValueError(f"QUEUE_TYPE không hỗ trợ: {s.queue_type}")


def make_blob(s: BootstrapSettings):
    if s.blob_type == "local":
        from app.adapters.local.fs_blob import FsBlob

        return FsBlob(s.blob_local_dir)
    if s.blob_type == "azure":
        from app.adapters.azure.blob import AzureBlob

        return AzureBlob(s.azure_blob_account_url, s.azure_blob_container, s.azure_storage_connection_string)
    if s.blob_type == "s3":
        from app.adapters.aws.s3 import S3Blob

        return S3Blob(s.s3_bucket, s.aws_region)
    raise ValueError(f"BLOB_TYPE không hỗ trợ: {s.blob_type}")
