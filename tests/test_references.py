from scitrace.references import References, observation


def test_short_references_persist_and_do_not_guess(store):
    refs = References(store, "task")
    full = "a" * 64
    encoded = refs.encode({"id": full, "evidence_ids": [full]})
    assert encoded == {"id": "ref1", "evidence_ids": ["ref1"]}
    restored = References(store, "task")
    assert restored.decode(encoded)["id"] == full
    assert restored.decode("请使用 ref1，ref999 未知") == f"请使用 {full}，ref999 未知"
    assert References(store, "other").decode("ref1") == "ref1"


def test_large_observation_stays_valid_json_and_keeps_original(basic_runtime):
    import json

    value = {"text": "正文" * 20000}
    result = json.loads(observation(basic_runtime, value))
    assert len(result["result"]["text"]) < 4000
    assert json.loads(basic_runtime.artifacts.path(result["artifact"]).read_text()) == value
