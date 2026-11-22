"""Turn a report into a GitHub issue body and a Discord message."""

from .alerts import AlertGroup
from .config import Settings
from .triage import TriageResult


def issue_title(report: dict) -> str:
    return f"[incident] {report.get('title', 'Untitled')}"[:240]


def issue_body(group: AlertGroup, result: TriageResult, settings: Settings) -> str:
    r = result.report
    lines = [
        f"**Alert:** `{group.alertname}` ({group.severity}) — {group.summary}",
        f"**Started:** {min((a.starts_at for a in group.alerts), default='unknown')}",
        "",
        "## Summary",
        r.get("summary", ""),
        "",
        "## Likely cause",
        f"{r.get('likely_cause', '')} _(confidence: {r.get('confidence', 'low')})_",
        "",
        "## Evidence",
    ]
    for e in r.get("evidence", []):
        finding = e.get("finding", "")
        if "\n" in finding:
            lines += [f"- **{e.get('source', '')}**", "", "  ```", *("  " + x for x in finding.splitlines()), "  ```"]
        else:
            lines.append(f"- **{e.get('source', '')}:** {finding}")
    if r.get("ruled_out"):
        lines += ["", "## Ruled out", *(f"- {x}" for x in r["ruled_out"])]
    lines += ["", "## Next steps", *(f"1. {x}" for x in r.get("next_steps", []))]
    runbook = r.get("runbook") or group.runbook
    if runbook:
        lines += ["", f"**Runbook:** [{runbook}]({settings.repo_url}/blob/main/{runbook})"]
    lines += [
        "",
        "---",
        _footer(result),
    ]
    return "\n".join(lines)


def _footer(result: TriageResult) -> str:
    if result.mode == "agent":
        return (f"_Investigated by the Trackside triage agent ({result.model}): {result.tool_calls} read-only tool "
                f"calls, {result.duration_s:.0f}s, ${result.usage.cost_usd:.2f}. It cannot change the system; "
                f"every step above is for a human._")
    return f"_Evidence-only report: the triage agent did not run ({result.outcome})._"


def chat_message(group: AlertGroup, result: TriageResult, ticket_url: str | None) -> str:
    r = result.report
    icon = "🔴" if group.severity == "page" else "🟠"
    parts = [f"{icon} **{r.get('title', group.alertname)}**",
             r.get("summary", ""),
             f"Likely cause ({r.get('confidence', 'low')} confidence): {r.get('likely_cause', '')}"]
    if r.get("next_steps"):
        parts.append(f"First step: {r['next_steps'][0]}")
    if ticket_url:
        parts.append(ticket_url)
    return "\n".join(p for p in parts if p)[:1900]


def resolved_message(alertname: str, ticket_url: str | None) -> str:
    return f"✅ **Resolved:** `{alertname}`" + (f" — {ticket_url}" if ticket_url else "")
