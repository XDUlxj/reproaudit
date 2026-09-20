"""单次 Agent run 的只读运行时配置。"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SciTraceContext:
    """选择 deterministic test world；不进入 Main State 或业务持久化。"""

    stub_scenario: Literal["happy_path", "need_resources"] = "happy_path"
