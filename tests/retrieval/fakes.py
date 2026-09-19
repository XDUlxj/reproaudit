"""无需下载模型的确定性双路编码器。"""

import hashlib
import re

from scitrace.retrieval.embedding import SparseEmbedding

TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)


class DeterministicHybridEncoder:
    """仅用于测试 Qdrant 数据流，不模拟真实模型质量。"""

    @property
    def dense_dimension(self) -> int:
        return 4

    def encode_documents(self, texts: list[str]):
        return [self._dense(text) for text in texts], [self._sparse(text) for text in texts]

    def encode_query(self, text: str):
        return self._dense(text), self._sparse(text)

    @staticmethod
    def _dense(text: str) -> list[float]:
        lowered = text.lower()
        values = [
            float("accuracy" in lowered or "准确率" in lowered),
            float("dataset" in lowered or "数据集" in lowered),
            float("install" in lowered or "安装" in lowered),
            0.1,
        ]
        return values

    @staticmethod
    def _sparse(text: str) -> SparseEmbedding:
        counts: dict[int, float] = {}
        for token in TOKEN_PATTERN.findall(text.lower()):
            index = int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], "big")
            counts[index] = counts.get(index, 0.0) + 1.0
        indices = sorted(counts)
        return SparseEmbedding(indices, [counts[index] for index in indices])
