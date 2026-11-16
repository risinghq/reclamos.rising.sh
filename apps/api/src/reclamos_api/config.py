import os
from dataclasses import dataclass, field
from urllib.parse import quote

DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-large"
DEFAULT_JUDGE_MODEL = "claude-sonnet-5-5"
DEFAULT_CARD_MODEL = "claude-sonnet-5-5"
# What every process together may spend on language models in one Lima day.
DEFAULT_DAILY_USD_CAP = 2.0
# Set from the evaluation's refusal sweep; docs/cases.md gives the reason.
DEFAULT_REFUSAL_MIN_SIMILARITY = 0.84
# Searches one client address may send a minute; 0 turns the limit off.
DEFAULT_SEARCHES_PER_MINUTE = 30
# The Vite dev server.
DEFAULT_WEB_ORIGINS = ("http://localhost:5173",)


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    queue_schema: str = "task_queue"
    pdf_store: str = "local"
    pdf_store_path: str = ".data/pdfs"
    pdf_bucket: str | None = None
    s3_endpoint_url: str | None = None
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_cache_path: str = ".data/models"
    anthropic_api_key: str | None = field(default=None, repr=False)
    openrouter_api_key: str | None = field(default=None, repr=False)
    judge_model: str = DEFAULT_JUDGE_MODEL
    card_model: str = DEFAULT_CARD_MODEL
    daily_usd_cap: float = DEFAULT_DAILY_USD_CAP
    refusal_min_similarity: float = DEFAULT_REFUSAL_MIN_SIMILARITY
    web_origins: tuple[str, ...] = DEFAULT_WEB_ORIGINS
    searches_per_minute: int = DEFAULT_SEARCHES_PER_MINUTE

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            database_url=_database_url(),
            pdf_store=os.environ.get("PDF_STORE", "local"),
            pdf_store_path=os.environ.get("PDF_STORE_PATH", ".data/pdfs"),
            pdf_bucket=os.environ.get("PDF_BUCKET"),
            s3_endpoint_url=os.environ.get("S3_ENDPOINT_URL"),
            embedding_model=os.environ.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
            embedding_cache_path=os.environ.get("EMBEDDING_CACHE_PATH", ".data/models"),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            openrouter_api_key=os.environ.get("OPENROUTER_API_KEY") or None,
            judge_model=os.environ.get("JUDGE_MODEL", DEFAULT_JUDGE_MODEL),
            card_model=os.environ.get("CARD_MODEL", DEFAULT_CARD_MODEL),
            daily_usd_cap=float(os.environ.get("DAILY_USD_CAP", DEFAULT_DAILY_USD_CAP)),
            refusal_min_similarity=float(
                os.environ.get("REFUSAL_MIN_SIMILARITY", DEFAULT_REFUSAL_MIN_SIMILARITY)
            ),
            web_origins=_origins(os.environ.get("WEB_ORIGINS")),
            searches_per_minute=int(
                os.environ.get("SEARCHES_PER_MINUTE", DEFAULT_SEARCHES_PER_MINUTE)
            ),
        )


def _origins(value: str | None) -> tuple[str, ...]:
    if value is None:
        return DEFAULT_WEB_ORIGINS
    return tuple(origin.strip() for origin in value.split(",") if origin.strip())


def _database_url() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return database_url
    host = os.environ.get("DB_HOST", "127.0.0.1")
    port = os.environ.get("DB_PORT", "5432")
    name = os.environ.get("DB_NAME", "reclamos")
    user = os.environ.get("DB_USER", "postgres")
    password = os.environ.get("DB_PASSWORD", "")
    # RDS generates passwords with characters such as '#' and ':' that end a
    # URL's credentials, so both parts are percent-encoded.
    credentials = quote(user, safe="")
    if password:
        credentials += ":" + quote(password, safe="")
    return f"postgresql://{credentials}@{host}:{port}/{name}"
