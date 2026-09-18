import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def fingerprint(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


class Record(BaseModel):
    """所有可持久化记录的基础模型，统一提供 ID、Schema 版本和创建时间。"""
    model_config = ConfigDict(extra="forbid") # Record 只允许传入模型声明过的字段，多出来的字段直接报错。
    id: str = Field(default_factory=lambda: str(uuid4()))
    schema_version: int = 1
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class Evidence(Record):
    """可追溯证据，保存来自论文、代码、网页或实验的原始证据片段。"""
    kind: Literal["paper", "code", "web", "experiment"]
    source: str
    text: str = Field(max_length=12000)
    page: int | None = None
    start_line: int | None = None
    end_line: int | None = None
    section: str | None = None
    source_span: str | None = None
    revision: str | None = None
    chunk_type: str = "paragraph"


class ResearchResource(Record):
    """科研资源记录，描述发现的代码仓库等资源及其可信来源状态。"""
    url: str
    kind: str = "repository"
    resource_status: Literal["official", "author_affiliated", "third_party", "unverified"] = (
        "unverified"
    )
    verification_confidence: float = Field(default=0, ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class DiscoveryResult(Record):
    """DiscoveryAgent 的发现结果，汇总已确认资源、缺失资源及相关证据。"""
    official_repository: str | None = Field(
        default=None, description="已验证官方仓库的 resource ID；未核实时必须为 null，不是 URL 或 repository ID"
    )
    resource_ids: list[str] = Field(default_factory=list, description="register_resource 返回的真实资源 ID 列表，不能编造")
    missing_resources: list[str] = Field(default_factory=list)
    discovery_status: str
    evidence_ids: list[str] = Field(default_factory=list)


class Claim(Record):
    """从论文中提取的科学主张，以及支持该主张的证据引用。"""
    text: str
    evidence_ids: list[str] = Field(default_factory=list)


class TraceLink(BaseModel):
    """Claim 与 Evidence 之间的追溯关系，描述证据如何支持某个科学主张。"""
    claim_id: str
    evidence_ids: list[str]
    relationship: str
    support: Literal["observed", "inferred"]


class TraceResult(Record):
    """TraceAgent 的追溯结果，汇总 Claim-Evidence 映射、缺失信息和不一致项。"""
    claims: list[Claim] = Field(default_factory=list)
    links: list[TraceLink] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    inconsistencies: list[str] = Field(default_factory=list)
    plan_id: str | None = None
    mode: Literal["code_assisted", "paper_only"] = "paper_only"


class CommandSpec(BaseModel):
    """受约束的命令执行规格，定义要执行的命令、工作目录和超时时间。"""
    model_config = ConfigDict(extra="forbid")
    argv: list[str] = Field(min_length=1, max_length=100)
    cwd: str = "."
    timeout_seconds: int = Field(default=600, ge=1, le=86400)

    @field_validator("argv")
    @classmethod
    def valid_argv(cls, value):
        '''在创建 CommandSpec 时，对 argv 字段进行额外校验'''
        if any("\x00" in arg or len(arg) > 8192 for arg in value):
            raise ValueError("命令参数含非法内容")
        return value

    @field_validator("cwd")
    @classmethod
    def relative_cwd(cls, value):
        '''在创建 CommandSpec 时，对 cwd 字段进行额外校验'''
        from pathlib import PurePosixPath

        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("工作目录必须位于实验目录中")
        return value


class ResourceInput(BaseModel):
    """复现实验所需的外部资源输入，并通过 SHA256 保证资源内容一致性。"""
    url: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    destination: str
    archive: Literal["none", "tar", "zip"] = "none"
    resource_id: str | None = None

    @field_validator("destination")
    @classmethod
    def safe_destination(cls, value):
        from pathlib import PurePosixPath

        p = PurePosixPath(value)
        if p.is_absolute() or ".." in p.parts or not value or value == ".":
            raise ValueError("资源目标必须是实验目录中的相对路径")
        return value


class MetricRule(BaseModel):
    """实验指标验证规则，定义目标值、容差及比较方式。"""
    name: str
    expected: float = Field(allow_inf_nan=False)
    absolute_tolerance: float = Field(default=0, ge=0, allow_inf_nan=False)
    comparison: Literal["close", "at_least", "at_most"] = "close"
    scope: Literal["paper_claim", "tutorial"] = "paper_claim"
    evidence_ids: list[str] = Field(default_factory=list)


class ReproductionPlan(Record):
    """可执行的论文复现计划，固定环境、资源、命令、指标规则和资源限制。"""
    version: int = Field(default=1, ge=1)
    claim_id: str
    mode: Literal["code_assisted", "paper_only"] = "code_assisted"
    repository_id: str | None = None
    repository_revision: str | None = None
    image: str = "scitrace-runner:0.1"
    resources: list[ResourceInput] = Field(default_factory=list)
    commands: list[CommandSpec] = Field(default_factory=list, max_length=30)
    metric_rules: list[MetricRule] = Field(default_factory=list)
    metric_parser: Literal["json", "fasttext"] = "json"
    metric_file: str = "metrics.json"
    assumptions: list[str] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    cpus: float = Field(default=2, gt=0, le=64)
    memory_mib: int = Field(default=4096, ge=128, le=262144)
    disk_mib: int = Field(default=1024, ge=128, le=16384)
    timeout_seconds: int = Field(default=600, ge=1, le=86400)
    download_limit_mib: int = Field(default=500, ge=1, le=100000)

    @field_validator("metric_file")
    @classmethod
    def safe_metric_file(cls, value):
        from pathlib import PurePosixPath

        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("指标文件必须是实验目录中的相对路径")
        return value

    provenance: Literal["strict", "assisted", "third_party", "alternative"] = "assisted"
    target_scope: Literal["paper_claim", "tutorial"] = "paper_claim"


class ApprovalRecord(Record):
    """Human-in-the-Loop 审批记录，保存高风险操作及用户的审批决定。"""
    task_id: str
    action_hash: str
    approval_type: str
    requested_action: dict
    reason: str
    risk: str
    user_decision: Literal["pending", "approved", "rejected"] = "pending"
    response: str = ""


class ExecutionResult(Record):
    """ExecutionAgent 的执行结果，记录实验状态、指标、日志、产物及失败信息。"""
    plan_id: str
    plan_hash: str
    status: Literal["success", "failed", "partial", "unknown", "running"]
    provenance: Literal["strict", "assisted", "third_party", "alternative"] | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    commands_run: list[dict] = Field(default_factory=list)
    repairs: list[str] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    failure_type: str | None = None
    failure_reason: str | None = None
    container_name: str | None = None
    runtime_seconds: float = 0
    image_id: str | None = None


class VerificationResult(Record):
    """实验验证结果，将实际执行结果与论文目标指标进行比较并给出验证状态。"""
    execution_id: str
    status: Literal[
        "verified", "partially_verified", "not_verified", "not_reproducible", "not_tested"
    ]
    provenance: str
    comparisons: list[dict] = Field(default_factory=list)
    reason: str
    assessment: str
