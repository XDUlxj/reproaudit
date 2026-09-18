from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    glm_api_key: SecretStr = SecretStr("")
    glm_model: str = "glm-4.7"
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4/"
    tavily_api_key: SecretStr = SecretStr("")
    database_url: SecretStr = SecretStr("")
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr = SecretStr("")
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_revision: str = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
    trusted_fake_dns_hosts: list[str] = Field(default_factory=list)
    artifact_root: Path = Path("artifacts")
    max_steps: int = Field(24, ge=1, le=100)
    specialist_steps: int = Field(10, ge=1, le=30)
    model_timeout: int = Field(90, ge=1)
    download_limit_mib: int = Field(500, ge=1)
    max_document_mib: int = Field(50, ge=1)
    max_chunks: int = Field(20000, ge=1)
    docker_image: str = "scitrace-runner:0.1"

    def require(self):
        """没配置完成就报错，后续改为降级处理"""
        missing = [
            name
            for name in ("glm_api_key", "tavily_api_key", "database_url")
            if not getattr(self, name).get_secret_value()
        ]
        if missing:
            raise ValueError("缺少配置：" + ", ".join(name.upper() for name in missing))

    def redact(self, text: str) -> str:
        for name in ("glm_api_key", "tavily_api_key", "database_url", "qdrant_api_key"):
            value = getattr(self, name).get_secret_value()
            if value:
                text = text.replace(value, "[REDACTED]")
        return text
