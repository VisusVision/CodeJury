from pathlib import Path

from pydantic_settings import BaseSettings

_ROOT_DIR = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _ROOT_DIR / ".env"


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/code_review"

    api_secret_key: str = "change-this-to-a-random-secret"

    ollama_base_url: str = "http://localhost:11434"
    ollama_general_model: str = "qwen2.5:7b"
    ollama_coder_model: str = "qwen2.5-coder:14b-instruct-q6_K"
    ollama_enabled: bool = True
    ollama_timeout: float = 300.0
    ollama_max_retries: int = 2
    ollama_retry_delay: float = 2.0
    ollama_max_concurrent: int = 2
    ollama_num_predict: int = 3072
    ollama_coder_num_ctx: int = 16384
    ollama_coder_num_gpu: int = -1
    ollama_coder_temperature: float = 0.0
    ollama_coder_top_p: float = 0.9
    ollama_coder_repeat_penalty: float = 1.15
    ollama_gpt_oss_num_predict: int = 4096
    ollama_gpt_oss_think: str = "low"

    llm_provider: str = "ollama"
    llm_general_provider: str = ""
    llm_coder_provider: str = ""

    nvidia_nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_nim_api_key: str = ""
    nvidia_nim_general_model: str = "qwen/qwen2.5-coder-32b-instruct"
    nvidia_nim_coder_model: str = "qwen/qwen2.5-coder-32b-instruct"
    nvidia_nim_timeout: float = 120.0
    nvidia_nim_max_retries: int = 2
    nvidia_nim_retry_delay: float = 2.0
    nvidia_nim_max_concurrent: int = 2
    nvidia_nim_rpm_limit: int = 35
    nvidia_nim_num_predict: int = 3072

    redis_url: str = "redis://localhost:6379/0"
    analysis_queue_name: str = "stream:analysis_jobs"
    analysis_consumer_group: str = "group:analysis_workers"
    analysis_job_ttl_seconds: int = 86400
    analysis_worker_poll_timeout_seconds: int = 5
    analysis_pipeline_timeout_seconds: int = 300
    sandbox_ready_timeout_seconds: int = 15
    analysis_worker_heartbeat_interval_seconds: int = 5
    analysis_worker_heartbeat_ttl_seconds: int = 15
    analysis_worker_sandbox_retry_seconds: int = 5

    auth_session_ttl_seconds: int = 28800
    auth_cookie_secure: bool = False
    cors_allowed_origins: str = "http://localhost:8080,http://127.0.0.1:8080"

    model_config = {"env_file": str(_ENV_FILE), "extra": "ignore"}


settings = Settings()
