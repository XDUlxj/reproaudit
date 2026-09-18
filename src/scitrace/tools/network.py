"""仅下载公开网络内容；DNS 固定到校验后的地址，重定向逐跳校验。"""

import hashlib
import ipaddress
import shutil
import socket
import ssl
import tarfile
import time
import zipfile
from http.client import HTTPConnection, HTTPSConnection
from pathlib import Path
from urllib.parse import urljoin, urlsplit


class DownloadError(ValueError):
    pass


def public_address(url: str, trusted_fake_dns_hosts=()) -> tuple[str, int, str, str]:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise DownloadError("只允许无凭据的 HTTP(S) 公网 URL")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in {80, 443}:
        raise DownloadError("外部资源只允许 80/443 端口")
    addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    ips = sorted({a[4][0] for a in addresses})

    def permitted(ip):
        address = ipaddress.ip_address(ip)
        # 部分本地代理使用 RFC 2544 fake-IP。只允许操作者列出的域名和该特定网段。
        fake_dns = (
            parsed.hostname in trusted_fake_dns_hosts
            and address.version == 4
            and address in ipaddress.ip_network("198.18.0.0/15")
        )
        return address.is_global or fake_dns

    if not ips or any(not permitted(ip) for ip in ips):
        rendered = ", ".join(ips) if ips else "无解析结果"
        hint = ""
        if ips and all(
            ipaddress.ip_address(ip).version == 4
            and ipaddress.ip_address(ip) in ipaddress.ip_network("198.18.0.0/15")
            for ip in ips
        ):
            hint = (
                f"；检测到本机代理 fake-IP。确认信任 {parsed.hostname} 后，将该域名加入 "
                "TRUSTED_FAKE_DNS_HOSTS"
            )
        raise DownloadError(
            f"禁止访问私网、回环或保留地址：{parsed.hostname} -> {rendered}{hint}"
        )
    return parsed.hostname, port, ips[0], parsed.scheme


class Downloader:
    def __init__(
        self, limit_bytes: int, consumed=0, on_bytes=None, on_retry=None, trusted_fake_dns_hosts=()
    ):
        self.trusted_fake_dns_hosts = trusted_fake_dns_hosts
        self.limit = limit_bytes
        self.consumed = consumed
        self.on_bytes = on_bytes
        self.on_retry = on_retry

    def get(self, url: str, max_bytes: int | None = None) -> bytes:
        for attempt in range(3):
            try:
                return self._get(url, max_bytes)
            except (OSError, TimeoutError):
                if attempt == 2:
                    raise
                if self.on_retry:
                    self.on_retry(url, attempt + 1)
                time.sleep(0.5 * (attempt + 1))
        raise RuntimeError("下载重试耗尽")

    def _get(self, url: str, max_bytes: int | None = None) -> bytes:
        deadline = time.monotonic() + 90
        limit = min(max_bytes or self.limit, self.limit - self.consumed)
        if limit <= 0:
            raise DownloadError("任务下载预算已耗尽")
        for _ in range(6):
            host, port, ip, scheme = public_address(url, self.trusted_fake_dns_hosts)
            conn = (
                HTTPSConnection(host, port, timeout=30)
                if scheme == "https"
                else HTTPConnection(host, port, timeout=30)
            )
            raw = socket.create_connection((ip, port), timeout=30)
            conn.sock = (
                ssl.create_default_context().wrap_socket(raw, server_hostname=host)
                if scheme == "https"
                else raw
            )
            parsed = urlsplit(url)
            target = parsed.path or "/"
            if parsed.query:
                target += "?" + parsed.query
            try:
                conn.request(
                    "GET",
                    target,
                    headers={"User-Agent": "SciTrace/0.1", "Accept-Encoding": "identity"},
                )
                response = conn.getresponse()
                if response.status in {301, 302, 303, 307, 308}:
                    url = urljoin(url, response.getheader("Location", ""))
                    continue
                if response.status != 200:
                    raise DownloadError(f"下载失败 HTTP {response.status}：{url}")
                length = response.getheader("Content-Length")
                if length and int(length) > limit:
                    raise DownloadError("资源超过下载大小限制")
                data = bytearray()
                # read1 允许逐次检查总耗时，防止慢速 chunked 响应持续刷新 socket 超时。
                while chunk := response.read1(min(65536, limit - len(data) + 1)):
                    if time.monotonic() > deadline:
                        raise DownloadError("单次下载超过 90 秒总时限：" + url)
                    data.extend(chunk)
                    self.consumed += len(chunk)
                    if self.on_bytes:
                        self.on_bytes(self.consumed)
                    if len(data) > limit:
                        raise DownloadError("流式下载超过大小限制")
                return bytes(data)
            finally:
                conn.close()
        raise DownloadError("重定向次数超限")


def safe_path(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or "\\" in name:
        raise ValueError("路径越界")
    return path


def extract_archive(archive: Path, destination: Path, kind: str, limit: int):
    destination.mkdir(parents=True, exist_ok=True)
    count, total = 0, 0
    if kind == "zip":
        with zipfile.ZipFile(archive) as z:
            for entry in z.infolist():
                count += 1
                total += entry.file_size
                if (
                    count > 30000
                    or total > limit
                    or (entry.external_attr >> 16) & 0o170000 == 0o120000
                ):
                    raise ValueError("归档超限或包含符号链接")
                path = safe_path(destination, entry.filename)
                if entry.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(entry) as stream, path.open("wb") as target:
                        shutil.copyfileobj(stream, target, 65536)
    else:
        with tarfile.open(archive) as tar:
            for entry in tar:
                count += 1
                total += entry.size
                if count > 30000 or total > limit or not (entry.isfile() or entry.isdir()):
                    raise ValueError("归档超限或含链接/特殊文件")
                path = safe_path(destination, entry.name)
                if entry.isdir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    stream = tar.extractfile(entry)
                    if stream:
                        with stream, path.open("wb") as target:
                            shutil.copyfileobj(stream, target, 65536)


def sha256(data: bytes):
    return hashlib.sha256(data).hexdigest()
