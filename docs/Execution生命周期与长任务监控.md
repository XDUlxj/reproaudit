**实验由独立子进程跑，Monitor 是常驻的轻量后台协程，定期检查 PostgreSQL 中所有** **`running`** **实验对应的进程状态；只有状态发生变化时，才重新进入 Agent 工作流。**

ExecutionAgent
     ↓
启动 run_001
     ↓
python train.py  ← 独立进程自己跑
     ↓
ExecutionAgent 不需要守着它


Monitor
   ↓
每 30s / 60s
查询 DB 中 status=running 的 Run
   ↓
检查对应实验是否结束
   ↓
没结束 → 什么都不做
   ↓
结束 → 更新 ExperimentRun
       → 触发后续流程

```python
class ExperimentRunner:

    def start(self, spec: ExperimentSpec) -> ExecutionHandle:
        ...

    def status(self, handle: ExecutionHandle) -> RunStatus:
        ...

    def terminate(self, handle: ExecutionHandle) -> None:
        ...
        
```


