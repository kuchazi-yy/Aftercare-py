"""集中定义运行配置，并从环境变量加载数据库、检索和模型参数。"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """描述应用运行时配置，避免业务模块直接读取环境变量。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8080
    mysql_dsn: str = "sqlite+aiosqlite:///./ac_py.db"
    redis_url: str = "redis://localhost:6380/0"
    elasticsearch_url: str = "http://localhost:9200"
    elasticsearch_alias: str = "aftercare-policies-current"
    llm_base_url: str = "https://api.siliconflow.cn/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimensions: int = Field(default=1024, ge=64, le=8192)
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    bm25_top_k: int = Field(default=5, ge=1, le=100)
    dense_top_k: int = Field(default=5, ge=1, le=100)
    rerank_top_k: int = Field(default=3, ge=1, le=20)
    prompt_token_budget: int = Field(default=6000, ge=1000, le=32000)
    output_token_limit: int = Field(default=256, ge=64, le=4096)
    recent_turns: int = Field(default=4, ge=1, le=20)
    tool_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    cache_policy_seconds: int = 1800
    cache_business_seconds: int = 30
    checkpoint_ttl_seconds: int = 604800
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3000"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回进程级配置单例，减少重复解析环境变量的开销。"""

    return Settings()
