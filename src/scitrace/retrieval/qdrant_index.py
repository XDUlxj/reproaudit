"""Qdrant dense + BM25 + RRF 索引与检索实现。"""

import hashlib
import uuid

from pydantic import TypeAdapter
from qdrant_client import QdrantClient, models

from scitrace.models import ContentLocator, ResourceChunk, RetrievalHit
from scitrace.retrieval.embedding import HybridEncoder
from scitrace.retrieval.errors import InvalidRetrievalRequestError

LOCATOR_ADAPTER = TypeAdapter(ContentLocator)


class QdrantHybridIndex:
    """将双路向量存入 Qdrant，并通过原生 RRF Query API 检索。"""

    DENSE_VECTOR = "dense"
    SPARSE_VECTOR = "bm25"

    def __init__(
        self,
        client: QdrantClient,
        encoder: HybridEncoder,
        *,
        collection_name: str = "scitrace_resources",
    ) -> None:
        self.client = client
        self.encoder = encoder
        self.collection_name = collection_name

    def ensure_collection(self) -> None:
        if self.client.collection_exists(self.collection_name):
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config={
                self.DENSE_VECTOR: models.VectorParams(
                    size=self.encoder.dense_dimension,
                    distance=models.Distance.COSINE,
                )
            },
            sparse_vectors_config={
                self.SPARSE_VECTOR: models.SparseVectorParams(modifier=models.Modifier.IDF)
            },
        )
        self.client.create_payload_index(
            collection_name=self.collection_name,
            field_name="resource_id",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )

    def replace_resource(self, resource_id: str, chunks: list[ResourceChunk]) -> None:
        """按 resource_id 先删后写，提供简单明确的幂等重建语义。"""
        self.ensure_collection()
        resource_filter = self._resource_filter([resource_id])
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(filter=resource_filter),
            wait=True,
        )
        if not chunks:
            return
        dense_vectors, sparse_vectors = self.encoder.encode_documents(
            [chunk.content for chunk in chunks]
        )
        points = []
        for chunk, dense, sparse in zip(chunks, dense_vectors, sparse_vectors, strict=True):
            points.append(
                models.PointStruct(
                    id=self._point_id(chunk),
                    vector={
                        self.DENSE_VECTOR: dense,
                        self.SPARSE_VECTOR: models.SparseVector(
                            indices=sparse.indices, values=sparse.values
                        ),
                    },
                    payload={
                        "resource_id": chunk.resource_id,
                        "content": chunk.content,
                        "locator": chunk.locator.model_dump(mode="json"),
                    },
                )
            )
        self.client.upsert(self.collection_name, points=points, wait=True)

    def retrieve(
        self,
        query: str,
        resource_ids: list[str],
        *,
        limit: int = 10,
        prefetch_limit: int = 30,
    ) -> list[RetrievalHit]:
        if not query.strip():
            raise InvalidRetrievalRequestError("query 不能为空")
        if not resource_ids:
            raise InvalidRetrievalRequestError("resource_ids 不能为空，禁止无范围全库检索")
        if limit < 1 or prefetch_limit < limit:
            raise InvalidRetrievalRequestError("prefetch_limit 必须大于等于 limit")
        self.ensure_collection()
        dense, sparse = self.encoder.encode_query(query)
        resource_filter = self._resource_filter(resource_ids)
        response = self.client.query_points(
            collection_name=self.collection_name,
            prefetch=[
                models.Prefetch(
                    query=dense,
                    using=self.DENSE_VECTOR,
                    filter=resource_filter,
                    limit=prefetch_limit,
                ),
                models.Prefetch(
                    query=models.SparseVector(indices=sparse.indices, values=sparse.values),
                    using=self.SPARSE_VECTOR,
                    filter=resource_filter,
                    limit=prefetch_limit,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,
            with_payload=True,
        )
        hits: list[RetrievalHit] = []
        for point in response.points:
            payload = point.payload or {}
            hits.append(
                RetrievalHit(
                    resource_id=str(payload["resource_id"]),
                    content=str(payload["content"]),
                    locator=LOCATOR_ADAPTER.validate_python(payload["locator"]),
                )
            )
        return hits

    @staticmethod
    def _resource_filter(resource_ids: list[str]) -> models.Filter:
        return models.Filter(
            must=[
                models.FieldCondition(
                    key="resource_id",
                    match=models.MatchAny(any=sorted(set(resource_ids))),
                )
            ]
        )

    @staticmethod
    def _point_id(chunk: ResourceChunk) -> str:
        identity = "\n".join(
            [
                chunk.resource_id,
                chunk.locator.model_dump_json(),
                hashlib.sha256(chunk.content.encode("utf-8")).hexdigest(),
            ]
        )
        return str(uuid.uuid5(uuid.NAMESPACE_URL, identity))
