import math

from scitrace.models.core import ExecutionResult, ReproductionPlan, VerificationResult


def effective_provenance(plan, resource_statuses=()):
    """记录实际条件的保守下界，不能原样采信模型填写的 strict 标签。"""
    if plan.provenance == "alternative":
        return "alternative"
    if plan.provenance == "third_party" or any(
        status != "official" for status in resource_statuses
    ):
        return "third_party"
    undocumented = any(not item.resource_id for item in plan.resources)
    if (
        plan.assumptions
        or plan.changes
        or undocumented
        or plan.target_scope == "tutorial"
        or not (plan.repository_id or plan.resources)
    ):
        return "assisted"
    return plan.provenance


def validate(plan: ReproductionPlan, result: ExecutionResult) -> VerificationResult:
    provenance = result.provenance or effective_provenance(plan)
    comparisons = []
    rules = [r for r in plan.metric_rules if r.scope == plan.target_scope]
    if result.status != "success":
        return VerificationResult(
            execution_id=result.id,
            status="not_tested",
            provenance=provenance,
            reason="执行未完整成功，不能据此否定科学主张",
            assessment="当前执行条件存在阻塞",
        )
    for rule in rules:
        actual = result.metrics.get(rule.name)
        passed = None
        if actual is not None and math.isfinite(actual):
            if rule.comparison == "close":
                passed = abs(actual - rule.expected) <= rule.absolute_tolerance
            elif rule.comparison == "at_least":
                passed = actual >= rule.expected - rule.absolute_tolerance
            else:
                passed = actual <= rule.expected + rule.absolute_tolerance
        comparisons.append(
            {
                "metric": rule.name,
                "actual": actual,
                "expected": rule.expected,
                "tolerance": rule.absolute_tolerance,
                "comparison": rule.comparison,
                "passed": passed,
                "scope": rule.scope,
            }
        )
    tested = [c for c in comparisons if c["passed"] is not None]
    if plan.target_scope == "tutorial":
        status, reason = "not_tested", "官方教程已执行；教程指标不验证论文 benchmark"
    elif not tested:
        status, reason = "not_tested", "缺少预先定义的比较条件或实际指标"
    elif len(tested) == len(rules) and all(c["passed"] for c in tested):
        status, reason = "verified", "实际指标满足预先定义的比较条件（仅限本计划目标）"
    elif any(c["passed"] for c in tested):
        status, reason = "partially_verified", "仅部分指标满足比较条件"
    else:
        status, reason = "not_verified", "实际指标未满足比较条件；需结合实验条件解释"
    return VerificationResult(
        execution_id=result.id,
        status=status,
        provenance=provenance,
        comparisons=comparisons,
        reason=reason,
        assessment="已记录资源、环境、参数和执行产物；不能外推至未测试的论文结论",
    )
