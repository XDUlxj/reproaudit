from scitrace.models.core import Evidence
from scitrace.tools.paper import PaperTools


def test_search_resolves_document_id_to_bound_index(basic_runtime):
    from types import SimpleNamespace

    calls = []
    basic_runtime.store.put("document", {"id": "doc", "index_id": "actual-index"})
    basic_runtime.index = SimpleNamespace(
        search=lambda index, query, limit: calls.append((index, query, limit)) or []
    )
    PaperTools(basic_runtime).search("doc", "datasets")
    assert calls == [("actual-index", "datasets", 5)]


def test_plan_requires_measured_resource_hash(basic_runtime):
    from types import SimpleNamespace

    import pytest

    from scitrace.models.core import ReproductionPlan, ResourceInput
    from scitrace.tools.trace import TraceTools

    tool = TraceTools(basic_runtime)
    url = "https://example.com/data.txt"
    basic_runtime.downloader = SimpleNamespace(get=lambda _: b"measured data")
    plan = ReproductionPlan(
        claim_id="claim", resources=[ResourceInput(url=url, sha256="a" * 64, destination="data")]
    )
    with pytest.raises(ValueError, match="未经实际下载核验"):
        tool.save_plan(plan)
    measured = tool.inspect_resource(url)
    plan.resources[0].sha256 = measured["sha256"]
    assert tool.save_plan(plan)["resources"][0]["sha256"] == measured["sha256"]


def test_repository_search_uses_saved_index(basic_runtime):
    from types import SimpleNamespace

    from scitrace.tools.repository import RepositoryTools

    r = basic_runtime
    r.store.put("repository", {"id": "repo", "index_id": "repo-index"})
    calls = []
    r.index = SimpleNamespace(search=lambda *args: calls.append(args) or [])
    RepositoryTools(r).search("repo", "cooking.stackexchange")
    assert calls == [("repo-index", "cooking.stackexchange", 5)]


def test_discovery_finish_resolves_urls_without_promoting_identity(basic_runtime):
    from types import SimpleNamespace

    from scitrace.agents.specialists import make_specialists

    r = basic_runtime
    r.runner = SimpleNamespace(run=lambda: None)
    def run(plan_id: str):
        """测试执行工具，不运行实验。"""
        return {}
    r.runner.run = run
    from scitrace.tools.discovery import DiscoveryTools
    from scitrace.tools.paper import PaperTools
    from scitrace.tools.repository import RepositoryTools
    from scitrace.tools.trace import TraceTools
    r.paper, r.discovery, r.trace, r.repository = (
        PaperTools(r), DiscoveryTools(r), TraceTools(r), RepositoryTools(r)
    )
    url = "https://github.com/example/repo"
    for id in ("r1", "r2"):
        r.store.put("resource", {"id": id, "url": url, "resource_status": "unverified"}, r.task_id)
    validate = make_specialists(r)["discovery_agent"].validate_result
    result = validate({"resource_ids": [url], "official_repository": url, "discovery_status": "completed"})
    assert result["resource_ids"] == ["r1", "r2"]
    assert result["official_repository"] is None
    assert result["missing_resources"]


def test_plan_rejects_non_executable_command_layout(basic_runtime):
    import pytest

    from scitrace.models.core import CommandSpec, ReproductionPlan
    from scitrace.tools.trace import TraceTools

    tool = TraceTools(basic_runtime)
    plan = ReproductionPlan(claim_id="claim", commands=[CommandSpec(argv=["make"])])
    plan.mode = "paper_only"
    with pytest.raises(ValueError, match="paper_only"):
        tool.save_plan(plan)
    plan.mode = "code_assisted"
    plan.commands[0].argv = ["cd", "source", "&&", "make"]
    with pytest.raises(ValueError, match="argv"):
        tool.save_plan(plan)
    plan.commands[0].argv = ["wget", "https://example.com/data"]
    with pytest.raises(ValueError, match="断网"):
        tool.save_plan(plan)


def test_tool_schemas_expose_record_and_resource_enums(basic_runtime):
    from scitrace.agents.loop import tool_for
    from scitrace.tools.discovery import DiscoveryTools
    from scitrace.tools.trace import TraceTools

    read = tool_for(TraceTools(basic_runtime).read_record, "read_record")
    register = tool_for(DiscoveryTools(basic_runtime).register, "register_resource")
    assert "document" in read.args["kind"]["enum"]
    assert "paper" not in read.args["kind"]["enum"]
    assert "mirror" not in register.args["resource_status"]["enum"]


def test_repository_url_alias_still_requires_approval(basic_runtime):
    import pytest

    from scitrace.policy import NeedsApproval
    from scitrace.tools.repository import RepositoryTools

    r = basic_runtime
    url = "https://github.com/example/repo"
    r.store.put(
        "resource", {"id": "registered", "url": url, "resource_status": "unverified"}, r.task_id
    )
    with pytest.raises(NeedsApproval):
        RepositoryTools(r).index(url)
    with pytest.raises(ValueError, match="可用资源"):
        RepositoryTools(r).index("mistyped-hash")


def test_local_path_aliases_only_match_explicit_authorization(basic_runtime, tmp_path, monkeypatch):
    import pytest

    monkeypatch.chdir(tmp_path)
    paper = tmp_path / "my-repo" / "ZIPIT! paper.pdf"
    paper.parent.mkdir()
    paper.write_bytes(b"%PDF")
    basic_runtime.local_inputs = [str(paper), str(paper.parent)]
    tool = PaperTools(basic_runtime)
    assert tool.resolve("./my-repo/ZIPIT! paper.pdf")["source"] == str(paper)
    assert tool._local_source("my-repo/../my-repo/ZIPIT! paper.pdf") == str(paper)
    assert tool._local_source("./my-repo/other.pdf") is None
    with pytest.raises(ValueError, match="未授权或无法识别"):
        tool.ingest("./my-repo/other.pdf")


def test_nul_replacement_preserves_offsets(basic_runtime):
    chunks = []
    text = "A" * 899 + "\x00" + "B" * 300
    PaperTools(basic_runtime)._chunks(chunks, text, "paper.pdf", "rev", page=2)
    assert "\x00" not in chunks[0].text
    assert chunks[0].text[899:901] == " B"
    assert chunks[1].source_span == "chars:900:2000"
    assert chunks[1].text.startswith("B")


def test_ingest_nul_text_and_metadata(basic_runtime, tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    path = tmp_path / "nul.pdf"
    original = b"%PDF-test-original"
    path.write_bytes(original)
    monkeypatch.setattr(
        "scitrace.tools.paper.PdfReader",
        lambda _: SimpleNamespace(
            is_encrypted=False,
            metadata={"/Title": "A\x00B"},
            pages=[SimpleNamespace(extract_text=lambda: "Formula A\x00B and dataset")],
        ),
    )
    r = basic_runtime
    r.local_inputs = [str(path)]
    builds = []
    r.index = SimpleNamespace(
        collection="test", build=lambda id, chunks: builds.append(chunks) or id
    )
    doc = PaperTools(r).ingest(str(path))
    assert doc["metadata"]["/Title"] == "A B"
    assert builds[0][0]["text"] == "Formula A B and dataset"
    assert r.artifacts.path(doc["artifact"]).read_bytes() == original
    assert any("U+0000" in warning for warning in doc["warnings"])
    for (payload, _) in r.store.data.values():
        assert "\\u0000" not in json.dumps(payload)


def test_chunks_preserve_page_and_span(basic_runtime):
    chunks = []
    PaperTools(basic_runtime)._chunks(chunks, "Evidence " * 400, "paper.pdf", "rev", page=4)
    assert len(chunks) > 1
    assert all(c.page == 4 and c.source_span.startswith("chars:") for c in chunks)
    assert all(c.revision == "rev" for c in chunks)
    assert len({c.id for c in chunks}) == len(chunks)


def test_claim_code_evidence_requires_real_ids(basic_runtime):
    import pytest

    from scitrace.tools.trace import TraceTools

    with pytest.raises(KeyError):
        TraceTools(basic_runtime).validate_result(
            {"claims": [{"id": "c", "text": "claim", "evidence_ids": ["invented"]}]}
        )


def test_official_label_requires_link_evidence(basic_runtime):
    from scitrace.tools.discovery import DiscoveryTools

    r = basic_runtime
    r.trusted_project_urls = []
    evidence = Evidence(kind="web", source="https://github.com/x/y", text="official implementation")
    r.store.put("evidence", evidence)
    result = DiscoveryTools(r).register(
        "https://github.com/x/y",
        "repository",
        "official",
        0.99,
        [evidence.id],
        "README says official",
    )
    assert result["resource_status"] == "unverified"
    assert result["verification_confidence"] < 0.5


def test_multiple_tables_same_page_do_not_collide(basic_runtime):
    chunks = []
    tool = PaperTools(basic_runtime)
    tool._chunks(chunks, "A | .5", "paper.pdf", "revision", page=2, chunk_type="table")
    tool._chunks(chunks, "B | .9", "paper.pdf", "revision", page=2, chunk_type="table")
    assert chunks[0].id != chunks[1].id


def test_real_pdf_ingestion_and_cache(basic_runtime, tmp_path):
    from types import SimpleNamespace

    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    r = basic_runtime
    path = tmp_path / "paper.pdf"
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 10 250 Td (We use the Cooking dataset.) Tj ET")
    page[NameObject("/Contents")] = stream
    writer.add_metadata({"/Title": "Test paper"})
    with path.open("wb") as out:
        writer.write(out)
    builds = []
    r.local_inputs = [str(path)]
    r.index = SimpleNamespace(
        collection="embedding-v1", build=lambda id, chunks: builds.append(chunks) or "index"
    )
    tool = PaperTools(r)
    first = tool.ingest(str(path))
    assert first["metadata"]["/Title"] == "Test paper"
    assert builds[0][0]["page"] == 1
    assert "Cooking" in builds[0][0]["text"]
    assert tool.ingest(str(path))["id"] == first["id"]
    assert len(builds) == 1
    r.index.collection = "embedding-v2"
    assert tool.ingest(str(path))["id"] != first["id"]
    assert len(builds) == 2
