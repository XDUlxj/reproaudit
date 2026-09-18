# SciTrace v0.1

SciTrace 是一个面向科研论文的 CLI Agent：追踪 Scientific Claim 的论文与代码证据，发现复现资源，生成可审批计划，并在 Docker 中执行实验、保存指标和来源记录。

当前提供真实服务适配与执行器，没有离线模拟服务回退。开发测试结果及尚未完成的真实联调见 [验收记录](docs/ACCEPTANCE.md)；每次迭代的已完成/TODO 见 [迭代记录](docs/ITERATIONS.md)。

完整操作说明见 [使用指南](docs/USER_GUIDE.md)；后续版本的代码导航、验证基线、TODO 和交付要求见 [开发交接](docs/HANDOFF.md)。

## 1. 安装和配置

需要 Python 3.12、uv、可用的 PostgreSQL 与 Qdrant。Docker 只在实际执行论文训练或评估时需要；应用本身在宿主虚拟环境运行。Python 3.13 允许安装但本次开发测试使用 3.12。

```bash
uv sync --locked
cp .env.example .env
```

编辑 `.env`：

| 配置 | 用途 |
| --- | --- |
| `GLM_API_KEY` / `GLM_MODEL` | 智谱标准 API 密钥及支持工具调用的模型；默认模型需按你的账号可用性确认 |
| `GLM_BASE_URL` | 默认 `https://open.bigmodel.cn/api/paas/v4/` |
| `TAVILY_API_KEY` | 资源搜索 |
| `DATABASE_URL` | 现有 PostgreSQL 连接；账号需在目标库创建 SciTrace 专用 schema |
| `QDRANT_URL` / `QDRANT_API_KEY` | 现有 Qdrant 服务 |
| `EMBEDDING_MODEL` / `EMBEDDING_REVISION` | 本地 multilingual-e5-small；已固定实际验证的模型 commit |
| `ARTIFACT_ROOT` | PDF、代码快照、索引原文、日志、模型缓存和报告的本地目录 |

密钥不要粘贴进论文输入或提交 Git。数据库和 Qdrant 可用并不代表迁移已完成：

```bash
uv run scitrace init
# 只在构建阶段联网安装 C++ 工具链；不会安装到宿主 Python 环境
# 镜像 tag 的实际 image ID 会在执行前固定并审批
uv run scitrace doctor --embedding --skip-docker
```

这会启用本地追踪模式：可以解析论文、发现与核验资源、构建检索索引、追踪 Claim 证据、生成复现计划、进行审批和导出报告。计划实际执行仍会要求 Docker，且不会退回到宿主机执行论文代码。

准备好执行实验时，再构建运行镜像：

```bash
docker build -f Dockerfile.runner -t scitrace-runner:0.1 .
uv run scitrace doctor --embedding
```

`init` 只创建 `scitrace`、`scitrace_checkpoints` schema 及其表，不重建数据库、不删除其他表。`doctor` 会实际调用智谱工具探针和一次 Tavily 查询；这些调用使用你的服务额度。`--embedding` 首次下载开源模型，后续从 `ARTIFACT_ROOT/models` 读取；编码使用 CPU，无 embedding API 费用。

如果代理把域名映射为 `198.18.x.x`，在 `.env` 中显式配置 `TRUSTED_FAKE_DNS_HOSTS`，例如：

```dotenv
TRUSTED_FAKE_DNS_HOSTS=["arxiv.org","export.arxiv.org","api.crossref.org","api.github.com","github.com","codeload.github.com","raw.githubusercontent.com","fasttext.cc","dl.fbaipublicfiles.com"]
```

仅列出你信任的目标域名。默认 `[]`，保留地址一律阻止。该配置只允许上述域名解析到 `198.18.0.0/15`，不会放行回环、链路本地或 RFC1918 内网。重定向目的域名仍需独立校验。

## 2. 使用

```bash
uv run scitrace run "这篇论文使用了哪些数据集？请给出页码和原文证据。" --paper 1607.01759

uv run scitrace run "查找这篇论文的官方代码，并给出官方身份依据" --paper 1607.01759

uv run scitrace run "追踪文本分类方法到代码入口，列出复现缺口，不运行实验" \
  --paper ./paper.pdf --repository https://github.com/facebookresearch/fastText

uv run scitrace run "分析方法实现与论文的一致性" --paper ./paper.pdf --repository ./my-repo
```

每次运行会输出任务 ID。用户提供仓库不自动意味着“官方”；首次使用未核实/第三方资源需要确认。可用 `--trusted-project https://...` 显式指定自己认可的官方项目页，项目页的直接链接可作为资源来源证据。

```bash
uv run scitrace status TASK_ID
uv run scitrace approve TASK_ID APPROVAL_ID approved
uv run scitrace resume TASK_ID

# 拒绝后 Supervisor 会先寻找合法替代路径
uv run scitrace approve TASK_ID APPROVAL_ID rejected
uv run scitrace resume TASK_ID

# 标题存在多个候选时，选择从 1 开始的序号
uv run scitrace approve TASK_ID APPROVAL_ID approved --response 2
uv run scitrace resume TASK_ID

uv run scitrace report TASK_ID
```

审批记录不能覆盖历史决定；修改计划生成新 ID 并递增版本。`resume` 不自动批准操作，不自动重跑已完成或状态不明的实验。进程异常后可恢复图 checkpoint；已开始但无法确认完成的实验标记 `unknown`，需要检查记录并另建明确的新计划。

## 3. fastText 快速验收

### v0.1.1 已验证的完整 Agent 路径

真实验收任务为 `78603a96-4544-4240-8f7b-e028a05aab1b`：论文 → Discovery → Trace → 计划 → 三类审批 → Docker 编译/训练/测试 → 模型产物 → 报告。实际 P@1 为 0.133、R@1 为 0.0575，论文 benchmark 为 `not_tested`。详细证据和已知限制见 [验收记录](docs/ACCEPTANCE.md) 与 [仓库查验表](docs/AUDIT_V0.1.1.md)。

```bash
uv run scitrace doctor --embedding

uv run scitrace run \
  "fastText Cooking 全链路验收。先解析入库论文；Discovery 搜索注册官方仓库；Trace 用固定 revision 1142dc4c4ecbc19cc16eee5cdd28472e689267e6 索引仓库，再直接调用 prepare_cooking_tutorial，不传参数。随后 Execution 执行计划并报告。教程不代表论文 benchmark。" \
  --paper 1607.01759 --trusted-project https://fasttext.cc --require-execution
```

按输出的任务 ID 和审批 ID 使用 `status`、`approve`、`resume`。`--require-execution` 明确要求单次实验完成；已有计划却没有执行记录时不能成功结束。每次实际实验只运行一次，重启后根据 checkpoint 和执行账本恢复。

`prepare_cooking_tutorial` 是 Trace 可选的受限工具：检索真实论文/代码/教程证据，核验下载，生成固定划分及默认训练参数的计划。它不替代 Supervisor，也不代表任意论文均可自动生成正确实验。验收使用明确固定的缓存提交；没有缓存时下载该提交快照，网络失败会明确停止。不要将其描述成“最新 HEAD”。

离线核验本次成功任务的日志、模型摘要与论文页码引用：

```bash
uv run python scripts/verify_cooking_acceptance.py 78603a96-4544-4240-8f7b-e028a05aab1b
```

### 固定计划的执行器单独验收

论文：[Bag of Tricks for Efficient Text Classification](https://arxiv.org/abs/1607.01759)。使用[官方 Cooking 教程](https://fasttext.cc/docs/en/supervised-tutorial.html)的 15,404 条数据、12,404/3,000 划分和 v0.9.2 源码。此案例验证应用执行链路；它不验证论文 benchmark。

```bash
# 下载官方资源、计算 SHA256、生成包含 4 条具体命令的计划；不运行实验
uv run scitrace prepare-fasttext

# 阅读生成的计划后提交给动态 Agent
uv run scitrace run "执行已有 fastText Cooking 教程计划，报告 P@1、R@1 和日志；明确论文 benchmark 尚未验证" \
  --plan artifacts/examples/fasttext-plan.json

# 按任务实际返回的审批 ID 逐项确认计划及本地镜像，再 resume
uv run scitrace status TASK_ID
```

生成的 `.sources.json` 保存真实来源、文件大小和 SHA256。验收命令依次在容器内编译源码、划分数据、训练和测试。线程数固定 2，其余使用教程默认训练参数；该差异已列入计划。工具不会预置“预期成功”的指标。报告中的 `Verification=not_tested` 表示论文 benchmark 未验证，即使教程命令成功。

## 4. 架构与执行约束

- 顶层是 LangGraph `SciTraceAgent` 动态循环；Discovery、Trace、Execution 各自执行受预算限制的独立 Agent Loop，以工具形式返回结果。不存在固定 Discovery→Trace→Execution 顺序。
- 基础工具组合实现解析、元数据、切片、表格提取、索引和检索。Paper 使用 BM25/精确匹配 + E5/Qdrant，Repository 补充文件名、Python AST 符号、行号。RRF 完成融合重排；原文保留在本地和证据记录中。
- PostgreSQL 记录任务与审批，专用 checkpoint schema 保存图状态；Specialist 中间消息单独持久化。任务锁禁止两个 CLI 同时运行同一任务。
- 审批在工具层执行。第三方资源、完整执行计划及实际镜像 ID 都有具体授权记录；计划中的参数假设、变更和预算一起审阅。不能靠模型口头“用户已同意”绕过。
- 容器非 root、断网、只读根文件系统、丢弃 capabilities，不挂载凭据或 Docker socket。宿主输入只读挂载；实验目录使用默认 1 GiB tmpfs，默认 2 CPU、4 GiB 内存、600 秒。
- Docker 主进程有计划时限，CLI 异常退出后容器也不会无限训练。运行日志写宿主任务目录并限制大小；输出在容器停止前导出。实验容器不是通用强对抗代码沙箱；本版定位单用户科研执行，不应暴露为公共任意代码运行服务。
- 原子网络错误最多自动重试两次并记录；不自动改依赖 pin、补科学参数或修改论文源码。额外依赖应写入明确的准备资源/镜像与计划，审批后执行。
- 指标 JSON 约定为有限数值对象，例如 `{"accuracy": 0.91}`；fastText 使用独立日志解析器。只有执行成功且存在事先确认的比较规则才计算验证结论。Provenance、Execution、Verification 分开报告。

## 5. 当前支持边界

首版支持文本 PDF 与 HTML，扫描件 OCR 和复杂表格不能保证解析；工具会报告缺口。远程仓库只支持 GitHub 快照，其他仓库通过本地输入；本地索引跳过符号链接、环境文件、依赖目录及超过 1 MB 的文件，因此数据/权重应通过计划资源显式提供。

执行环境需要预先构建镜像；没有 GPU、远程执行、任意论文从零实现或自动科研源码修复。生成 PDF/Repo 索引不意味着每条证据关联都正确，报告对 observed/inferred 做区分，科研结论仍应检查原文定位。

API 故障、数据库不可用、模型输出不合法或达到步数预算都会留下明确失败/部分结果；不会回退到硬编码答案。模型成本只记录 provider 返回的 token 用量，不猜测实际账单。

## 6. 开发测试

```bash
uv run ruff check src tests
uv run pytest -q
# 配置并启动真实服务后才启用；默认跳过，不以替身代替
SCITRACE_INTEGRATION=1 uv run pytest -m integration -q
```

单元测试中的可控模型/内存存储只用于验证路由和恢复；生产 CLI 始终使用真实服务。`tests/test_indexing.py` 使用 Qdrant 官方嵌入式引擎验证混合检索过滤，不能替代 Qdrant 服务端联调。
