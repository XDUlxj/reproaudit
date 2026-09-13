
from pydantic import BaseModel


class ScientificClaim(BaseModel):
    """论文生命的数据结构"""
    text: str # 论文中指标的字符片段
    metric: str | None = None # 指标的具体单位
    expected_value: float | None = None # 论文给出的期望值
