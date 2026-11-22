"""Settings, read from the environment. Every external output is optional: with
none configured the agent still investigates and writes its reports to the outbox."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    readonly_database_url: str
    prometheus_url: str = "http://prometheus:9090"
    loki_url: str = "http://loki:3100"
    airflow_url: str = "http://airflow-apiserver:8080"
    runbooks_dir: Path = Path("/app/docs/runbooks")
    outbox_dir: Path = Path("/outbox")

    # Claude. No key means evidence-only fallback reports.
    anthropic_api_key: str | None = None
    model: str = "claude-opus-5-5"
    effort: str = "high"
    max_iterations: int = 15
    monthly_budget_usd: float = 5.0
    per_incident_budget_usd: float = 1.0

    # Outputs.
    github_token: str | None = None
    github_repo: str | None = None
    discord_webhook_url: str | None = None

    # Links the reports point readers to.
    grafana_url: str = "http://localhost:3000"
    prometheus_public_url: str = "http://localhost:9090"
    repo_url: str = "https://github.com/matthosch/trackside"

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ.get

        def optional(name: str) -> str | None:
            return env(name) or None

        return cls(
            database_url=os.environ["DATABASE_URL"],
            readonly_database_url=os.environ["READONLY_DATABASE_URL"],
            prometheus_url=env("PROMETHEUS_URL", cls.prometheus_url),
            loki_url=env("LOKI_URL", cls.loki_url),
            airflow_url=env("AIRFLOW_URL", cls.airflow_url),
            runbooks_dir=Path(env("RUNBOOKS_DIR", str(cls.runbooks_dir))),
            outbox_dir=Path(env("OUTBOX_DIR", str(cls.outbox_dir))),
            anthropic_api_key=optional("ANTHROPIC_API_KEY"),
            model=env("AGENT_MODEL", cls.model),
            effort=env("AGENT_EFFORT", cls.effort),
            max_iterations=int(env("AGENT_MAX_ITERATIONS", cls.max_iterations)),
            monthly_budget_usd=float(env("AGENT_MONTHLY_BUDGET_USD", cls.monthly_budget_usd)),
            per_incident_budget_usd=float(env("AGENT_INCIDENT_BUDGET_USD", cls.per_incident_budget_usd)),
            github_token=optional("GITHUB_TOKEN"),
            github_repo=optional("GITHUB_REPO"),
            discord_webhook_url=optional("DISCORD_WEBHOOK_URL"),
            grafana_url=env("GRAFANA_PUBLIC_URL", cls.grafana_url),
            prometheus_public_url=env("PROMETHEUS_PUBLIC_URL", cls.prometheus_public_url),
            repo_url=env("REPO_URL", cls.repo_url),
        )
