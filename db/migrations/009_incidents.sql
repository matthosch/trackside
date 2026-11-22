-- The triage agent's own records. One incident per Alertmanager alert group from
-- the time it starts firing until it resolves; one agent run per investigation.

CREATE TABLE ops.incidents (
    id           bigserial PRIMARY KEY,
    group_key    text NOT NULL,                 -- Alertmanager's groupKey
    alertname    text NOT NULL,
    labels       jsonb NOT NULL,                -- the group's common labels
    status       text NOT NULL DEFAULT 'firing' CHECK (status IN ('firing', 'resolved')),
    started_at   timestamptz NOT NULL DEFAULT now(),
    resolved_at  timestamptz,
    ticket_url   text,
    chat_sent    boolean NOT NULL DEFAULT false,
    report       jsonb
);

-- At most one open incident per alert group; a group that fires again after
-- resolving opens a new incident.
CREATE UNIQUE INDEX incidents_one_open_per_group ON ops.incidents (group_key) WHERE status = 'firing';

CREATE TABLE ops.agent_runs (
    id                 bigserial PRIMARY KEY,
    incident_id        bigint NOT NULL REFERENCES ops.incidents (id) ON DELETE CASCADE,
    started_at         timestamptz NOT NULL DEFAULT now(),
    duration_s         real,
    mode               text NOT NULL CHECK (mode IN ('agent', 'fallback')),
    outcome            text NOT NULL,          -- ok | no_api_key | over_budget | api_error | ...
    model              text,
    tool_calls         integer NOT NULL DEFAULT 0,
    input_tokens       integer NOT NULL DEFAULT 0,
    output_tokens      integer NOT NULL DEFAULT 0,
    cache_read_tokens  integer NOT NULL DEFAULT 0,
    cache_write_tokens integer NOT NULL DEFAULT 0,
    cost_usd           numeric(10, 4) NOT NULL DEFAULT 0
);

CREATE INDEX agent_runs_started_at ON ops.agent_runs (started_at);
