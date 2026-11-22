"""Alertmanager's webhook payload (version 4), reduced to what the agent uses."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Alert:
    status: str
    labels: dict[str, str]
    annotations: dict[str, str]
    starts_at: str
    fingerprint: str = ""


@dataclass(frozen=True)
class AlertGroup:
    group_key: str
    status: str                       # firing | resolved
    common_labels: dict[str, str]
    common_annotations: dict[str, str]
    alerts: list[Alert] = field(default_factory=list)

    @property
    def alertname(self) -> str:
        return self.common_labels.get("alertname") or (self.alerts[0].labels.get("alertname", "unknown")
                                                       if self.alerts else "unknown")

    @property
    def severity(self) -> str:
        return self.common_labels.get("severity", "ticket")

    @property
    def runbook(self) -> str | None:
        return self.common_annotations.get("runbook") or next(
            (a.annotations["runbook"] for a in self.alerts if "runbook" in a.annotations), None)

    @property
    def summary(self) -> str:
        return self.common_annotations.get("summary") or next(
            (a.annotations["summary"] for a in self.alerts if "summary" in a.annotations), self.alertname)

    @classmethod
    def from_webhook(cls, payload: dict) -> "AlertGroup":
        if str(payload.get("version")) != "4":
            raise ValueError(f"unsupported Alertmanager webhook version {payload.get('version')!r}")
        return cls(
            group_key=payload["groupKey"],
            status=payload["status"],
            common_labels=payload.get("commonLabels") or {},
            common_annotations=payload.get("commonAnnotations") or {},
            alerts=[
                Alert(status=a["status"], labels=a.get("labels") or {}, annotations=a.get("annotations") or {},
                      starts_at=a.get("startsAt", ""), fingerprint=a.get("fingerprint", ""))
                for a in payload.get("alerts", [])
            ],
        )

    def brief(self) -> str:
        """The alert as the agent first sees it."""
        lines = [f"Alert: {self.alertname} ({self.severity}), status {self.status}",
                 f"Summary: {self.summary}"]
        if self.runbook:
            lines.append(f"Runbook: {self.runbook}")
        for alert in self.alerts:
            extra = {k: v for k, v in alert.labels.items() if k not in ("alertname", "severity")}
            lines.append(f"- {alert.status} since {alert.starts_at}; labels {extra}")
            for key, value in alert.annotations.items():
                if key not in ("summary", "runbook"):
                    lines.append(f"  {key}: {value}")
        return "\n".join(lines)
