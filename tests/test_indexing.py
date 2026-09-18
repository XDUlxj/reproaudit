from scitrace.indexing.hybrid import rrf, tokens


def test_rrf_rewards_both_channels():
    ranking = rrf([["keyword", "shared"], ["semantic", "shared"]])
    assert ranking[0][0] == "shared"


def test_exact_tokens_preserve_scientific_keys():
    values = tokens("Table 3 learning_rate ResNet-50 92.4% 数据集")
    assert {"learning_rate", "resnet-50", "92.4%"}.issubset(values)


def test_hybrid_qdrant_filter_and_provenance(tmp_path):
    from qdrant_client import QdrantClient

    from scitrace.config import Settings
    from scitrace.indexing.hybrid import HybridIndex
    from scitrace.storage import Artifacts

    # 使用 Qdrant 自带本地引擎验证真实过滤/存储语义；编码器在单测中固定。
    index = object.__new__(HybridIndex)
    index.settings = Settings(_env_file=None, artifact_root=tmp_path)
    index.artifacts = Artifacts(tmp_path)
    index.client = QdrantClient(":memory:")
    index.collection = "test_e5"
    index.encode = lambda texts, query=False: [[1.0] + [0.0] * 383 for _ in texts]
    first = index.build(
        "doc-a", [{"id": "a", "text": "learning_rate 0.001", "source": "a.py", "page": 2}]
    )
    second = index.build("doc-b", [{"id": "b", "text": "learning_rate 0.1", "source": "b.py"}])
    assert first != second
    hits = index.search(first, "learning_rate")
    assert [hit["id"] for hit in hits] == ["a"]
    assert hits[0]["page"] == 2
