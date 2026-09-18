import ast
import json
import re
import shutil
from pathlib import Path
from urllib.parse import urlsplit

from scitrace.models.core import Evidence, fingerprint
from scitrace.tools.network import extract_archive


class RepositoryTools:
    def __init__(self, runtime):
        self.r = runtime

    def index(self, resource_id: str, revision: str = "HEAD") -> dict:
        """Index a registered repository using its exact resource ID (or uniquely registered URL). Approval is required before reading; returns repository id and index_id."""
        try:
            resource = self.r.store.get("resource", resource_id)
        except KeyError:
            candidates = self.r.store.find("resource", self.r.task_id)
            matches = [c for c in candidates if c.get("url") == resource_id]
            if len(matches) == 1:
                # 只解析当前任务中完全匹配且唯一的 URL，不模糊猜测哈希或来源。
                resource = matches[0]
            else:
                known = [{"id": c["id"], "url": c["url"]} for c in candidates[-20:]]
                raise ValueError(f"资源引用不存在或不唯一：{resource_id!r}；可用资源：{known}") from None
        self.r.policy.resource(resource)
        resource_id = resource["id"]
        source = resource["url"]
        if revision != "HEAD":
            for cached in self.r.store.find("repository"):
                if cached.get("revision") != revision:
                    continue
                old_resource = self.r.store.get("resource", cached["resource_id"])
                if old_resource["url"].rstrip("/").lower() != source.rstrip("/").lower():
                    continue
                if not self.r.artifacts.path(cached["artifact"]).is_dir():
                    continue
                # 不覆盖旧快照的资源绑定；新资源授权仍独立保留。
                cached = {**cached, "id": fingerprint([resource_id, revision]), "resource_id": resource_id}
                self.r.store.put("repository", cached, self.r.task_id)
                return cached
        parts = urlsplit(source)
        if source in self.r.local_inputs:
            source_path = Path(source).resolve()
            files = self._files(source_path)
            revision = fingerprint(
                [
                    (str(p.relative_to(source_path)), fingerprint(p.read_bytes().hex()))
                    for p in files
                ]
            )
            id = fingerprint([source, revision])
            root = self.r.artifacts.path(f"repositories/{id}/source")
            if not root.exists():
                root.mkdir(parents=True)
                for p in files:
                    dst = root / p.relative_to(source_path)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(p, dst)
        else:
            if parts.hostname != "github.com":
                raise ValueError("首版远程仓库快照仅支持 GitHub；其他仓库请提供本地副本")
            segments = parts.path.strip("/").removesuffix(".git").split("/")
            if len(segments) != 2 or any(
                not s.replace("-", "").replace("_", "").replace(".", "").isalnum() for s in segments
            ):
                raise ValueError("请提供 GitHub 仓库根 URL")
            owner, repo = segments
            from urllib.parse import quote

            try:
                metadata = (
                    {"sha": revision}
                    if re.fullmatch(r"[0-9a-f]{40}", revision)
                    else json.loads(
                        self.r.downloader.get(
                            f"https://api.github.com/repos/{owner}/{repo}/commits/{quote(revision, safe='')}",
                            2_000_000,
                        )
                    )
                )
            except ValueError as exc:
                cached_revisions = []
                for cached in self.r.store.find("repository"):
                    previous = self.r.store.get("resource", cached["resource_id"])
                    if previous["url"].rstrip("/").lower() == source.rstrip("/").lower():
                        cached_revisions.append(cached["revision"])
                raise ValueError(
                    f"{exc}；无法解析远程 revision。可明确指定已缓存不可变 revision 后重试："
                    f"{sorted(set(cached_revisions))}；不得将缓存版本称为最新 HEAD"
                ) from exc
            revision = metadata["sha"]
            id = fingerprint([source, revision])
            root = self.r.artifacts.path(f"repositories/{id}/source")
            if not root.exists():
                data = self.r.downloader.get(
                    f"https://codeload.github.com/{owner}/{repo}/tar.gz/{revision}"
                )
                ref = self.r.artifacts.write(f"repositories/{id}/snapshot.tar.gz", data)
                temp = self.r.artifacts.path(f"repositories/{id}/unpack")
                extract_archive(self.r.artifacts.path(ref), temp, "tar", 500 * 1024**2)
                children = list(temp.iterdir())
                if len(children) != 1 or not children[0].is_dir():
                    raise ValueError("仓库快照格式异常")
                shutil.move(str(children[0]), root)
        chunks = []
        for path in self._files(root):
            try:
                text = path.read_text()
            except UnicodeDecodeError:
                continue
            relative = str(path.relative_to(root))
            symbols = []
            if path.suffix == ".py":
                try:
                    tree = ast.parse(text)
                    symbols = [
                        (n.lineno, n.name)
                        for n in ast.walk(tree)
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    ]
                except SyntaxError:
                    pass
            lines = text.splitlines()
            for start in range(0, len(lines), 25):
                body = "\n".join(lines[start : start + 30])[:6000]
                names = ", ".join(name for line, name in symbols if start < line <= start + 30)
                chunk = Evidence(
                    id=fingerprint([id, relative, start]),
                    created_at="",
                    kind="code",
                    source=f"{source}::{relative}",
                    text=body,
                    start_line=start + 1,
                    end_line=min(start + 30, len(lines)),
                    section=names or relative,
                    revision=revision,
                )
                chunks.append(chunk.model_dump(mode="json"))
                self.r.store.put("evidence", chunk, self.r.task_id)
        index_id = self.r.index.build(id, chunks)
        result = {
            "id": id,
            "schema_version": 1,
            "resource_id": resource_id,
            "revision": revision,
            "index_id": index_id,
            "artifact": str(root.relative_to(self.r.artifacts.root)),
        }
        self.r.store.put("repository", result, self.r.task_id)
        return result

    def search(self, repository_id: str, query: str, limit: int = 5) -> list[dict]:
        """Search an indexed repository for code, configs or README using its repository id; returns original evidence and line numbers."""
        if not 1 <= limit <= 10:
            raise ValueError("limit 应为 1..10")
        repository = self.r.store.get("repository", repository_id)
        return self.r.index.search(repository["index_id"], query, limit)

    @staticmethod
    def _files(root):
        skipped = {".git", ".venv", "node_modules", "__pycache__", ".env", "artifacts"}
        files, total = [], 0
        for p in sorted(root.rglob("*")):
            if p.is_symlink() or any(
                part in skipped or part.startswith(".env") for part in p.relative_to(root).parts
            ):
                continue
            if not p.is_file() or p.stat().st_size > 1_000_000:
                continue
            total += p.stat().st_size
            if total > 100_000_000 or len(files) >= 10000:
                raise ValueError("仓库文本索引超过首版大小限制")
            files.append(p)
        return files
