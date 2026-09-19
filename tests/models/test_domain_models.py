"""领域模型关键契约测试。"""

from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from scitrace.models import (
    ArtifactOutput,
    ExperimentRun,
    MetricCriterion,
    PaperResource,
    ResearchResource,
    Task,
    VerificationCriterion,
    WebLocation,
)


def test_task_defaults_to_created() -> None:
    """新建请求还未进入 Agent loop 时必须处于 created。"""
    assert Task(query="复现论文 X 的 Table 3").status == "created"


def test_resource_union_dispatches_by_kind() -> None:
    """资源多态解析只依赖明确的 kind 判别字段。"""
    resource = TypeAdapter(ResearchResource).validate_python(
        {"kind": "paper", "name": "Paper X", "locations": [{"kind": "web", "url": "https://x.org"}]}
    )
    assert isinstance(resource, PaperResource)
    assert resource.locations == [WebLocation(url="https://x.org")]


def test_verification_union_dispatches_by_kind() -> None:
    """验证判据可安全反序列化为对应值对象。"""
    criterion = TypeAdapter(VerificationCriterion).validate_python(
        {"kind": "metric", "name": "accuracy", "reference_value": 90.0,
         "operator": "approximately_equal", "tolerance": 0.5}
    )
    assert isinstance(criterion, MetricCriterion)


def test_terminal_run_requires_finished_time() -> None:
    """ExperimentRun 生命周期不允许终态缺失结束时间。"""
    with pytest.raises(ValidationError):
        ExperimentRun(experiment_spec_id="spec_001", status="failed")


def test_running_run_rejects_finished_time() -> None:
    """Monitor 仍在追踪的 run 不能携带终态时间。"""
    with pytest.raises(ValidationError):
        ExperimentRun(experiment_spec_id="spec_001", finished_at=datetime.now(UTC))


def test_artifact_requires_sha256() -> None:
    """ArtifactStore 元数据必须可校验来源完整性。"""
    with pytest.raises(ValidationError):
        ArtifactOutput(name="log", uri="artifact://run/log", sha256="not-a-hash")
