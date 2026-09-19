"""科研资源及其位置描述模型。"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from scitrace.models.base import Record


class WebLocation(BaseModel):
    """位于 Web 的资源入口。"""

    kind: Literal["web"] = "web"
    url: str = Field(min_length=1)


class LocalLocation(BaseModel):
    """位于受控本地工作区的资源入口。"""

    kind: Literal["local"] = "local"
    path: str = Field(min_length=1)


class AttachmentLocation(BaseModel):
    """由用户附件提供的资源入口。"""

    kind: Literal["attachment"] = "attachment"
    attachment_id: str = Field(min_length=1)
    filename: str = Field(min_length=1)


ResourceLocation = Annotated[
    WebLocation | LocalLocation | AttachmentLocation,
    Field(discriminator="kind"),
]


class ResourceBase(Record):
    """已识别、标准化且可被任务引用的科研资源。"""

    kind: Literal["paper", "repository", "dataset", "model"]
    name: str = Field(min_length=1)
    locations: list[ResourceLocation] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PaperResource(ResourceBase):
    kind: Literal["paper"] = "paper"
    doi: str | None = None
    arxiv_id: str | None = None


class RepositoryResource(ResourceBase):
    kind: Literal["repository"] = "repository"
    revision: str | None = None


class DatasetResource(ResourceBase):
    kind: Literal["dataset"] = "dataset"
    version: str | None = None


class ModelResource(ResourceBase):
    kind: Literal["model"] = "model"
    revision: str | None = None


ResearchResource = Annotated[
    PaperResource | RepositoryResource | DatasetResource | ModelResource,
    Field(discriminator="kind"),
]
