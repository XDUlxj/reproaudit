from scitrace.models.core import ApprovalRecord, fingerprint


class NeedsApproval(Exception):
    def __init__(self, record: ApprovalRecord):
        self.record = record
        super().__init__(record.reason)


class DeniedAction(ValueError):
    pass


class Policy:
    def __init__(self, store, task_id):
        self.store, self.task_id = store, task_id

    def require(self, kind: str, action: dict, reason: str, risk: str) -> ApprovalRecord:
        digest = fingerprint({"type": kind, "action": action})
        id = fingerprint({"task": self.task_id, "action": digest})
        try:
            record = ApprovalRecord.model_validate(self.store.get("approval", id))
        except KeyError:
            record = ApprovalRecord(
                id=id,
                task_id=self.task_id,
                action_hash=digest,
                approval_type=kind,
                requested_action=action,
                reason=reason,
                risk=risk,
            )
            self.store.put("approval", record, self.task_id)
        if record.user_decision == "rejected":
            raise DeniedAction("用户已拒绝此操作，请寻找其他路径：" + reason)
        if record.user_decision != "approved":
            raise NeedsApproval(record)
        return record

    def resource(self, resource: dict):
        if resource["resource_status"] != "official":
            self.require(
                "third_party_repository",
                resource,
                "资源尚未确认为官方，使用前需确认",
                "非官方或未核实资源会影响复现来源可信度",
            )

    def plan(self, plan):
        # 首次执行完整计划也审阅：LLM 不能自行批准它生成的命令、参数或资源。
        if plan.blockers:
            raise ValueError("计划仍有阻塞项：" + "; ".join(plan.blockers))
        self.require(
            "execution_plan",
            plan.model_dump(mode="json"),
            "确认具体实验计划、参数假设、来源和执行预算",
            "请检查命令、资源、镜像及科学条件；变更计划后需重新确认",
        )
