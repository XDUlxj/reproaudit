from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class SciTraceState(TypedDict, total=False): # total=False 以下字段可以暂时不存在
    task_id: str # 任务id
    user_query: str # 用户请求
    messages: Annotated[list, add_messages] # 对话记录，新消息加进已有列表，且自动按 `tool_call_id` 把 ToolMessage 接回对应的 AIMessage
    steps: int # 决策步数，超过最大限制就要收尾
    action: dict # 本轮的工具调用，supervisor写入
    pending_approval: str | None # 待审批的id
    observations: list[dict] # 工具调用的结果
    action_counts: dict[str, int] # 工具调用的次数
    final_answer: str | None # 最终答案
    fatal_error: str | None # 致命错误，直接图返回
    status: str # running / waiting_approval / partial / finished / failed
    requires_execution: bool # 从 task 带过来的执行要求
    finish_corrections: int # finish 守卫的纠正次数，防止没有证据提前收工
