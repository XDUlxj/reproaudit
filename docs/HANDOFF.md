# SciTrace 开发交接

基线版本：v0.1.1。更新日期：2026-09-17。面向下一位开发者或后续开发会话；操作命令见 [使用指南](USER_GUIDE.md)。

## 1. 当前结论与证据

项目已完成一个真实 fastText Cooking 教程闭环，使用智谱、Tavily、PostgreSQL/checkpoint、Qdrant、E5 和 Docker。案例经过修复、审批和跨进程恢复，不是首次无人干预或空缓存验收。原论文 benchmark 为 `not_tested`，通用规划和学术关联质量尚未全面验收。

| 基线项 | 历史验证结果 / 位置 |
| --- | --- |
| 应用 / 依赖 | `pyproject.toml` 与 `uv.lock`：0.1.1；Python 3.12 |
| 单元回归 | 2026-09-15：64 passed、6 skipped；`artifacts/acceptance/v0.1.1-unit.xml` |
| 真实集成 | 2026-09-15：6 passed；`artifacts/acceptance/v0.1.1-integration.xml` |
| 全链路任务 | `78603a96-4544-4240-8f7b-e028a05aab1b`，finished；document/discovery/repository/trace/plan/execution/verification 各 1，approval 3 |
| 仓库提交 | `1142dc4c4ecbc19cc16eee5cdd28472e689267e6`，不是最新 HEAD 或 v0.9.2 |
| 实际实验 | 四条命令均退出 0；N=3000，P@1=0.133，R@1=0.0575；有 bin/vec 模型与日志 |
| 执行 ID | `59a2ea0ae3a9b70aa32ab7e6aa2f961ccca3f8aefc9e98d248b4b60e4a58140d` |
| 复查证据 | `artifacts/acceptance/v0.1.1-cooking.json`、`v0.1.1-idempotency.json`；任务与执行目录 |

这些是已有记录的历史结果，本文创建时没有重新运行服务或实验。后续版本需重新验证并记录日期，不能沿用旧结果宣称新代码通过。完整边界见 [仓库查验](AUDIT_V0.1.1.md)、[验收记录](ACCEPTANCE.md)、[迭代记录](ITERATIONS.md)。

## 2. 必须保留的设计约束

1. 保留动态 Supervisor、基础 Paper Tools 和三个独立 Agent-as-Tool Loop。不要为了一个配方把系统改成固定 Discovery → Trace → Execution 流水线。
2. 论文、README、网页和模型输出属于不可信内容，不能覆盖工具权限或审批。宿主仅运行应用；论文仓库脚本必须经 Docker 工具运行。
3. 审批绑定具体动作和摘要，资源、计划、镜像分别授权；变化后不能沿用旧审批，也不能用模型“用户已同意”代替记录。
4. 执行账本与 checkpoint 分工保留。已成功执行幂等返回；状态不明不自动重跑。不能靠删除历史记录恢复所谓正常流程。
5. 原始 PDF、代码快照、日志和模型放 artifact store；图状态只保留引用及有界摘要。证据保留版本、页码或行号。
6. exact/BM25 与 vector 两路检索都保留，embedding revision、内容和仓库版本不能混用缓存。
7. Provenance、Execution、Verification 分开。教程成功不能标记原论文 verified，执行失败不等于 Claim 被证伪；没有账本不能编造实验失败原因。

## 3. 代码导航

| 文件 / 模块 | 职责与修改注意事项 |
| --- | --- |
| `src/scitrace/cli.py` | 配置/初始化/诊断、创建任务、审批恢复、导出；新参数同步指南和 CLI 测试 |
| `config.py`、`.env.example` | 配置与脱敏；默认模型和模板模型可能不同，以实际配置为准，不写真实密钥 |
| `graph/builder.py`、`graph/state.py` | Supervisor 决策、interrupt、完成条件；当前完成协调针对单实验目标 |
| `agents/loop.py`、`agents/specialists.py` | Specialist 工具权限、对话恢复、重复调用收敛；Cooking 计划成功直接返回持久 Trace |
| `runtime.py`、`references.py` | 服务/工具装配、事件、持久短引用映射；模型见 refN，持久记录保留完整 ID |
| `models/core.py` | 版本化业务契约、计划/命令/预算/验证模型；变更先考虑老记录读取兼容 |
| `storage.py` | PostgreSQL records、任务关联、迁移、锁、artifact 边界；现有业务迁移版本 1/2 |
| `tools/paper.py` | 输入解析、本地授权、PDF/HTML ingestion、NUL 等长替换、检索 |
| `indexing/hybrid.py` | E5/Qdrant 与关键词融合；模型固定提交及 query/passage 前缀 |
| `tools/discovery.py` | Tavily、网页证据、资源身份；README 自述不自动提升官方身份 |
| `tools/repository.py` | 固定版本快照、目录/文本/AST 检索；resource ID 与 repository ID 不可混用 |
| `tools/trace.py` | Claim/证据关系、实际资源摘要、计划校验、受限 Cooking 配方 |
| `policy.py` | 动作摘要与审批守卫；拒绝路径和计划变化需回归 |
| `tools/network.py` | DNS/重定向/SSRF、预算与时限、安全解压；不自动扩展可信域名 |
| `execution/runner.py`、`Dockerfile.runner` | 隔离、账本、实际命令、指标、tmpfs tar 流导出；不能退回空产物的 docker cp 行为 |
| `validation/validator.py` | 独立指标比较，教程或缺少条件为 not_tested |
| `reporting/report.py` | 从真实记录导出结论、证据池、审批、指标与产物 |
| `tests/`、`scripts/verify_cooking_acceptance.py` | 工程回归、显式真实集成、单案例离线复查 |

## 4. 接手后的检查顺序

先查看 `git status --short` 和上述三份记录，再阅读架构文件 `SciTrace_V1_Architecture.md`。本轮工作区包含大量未提交文件及旧 `reproaudit` 删除项；这些属于现有工作，不能 reset、恢复旧框架或清理掉用户产物。

在仓库根目录执行：

```bash
uv sync --locked
uv run scitrace --help
uv run scitrace run --help
uv run ruff check src tests scripts
uv run pytest -q
```

本地配置和真实服务准备好后再执行以下检查；诊断和集成会消耗服务额度，运行 Docker 测试：

```bash
uv run scitrace init
uv run scitrace doctor --embedding
SCITRACE_INTEGRATION=1 uv run pytest -m integration -q
```

默认跳过真实集成是预期行为，不能将 skipped 写成通过。新机器需要自己的 `.env`、运行镜像和模型缓存，Git 克隆不包含完整历史 `artifacts`。已有成功任务的离线复查命令见使用指南；若产物缺失，记录“无法复查”，不要生成替身补齐。

## 5. 已知限制与待办优先级

| 优先级 | TODO | 完成标准 |
| --- | --- | --- |
| P0 | 固定 Cooking 发布回归并统计多次真实运行、冷缓存运行 | 每次记录配置、代码/镜像/数据摘要、审批、命令、日志、产物；统计首次成功率，不只保留成功案例 |
| P0 | 更清晰的 ID/参数错误纠正和无进展诊断 | 未注册/错类型引用明确报错；不会虚构 ID、重复耗尽预算或绕过审批；重启后映射一致 |
| P1 | 一个原论文 benchmark 严格验证 | 预先固定数据划分、方法配置、比较指标/容差与证据；真实执行后由独立 Validator 比较 |
| P1 | 计划语义校验与更多可审阅配方 | 防止 train/valid 重叠、错指标、错权重；配方仍可选，不替代动态调度 |
| P1 | 多实验完成条件 | 明确每个实验的必需结果及失败策略，不能用任一成功账本结束整个多实验任务 |
| P2 | 复杂表格/公式与检索质量评估 | 人工标注集可复查，分别报告证据召回和科学关联准确性 |
| P2 | 远程执行、GPU、Web、OCR | CLI 和审批/幂等契约稳定后扩展，单独定义安全与验证范围 |

现有网络重试不等于自动环境修复系统。不要自动升级科学依赖、修改训练参数或论文源码。计划命令校验不是完整语义证明；隔离容器也不是公共多租户强对抗沙箱。历史暴露密钥是否已在服务端轮换尚未确认，不在文档保存任何凭据。

## 6. 每个版本的交付清单

1. 定义版本范围和验收标准，列出需要真实验证的路径及不能证明的科学结论。
2. 修改代码并为核心状态、审批、证据保存、执行边界保留必要中文注释；加入针对实际风险的回归。
3. 业务记录/状态变更提供兼容或迁移说明。迁移追加在专用 schema，备份后验证；不得删除旧任务或 checkpoint 来通过测试。
4. 更新 `pyproject.toml` 版本，执行 `uv lock`；检查 `uv.lock` 同步。runner 镜像是否变化单独说明，不能只凭 tag 判断镜像内容。
5. 完成静态/单元检查；真实集成、冷缓存、重启审批、成功幂等、unknown 不重跑分别报告通过/失败/未运行。
6. 更新 USER_GUIDE、ACCEPTANCE、ITERATIONS 和本文。真实结果保存到新的版本/任务证据位置，保留失败历史。
7. 检查 `git diff --check` 和待交付文件，避免提交 `.env`、缓存、模型和实验数据。提交/发布按当次用户指令执行。

离线核验脚本目前输出固定 `v0.1.1-cooking.json`；下一版若沿用它，应先增加版本/输出参数，避免覆盖基线摘要。仓库版本、记录 schema_version、计划版本、embedding revision、镜像 ID 是不同概念，升级时分别记录。

## 7. 后续会话可直接使用的交接说明

```text
请继续开发 SciTrace。先阅读 docs/HANDOFF.md、docs/ITERATIONS.md、
docs/ACCEPTANCE.md 和 SciTrace_V1_Architecture.md，再检查工作区实际代码。
基线为 v0.1.1：真实 Cooking 教程闭环通过，但不是原论文 benchmark 验证，
也不是首次无干预/空缓存成功。保留动态 Supervisor 与三个独立 Agent Loop，
Docker 执行、动作摘要审批、幂等账本、原文证据和 exact/vector 两路检索。
不要覆盖已有未提交修改、恢复 reproaudit、打印凭据或在宿主运行论文脚本。
本次目标：[填写版本与具体任务]。
验收要求：[填写真实案例、比较标准、预算和需要保留的证据]。
结束时更新使用指南、验收记录、迭代表及 handoff，区分已实现与已验证。
```
