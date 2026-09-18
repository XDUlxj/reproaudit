# SciTrace 迭代版本记录

状态定义：**已实现**表示代码已交付；**已验证**表示有对应测试/实测证据；**待联调**表示尚未满足真实运行前置条件。不能将前两者等同于完整科研复现成功。

## v0.1.1 文档补充 / 2026-09-17

| 已完成 | 验证证据 | 限制 / TODO | 下一步 |
| --- | --- | --- | --- |
| 新增 [使用指南](USER_GUIDE.md) 与 [开发交接](HANDOFF.md)，补充配置、完整链路命令、逐项审批、报告解读、故障排查、代码导航、升级清单及后续会话模板；README 增加入口 | 对照当前 CLI 参数、配置、代码路径和已有验收记录核对；文档链接与 diff 格式检查 | 本次仅补充文档，没有重跑真实服务或实验；沿用 2026-09-15 的历史验证基线 | 按 handoff 的发布门槛验证下一版，优先多次/冷缓存验收与原论文 benchmark |

## v0.1.1 本轮交付 / 2026-09-15

| 已完成 | 验证证据 | 限制 / TODO | 下一步 |
| --- | --- | --- | --- |
| 完整仓库查验；版本和锁文件更新 0.1.1；短引用映射及有界合法 JSON 观察；仓库 ID 绑定和固定提交复用；可选 Cooking 配方；有执行要求的完成条件；真实摘要核验和缓存复用；下载总时限；tmpfs 流式导出；成功账本终态协调；报告和中文操作说明 | 64 单测通过；6 项真实服务/容器集成通过；任务 `78603a96-4544-4240-8f7b-e028a05aab1b` 跨进程完成全部阶段，4 条 Docker 命令成功；P@1=0.133、R@1=0.0575；bin/vec 摘要和论文引用核验通过 | 只完成一个教程案例，不是原论文 benchmark；过程中修复和恢复，不是首次无人干预成功；来源未自动核实则保留 third_party；通用规划和科学关联质量、字体/复杂表格仍需评估；旧密钥轮换未代办 | 固定本案例为发布验收，扩充多次运行成功率、原论文 benchmark 和更多受限配方 |

详细逐项结论见 [AUDIT_V0.1.1.md](AUDIT_V0.1.1.md)，实际日志/产物和历史失败见 [ACCEPTANCE.md](ACCEPTANCE.md)。本节是最新状态；下方记录保留各次修复时的历史验证边界。

## 历史计划与修复记录

| 版本 / 日期 | 已完成 | 验证结果 | TODO / 限制 | 下一步建议 |
| --- | --- | --- | --- | --- |
| v0.1.0 / 2026-09-14 | Python 3.12 + uv 锁文件；CLI；LangGraph Supervisor；三个独立 Specialist Loop；真实智谱/Tavily/PostgreSQL/Qdrant 适配；E5 混合检索；PDF 与代码证据；审批/恢复；Docker 执行；规则验证；双格式报告；中文注释及 README | 本地单测、静态检查、CLI 启动通过；真实 E5 CPU 编码与中英检索通过；官方 fastText 源码/数据下载及摘要校验通过。详见 ACCEPTANCE.md | 智谱/Tavily/数据库凭据未配置；Qdrant 默认端点探测未通过；Docker 未安装，真实训练与全服务端到端验收未运行 | 优先配置现有服务并安装 Docker，完成 Cooking 真实训练和跨进程审批恢复验收，记录 P@1/R@1、耗时及问题；不要先扩功能 |
| v0.1.1 / 2026-09-15（开发中） | 增加无 Docker 的本地追踪模式及 `doctor --skip-docker`；论文解析失败立即停止并返回根因；Specialist 相同错误连续两次后返回 blocker；控制台事件显示脱敏错误详情；fake-IP 拦截信息包含域名和配置指引；项目内持久化 Python 3.12；清理 `.env.example` 中的真实凭据 | PostgreSQL、智谱 `glm-4.5-air` 工具调用、Tavily、本地 E5 384 维编码均通过真实诊断；静态检查通过；47 passed、5 个真实服务/执行测试 skipped；失败任务 `e5081b6b-b6b0-47aa-811f-6e61a762461b` 已完成根因复盘 | Qdrant Cloud TLS 握手超时；修复后的 arXiv 简单问答尚未重新完成端到端验证；Docker 与 fastText 实际训练继续延期；已暴露的智谱、Tavily、Qdrant 密钥需要在服务端轮换 | 先修正并验证 Qdrant Cloud REST 地址 `:6333`、网络与 API Key，再重跑 arXiv 数据集问答并人工核对页码/原文；随后更新 ACCEPTANCE.md，最后再处理 Docker |
| v0.2 / 计划 | — | 未运行 | 原论文 benchmark 严格验证、更多论文/仓库案例、复杂表格与检索质量评估 | 选择一个原始数据集和论文指标，预先固定比较标准与实验条件，建立 Discovery/Trace/HITL/Verification 指标基线 |
| 后续 / 计划 | — | 未运行 | 远程 GPU、Web 交互、OCR、更广泛环境准备能力 | 在 CLI 闭环稳定后扩展执行后端与交互界面，保留现有审批与 provenance 合约 |

## 本版已实现的关键行为

- 不要求固定上传 PDF 或先做 Discovery；简单问题和已有仓库/计划均有直接路径。
- 工具权限隔离，模型不能通过 prompt 自行批准计划。拒绝审批后回到 Supervisor 重新决策。
- PostgreSQL checkpoint 保留图进度，Specialist 中间决策单独持久化；执行账本以任务和计划摘要确定幂等键。
- 每项审批绑定操作内容；修改计划、镜像或资源后不能复用旧决定。已开始但不确定完成的实验不会自动重跑。
- 容器禁止网络和宿主写挂载；默认 CPU/内存/时长/临时磁盘限制，并设置主进程 TTL。
- 原文证据保存页码、代码行号、来源与版本；向量缓存按模型 revision 和内容区分。
- 指标比较不会将教程运行成功描述为论文已验证；缺少标准或环境失败不作科学证伪。
- 论文下载、解析或索引失败会保留 observation，并以 `partial` 和具体根因结束，不再扩散调用无关 Specialist。
- 本机代理将域名解析到 `198.18.0.0/15` 时，仅允许 `.env` 中明确列出的可信域名；回环和 RFC1918 私网继续禁止。
- Docker 可以在追踪与规划阶段跳过；ExecutionAgent 仍不允许把论文命令直接运行在宿主机。

## v0.1.1 首轮真实联调记录

- 命令：`uv run scitrace run "这篇论文使用了哪些数据集？请给出页码和原文证据。" --paper 1607.01759`。
- 原始行为：`paper_ingest` 因 fake-IP 安全校验失败后，Supervisor 继续尝试 Discovery 和 Trace，最终达到重复调用预算；任务正确标记为 `partial`，但错误呈现与收敛不合格。
- 根因：`.env` 的 `TRUSTED_FAKE_DNS_HOSTS` 为空；arXiv 等公开域名由本机代理解析到 `198.18.0.0/15`。Trace 没有有效 `paper_index_id`，后续检索错误属于连锁失败。
- 修复：为当前本机配置明确的公开域名白名单；`paper_ingest` 在内部下载重试耗尽后直接终止；控制台和报告保留首个错误；Specialist 对相同错误设置收敛限制。
- 当前结论：代码层回归验证通过，Qdrant Cloud 仍在 TLS 握手阶段超时，因此本轮尚未取得可信的论文数据集答案。
- Shell 提示：zsh 交互环境把单独粘贴的 `# ...` 当作命令，产生 `command not found: #`；README 的首组可复制示例已移除注释行。该提示与 Agent 任务失败无关。

## v0.1.1 PDF 空字符修复 / 2026-09-15

- 问题：任务 `e58a77dc-b942-43a2-afec-e27f71c6bc02` 解析 ZIPIT 本地 PDF 时，提取文本包含 `U+0000`，PostgreSQL JSONB 拒绝写入，任务以 `partial` 结束。
- 已完成：论文正文、表格切片和 PDF 元数据中的空字符替换为等长空格；原始 PDF artifact 保持不变，正文字符偏移保留；报告加入特殊符号核对提示；解析缓存增加版本标识。
- 验证：新增空字符偏移及完整 ingestion 回归测试；49 passed、5 skipped；Ruff 通过。测试使用可控解析器和本地存储替身，未验证真实 PostgreSQL/Qdrant 端到端任务。
- TODO / 下一步：重跑该本地 PDF 任务，核对原页公式与证据；随后验证仓库追踪、计划审批及 Docker 实验，不将本次解析修复视为复现成功。

## 逐项修复历史

### Discovery 结束结果资源引用 / 2026-09-15

- 任务 `ef3b56fa-fb60-49cc-a0c2-779107cd4073` 多次在 Discovery finish 将 GitHub URL 填入 resource ID；另有虚构/截断 evidence ID，最终预算耗尽，实验未开始。
- 已完成：Discovery 结束校验支持当前任务已注册 URL 的精确匹配；重复注册保留全部匹配资源 ID，不猜测哈希或任意选择审批对象；官方身份以持久记录为准，未核验时置 null 并记录需审批的缺口；非法 evidence 返回已注册资源的真实引用目录；schema 描述明确 ID 类型。
- 验证：60 passed、5 skipped，Ruff 通过；新增重复 URL 与官方身份不提升回归测试。真实全流程尚未验证， malformed URL / evidence ID 仍不会自动猜测或接受。
- TODO：新任务重跑 Discovery → Trace → 计划审批 → Docker，确认不再因未核实官方身份反复结束失败；ai.meta.com 的 fake-IP 信任名单需用户按实际需求配置，当前未自动扩展。

### 仓库检索能力与计划命令校验 / 2026-09-15

- 任务 `708f0d24-baf6-4c3a-b36f-78956dc130ee` 完成仓库索引，但计划将教程实验写为 paper_only，含实验内 wget 和无效的 cd/&& argv；Execution 因 blocker 未启动。现存教程证据包含数据下载地址，“缺少地址”未被证据支持。
- 已完成：为 Trace 增加 repository_hybrid_search，按仓库记录绑定 index_id 检索 README/教程/代码/配置；明确教程 scope、实际指标解析及无阈值时可保留空规则；保存前拒绝 paper_only 实验命令、直接 shell 操作符和独立联网下载命令；同一记录第三次读取时停止 Specialist，计数持久化。
- 验证：59 passed、5 skipped，Ruff 通过；新增仓库检索绑定、无效命令布局和重复读取回归测试。真实自动规划和 Docker 执行仍未验证，长 ID 引用错误仍是已知限制。
- TODO / 下一步：新建真实任务验证 Trace 从已索引教程提取数据地址并保存合格计划，再审批执行；旧计划未修订，不应继续批准旧计划实验。

### 未执行失败结论与虚构资源摘要 / 2026-09-15

- 任务 `4399b33d-7e47-4b0a-a352-047cbe66d4cb` 已索引仓库并保存计划，但计划包含未经证实的失败 blocker 和疑似虚构的重复样式 SHA256。执行器因 blocker 拒绝启动，execution 为空；模型仍描述编译/下载/内存失败。
- 已完成：无执行记录时使用确定性的未执行结论，避免继续展示模型编造的执行报告；inspect_resource 保存版本化下载核验记录；Agent save_plan 要求资源 URL 和 SHA256 与当前任务核验事实完全匹配。
- 验证：56 passed、5 skipped，Ruff 通过；新增真实摘要来源校验回归测试。历史计划与回答未修改，新保护不代表旧计划已经合格。
- TODO：全流程真实执行仍未完成；科学配置（含训练/验证划分）的语义验证仍需加强。旧计划 head/tail 各 10000 条会造成数据重叠，不应批准或照此运行。

### 全流程提前结束与报告证据池 / 2026-09-15

- 真实任务 `659f38e5-297d-4766-b778-ab5398fda6b3` 的 Trace 多次误传 URL/拼错 resource ID；无仓库索引、Claim、计划、审批或执行记录，Supervisor 却结束为 finished。此任务未完成全流程验收。
- 已完成：仓库工具接受当前任务唯一且完全匹配的已注册 URL，仍经过原审批；非法引用返回合法资源目录，不模糊猜测 ID；无计划时阻止 Execution Specialist；调用 Execution 后无执行账本的任务结束为 partial。
- 报告补充任务证据池，以及按 document revision 绑定的跨任务缓存论文证据；明确入库证据不等于 Claim 支持关系。旧报告需重新导出，不会自动改写历史状态。
- 验证：55 passed、5 skipped，Ruff 通过；新增审批边界、无计划提前结束、跨任务缓存证据导出回归测试。真实模型端到端仍待验收，完整科学证据链和 Cooking 实验仍未验证。
- 下一步：先完成仓库读取审批与索引，验证 Trace 保存计划，再验证审批后 Docker 编译/训练/测试；后续强化目标完成条件及长 ID 引用可靠性。

### Runner 镜像下载失败修复 / 2026-09-15

- 真实构建日志显示 Debian HTTP 软件包下载多次返回 502 或连接失败（代理 fake-IP `198.18.0.141`），apt 以 100 退出；Docker daemon 已运行，doctor 因镜像尚未构建成功而失败。
- 已完成：Dockerfile.runner 的 Debian 源切换 HTTPS，apt 增加有限重试与 30 秒连接超时，保留软件包签名和 TLS 校验。
- 验证 / TODO：尚未重新构建验证；需重跑镜像构建及 doctor。如仍发生 502，排查 Docker Desktop 和本机代理到 Debian 的网络路径；SciTrace 下载器白名单不控制 Docker 构建网络。

### 本地论文路径归一化修复 / 2026-09-15

- 任务 `075edc01-22d6-445f-86bd-94765702cc79` 已成功 resolve 本地 PDF，但 ingestion 落入网络 URL 校验分支。
- 已完成：resolve/ingest 将本地路径归一化后与显式授权路径比较，支持同一文件的相对/绝对路径；工具说明要求沿用 resolve 的 source；未授权路径给出具体参数和纠正提示，不再交给网络下载器。
- 边界：授权仓库目录不能自动授权目录内任意论文文件；路径处理没有扩大本地读取权限。
- 验证：50 passed、5 skipped，Ruff 通过；真实模型任务仍待重跑。若模型改写了实际文件名，新的错误会明确显示该参数。

### Specialist 记录上下文与工具契约 / 2026-09-15

- 真实任务 `1972f2c3-73c7-4e4e-b11a-9a1fd60cd376` 已完成 PDF 入库及 Supervisor 混合检索；Trace 将 document ID 当作 index_id、将 resource ID 当作 repository ID，并传入非法记录类型。Discovery 曾传入非法资源身份 `mirror`。
- 已完成：新 Specialist loop 获得有界任务记录目录；工具 schema 枚举合法记录类型和资源身份；明确资源必须先 index_repository 才产生仓库记录；Paper 检索支持将已保存 document ID 解析到绑定 index_id。
- 验证：52 passed、5 skipped，Ruff 通过；新增 ID 解析及工具 schema 回归测试。真实 Specialist 行为修复仍待新任务联调，既有 loop 保留原审批和对话。
- 当前审批仅请求读取未核实 GitHub 仓库，未批准实验执行；README 自述官方不足以自动提升来源身份。

本版不会自动迁移框架版本、修补科研源码或安装任意未审阅依赖。自动修复当前仅覆盖有记录的有限网络重试。额外依赖通过构建好的镜像和具体计划进入审批。

首版报告和数据模型支持规则比较，但没有经过原论文 benchmark 的真实准确性评估；不能报告 Discovery/Trace 的学术质量分数。当前测试覆盖的是工程行为和部分真实基础设施，不代表科学正确率。
