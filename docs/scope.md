# Trackside: project scope

Agreed 2026-11-16. Status: planning; nothing is built yet.

## Purpose

Trackside is an operations showcase with a GT3 race app as its workload. It targets the
Operations Engineer, BizTech role at Airbnb (Global Operations), whose posting centres on
observability, incident response, data pipelines, infrastructure as code, CI/CD, and applying
AI to operational health. There is no deadline.

## The app

Pick a race, see what to watch, see where to stay.

- **What to watch:** pace by car model at the circuit from previous years, and Balance of
  Performance (BoP) changes since the last round and since last year. Stint and pit-stop
  analysis comes later. No LLM-written previews.
- **Where to stay:** synthetic listings around each circuit with distance, capacity, and a
  nightly price that rises as race weekend approaches. Labelled as sample data, with no Airbnb
  name, logo, or styling.
- **Calendar:** every round, re-polled on a schedule because provisional dates move.

Out of scope: accounts, fly-vs-drive comparison, airfare, car rental, routing, weather.

## Data

| Dataset | Source | Notes |
|---|---|---|
| Lap-by-lap timing (core) | Al Kamel CSV archives: IMSA GTD/GTD Pro (`imsa.results.alkamelcloud.com`, 2016–2026) and GT World Challenge America (`usac.alkamelsystems.com`, 2023–2026) | Same file family on both hosts. `;`-delimited, UTF-8 BOM. Filenames are inconsistent, so discover links from the listing pages instead of constructing URLs. |
| BoP bulletins | IMSA technical bulletin PDFs | imsa.com is behind a bot challenge, so bulletins are downloaded by hand into a drop folder. The pipeline parses what lands there and alerts when an event has none. |
| Calendars | SRO and IMSA series sites (HTML) | 2027 calendars are published and provisional. |
| Stays | Seeded generator, snapshotted daily | Synthetic. |
| Europe (second tier, later) | GT World Challenge Europe site | Calendar and classification only; no public lap-level data. |

**Handling Al Kamel's data.** Their results pages state the data is wholly owned by Al Kamel
Systems and must not be distributed without consent. Raw files stay out of the repo and in a
private bucket. The public app shows only derived aggregates, with attribution. Fetching is
once per session, cached, and rate-limited. A permission request is drafted in
`al-kamel-permission-email.md`.

**Stream.** A replayer pushes archived laps through SQS at real or accelerated speed as a
simulated race weekend. Real live timing is not used (undocumented feeds, paid official
access).

## Stack

| Layer | Choice |
|---|---|
| Pipeline | Airflow, Python DAGs |
| API | Go, instrumented with Prometheus metrics |
| Frontend | TypeScript, React |
| Datastore | Postgres only; raw → staging → marts in SQL |
| Queue | SQS |
| Observability | Prometheus, Grafana, Loki |
| Infrastructure | Terraform on AWS |
| CI/CD | GitHub Actions; later ArgoCD |

## Triage agent

- Claude via the Anthropic API, triggered by an Alertmanager webhook to a small Python service.
- Strictly read-only. Tools: query Prometheus, query Loki, list recent deploys, read Airflow
  task state, search runbooks. It takes no remediation actions.
- Output: a Jira ticket with a root-cause suggestion, evidence, and a runbook link, plus a
  chat notification (Slack if a personal workspace exists, otherwise Discord).
- A monthly spend cap of a few dollars.
- Demoed with a fault-injection script: missing session in a timing CSV, changed BoP PDF
  layout, lap times outside plausible bounds, stalled stream, API latency spike. One scenario
  gets a written postmortem.

## Service levels

Alerts fire on these, not on raw resource usage.

1. API availability and latency.
2. Pipeline freshness: session data loaded within N hours of publication.
3. Data completeness: expected sessions and laps present.
4. Stream lag for the replayer.

## Infrastructure

- Docker Compose for local runs, including self-hosted Prometheus, Grafana, and Loki.
- AWS: one 4 GB instance at about $30/month, provisioned with Terraform.
- Grafana Cloud free tier for the always-on public dashboards and logs. Its current limits
  are not yet verified; check before stage 4.
- Postgres in a container with nightly dumps to S3 and a tested restore runbook.
- A purchased domain, with DNS and TLS managed in Terraform. Availability of a Trackside
  domain is not yet checked.
- k3s and ArgoCD as the final stage.

## Delivery

- One public monorepo: `api/`, `web/`, `pipelines/`, `agent/`, `infra/`, `docs/` (runbooks,
  postmortems, ADRs), plus the existing `landing/`.
- GitHub Actions: lint and unit tests per language, SQL transform tests against a Postgres
  service container, DAG import checks, `terraform plan` on pull requests, container image
  scan, deploy on merge to main.
- README with an architecture diagram, a short demo recording of an incident being triaged,
  and links to the app, Grafana, and Airflow.
- ADRs for the choices an interviewer is likely to question: Airflow, k3s, read-only agent.

## Stages

Each stage is shippable. The application can go in after stage 4.

1. **Calendar and stays.** Go API, React frontend, Postgres, on Docker Compose with
   Prometheus, Grafana, and Loki.
2. **Timing pipeline.** Airflow batch load of IMSA GTD and GT World Challenge America, the
   "what to watch" panel, data-quality alerts.
3. **Triage agent.** With the fault-injection scenarios.
4. **Cloud.** Terraform on AWS, GitHub Actions deploys.
5. **BoP parsing.** From the manual drop folder.
6. **Lap stream.** Replayer through SQS.
7. **Europe.** Calendar, stays, and classification for GT World Challenge Europe.
8. **Kubernetes.** k3s and ArgoCD.
