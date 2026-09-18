import json

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel

from scitrace.agents.loop import BASE_PROMPT, tool_for
from scitrace.agents.specialists import make_specialists
from scitrace.graph.state import SciTraceState
from scitrace.models.core import fingerprint
from scitrace.policy import NeedsApproval
from scitrace.references import observation


class Goal(BaseModel):
    goal: str


class Finish(BaseModel):
    answer: str


def execution_completion(r, state):
    """单实验任务的完成条件由账本和验证记录判定，避免完成后继续空转。"""
    if not state.get("requires_execution"):
        return None
    executions = r.store.find("execution", r.task_id)
    if len(executions) != 1 or executions[0]["status"] != "success":
        return None
    execution = executions[0]
    verification = next(
        (
            v
            for v in r.store.find("verification", r.task_id)
            if v["execution_id"] == execution["id"]
        ),
        None,
    )
    if not verification:
        return None
    return {
        "status": "finished",
        "action": {"name": "finish"},
        "pending_approval": None,
        "final_answer": (
            f"实验执行成功，执行 ID：{execution['id']}。\n"
            f"实际指标：{json.dumps(execution['metrics'], ensure_ascii=False)}。\n"
            f"耗时：{execution['runtime_seconds']:.2f} 秒。\n"
            f"验证状态：{verification['status']}；{verification['reason']}。\n"
            "命令、日志和产物清单见报告。"
        ),
    }


def build_graph(r, checkpointer):
    specialists = make_specialists(r)
    basics = {
        name: tool_for(fn, name)
        for name, fn in {
            "paper_resolve": r.paper.resolve,
            "paper_ingest": r.paper.ingest,
            "paper_hybrid_search": r.paper.search,
            "read_evidence": r.paper.evidence,
            "read_record": r.trace.read_record,
        }.items()
    } # supervisor 可以使用的基础工具
    schemas = (
        list(basics.values())
        + [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": Goal.model_json_schema(),
                },
            }
            for name, description in {
                "discovery_agent": "发现和核实科研资源。goal 包含目标和已有证据 ID。",
                "trace_agent": "追踪 Claim 证据及生成计划。goal 包含论文/仓库/index ID。",
                "execution_agent": "执行已存在的计划。goal 必须包含 plan ID。",
            }.items()
        ]
        + [
            {
                "type": "function",
                "function": {
                    "name": "finish",
                    "description": "用户目标满足或所有合法路径均阻塞时结束。",
                    "parameters": Finish.model_json_schema(),
                },
            }
        ]
    ) # 这才是所有工具，包括 agent as tool
    model = r.model.bind_tools(schemas, parallel_tool_calls=False)

    def supervisor(state):
        completed = execution_completion(r, state)
        if completed:
            return completed
        steps = state.get("steps", 0)
        if steps >= r.settings.max_steps:
            return {
                "status": "partial",
                "final_answer": "达到任务决策预算；请查看已收集证据与阻塞项。",
                "action": {"name": "finish"},
            }
        messages = state.get("messages", [])
        if not messages:
            messages = [
                SystemMessage(
                    BASE_PROMPT
                    + "你是 SciTraceAgent Supervisor，动态决定下一步。简单论文问题直接用 Paper Tools；不强制调用 Specialist。所有 Specialist 结果返回后重新判断目标。遇到拒绝先找其他合法路径；未执行不能宣称复现。引用使用 evidence ID。"
                ),
                HumanMessage(state["user_query"]),
            ]
        response = model.invoke(messages)
        r.record_usage("SciTraceAgent", response)
        new_messages = ([*messages] if not state.get("messages") else []) + [response]
        if len(response.tool_calls) != 1:
            for call in response.tool_calls:
                new_messages.append(ToolMessage("每轮只能调用一个工具", tool_call_id=call["id"]))
            if not response.tool_calls:
                new_messages.append(HumanMessage("请调用一个工具或 finish。"))
            return {"messages": new_messages, "steps": steps + 1, "action": {"name": "retry"}}
        action = response.tool_calls[0]
        action = {**action, "args": r.references.decode(action["args"])}
        if action["name"] == "finish": # 模型希望结束，但仍然需要判定
            answer = Finish.model_validate(action["args"]).answer # 拿到 action 中的 answer 参数
            execution_requested = any(
                o["tool"] == "execution_agent" for o in state.get("observations", [])
            ) # 检查是否调用过 execution_agent
            executions = r.store.find("execution", r.task_id) # 检查当前任务的执行记录
            plans = r.store.find("plan", r.task_id) # 检查当前任务形成的复现计划
            requires_execution = state.get("requires_execution", False) or execution_requested # 判定当前任务是否需要执行
            # 用户任务本身要求执行
            # requires_execution == True
            # 或者
            # 之前已经调用过 execution_agent
            # execution_requested == True
            if (
                requires_execution
                and not execution_requested
                and not executions
                and plans
                and not any(p.get("blockers") for p in plans)
            ): # 明明已经有一个可以执行的实验计划，而且用户要求执行实验，没执行就想 finish
                if state.get("finish_corrections", 0) < 2:
                    return {
                        "messages": [
                            *new_messages,
                            ToolMessage(
                                "当前已有可执行计划，尚无执行记录，目标未完成。请调用 execution_agent；计划引用："
                                + observation(r, [{"plan_id": p["id"]} for p in plans]),
                                tool_call_id=action["id"],
                            ),
                        ],
                        "steps": steps + 1,
                        "action": {"name": "retry"},
                        "finish_corrections": state.get("finish_corrections", 0) + 1,
                    }
            if requires_execution and not executions: # 任务要求执行，但数据库里一条 Execution 记录都没有，就不能算完成
                return {
                    "messages": new_messages,
                    "steps": steps + 1,
                    "action": action,
                    "final_answer": (
                        "实验尚未开始：没有执行记录，任务未完成。"
                        "不能报告编译失败、训练失败或内存不足。"
                        "请查看工具错误和计划阻塞项；阻塞项是待解决条件，"
                        "不是实际实验结果。"
                    ),
                    "status": "partial",
                }
            if executions:
                # 执行结论由账本生成；不接受模型用自然语言补造指标或失败原因。
                latest = executions[-1]
                answer = (
                    f"执行状态：{latest['status']}；执行 ID：{latest['id']}。\n"
                    f"实际指标：{json.dumps(latest.get('metrics', {}), ensure_ascii=False)}。\n"
                    f"失败原因：{latest.get('failure_reason') or '无'}。\n"
                    "完整命令、日志、产物和比较范围见报告。"
                )
                for verification in r.store.find("verification", r.task_id):
                    if verification["execution_id"] == latest["id"]:
                        answer += (
                            f"\n验证状态：{verification['status']}；{verification['reason']}。"
                        )
            return {
                "messages": new_messages,
                "steps": steps + 1,
                "action": action,
                "final_answer": answer,
                "status": "partial"
                if executions and executions[-1]["status"] != "success"
                else "finished",
            }
        counts = dict(state.get("action_counts", {}))
        key = fingerprint([action["name"], action["args"]])
        counts[key] = counts.get(key, 0) + 1
        if counts[key] > 2:
            return {
                "messages": new_messages,
                "steps": steps + 1,
                "action": {"name": "finish"},
                "final_answer": "连续重复调用未取得进展，已停止。请查看阻塞记录。",
                "status": "partial",
            }
        return {
            "messages": new_messages,
            "steps": steps + 1,
            "action": action,
            "action_counts": counts,
            "status": "running",
        }

    def execute(state):
        action = state["action"]
        try:
            if action["name"] in specialists:
                goal = Goal.model_validate(action["args"])
                if (
                    action["name"] == "trace_agent"
                    and "\n论文输入：" in state.get("user_query", "")
                    and not r.store.find("document", r.task_id)
                ):
                    raise ValueError(
                        "用户提供的论文尚未入库；先调用 paper_resolve/paper_ingest，Trace 只检索已建立的索引"
                    )
                if action["name"] == "execution_agent" and not r.store.find("plan", r.task_id):
                    raise ValueError(
                        "当前任务没有持久化复现计划，不能进入 Execution。"
                        "请先用 Trace 索引仓库、保存证据链和计划，审批后再执行；"
                        "无法完成时必须报告阻塞和未执行状态。"
                    )
                result = specialists[action["name"]].run(goal.goal)
            elif action["name"] in basics:
                result = basics[action["name"]].invoke(action["args"])
            else:
                raise ValueError("未知工具")
            r.event("SciTraceAgent", action["name"], "completed")
        except NeedsApproval as exc:
            return {"pending_approval": exc.record.id, "status": "waiting_approval"}
        except Exception as exc:
            detail = r.settings.redact(str(exc))[:1500]
            result = {"error": detail}
            r.event("SciTraceAgent", action["name"], "error", detail)
            # Downloader 已完成有限重试。论文解析/索引仍失败时，继续调用其他
            # Specialist 不可能回答依赖原文的问题，因此直接保留根因并停止。
            if action["name"] == "paper_ingest":
                ref = r.artifacts.json(
                    f"tasks/{r.task_id}/observations/{state['steps']}.json", result
                )
                return {
                    "messages": [
                        ToolMessage(
                            json.dumps(result, ensure_ascii=False), tool_call_id=action["id"]
                        )
                    ],
                    "fatal_error": detail,
                    "final_answer": "论文处理失败：" + detail,
                    "observations": [
                        *state.get("observations", []),
                        {"tool": action["name"], "artifact": ref},
                    ],
                    "status": "partial",
                }
        ref = r.artifacts.json(f"tasks/{r.task_id}/observations/{state['steps']}.json", result)
        observations = [*state.get("observations", []), {"tool": action["name"], "artifact": ref}]
        return {
            "messages": [ToolMessage(observation(r, result), tool_call_id=action["id"])],
            "observations": observations,
            "pending_approval": None,
            "status": "running",
        }

    def approval(state):
        record = r.store.get("approval", state["pending_approval"])
        # interrupt 节点之前只有只读操作；用户决定由 CLI 原子写入业务表。
        interrupt(
            {
                "approval_id": record["id"],
                "reason": record["reason"],
                "risk": record["risk"],
                "action": record["requested_action"],
            }
        )
        record = r.store.get("approval", record["id"])
        if record["user_decision"] == "pending":
            raise ValueError("请先使用 approve 命令记录批准或拒绝")
        if record["user_decision"] == "rejected":
            return {
                "pending_approval": None,
                "status": "running",
                "messages": [
                    ToolMessage(
                        "用户拒绝：" + record["reason"] + "。寻找合法替代路径，如 paper-only。",
                        tool_call_id=state["action"]["id"],
                    )
                ],
                "action": {"name": "replan"},
            }
        return {"pending_approval": None, "status": "running"}

    graph = StateGraph(SciTraceState)
    graph.add_node("supervisor", supervisor)
    graph.add_node("execute", execute)
    graph.add_node("approval", approval)
    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        lambda s: (
            END
            if s["action"]["name"] == "finish"
            else "supervisor"
            if s["action"]["name"] == "retry"
            else "execute"
        ),
    )
    graph.add_conditional_edges(
        "execute",
        lambda s: (
            END
            if s.get("fatal_error")
            else "approval"
            if s.get("pending_approval")
            else "supervisor"
        ),
    )
    graph.add_conditional_edges(
        "approval", lambda s: "supervisor" if s["action"]["name"] == "replan" else "execute"
    )
    return graph.compile(checkpointer=checkpointer)
