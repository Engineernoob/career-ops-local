# STAR Story Bank

Accumulated interview stories across all evaluations.
Each story maps to one or more competencies.
When answering behavioral questions, pull from here — adapt, don't memorize.

---

## Story 001 — Microservices Migration

**Competencies:** Technical leadership, handling ambiguity, cross-team influence, system design

**S — Situation**
Our monolith had grown to 1.2M lines of code. 6 product teams were blocked from shipping independently — every change required coordination. P99 latency was 3.2s during peak traffic. Engineering morale was low.

**T — Task**
As the most senior IC on the infrastructure team, I was tasked with designing and leading a path out of the monolith. No deadline — just "do it without breaking production."

**A — Action**
I spent 2 weeks on discovery before writing a single line of code. Mapped every service boundary. Identified the safest first domain to extract (authentication — low traffic, clear interface). Wrote an ADR proposing strangler-fig pattern with traffic shadowing. Got buy-in from 6 team leads. Built a shared testing harness so each team could validate their domain before cutover. Ran 6-week sprints — one domain per sprint. Each team owned their migration.

**R — Result**
Migrated 100% of traffic in 8 months with zero downtime incidents. P99 latency dropped from 3.2s → 180ms. Teams went from monthly releases to weekly. ADR process I established was adopted org-wide — still used today.

**Tips**
- Lead with "I was responsible for the design" — not "we migrated"
- The discovery phase shows senior judgment ("I didn't just start coding")
- The team ownership framing shows leadership without authority

---

## Story 002 — Real-Time Pipeline

**Competencies:** Technical decision-making, ownership, delivering business impact

**S — Situation**
Enterprise customers were churning over stale analytics. Our nightly batch jobs meant dashboards were always 24 hours behind. Three customers cited this in their renewal calls.

**T — Task**
Design and build a real-time streaming pipeline with sub-5-second latency. Budget constraint: under $30k/year infra cost.

**A — Action**
Evaluated Kafka vs Kinesis vs Pulsar. Chose Kafka for ecosystem maturity and operational familiarity. Built Go consumers with sarama, implemented exactly-once semantics with idempotent producers. Chose ClickHouse for real-time OLAP (vs Redshift which couldn't handle our query patterns). Built a backfill system to replay 18 months of historical events without downtime. Wrote runbooks and alert playbooks before launch.

**R — Result**
Latency: 24 hours → 3 seconds. Pipeline handles 1M+ events/day at 99.95% uptime. Three enterprise customers renewed citing this feature. Infrastructure cost: $24k/year — 20% under budget.

**Tips**
- The budget constraint shows you think about business, not just tech
- "Three customers renewed" is the business impact — lead with it
- Mention the backfill system — it shows you thought about the full picture

---

## Story 003 — Cost Reduction

**Competencies:** Business impact, initiative, stakeholder communication

**S — Situation**
AWS bills hit $400k/month — 3x growth in 18 months. Engineering leadership received a board mandate to cut costs. No team wanted to own it.

**T — Task**
I volunteered to lead the cost optimization initiative. Target: $100k+/month savings without performance regression.

**A — Action**
Built a custom cost attribution system to map spend to teams and features (existing tools couldn't do this at our granularity). Found three main opportunities: over-provisioned ECS tasks (switched to Fargate Spot — 70% cost reduction for batch workloads), idle Elasticsearch clusters (migrated to OpenSearch Serverless), data transfer costs (CloudFront caching cut egress 40%). Presented findings to each team as opportunities, not mandates. Executed over 10 weeks.

**R — Result**
Monthly AWS spend: $400k → $280k. Annual savings: $1.44M. Zero performance regressions across 6 teams. Presented to the board. Process I built is now quarterly standard practice.

**Tips**
- "I volunteered" is a leadership signal — no one else wanted it
- The attribution system shows you diagnosed before you cut
- Frame it as "opportunities I brought to teams" not "cuts I forced"
