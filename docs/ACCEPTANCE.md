# SciTrace v0.1.1 验收记录

## 当前结果 / 2026-09-15

**真实 Cooking 全链路通过，论文 benchmark 未验证。** 所有服务均使用真实配置：智谱、Tavily、PostgreSQL/checkpoint、Qdrant、E5 与 Docker。执行使用明确固定的本地仓库快照，数据由真实下载核验后复用；不是从空缓存下载所有资源的验收。

| 验收项 | 结果 / 证据 |
| --- | --- |
| 成功任务 | `78603a96-4544-4240-8f7b-e028a05aab1b`，状态 finished |
| 全链路记录 | document=1、discovery=1、repository=1、trace=1、plan=1、approval=3、execution=1、verification=1 |
| 固定提交 | `1142dc4c4ecbc19cc16eee5cdd28472e689267e6`；不冒称最新 HEAD 或 v0.9.2 |
| 数据 SHA256 | `49f2fc08801e2915c813f7d9f1f4f526a4a296efd54531c05d98459e5a331ca6` |
| 实验条件 | 2 CPU、4 GiB、600 秒上限；非 root、断网、只读根；12404 训练 / 3000 验证 |
| 实际命令 | make、数据划分、supervised、test；4 条均 exit code 0 |
| 指标 | N=3000，P@1=0.133，R@1=0.0575 |
| 执行耗时 | 16.4207 秒，包含准备、编译、训练、测试与导出；不包含模型规划和等待审批时间 |
| 执行 ID | `59a2ea0ae3a9b70aa32ab7e6aa2f961ccca3f8aefc9e98d248b4b60e4a58140d` |
| bin 模型 | 6,382,062 字节；SHA256 `d771cdd34a40c633e97bf0634a4b8dc27f4be4e800b77b898f55be0b15bbe20a` |
| vec 模型 | 15,782,118 字节；SHA256 `9668b842b5086a0f61f34c01a9b7f1bd04225574416e4878e19a30485aa2e6d0` |
| 原文核验 | 配方 Trace 引用的论文文本能在对应 PDF 原页提取文本中找到；代码与教程保留行号 |
| 审批与恢复 | 资源、计划、镜像三类审批，独立 CLI 进程恢复；终态协调后仍仅一条 execution |
| 幂等实测 | 新进程再次调用相同执行入口，execution ID 与记录不变，Docker 调用数为 0；`artifacts/acceptance/v0.1.1-idempotency.json` |
| 简单论文路由 | 任务 `02c69353-e419-4974-afaf-92c3757fafd4` 仅 resolve/ingest/两次 paper search 后结束，无 Specialist 和实验；答案学术质量仍需逐项审阅 |
| 单元回归 | 64 passed、6 skipped（真实集成单独运行）；`artifacts/acceptance/v0.1.1-unit.xml` |
| 真实集成 | 6 passed：模型、Postgres/checkpoint、Qdrant、Tavily、Docker、tmpfs 导出；`artifacts/acceptance/v0.1.1-integration.xml` |
| 科学验证 | `not_tested`；教程不验证论文 benchmark，仓库未核实官方身份时 provenance 保守记为 third_party |

报告：`artifacts/tasks/78603a96-4544-4240-8f7b-e028a05aab1b/report.md` 和 `report.json`。

命令日志和模型产物：`artifacts/executions/59a2ea0ae3a9b70aa32ab7e6aa2f961ccca3f8aefc9e98d248b4b60e4a58140d/`。

机器验收摘要：`artifacts/acceptance/v0.1.1-cooking.json`。可重新运行 `uv run python scripts/verify_cooking_acceptance.py 78603a96-4544-4240-8f7b-e028a05aab1b`，检查阶段记录、日志、模型大小/摘要与论文原文引用。

本次是在查验修复过程中跨进程完成的任务，最后根据真实成功账本协调 finished 状态，未重跑实验。不能报告“首次无干预运行全部成功”。失败记录、未全面验证项和下一步见 [仓库查验表](AUDIT_V0.1.1.md)。

## 历史基线 / v0.1.0

以下为初次交付时的历史记录，不代表当前服务状态。

日期：2026-09-14。环境：macOS arm64，Python 3.12.14，依赖固定于 `uv.lock`。

**结论：代码与本地工程测试已交付；完整真实服务闭环尚未验收，不能宣称 fastText 已训练完成或论文已复现。**

## 已通过

| 检查 | 结果与证据 |
| --- | --- |
| 安装 | `uv sync --python 3.12` 成功；后续 `uv sync --offline --locked` 成功 |
| 静态检查 | `ruff check src tests` 通过；Python compileall 通过 |
| 自动化测试 | 45 passed，5 skipped；跳过项均为显式真实服务联调。机器记录：`artifacts/acceptance/pytest.xml` |
| CLI | `scitrace --help`、`run --help`、`doctor` 可启动；doctor 对缺失依赖以非零退出码报告 |
| 真实本地 embedding | `intfloat/multilingual-e5-small`，commit `614241f622f53c4eeff9890bdc4f31cfecc418b3`，CPU 实际编码两条中英文文本，输出 384 维。记录：`artifacts/acceptance/embedding.json` |
| 混合检索基础 | 实际 E5 编码 + Qdrant 官方嵌入式引擎，中文“论文使用哪些数据集？”将英文数据集证据排在首位，并返回页码。记录：`artifacts/acceptance/hybrid.json`。不是服务端联调 |
| fastText 准备 | 成功下载官方 v0.9.2 源码及 Cooking 数据；真实计算 SHA256，生成 4 条容器命令的计划。可追踪清单：`examples/fasttext-cooking.sources.json` |

自动化用例包含：动态路由、Discovery-only、已有计划直接进入 Execution、拒绝后 paper-only、审批摘要变化、重启恢复图逻辑、执行不重复提交、命令失败/超时日志、Docker 隔离参数、SSRF/路径/归档限制、PDF 实际解析与页码、表格 ID 不冲突、模型 revision 缓存区分、证据 ID 验证、报告事实输出与规则验证。

其中模型和 PostgreSQL 在单测中使用可控替身；Qdrant 嵌入式测试产生“payload index 在 local 模式不生效”的库提示，不影响过滤语义测试，不作为生产服务端索引性能证据。

## 未通过环境诊断 / 未运行验收

| 项目 | 当前事实 | 下一步 |
| --- | --- | --- |
| 智谱工具调用 | `GLM_API_KEY` 未配置，未调用真实模型 | 配置密钥和账号可用的 `GLM_MODEL`，运行 doctor |
| Tavily | `TAVILY_API_KEY` 未配置，未运行真实搜索 | 配置密钥并进行搜索探针 |
| PostgreSQL / checkpoint | `DATABASE_URL` 未配置；迁移与跨进程持久化未连接真实数据库验证 | 配置现有数据库，运行 init，再进行暂停/退出/审批/恢复验收 |
| Qdrant 服务 | 未提供实际连接配置；默认 localhost:6333 最终探测返回 502 | 配置已有服务地址/认证，重新诊断并建立索引 |
| Docker | PATH 和常见安装位置未找到 Docker | 安装并启动 Docker，构建 runner 镜像 |
| fastText 编译、训练、评估 | **未运行**；没有 P@1/R@1 结果 | 满足上述条件后提交固定计划，在容器内执行 |
| 全链路科研质量 | **未验收**；目前没有原论文 benchmark 验证 | 先完成 Cooking 工程闭环，再单独选择原论文实验 |

最终机器诊断：`artifacts/acceptance/doctor.json`。本地网络使用 fake-IP 代理；仅对已选定的官方资源域名显式开启对应配置后，资源下载成功。此配置没有放行内网地址。

## fastText 固定资源

| 资源 | 字节数 | SHA256 |
| --- | ---: | --- |
| 官方 v0.9.2 源码归档 | 4036722 | `7ea4edcdb64bfc6faaaec193ef181bdc108ee62bb6a04e48b2e80b639a99e27e` |
| 官方 Cooking 数据归档 | 457609 | `49f2fc08801e2915c813f7d9f1f4f526a4a296efd54531c05d98459e5a331ca6` |

来源及生成的计划见 `examples/fasttext-cooking.sources.json` 和 `examples/fasttext-cooking.plan.json`。教程执行成功也只证明对应执行事实，报告仍将论文 benchmark 标记为 `not_tested`。

## 真实联调顺序

1. 配置 `.env` 中的真实服务；执行 `uv run scitrace init`。
2. 安装/启动 Docker，按 README 构建 `scitrace-runner:0.1`；运行 `doctor --embedding`。
3. 运行 `SCITRACE_INTEGRATION=1 uv run pytest -m integration -q`。
4. 通过 `run --plan examples/fasttext-cooking.plan.json` 提交任务，检查计划、镜像审批与重启恢复。
5. 保存执行日志、实际指标、报告，并更新本文件和 ITERATIONS.md；失败则记录具体环境或代码问题。
