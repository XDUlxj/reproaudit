"""ArtifactStore 的路径安全和完整性测试。"""

import pytest

from scitrace.persistence import LocalArtifactStore


def test_local_artifact_store_is_idempotent_and_hashes_content(tmp_path) -> None:
    store = LocalArtifactStore(tmp_path)

    first = store.put_bytes(
        namespace="resources/paper-1/figures",
        name="figure.png",
        content=b"image",
        media_type="image/png",
    )
    second = store.put_bytes(
        namespace="resources/paper-1/figures",
        name="figure.png",
        content=b"image",
        media_type="image/png",
    )

    assert first == second
    assert store.resolve(first).read_bytes() == b"image"


def test_local_artifact_store_rejects_path_traversal(tmp_path) -> None:
    store = LocalArtifactStore(tmp_path)

    with pytest.raises(ValueError):
        store.put_bytes(
            namespace="../outside",
            name="figure.png",
            content=b"image",
            media_type="image/png",
        )
