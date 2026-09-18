from typing import Literal
from urllib.parse import urlsplit

import httpx

from scitrace.models.core import Evidence, ResearchResource, fingerprint


class DiscoveryTools:
    def __init__(self, runtime):
        self.r = runtime

    def search(self, query: str) -> dict:
        """Search public research resources using Tavily; results are candidates, not proof of official status."""
        response = httpx.post(
            "https://api.tavily.com/search",
            timeout=45,
            headers={
                "Authorization": "Bearer " + self.r.settings.tavily_api_key.get_secret_value()
            },
            json={
                "query": query,
                "max_results": 5,
                "search_depth": "basic",
                "include_raw_content": False,
            },
        )
        response.raise_for_status()
        results = []
        for item in response.json().get("results", []):
            evidence = Evidence(
                id=fingerprint([item["url"], item.get("content", "")]),
                kind="web",
                source=item["url"],
                text=item.get("content", "")[:6000],
            )
            self.r.store.put("evidence", evidence, self.r.task_id)
            results.append(
                {
                    "url": item["url"],
                    "title": item.get("title"),
                    "evidence_id": evidence.id,
                    "snippet": evidence.text,
                }
            )
        return {"results": results}

    def fetch(self, url: str) -> dict:
        """Read a public project page or README, preserving its evidence ID. No repository execution."""
        from bs4 import BeautifulSoup

        data = self.r.downloader.get(url, 2_000_000)
        soup = BeautifulSoup(data, "html.parser")
        for element in soup(["script", "style"]):
            element.decompose()
        text = soup.get_text("\n", strip=True)
        links = [a.get("href") for a in soup.find_all("a", href=True)]
        evidence = Evidence(
            id=fingerprint([url, data.hex()]),
            kind="web",
            source=url,
            text=(text[:8000] + "\n" + "\n".join(links)[:3000])[:12000],
        )
        self.r.artifacts.write(f"web/{evidence.id}/original.html", data)
        self.r.artifacts.write(f"web/{evidence.id}/text.txt", text.encode())
        self.r.store.put("evidence", evidence, self.r.task_id)
        return evidence.model_dump(mode="json")

    def register(
        self,
        url: str,
        kind: str,
        resource_status: Literal["official", "author_affiliated", "third_party", "unverified"],
        verification_confidence: float,
        evidence_ids: list[str],
        reason: str,
    ) -> dict:
        """Register a candidate and provenance. Official status requires a direct link in a supplied paper or trusted project page."""
        evidence = [self.r.store.get("evidence", id) for id in evidence_ids]
        if resource_status == "official":
            # 官网自称 official 不够；需要已确认论文证据里的直接链接。
            direct = any(e["kind"] == "paper" and url.rstrip("/") in e["text"] for e in evidence)
            trusted = any(
                e["source"] in self.r.trusted_project_urls and url.rstrip("/") in e["text"]
                for e in evidence
            )
            if not (direct or trusted):
                resource_status = "unverified"
                reason += "；缺少可信原文直接链接，已降为 unverified"
                verification_confidence = min(verification_confidence, 0.49)
        if urlsplit(url).scheme not in {"https", "http"}:
            raise ValueError("资源必须使用 HTTP(S) URL")
        resource = ResearchResource(
            id=fingerprint([url, resource_status, sorted(evidence_ids)]),
            url=url,
            kind=kind,
            resource_status=resource_status,
            verification_confidence=verification_confidence,
            evidence_ids=evidence_ids,
            reason=reason,
        )
        self.r.store.put("resource", resource, self.r.task_id)
        return resource.model_dump(mode="json")
