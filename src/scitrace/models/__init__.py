"""SciTrace V2 的稳定领域模型导出。"""

from scitrace.models.execution import (
    ArtifactOutput,
    CommandRun,
    ExperimentRun,
    LocalExecutionHandle,
    MetricOutput,
    ObservedOutput,
)
from scitrace.models.experiment import (
    ArtifactCriterion,
    ExperimentSpec,
    MetricCriterion,
    OutputRequirement,
    VerificationCriterion,
)
from scitrace.models.resource import (
    AttachmentLocation,
    DatasetResource,
    LocalLocation,
    ModelResource,
    PaperResource,
    RepositoryResource,
    ResearchResource,
    ResourceLocation,
    WebLocation,
)
from scitrace.models.retrieval import (
    ContentLocator,
    FileLocator,
    PaperLocator,
    ResourceChunk,
    RetrievalHit,
)
from scitrace.models.task import Task

__all__ = [
    "ArtifactCriterion", "ArtifactOutput", "AttachmentLocation", "CommandRun",
    "DatasetResource", "ExperimentRun", "ExperimentSpec", "LocalExecutionHandle",
    "ContentLocator", "FileLocator", "LocalLocation", "MetricCriterion", "MetricOutput",
    "ModelResource", "ObservedOutput", "PaperLocator", "ResourceChunk", "RetrievalHit",
    "OutputRequirement", "PaperResource", "RepositoryResource", "ResearchResource",
    "ResourceLocation", "Task", "VerificationCriterion", "WebLocation",
]
