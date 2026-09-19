"""Dense 与 BM25 sparse 编码接口及 FastEmbed 实现。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SparseEmbedding:
    indices: list[int]
    values: list[float]


class HybridEncoder(Protocol):
    """可替换的双路文本编码器。"""

    @property
    def dense_dimension(self) -> int: ...

    def encode_documents(self, texts: list[str]) -> tuple[list[list[float]], list[SparseEmbedding]]: ...

    def encode_query(self, text: str) -> tuple[list[float], SparseEmbedding]: ...


class FastEmbedHybridEncoder:
    """CPU 友好的 FastEmbed dense + Qdrant/BM25 编码器。"""

    def __init__(
        self,
        *,
        dense_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        dense_dimension: int = 384,
        sparse_model: str = "Qdrant/bm25",
    ) -> None:
        from fastembed import SparseTextEmbedding, TextEmbedding

        self._dense = TextEmbedding(model_name=dense_model)
        self._sparse = SparseTextEmbedding(model_name=sparse_model)
        self._dense_dimension = dense_dimension

    @property
    def dense_dimension(self) -> int:
        return self._dense_dimension

    def encode_documents(self, texts: list[str]) -> tuple[list[list[float]], list[SparseEmbedding]]:
        dense = [vector.tolist() for vector in self._dense.passage_embed(texts)]
        sparse = [
            SparseEmbedding(vector.indices.tolist(), vector.values.tolist())
            for vector in self._sparse.passage_embed(texts)
        ]
        return dense, sparse

    def encode_query(self, text: str) -> tuple[list[float], SparseEmbedding]:
        dense = next(iter(self._dense.query_embed(text))).tolist()
        sparse_vector = next(iter(self._sparse.query_embed(text)))
        return dense, SparseEmbedding(
            sparse_vector.indices.tolist(), sparse_vector.values.tolist()
        )
