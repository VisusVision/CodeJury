from pathlib import Path

from pydantic_settings import BaseSettings

_ROOT_DIR = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _ROOT_DIR / ".env"


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/code_review"

    api_secret_key: str = "change-this-to-a-random-secret"

    ollama_base_url: str = "http://localhost:11434"
    ollama_general_model: str = "qwen2.5:7b"
    ollama_coder_model: str = "qwen2.5-coder:7b"
    ollama_enabled: bool = True
    ollama_timeout: float = 120.0
    ollama_max_retries: int = 2
    ollama_retry_delay: float = 2.0
    ollama_max_concurrent: int = 4
    ollama_num_predict: int = 1024

    redis_url: str = "redis://localhost:6379/0"
    analysis_queue_name: str = "stream:analysis_jobs"
    analysis_consumer_group: str = "group:analysis_workers"
    analysis_job_ttl_seconds: int = 86400
    analysis_worker_poll_timeout_seconds: int = 5

    model_config = {"env_file": str(_ENV_FILE), "extra": "ignore"}


settings = Settings()
