"""大文件 Artifact 的本地持久化实现。"""

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Protocol

from scitrace.models.retrieval import ArtifactReference


class ArtifactStore(Protocol):
    """Parser 等基础设施可依赖的最小 ArtifactStore 契约。"""

    def put_bytes(
        self, *, namespace: str, name: str, content: bytes, media_type: str
    ) -> ArtifactReference: ...


class LocalArtifactStore:
    """将 Artifact 原子写入受控本地根目录。"""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    def put_bytes(
        self, *, namespace: str, name: str, content: bytes, media_type: str
    ) -> ArtifactReference:
        namespace_path = Path(namespace)
        if namespace_path.is_absolute() or ".." in namespace_path.parts:
            raise ValueError("Artifact namespace 必须是安全的相对路径")
        safe_name = Path(name).name
        if not safe_name or safe_name != name:
            raise ValueError("Artifact name 不能包含目录或为空")

        target_dir = self.root / namespace_path
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / safe_name
        digest = hashlib.sha256(content).hexdigest()
        descriptor, temporary_name = tempfile.mkstemp(dir=target_dir, prefix=".pending-")
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            Path(temporary_name).replace(target)
        except BaseException:
            Path(temporary_name).unlink(missing_ok=True)
            raise

        relative = target.relative_to(self.root).as_posix()
        return ArtifactReference(
            name=safe_name,
            uri=f"artifact://{relative}",
            sha256=digest,
            media_type=media_type,
        )

    def resolve(self, reference: ArtifactReference) -> Path:
        """将本 Store 生成的 URI 安全解析为本地文件。"""
        prefix = "artifact://"
        if not reference.uri.startswith(prefix):
            raise ValueError("不是本地 Artifact URI")
        candidate = (self.root / reference.uri.removeprefix(prefix)).resolve()
        if not candidate.is_relative_to(self.root):
            raise ValueError("Artifact URI 越过存储根目录")
        return candidate
