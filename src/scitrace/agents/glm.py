"""GLM OpenAI-compatible ChatModel 配置。"""

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI


def build_glm_model(env_file: str | Path = ".env") -> ChatOpenAI:
    """从本地环境构造 GLM 模型；缺失配置时立即给出明确错误。"""
    load_dotenv(dotenv_path=env_file, override=False)
    required = ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        names = ", ".join(missing)
        raise RuntimeError(f"缺少 GLM 配置：{names}")

    return ChatOpenAI(
        api_key=os.environ["GLM_API_KEY"],
        model=os.environ["GLM_MODEL"],
        base_url=os.environ["GLM_BASE_URL"],
        temperature=0,
        timeout=60,
        max_retries=2,
    )
