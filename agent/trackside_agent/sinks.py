"""Where reports go. The outbox always gets a copy; GitHub and Discord only when
their credentials are configured. A failing output is logged and counted, never
allowed to stop the others."""

import json
import logging
import re
import urllib.request
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

Post = Callable[[str, str, dict, dict[str, str]], dict]


def http_send(method: str, url: str, body: dict, headers: dict[str, str]) -> dict:
    request = urllib.request.Request(
        url, method=method, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "trackside-agent/0.1", **headers})
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read()
    return json.loads(raw) if raw else {}


class Outbox:
    """Markdown copies of every report, for local runs and as an audit trail."""

    def __init__(self, directory: Path):
        self.dir = directory

    def write(self, incident_id: int, title: str, body: str) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"incident-{incident_id:04d}.md"
        path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
        return path

    def append(self, incident_id: int, text: str) -> None:
        path = self.dir / f"incident-{incident_id:04d}.md"
        if path.exists():
            with path.open("a", encoding="utf-8") as f:
                f.write(f"\n{text}\n")


class GitHubIssues:
    API = "https://api.github.com"

    def __init__(self, token: str, repo: str, send: Post = http_send):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
            raise ValueError(f"GITHUB_REPO must look like owner/name, got {repo!r}")
        self.repo = repo
        self._send = send
        self._headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                         "X-GitHub-Api-Version": "2022-11-28"}

    def create(self, title: str, body: str, labels: list[str]) -> str:
        issue = self._send("POST", f"{self.API}/repos/{self.repo}/issues",
                           {"title": title, "body": body, "labels": labels}, self._headers)
        return issue["html_url"]

    def resolve(self, issue_url: str, comment: str) -> None:
        number = int(issue_url.rstrip("/").rsplit("/", 1)[-1])
        base = f"{self.API}/repos/{self.repo}/issues/{number}"
        self._send("POST", f"{base}/comments", {"body": comment}, self._headers)
        self._send("PATCH", base, {"state": "closed", "state_reason": "completed"}, self._headers)


class Discord:
    def __init__(self, webhook_url: str, send: Post = http_send):
        if not webhook_url.startswith("https://discord.com/api/webhooks/"):
            raise ValueError("DISCORD_WEBHOOK_URL must be a discord.com webhook URL")
        self.url = webhook_url
        self._send = send

    def post(self, content: str) -> None:
        # No mentions: an incident message must never ping @everyone by accident.
        self._send("POST", self.url, {"content": content, "allowed_mentions": {"parse": []}}, {})
