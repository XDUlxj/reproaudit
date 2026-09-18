import io
import json
import re
from pathlib import Path
from urllib.parse import quote

from bs4 import BeautifulSoup
from defusedxml import ElementTree
from pypdf import PdfReader

from scitrace.models.core import Evidence, fingerprint
from scitrace.tools.network import sha256


class PaperTools:
    def __init__(self, runtime):
        self.r = runtime

    def _local_source(self, source: str) -> str | None:
        # 模型可能把 CLI 的绝对路径改写成相对路径。仅接受解析后仍与
        # 用户显式授权文件完全相同的路径，不能借仓库目录权限读取任意文件。
        if source.startswith(("http://", "https://")):
            return None
        candidate = str(Path(source).resolve())
        authorized = {str(Path(p).resolve()) for p in self.r.local_inputs}
        return candidate if candidate in authorized else None

    def resolve(self, source: str) -> dict:
        """Resolve a title, DOI, arXiv ID, HTTP URL, or explicit local PDF. Returns candidates when ambiguous."""
        source = source.strip()
        local = self._local_source(source)
        if local:
            return {"source": local, "type": "local_pdf"}
        arxiv = re.search(r"(?:arxiv.org/(?:abs|pdf)/|arxiv:)?(\d{4}\.\d{4,5}(?:v\d+)?)", source)
        if arxiv:
            return {"source": f"https://arxiv.org/pdf/{arxiv[1]}", "arxiv_id": arxiv[1]}
        doi = re.fullmatch(r"(?:https://doi.org/)?(10\.\d{4,9}/\S+)", source)
        if doi:
            raw = self.r.downloader.get(
                "https://api.crossref.org/works/" + quote(doi[1], safe=""), 2_000_000
            )
            meta = json.loads(raw)["message"]
            links = [
                link["URL"]
                for link in meta.get("link", [])
                if link.get("content-type") == "application/pdf"
            ]
            return {
                "doi": doi[1],
                "title": meta.get("title"),
                "source": links[0] if links else meta.get("URL"),
                "warning": None if links else "未找到开放 PDF，可提供本地 PDF",
            }
        if source.startswith(("https://", "http://")):
            return {"source": source}
        raw = self.r.downloader.get(
            "https://export.arxiv.org/api/query?search_query="
            + quote("all:" + source)
            + "&max_results=5",
            2_000_000,
        )
        root = ElementTree.fromstring(raw)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        candidates = [
            {
                "title": e.findtext("a:title", default="", namespaces=ns).strip(),
                "source": e.findtext("a:id", default="", namespaces=ns).replace("/abs/", "/pdf/"),
            }
            for e in root.findall("a:entry", ns)
        ]
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            return {"candidates": [], "missing": "未找到论文，请提供 DOI、URL 或 PDF"}
        choice = self.r.policy.require(
            "paper_selection",
            {"query": source, "candidates": candidates},
            "发现多个候选论文，请在审批回复中填写候选序号（从 1 开始）",
            "选择不同论文会改变证据目标",
        )
        try:
            index = int(choice.response) - 1
            if not 0 <= index < len(candidates):
                raise ValueError()
            return candidates[index]
        except ValueError as exc:
            raise ValueError("论文选择回复必须为有效候选序号") from exc

    def ingest(self, source: str) -> dict:
        """Parse PDF/HTML and build an index. Pass the exact source returned by paper_resolve; never rewrite local filenames."""
        local = self._local_source(source)
        if local:
            source = local
            path = Path(local)
            if path.stat().st_size > self.r.settings.max_document_mib * 1024**2:
                raise ValueError("本地文档超过大小限制")
            data = path.read_bytes()
        else:
            if not source.startswith(("http://", "https://")):
                raise ValueError(
                    f"未授权或无法识别的论文路径：{source!r}；"
                    "请使用 paper_resolve 返回的完整 source，不能改写文件名"
                )
            data = self.r.downloader.get(source, self.r.settings.max_document_mib * 1024**2)
        document_id = fingerprint(
            {
                "sha": sha256(data),
                "source": source,
                "index_version": self.r.index.collection,
                "text_extraction_version": 2,
            }
        )
        try:
            cached = self.r.store.get("document", document_id)
            self.r.store.put("document", cached, self.r.task_id)
            return cached
        except KeyError:
            pass
        ref = self.r.artifacts.write(f"documents/{document_id}/original", data)
        chunks, warnings = [], []
        metadata = {}
        if data.startswith(b"%PDF"):
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise ValueError("暂不支持加密 PDF")
            if len(reader.pages) > 500:
                raise ValueError("PDF 页数超过 500 页限制")
            metadata = {
                str(k).replace("\x00", " "): str(v).replace("\x00", " ")
                for k, v in (reader.metadata or {}).items()
            }
            for number, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                self._chunks(chunks, text, source, document_id, page=number)
            # 表格独立提取；失败记录缺口，不能由 LLM 补造表格数字。
            try:
                import pdfplumber

                with pdfplumber.open(io.BytesIO(data)) as pdf:
                    for number, page in enumerate(pdf.pages, 1):
                        for table in page.extract_tables():
                            text = "\n".join(" | ".join(str(v or "") for v in row) for row in table)
                            self._chunks(
                                chunks, text, source, document_id, page=number, chunk_type="table"
                            )
            except Exception:
                warnings.append("表格解析失败，请人工核对原始页面")
            if not any(c.chunk_type == "table" for c in chunks):
                warnings.append("未识别结构化表格；涉及表格的精确数值需核对原 PDF")
        else:
            soup = BeautifulSoup(data, "html.parser")
            for tag in soup(["script", "style", "nav"]):
                tag.decompose()
            metadata = {"title": soup.title.get_text() if soup.title else ""}
            text = soup.get_text("\n", strip=True)
            links = "\n".join(a.get("href", "") for a in soup.find_all("a", href=True))
            self._chunks(chunks, text + "\nLinks:\n" + links, source, document_id)
        if not chunks:
            raise ValueError("没有可提取文本；首版不支持扫描件 OCR")
        if b"%PDF" == data[:4]:
            warnings.append(
                "提取文本中的空字符 U+0000 如存在则替换为等长空格；"
                "原始 PDF 保持不变，公式与特殊符号请核对原页"
            )
        for chunk in chunks:
            self.r.store.put("evidence", chunk, self.r.task_id)
        serialized = [c.model_dump(mode="json") for c in chunks]
        index_id = self.r.index.build(document_id, serialized)
        doc = {
            "id": document_id,
            "schema_version": 1,
            "source": source,
            "artifact": ref,
            "index_id": index_id,
            "metadata": metadata,
            "warnings": warnings,
            "evidence_count": len(chunks),
        }
        self.r.store.put("document", doc, self.r.task_id)
        return doc

    def _chunks(self, chunks, text, source, revision, page=None, chunk_type="paragraph"):
        # PDF 字体映射可能产生 NUL，PostgreSQL JSONB 不接受它。
        # 等长替换保留原页字符偏移；原始文件仍保存为逐字节未修改的 artifact。
        text = text.replace("\x00", " ")
        # 短切片减少 E5 输入截断；source_span 保留原页文本中的字符位置。
        for start in range(0, len(text), 900):
            fragment = text[start : start + 1100].strip()
            if not fragment:
                continue
            id = fingerprint([revision, page, chunk_type, start, fragment])
            chunks.append(
                Evidence(
                    id=id,
                    created_at="",
                    kind="paper",
                    source=source,
                    text=fragment,
                    page=page,
                    source_span=f"chars:{start}:{start + 1100}",
                    revision=revision,
                    chunk_type=chunk_type,
                )
            )

    def search(self, index_id: str, query: str, limit: int = 5) -> list[dict]:
        """Search with the index_id from the document record, not its id. Returns original text and page provenance."""
        if not 1 <= limit <= 10:
            raise ValueError("limit 应为 1..10")
        # 接受可验证的 document ID 别名，不能通过猜测另一个索引绕过版本绑定。
        try:
            document = self.r.store.get("document", index_id)
        except KeyError:
            pass
        else:
            index_id = document["index_id"]
        return self.r.index.search(index_id, query, limit)

    def evidence(self, evidence_id: str) -> dict:
        """Read one persisted evidence record by its ID."""
        return self.r.store.get("evidence", evidence_id)
