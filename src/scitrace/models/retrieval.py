"""Retrieval 基础设施与 Agent Tool 之间的稳定 DTO。"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class PaperLocator(BaseModel):
    """论文原文中的页码位置；页码从 1 开始。"""

    kind: Literal["paper"] = "paper"
    start_page: int = Field(ge=1)
    end_page: int | None = Field(default=None, ge=1)
    section: str | None = None


class FileLocator(BaseModel):
    """仓库文件中的行范围；行号从 1 开始。"""

    kind: Literal["file"] = "file"
    path: str = Field(min_length=1)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)


ContentLocator = Annotated[PaperLocator | FileLocator, Field(discriminator="kind")]


class ArtifactReference(BaseModel):
    """ResourceChunk 关联的非 Entity Artifact 元数据。"""

    name: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    media_type: str = Field(min_length=1)


class ResourceChunk(BaseModel):
    """由 ResearchResource 派生的可检索文本块，不是领域 Entity。"""

    resource_id: str = Field(min_length=1)
    content: str = Field(min_length=1) # 原始资源内容
    locator: ContentLocator # locator 负责说明这段 content 来自哪里
    artifacts: list[ArtifactReference] = Field(default_factory=list)


class RetrievalHit(BaseModel):
    """按相关性排序后交给 AnalysisAgent 的检索结果。"""

    resource_id: str
    locator: ContentLocator
    content: str
    artifacts: list[ArtifactReference] = Field(default_factory=list)
