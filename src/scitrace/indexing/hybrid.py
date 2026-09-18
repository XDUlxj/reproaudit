import re
from collections import defaultdict
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient, models
from rank_bm25 import BM25Okapi

from scitrace.models.core import fingerprint


def tokens(text):
    return re.findall(r"[a-z0-9_./%-]+|[\u4e00-\u9fff]", text.lower())


def rrf(rankings: list[list[str]]) -> list[tuple[str, float]]:
    scores = defaultdict(float)
    for ranking in rankings:
        for position, id in enumerate(ranking):
            scores[id] += 1 / (60 + position + 1)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))


class HybridIndex:
    def __init__(self, settings, artifacts, client=None):
        self.settings, self.artifacts = settings, artifacts
        self.client = (
            client
            if client is not None
            else QdrantClient(
                url=settings.qdrant_url,
                api_key=settings.qdrant_api_key.get_secret_value() or None,
                timeout=30,
            )
        )
        self._encoder = None
        self.collection = (
            "scitrace_e5_"
            + fingerprint(
                {"model": settings.embedding_model, "revision": settings.embedding_revision}
            )[:12]
        )

    @property
    def encoder(self):
        if self._encoder is None:
            from sentence_transformers import SentenceTransformer

            self._encoder = SentenceTransformer(
                self.settings.embedding_model,
                revision=self.settings.embedding_revision,
                device="cpu",
                trust_remote_code=False,
                cache_folder=str(self.settings.artifact_root / "models"),
            )
        return self._encoder

    def encode(self, texts, query=False):
        prefix = "query: " if query else "passage: "
        return self.encoder.encode(
            [prefix + t for t in texts], normalize_embeddings=True, show_progress_bar=False
        ).tolist()

    def build(self, document_id: str, chunks: list[dict]) -> str:
        if not chunks:
            raise ValueError("无可索引内容")
        if len(chunks) > self.settings.max_chunks:
            raise ValueError("文档切片数量超限")
        index_id = fingerprint(
            {
                "document": document_id,
                "collection": self.collection,
                "content": chunks,
                "chunker": 1,
            }
        )
        ref = f"indexes/{index_id}.json"
        if self.artifacts.path(ref).exists() and self.client.collection_exists(self.collection):
            return index_id
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                self.collection,
                vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE),
            )
            self.client.create_payload_index(
                self.collection, "index_id", models.PayloadSchemaType.KEYWORD
            )
        for start in range(0, len(chunks), 32):
            batch = chunks[start : start + 32]
            vectors = self.encode([c["text"] for c in batch])
            points = [
                models.PointStruct(
                    id=str(uuid5(NAMESPACE_URL, index_id + c["id"])),
                    vector=v,
                    payload={"index_id": index_id, "evidence_id": c["id"]},
                )
                for c, v in zip(batch, vectors, strict=True)
            ]
            self.client.upsert(self.collection, points=points, wait=True)
        self.artifacts.json(ref, chunks)
        return index_id

    def search(self, index_id: str, query: str, limit=5):
        import json

        chunks = json.loads(self.artifacts.path(f"indexes/{index_id}.json").read_text())
        corpus = [
            tokens(c["text"] + " " + c["source"] + " " + (c.get("section") or "")) or [""]
            for c in chunks
        ]
        bm25 = BM25Okapi(corpus)
        scores = bm25.get_scores(tokens(query))
        order = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)
        keyword = [chunks[i]["id"] for i in order[:20] if set(tokens(query)) & set(corpus[i])]
        exact = [c["id"] for c in chunks if query.casefold() in c["text"].casefold()][:20]
        vector = self.encode([query], query=True)[0]
        response = self.client.query_points(
            self.collection,
            query=vector,
            limit=20,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(key="index_id", match=models.MatchValue(value=index_id))
                ]
            ),
        )
        semantic = [p.payload["evidence_id"] for p in response.points]
        lookup = {c["id"]: c for c in chunks}
        return [
            {**lookup[id], "score": score}
            for id, score in rrf([exact, keyword, semantic])[:limit]
            if id in lookup
        ]
