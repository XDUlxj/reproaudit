from uuid import uuid4

from langchain_openai import ChatOpenAI

from scitrace.execution.runner import DockerRunner
from scitrace.indexing.hybrid import HybridIndex
from scitrace.policy import Policy
from scitrace.references import References
from scitrace.storage import Artifacts
from scitrace.tools.discovery import DiscoveryTools
from scitrace.tools.network import Downloader
from scitrace.tools.paper import PaperTools
from scitrace.tools.repository import RepositoryTools
from scitrace.tools.trace import TraceTools


class Runtime:
    def __init__(
        self,
        settings,
        store,
        task_id,
        model=None,
        index=None,
        local_inputs=None,
        trusted_project_urls=None,
        on_event=None,
    ):
        self.settings = settings
        self.store = store
        self.task_id =  task_id
        self.artifacts = Artifacts(settings.artifact_root)
        self.policy = Policy(store, task_id)
        self.references = References(store, task_id)
        self.local_inputs = local_inputs or []
        self.trusted_project_urls = trusted_project_urls or []
        self.on_event = on_event # 事件回调：任何 agent 调了什么工具、成功 / 失败，实时打印到控制台
        self.model = model or ChatOpenAI(
            model=settings.glm_model,
            base_url=settings.glm_base_url,
            api_key=settings.glm_api_key.get_secret_value(),
            temperature=0,
            timeout=settings.model_timeout,
            max_retries=2,
            max_tokens=4096,
        )
        self.index = index or HybridIndex(settings, self.artifacts)
        try:
            consumed = self.store.get("download_budget", task_id)["bytes"]
        except KeyError:
            consumed = 0
        self.downloader = Downloader(
            settings.download_limit_mib * 1024**2,
            consumed,
            lambda size: self.store.put("download_budget", {"id": task_id, "bytes": size}, task_id),
            lambda url, attempt: self.event(
                "Downloader", f"network_retry_{attempt}: {url}", "retry"
            ),
            trusted_fake_dns_hosts=settings.trusted_fake_dns_hosts,
        )
        self.paper = PaperTools(self)
        self.discovery = DiscoveryTools(self)
        self.repository = RepositoryTools(self)
        self.trace = TraceTools(self)
        self.runner = DockerRunner(self)

    def event(self, agent, action, status, detail=None):
        event = {
            "id": str(uuid4()),
            "agent": agent,
            "action": action,
            "status": status,
        }
        if detail:
            event["detail"] = self.settings.redact(str(detail))[:1500]
        self.store.put("event", event, self.task_id)
        if self.on_event:
            self.on_event(event)

    def record_usage(self, agent, response):
        """记录 LLM 使用情况"""
        self.store.put(
            "usage",
            {
                "id": str(uuid4()),
                "agent": agent,
                "model": self.settings.glm_model,
                "tokens": response.usage_metadata or {},
            },
            self.task_id,
        )
