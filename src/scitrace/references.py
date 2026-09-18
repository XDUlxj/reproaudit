"""模型使用短引用，持久记录继续使用完整稳定 ID；映射随任务保存以支持重启。"""

import re

from scitrace.models.core import fingerprint


class References:
    """把 SciTrace 内部很长的 UUID / SHA256 ID 临时压缩成 ref1、ref2，让 LLM 少吃 Token；等 LLM 返回结果后，再把 ref1 还原成真实 ID"""
    def __init__(self, store, task_id):
        self.store, self.task_id = store, task_id
        try:
            self.record = store.get("references", task_id)
        except KeyError:
            self.record = {"id": task_id, "schema_version": 1, "mapping": {}}

    def encode(self, value):
        mapping = self.record["mapping"]
        reverse = {v: k for k, v in mapping.items()}

        def walk(item):
            if isinstance(item, dict):
                return {k: walk(v) for k, v in item.items()}
            if isinstance(item, list):
                return [walk(v) for v in item]
            # 摘要也可使用短引用，decode 后仍由下载事实严格比对。
            if isinstance(item, str):

                def alias_for(match):
                    original = match[0]
                    if original in reverse:
                        return reverse[original]
                    alias = f"ref{len(mapping) + 1}"
                    mapping[alias] = original
                    reverse[original] = alias
                    return alias

                return re.sub(
                    r"\b(?:[0-9a-f]{64}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\b",
                    alias_for,
                    item,
                )
            return item

        result = walk(value)
        self.store.put("references", self.record, self.task_id)
        return result

    def decode(self, value):
        if isinstance(value, dict):
            return {k: self.decode(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.decode(v) for v in value]
        if isinstance(value, str):
            # 自然语言 goal/answer 中的引用同样展开，不对未知 ID 作模糊修复。
            return re.sub(r"\bref\d+\b", lambda m: self.record["mapping"].get(m[0], m[0]), value)
        return value


def observation(runtime, value):
    """返回合法、有限的结构化观察；完整大对象保存在 artifact 中。"""
    import json

    ref = runtime.artifacts.json(
        f"tasks/{runtime.task_id}/tool-results/{fingerprint(value)}.json", value
    )

    def compact(item):
        if isinstance(item, dict):
            return {k: compact(v) for k, v in item.items()}
        if isinstance(item, list):
            return [compact(v) for v in item[:12]]
        if isinstance(item, str) and len(item) > 3000:
            return item[:3000] + "\n[摘要截断；完整内容见 artifact]"
        return item

    result = compact(value)
    refs = getattr(runtime, "references", None)
    if refs:
        result = refs.encode(result)
    return json.dumps({"result": result, "artifact": ref}, ensure_ascii=False)
