import pytest

from scitrace.models.core import ReproductionPlan
from scitrace.policy import DeniedAction, NeedsApproval, Policy


def test_approval_bound_to_plan_content(store):
    policy = Policy(store, "task")
    plan = ReproductionPlan(claim_id="claim")
    with pytest.raises(NeedsApproval) as first:
        policy.plan(plan)
    record = first.value.record
    record.user_decision = "approved"
    store.put("approval", record, "task")
    policy.plan(plan)
    plan.assumptions.append("batch size 32")
    with pytest.raises(NeedsApproval) as changed:
        policy.plan(plan)
    assert changed.value.record.id != record.id


def test_rejection_is_persistent(store):
    policy = Policy(store, "task")
    with pytest.raises(NeedsApproval) as request:
        policy.require("third_party_repository", {"url": "https://example.com"}, "reason", "risk")
    record = request.value.record
    record.user_decision = "rejected"
    store.put("approval", record)
    with pytest.raises(DeniedAction):
        policy.require("third_party_repository", {"url": "https://example.com"}, "reason", "risk")


def test_other_task_cannot_reuse_approval(store):
    with pytest.raises(NeedsApproval) as a:
        Policy(store, "a").require("x", {"v": 1}, "", "")
    record = a.value.record
    record.user_decision = "approved"
    store.put("approval", record)
    with pytest.raises(NeedsApproval):
        Policy(store, "b").require("x", {"v": 1}, "", "")
