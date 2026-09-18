# SciTrace 使用指南

适用版本：v0.1.1。更新日期：2026-09-17。本文面向使用者；后续开发请阅读 [开发交接](HANDOFF.md)。

## 1. 能力与运行方式

SciTrace 在宿主 Python 虚拟环境中运行 Agent，使用真实智谱、Tavily、PostgreSQL 和 Qdrant 服务。论文仓库的编译、训练、测试只在 Docker 内执行。

目前可以进行论文问答、寻找资源、追踪论文与代码关联、生成计划、审批恢复、执行实验及导出报告。已经完成一个真实 fastText Cooking 教程闭环；尚未验证原论文 benchmark，也不能保证任意论文自动复现。详细验证边界见 [验收记录](ACCEPTANCE.md)。

## 2. 首次配置

在仓库根目录执行。需要 uv、Python 3.12 和已准备好的 PostgreSQL、Qdrant；本项目不自动部署这两个服务。

```bash
uv sync --locked
```

仅在没有 `.env` 时复制模板，避免覆盖已有配置：

```bash
cp .env.example .env
```

编辑 `.env`，填写以下配置。不要提交密钥或将其写入任务输入。

| 配置 | 说明 |
| --- | --- |
| `GLM_API_KEY`、`GLM_MODEL`、`GLM_BASE_URL` | 智谱标准 API；模型必须支持工具调用，模型名以账号实际可用项为准 |
| `TAVILY_API_KEY` | 资源搜索密钥 |
| `DATABASE_URL` | PostgreSQL 连接，账号需要创建项目专用 schema 的权限 |
| `QDRANT_URL`、`QDRANT_API_KEY` | Qdrant REST 地址与认证；云端使用服务提供的 HTTPS 地址 |
| `ARTIFACT_ROOT` | 默认 `artifacts`；保存论文、索引、下载、实验产物和报告 |
| `EMBEDDING_MODEL`、`EMBEDDING_REVISION` | 默认 E5-small 固定提交，CPU 编码、384 维 |
| `DOCKER_IMAGE` | 默认 `scitrace-runner:0.1`；应用版本 0.1.1 不要求改这个镜像 tag |
| `MAX_STEPS`、`SPECIALIST_STEPS`、`MODEL_TIMEOUT` | 默认 24、10、90 秒；控制决策预算和模型请求超时 |

环境变量会覆盖 `.env` 中的同名值。先初始化，再诊断：

```bash
uv run scitrace init
uv run scitrace doctor --embedding --skip-docker
```

`init` 创建 `scitrace` 与 `scitrace_checkpoints` 专用 schema，不清空现有数据库。`doctor` 会真实调用模型与 Tavily，消耗相应额度。首次 embedding 安装/加载涉及 PyTorch 和模型下载：这是本地向量检索依赖，即使尚未进入 Agent Loop 也可能发生。

`--skip-docker` 适用于追踪和规划阶段，不能启用宿主机实验执行。准备实际实验时，启动 Docker Desktop，等待 `docker info` 能返回服务端信息，再构建镜像：

```bash
docker info
docker build -f Dockerfile.runner -t scitrace-runner:0.1 .
uv run scitrace doctor --embedding
```

## 3. 常用任务

### 论文问答

```bash
uv run scitrace run "这篇论文使用了哪些数据集？请给出页码和原文证据。" --paper 1607.01759
```

`1607.01759` 是 arXiv 论文 ID，不是仓库文件名。系统会解析论文入口并下载，原始文件保存为 `ARTIFACT_ROOT/documents/<document_id>/original`，文件名不要求带 `.pdf`。也可输入 DOI、URL、标题或本地 PDF；标题无法唯一确定时会请求选择。

本地路径含空格或 `!` 时，用单引号包住整个路径：

```bash
uv run scitrace run "分析论文方法并给出原文证据，暂不运行实验" \
  --paper './my-repo/Stoica 等 - 2024 - ZIPIT! MERGING MODELS FROM DIFFERENT TASKS.pdf'
```

### 只找代码或追踪已有仓库

```bash
uv run scitrace run "查找官方代码，说明身份核验依据，不执行实验" --paper 1607.01759

uv run scitrace run "追踪论文方法到代码入口，列出差异，不运行实验" \
  --paper ./paper.pdf --repository ./my-repo
```

将示例路径替换成实际文件/代码目录。`--repository` 必须显式填写，不能把仓库路径直接附在命令尾部。仅含 PDF 的目录不等于论文代码仓库。用户提供的仓库也不会自动标记为官方资源。

### 完整 Agent 链路验收

以下是 v0.1.1 已跑通案例对应的目标描述。它使用受限 Cooking 配方，仍由动态 Supervisor 调度，各阶段可能暂停审批。

```bash
uv run scitrace run \
  "fastText Cooking 全链路验收。先解析入库论文；Discovery 搜索注册官方仓库；Trace 用固定 revision 1142dc4c4ecbc19cc16eee5cdd28472e689267e6 索引仓库，再直接调用 prepare_cooking_tutorial，不传参数。随后 Execution 执行计划并报告。教程不代表论文 benchmark。" \
  --paper 1607.01759 --trusted-project https://fasttext.cc --require-execution
```

`--require-execution` 要求单次实验实际完成，不能仅生成计划就成功结束。`--trusted-project` 指定认可的项目页，可作为资源身份核验入口，不自动批准代码运行。

配方核验真实资源摘要，使用 15,404 条数据、12,404/3,000 划分和两线程默认训练配置。固定提交不是“最新 HEAD”。首次无缓存仍需下载快照，代理故障可能导致失败。本案例历史验收经过修复与恢复，尚无多次从空缓存首次运行成功率统计。

### 已有计划直接执行

```bash
uv run scitrace prepare-fasttext
uv run scitrace run "执行 Cooking 教程计划，报告指标、日志和模型产物；论文 benchmark 未验证" \
  --plan artifacts/examples/fasttext-plan.json --require-execution
```

先检查生成的计划和 `.sources.json`。此路径使用 v0.9.2 固定资源，主要测试执行器，不覆盖从论文发现仓库的完整过程；不要与上面的固定 commit 验收混为同一次实验。

## 4. 审批与恢复

保存控制台返回的任务 ID。以下 `TASK_ID` 与 `APPROVAL_ID` 都要替换成当前任务实际值。

```bash
uv run scitrace status TASK_ID
uv run scitrace approve TASK_ID APPROVAL_ID approved
uv run scitrace resume TASK_ID
```

`status` 会显示当前待审批内容。阅读资源来源、命令、工作目录、镜像、预算、参数假设后再决定。资源使用、计划执行、实际镜像可能分别请求审批；批准一次不代表统一批准未来全部操作。当前 CLI 没有“一键批准所有”命令。

拒绝操作：

```bash
uv run scitrace approve TASK_ID APPROVAL_ID rejected
uv run scitrace resume TASK_ID
```

选择候选论文时，`--response` 是从 1 开始的候选序号：

```bash
uv run scitrace approve TASK_ID APPROVAL_ID approved --response 2
uv run scitrace resume TASK_ID
```

审批只绑定具体操作及其摘要，不能改写历史决定；计划、资源或镜像变化可能要求新审批。`approve` 只记录决定，随后必须 `resume`。同一任务不要同时启动两个恢复进程。

恢复使用 PostgreSQL checkpoint 与执行账本。成功实验不会自动重跑；`unknown` 表示不能确认执行结果，需要人工检查容器与日志。不要删除账本或反复恢复来强制重跑。已结束的 `partial` 任务通常需要修复原因后新建任务；`resume` 不是重置决策预算或通用重试按钮。

## 5. 读取报告与复查结果

```bash
uv run scitrace report TASK_ID
```

报告保存为 `ARTIFACT_ROOT/tasks/TASK_ID/report.md` 与 `report.json`。报告导出读取已有业务记录，不会重新执行实验。

| 字段 / 状态 | 应如何理解 |
| --- | --- |
| Task `finished` | 当前任务的结束条件满足，不等于论文被科学验证 |
| Task `waiting_approval` | 已暂停，等待当前具体操作决定 |
| Task `partial` | 目标未全部完成，检查错误、缺口和预算 |
| Execution `success` / `failed` / `unknown` | 实际执行成功、失败或结果不确定；以命令退出码和日志为依据 |
| Verification `not_tested` | 没有完成科学比较；教程即使运行成功也属于此状态 |
| Provenance 与 observed/inferred | 来源身份与关联证据强度；推断不能直接当作已证实关系 |

检查论文页码/原文、代码行号、仓库 revision、资源 SHA256、实际命令、日志、指标和模型摘要。没有 execution 记录时，不能认定发生了编译失败、OOM 或训练失败。

现有成功任务为 `78603a96-4544-4240-8f7b-e028a05aab1b`，历史指标 N=3000、P@1=0.133、R@1=0.0575。多线程重跑指标可能变化，不以这两个值作为硬编码成功阈值。

若保留了该任务报告和所有本地产物，可离线复查：

```bash
uv run python scripts/verify_cooking_acceptance.py 78603a96-4544-4240-8f7b-e028a05aab1b
```

脚本检查阶段记录、四条命令、数据划分、模型和论文原文定位，不调用模型或重跑实验；会更新 `artifacts/acceptance/v0.1.1-cooking.json`。它当前固定使用根目录 `artifacts`，不是任意论文的通用验收器。新机器仅克隆 Git 通常没有这些被忽略的历史产物。

## 6. 常见问题

| 现象 | 处理方式 |
| --- | --- |
| `zsh: command not found: #` | 交互 shell 把注释当作命令；复制代码块中的命令，跳过注释行 |
| `docker: command not found` | 安装 Docker Desktop，并确认 docker CLI 在 PATH |
| Cannot connect to Docker daemon | 启动 Docker Desktop，等待 `docker info` 返回服务端信息 |
| apt 构建 exit code 100 / 502 | 检查错误前面的下载日志与 Docker Desktop 代理；runner 已采用 HTTPS 和有限重试，SciTrace 域名白名单不控制 apt |
| PostgreSQL password authentication failed | 核对数据库、用户、密码以及环境变量是否覆盖 `.env` |
| 尚未 `scitrace init` | 服务已连接但项目表未初始化，执行 `uv run scitrace init` |
| Qdrant 502 / 无法获取版本 | 检查 REST 地址、代理与服务可达性；不要关闭兼容检查来掩盖连接失败 |
| API key insecure connection | 检查是否把 Qdrant 密钥用于 HTTP，云端应使用实际 HTTPS 地址 |
| fake-IP `198.18.x.x` 被拒绝 | 仅在确认目标域名可信后加入 `TRUSTED_FAKE_DNS_HOSTS`，不要放行整个保留网段 |
| HF 未认证下载警告 | 不等于模型失败；可配置本地 `HF_TOKEN`。完整缓存后可用 `HF_HUB_OFFLINE=1` 避免 Hub 联网检查 |
| 工具参数/证据 ID 错误 | 查看原始 observation 和真实引用目录；不要猜测或手工伪造哈希 |
| 达到决策预算 | 先排查重复调用和阻塞项；`SPECIALIST_STEPS` 可调整，增加预算不保证解决错误 |

fake-IP 配置是 JSON 域名列表，例如：

```dotenv
TRUSTED_FAKE_DNS_HOSTS=["arxiv.org","export.arxiv.org","github.com","api.github.com","codeload.github.com","raw.githubusercontent.com","fasttext.cc","dl.fbaipublicfiles.com"]
```

只添加实际信任的域名，重定向目标也会独立校验。该选项不放行回环或 RFC1918 私网。扫描件 OCR、远程 GPU、Web、多用户、任意科研源码自动修复仍不在本版支持范围。
