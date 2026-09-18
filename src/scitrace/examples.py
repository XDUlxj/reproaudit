"""验收用固定计划生成器；不替代应用的动态编排。"""

import json
from pathlib import Path

from scitrace.models.core import CommandSpec, ReproductionPlan, ResourceInput
from scitrace.tools.network import Downloader, sha256

TUTORIAL_URL = "https://fasttext.cc/docs/en/supervised-tutorial.html"
PAPER_URL = "https://arxiv.org/abs/1607.01759"
CODE_URL = "https://codeload.github.com/facebookresearch/fastText/tar.gz/refs/tags/v0.9.2"
DATA_URL = "https://dl.fbaipublicfiles.com/fasttext/data/cooking.stackexchange.tar.gz"


def prepare_fasttext(output: Path, downloader=None):
    downloader = downloader or Downloader(50 * 1024**2)
    code = downloader.get(CODE_URL, 20 * 1024**2)
    dataset = downloader.get(DATA_URL, 10 * 1024**2)
    split = (
        "from pathlib import Path; "
        "p=Path('data/cooking.stackexchange.txt'); "
        "rows=p.read_bytes().splitlines(keepends=True); "
        "assert len(rows)==15404, 'unexpected dataset size'; "
        "Path('cooking.train').write_bytes(b''.join(rows[:12404])); "
        "Path('cooking.valid').write_bytes(b''.join(rows[12404:])); "
        "print('train=12404 valid=3000')"
    )
    plan = ReproductionPlan(
        claim_id="fasttext-official-cooking-tutorial",
        target_scope="tutorial",
        provenance="assisted",
        repository_revision="v0.9.2 (archive SHA256 pinned)",
        resources=[
            ResourceInput(url=CODE_URL, sha256=sha256(code), destination="source", archive="tar"),
            ResourceInput(url=DATA_URL, sha256=sha256(dataset), destination="data", archive="tar"),
        ],
        commands=[
            CommandSpec(argv=["make", "-j2"], cwd="source/fastText-0.9.2"),
            CommandSpec(argv=["python", "-c", split]),
            CommandSpec(
                argv=[
                    "./source/fastText-0.9.2/fasttext",
                    "supervised",
                    "-input",
                    "cooking.train",
                    "-output",
                    "model_cooking",
                    "-thread",
                    "2",
                ]
            ),
            CommandSpec(
                argv=[
                    "./source/fastText-0.9.2/fasttext",
                    "test",
                    "model_cooking.bin",
                    "cooking.valid",
                ]
            ),
        ],
        metric_parser="fasttext",
        assumptions=[
            "只验证官方 Cooking 教程执行闭环，不验证论文 benchmark。",
            "沿用官方教程默认训练参数，线程数固定为 2 以满足 CPU 预算；记录为执行条件差异。",
            "教程示例数值不作为论文比较阈值；不预设运行结果。",
            "使用本地构建的 Linux C++ 工具链镜像，镜像 ID 在运行前另行确认。",
        ],
        changes=["线程数固定为 2；不得将本实验描述为论文严格复现。"],
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(plan.model_dump_json(indent=2))
    manifest = {
        "paper": PAPER_URL,
        "tutorial": TUTORIAL_URL,
        "code": {"url": CODE_URL, "sha256": sha256(code), "bytes": len(code)},
        "dataset": {"url": DATA_URL, "sha256": sha256(dataset), "bytes": len(dataset)},
        "execution_status": "not_run",
        "verification": "not_tested",
    }
    output.with_suffix(".sources.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2)
    )
    return plan
