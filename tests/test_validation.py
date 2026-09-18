import pytest

from scitrace.models.core import ExecutionResult, MetricRule, ReproductionPlan
from scitrace.validation.validator import validate


@pytest.mark.parametrize(
    "actual,status", [(0.91, "verified"), (0.5, "not_verified"), (None, "not_tested")]
)
def test_comparison(actual, status):
    plan = ReproductionPlan(
        claim_id="x",
        metric_rules=[MetricRule(name="accuracy", expected=0.90, absolute_tolerance=0.02)],
    )
    result = ExecutionResult(
        plan_id=plan.id,
        plan_hash="x",
        status="success",
        metrics={} if actual is None else {"accuracy": actual},
    )
    assert validate(plan, result).status == status


def test_tutorial_never_verifies_paper():
    plan = ReproductionPlan(
        claim_id="x",
        target_scope="tutorial",
        metric_rules=[MetricRule(name="P@1", expected=0.1, scope="tutorial")],
    )
    result = ExecutionResult(plan_id=plan.id, plan_hash="x", status="success", metrics={"P@1": 0.1})
    assert validate(plan, result).status == "not_tested"


def test_failed_execution_not_disproof():
    plan = ReproductionPlan(claim_id="x")
    result = ExecutionResult(
        plan_id=plan.id, plan_hash="x", status="failed", failure_type="hardware"
    )
    assert validate(plan, result).status == "not_tested"


def test_scientific_change_cannot_be_labelled_strict():
    from scitrace.validation.validator import effective_provenance

    plan = ReproductionPlan(claim_id="x", provenance="strict", changes=["framework migration"])
    assert effective_provenance(plan) == "assisted"


def test_nonofficial_resource_downgrades_provenance():
    from scitrace.validation.validator import effective_provenance

    plan = ReproductionPlan(claim_id="x", provenance="strict")
    assert effective_provenance(plan, ["third_party"]) == "third_party"
