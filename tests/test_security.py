import io
import socket
import tarfile
import zipfile

import pytest
from pydantic import ValidationError

from scitrace.models.core import CommandSpec, ResourceInput
from scitrace.tools.network import DownloadError, extract_archive, public_address, safe_path


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "http://u:p@example.com", "http://example.com:8080"]
)
def test_reject_url(url):
    with pytest.raises(DownloadError):
        public_address(url)


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "192.168.1.1"]
)
def test_private_dns(monkeypatch, address):
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **kw: [(None, None, None, None, (address, 80))]
    )
    with pytest.raises(DownloadError):
        public_address("http://example.com")


def test_path_traversal(tmp_path):
    with pytest.raises(ValueError):
        safe_path(tmp_path, "../outside")
    with pytest.raises(ValidationError):
        CommandSpec(argv=["echo"], cwd="../../")
    with pytest.raises(ValidationError):
        ResourceInput(url="https://example.com", sha256="a" * 64, destination="/etc/x")


def test_archive_traversal(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../escape", "bad")
    with pytest.raises(ValueError):
        extract_archive(archive, tmp_path / "out", "zip", 1000)
    assert not (tmp_path / "escape").exists()


def test_archive_symlink(tmp_path):
    archive = tmp_path / "bad.tar"
    with tarfile.open(archive, "w") as tar:
        entry = tarfile.TarInfo("link")
        entry.type, entry.linkname = tarfile.SYMTYPE, "/etc/passwd"
        tar.addfile(entry)
    with pytest.raises(ValueError):
        extract_archive(archive, tmp_path / "out", "tar", 1000)


def test_archive_size(tmp_path):
    archive = tmp_path / "large.tar"
    with tarfile.open(archive, "w") as tar:
        entry = tarfile.TarInfo("data")
        entry.size = 100
        tar.addfile(entry, io.BytesIO(b"a" * 100))
    with pytest.raises(ValueError):
        extract_archive(archive, tmp_path / "out", "tar", 10)


def test_fake_dns_requires_specific_host_and_range(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **kw: [(None, None, None, None, ("198.18.0.2", 443))]
    )
    with pytest.raises(DownloadError):
        public_address("https://example.com")
    assert public_address("https://example.com", ["example.com"])[2] == "198.18.0.2"
    with pytest.raises(DownloadError):
        public_address("https://evil.example", ["example.com"])
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **kw: [(None, None, None, None, ("127.0.0.1", 443))]
    )
    with pytest.raises(DownloadError):
        public_address("https://example.com", ["example.com"])


def test_fake_dns_error_names_required_host(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(None, None, None, None, ("198.18.0.9", 443))],
    )
    with pytest.raises(DownloadError, match="TRUSTED_FAKE_DNS_HOSTS") as error:
        public_address("https://arxiv.org/pdf/1607.01759")
    assert "arxiv.org" in str(error.value)
