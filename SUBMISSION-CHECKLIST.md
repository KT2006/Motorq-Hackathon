# Final Hackathon Submission Checklist

This is the **single completion checklist** for the project. It supersedes the
original day-by-day runbook in [`plan.md`](plan.md), whose checklist is a
planning draft, not a current status report. Work through these phases in
order. A phase is complete only when its acceptance checks pass and its
evidence exists in the repository or submission package.

The brief's numeric targets are acceptance criteria, not claims to copy into
the report. If a target fails, keep improving the implementation and rerun it;
do not present an unmeasured target as achieved. Use synthetic data only.

## Phase 1 — Baseline and requirement traceability

- [x] Create a requirement matrix from the problem statement and every section
  of the solution-document template. For each requirement, record its
  implementation path, acceptance test, evidence file, and status.
- [x] Freeze the benchmark environment and demo scope: hardware, Docker
  resources, seed size, dates, timezone, API ranges, and exact startup command.
- [x] Reconcile all conflicting project figures (vehicle counts, event counts,
  date ranges, costs, throughput, latency, coverage, and failure rates) against
  reproducible runs. Remove or relabel stale/unverified numbers in the README
  and docs.
- [x] Review the current commit and worktree. Keep real credentials, generated
  personal data, and local-only files out of Git; retain only synthetic
  datasets intended for submission.
- [x] Agree on one canonical implementation for seeding, segmentation, cost
  rollup, API schemas, and benchmark reporting. Record any intentionally
  simplified demo path rather than describing it as production behavior.

**Exit gate:** every official requirement has an explicit pass condition and
evidence destination; there are no contradictory claims in the project docs.

## Phase 2 — Make the judge's end-to-end journey dependable

- [ ] On a clean clone, follow the README exactly: copy `.env.example`, set
  required values, and start the complete stack with the documented Compose
  command. Confirm health checks, service readiness, seed completion, and
  useful failure logs.
- [x] Make startup deterministic: the dashboard must not be considered ready
  before the API and its required seed data are ready. Confirm restart and
  re-seed behavior does not silently duplicate or corrupt data.
- [x] Use the canonical segmentation and cost-engine code from the seeder;
  remove or reconcile the current simplified duplicate implementations.
- [x] Align seeded dates with the dashboard's default query dates. Use a
  configurable reporting period or derive it from available data; verify empty
  ranges show a clear empty state, not misleading zeroes or broken charts.
- [ ] Verify browser-to-API routing with the Compose Nginx proxy and confirm
  the token, summary, offender, vehicle-cost, live-status, and chat requests
  return expected status codes and response shapes.
- [x] Fix the vehicle drill-down identity flow: preserve or retrieve the VIN
  from the vehicle UUID so clicking a leaderboard row can also load live
  status. Test both a vehicle with live data and one without it.
- [ ] Verify overview → offender leaderboard → vehicle detail → live status →
  AI assistant in a real browser using seeded data. Check responsive layout,
  loading/error/empty states, currency/date labels, console errors, and
  refresh/deep-link behavior.
- [ ] Add an automated smoke test for that critical flow, including login and
  at least one assertion against a known seeded result.

**Exit gate:** a reviewer can start the stack from a clean clone and complete
the full product journey without manual database fixes or unexplained errors.

## Phase 3 — Meet the data, streaming, and scale expectations

- [ ] Make bulk and streaming modes first-class, runnable paths. The normal demo
  must show a continuous stream reaching Redpanda, the consumer, PostgreSQL,
  Redis, and a visible dashboard/API result—not only a one-time sample publish.
- [ ] Generate and validate a reproducible **100,000+ vehicle** synthetic
  dataset with plausible trips, idling, fuel types, faults, GPS noise, bursts,
  duplicate messages, and out-of-order delivery. Record generation time,
  dataset size, and loaded row counts.
- [x] Verify event schema validation and evolution. Malformed events must be
  observable and recoverable (for example via a dead-letter path); do not
  silently drop them and then claim lossless processing.
- [ ] Verify idempotency and ordering end to end: replay duplicates, deliver
  out-of-order messages, interrupt the consumer, restart it, and prove no
  committed event is lost or double-counted. Ensure offset commits and Redis
  side effects have an explicitly tested failure/retry policy.
- [ ] Demonstrate back-pressure and recovery: report consumer lag during a
  burst, stop/restart a broker or consumer, and show that lag drains and
  persisted data reconciles.
- [ ] Run a reproducible performance test on a stated benchmark environment
  against the brief's **100,000 events/second** target and **3× burst for five
  minutes without data loss**. Capture offered and accepted event rates,
  p95/p99 ingest-to-dashboard and API latency, error counts, consumer lag, and
  post-test reconciliation. Provision a capable test environment if a laptop
  cannot meet the target; do not substitute a rate-limit test for a successful
  throughput test.
- [x] Test data partitioning and scale behavior for telemetry; document
  partition/shard keys, hot/warm/cold retention, storage estimates, and the
  cost assumptions. Add the implementation needed to meet the chosen
  partitioning design rather than describing a hypothetical partition.
- [x] Keep PostgreSQL, Redis, Redpanda, and the no-vector-store decision
  justified by their actual roles and tested failure/consistency behavior.

**Exit gate:** the synthetic scale dataset exists, the streaming pipeline is
demonstrated, and benchmark results either meet the specified targets or the
project is explicitly not ready to claim 100% completion.

## Phase 4 — Correctness, product value, and secure access

- [x] Validate segmentation and cost calculations against hand-checkable
  examples and independent SQL/data checks. Test short/noisy stops, long idles,
  missing markers, midnight boundaries, duplicate events, and multiple fuel
  types. Ensure trips, idle events, and daily rollups reconcile.
- [x] Use cited regional fuel prices and idle-burn assumptions. Clearly label
  synthetic estimates, dates, units, and assumptions in the UI and solution
  document. Prove the displayed idle-cost result can be traced to source
  telemetry and a calculation.
- [x] Prove the weighted offender ranking beats or adds useful signal beyond a
  clearly defined naive baseline on reproducible sample data. Explain score
  normalization and weights; show at least one case where the rankings differ.
- [x] Make the AI assistant strictly use bounded, read-only tools; validate
  tool arguments and output; cap tool calls and latency; handle unavailable
  LLMs and invalid model output safely; and audit requests, tool calls,
  outcomes, and actor identity.
- [ ] Evaluate the AI against a small fixed set of fleet questions. Check that
  answers cite retrieved values, do not invent metrics when data is missing,
  and produce actionable recommendations. Report pass criteria and failures.
- [ ] Remove production-default JWT secrets and prevent demo passwords or API
  keys from being embedded in public JavaScript. Use an actual login/auth
  flow; hash credentials server-side and rotate secrets through environment
  configuration or a secret manager.
- [ ] Implement and test authorization boundaries, including fleet/tenant
  isolation, not merely valid-JWT authentication. Add negative tests for
  cross-tenant reads and unauthorized access.
- [x] Document and implement the scoped security controls required by the
  brief: TLS in transit, mTLS for device/broker ingress where applicable,
  encryption at rest, secret handling, rate limits, input validation, and
  OWASP API risks. Avoid wildcard CORS in the submission deployment.
- [x] Make audit logging cover sensitive data access as well as AI actions.
  Define location masking, retention, and deletion/right-to-erasure behavior;
  test the deletion path on synthetic records.
- [ ] Resolve and rerun the image/dependency security scan. Do not dismiss
  findings as base-image-only without recording current severity, remediation,
  and accepted residual risk.

**Exit gate:** calculations are independently checkable, recommendations are
grounded, access boundaries have negative tests, and security claims match
implemented controls.

## Phase 5 — Automated tests, reliability, and benchmark evidence

- [ ] Raise test coverage for the core services and algorithms to the brief's
  **80%+** target. Measure coverage on production modules; do not count copied
  test-only logic as coverage of the production implementation.
- [ ] Run unit, database/cache/broker integration, API contract, acceptance,
  and end-to-end smoke tests automatically in CI on every pull request and
  push. Ensure CI fails on a failing test, lint error, build error, or
  configured critical security finding.
- [ ] Add edge/failure tests for duplicate and malformed events, out-of-order
  delivery, broker/database/cache outage, consumer restart, seed retry,
  expired/invalid tokens, rate limiting, date boundaries, tenant isolation,
  and AI/tool failures.
- [ ] Run separate, reproducible tests for normal successful load, the target
  burst, a soak run, and intentional rate-limit behavior. Report p50/p95/p99,
  success/error counts, throughput, and lag; label the purpose of each run.
- [ ] Run a security scan (dependencies and container; add static/dynamic
  checks) and a failure-recovery/chaos test. Archive commands, versions,
  environment, raw output, and concise findings under `docs/evidence/`.
- [ ] Capture an observability screenshot showing throughput, consumer lag,
  error rate, and latency percentiles. Add a short troubleshooting walkthrough
  that traces one latency spike from metric to logs/root cause.
- [ ] Ensure all evidence is reproducible from documented commands, with no
  secrets in logs or artifacts.

**Exit gate:** CI is green; required coverage and performance targets are
measured; failure behavior and security scan are evidenced, not asserted.

## Phase 6 — Architecture, deployment, and repository readiness

- [x] Update the README with the actual architecture, prerequisites, exact
  Compose instructions, environment variables, URLs, health checks, demo
  credentials policy, tests, limitations, benchmark hardware/results, and
  troubleshooting steps. Fix incorrect health URLs and stale scale claims.
- [x] Keep the OpenAPI file in sync with the running API, including auth,
  status/error responses, pagination, rate limits, and examples. Document
  event topic, key, schema, and evolution contract.
- [x] Finish accurate architecture artifacts: C4 context/container view,
  event-to-insight latency/data-flow, ER diagram and 3NF notes, deployment
  topology, two key sequence diagrams (including failure), and core-service
  layer boundaries.
- [ ] Re-run SQL `EXPLAIN ANALYZE` on the actual three hottest queries before
  and after each optimization. Save raw plans and honestly compare the same
  dataset/environment. Remove claims that keyset pagination or an index is
  implemented unless code and plans prove it.
- [x] Complete 3–5 ADRs with context, alternatives, decision, and consequences;
  include storage/CAP/PACELC, messaging/replay, idempotency, scoring, and the
  vector-store decision as applicable.
- [ ] Validate the Kubernetes/Helm deployment and Terraform for the selected
  cloud in a safe test environment. Document which infrastructure is actually
  deployed, how secrets and networking are configured, and what remains a
  local-only path. Include frontend and dependencies, not just an API
  deployment manifest.
- [x] Verify horizontal scaling and availability claims; either demonstrate
  replicas/failover or describe the prototype's single points of failure
  without claiming the 99.9% target.
- [x] Add an SBOM or dependency/license inventory and make sure all Dockerfiles,
  test data, docs, and service folders required to reproduce the submission
  are present.
- [x] Keep local `.env`, generated noise, caches, and unrelated artifacts out
  of the submitted repository; verify `.env.example` is complete but contains
  placeholders only.

**Exit gate:** the repository accurately explains, builds, tests, and deploys
the submitted system; diagrams, API contract, query plans, and implementation
agree.

## Phase 7 — Complete the official solution document and demo

- [ ] Fill every part of the provided solution template (sections 1–17):
  executive summary; validated problem and assumptions; impact metrics;
  user journey/screenshots; value proposition and innovation evidence;
  feature/status table; architecture and data capacity; low-level design and
  complexity; measured NFRs; security/compliance; test strategy; observability;
  AI purpose/design/evaluation; ADRs/risks/next steps; demo link; repository
  checklist; conclusion; AI/open-source/data declarations; references.
- [ ] Include a feature matrix linking every feature to its user story,
  implementation path, test/evidence, status, and demo-video timestamp.
- [ ] Attach real product screenshots, observability screenshot, actual
  benchmark plots/tables, coverage output, security scan summary, SQL plans,
  diagrams, citations for assumptions, and accurate deployment evidence.
- [ ] Clearly distinguish facts, assumptions, synthetic results, local
  measurements, cloud measurements, targets, and future work. Do not claim
  interviews, production data, measured 100K scale, or deployed cloud
  infrastructure unless actually completed.
- [ ] Export the solution document to the required final format (PDF), review
  every page for readable diagrams, complete fields, working links, and
  spelling/formatting.
- [ ] Record and review a **≤5-minute** demo: problem and user (brief), working
  dashboard with real seeded results, drill-down/live stream, grounded AI
  recommendation with tool trace, architecture/trade-offs, and measured
  evidence. Show the actual submitted build, not mock screens.
- [ ] Make the demo link accessible to reviewers and confirm playback without
  requiring team credentials.

**Exit gate:** the PDF and video are final, accessible, and consistent with the
actual code and benchmark artifacts.

## Phase 8 — Final release and submission lock

- [ ] Start from a fresh clone or clean machine and follow only the README.
  Re-run Compose startup, smoke flow, CI test commands, frontend build, and
  release checks. Record the result.
- [ ] Check every box in this document; resolve every blocker and remove all
  knowingly stale, contradictory, or unsupported claims.
- [ ] Review Git status, ignore rules, commit history for accidental secrets,
  repository links, document/video permissions, and final submission forms.
- [ ] Commit all intended final source and evidence; create and push the
  required `v1.0-submission` tag on that exact commit.
- [ ] Confirm the GitHub repository, solution PDF, demo video, CI results, and
  tag are visible and accessible from a reviewer account.
- [ ] Submit those exact links/files. After submission, make no untracked code
  or evidence changes; if a correction is necessary, re-run the release gate
  and update the submitted commit/tag consistently.

## Definition of done

The work is over only when every checkbox above passes, every numeric target
is supported by reproducible evidence, the official solution PDF and demo are
accessible, CI is green, and `v1.0-submission` identifies the exact submitted
commit. A box with no evidence is not complete.
