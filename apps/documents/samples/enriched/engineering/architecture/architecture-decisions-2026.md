---
document_type: "reference"
topic: "Engineering"
sensitivity: "internal"
summary: "Architecture decisions 2026 sets out how Engineering work is requested and approved. Managers approve within 5 working days."
keywords:
  - "engineering"
  - "reference"
  - "approval"
  - "self-service"
related_documents:
  - "Platform ADRs.pptx"
---

# Architecture decisions 2026

_Source: Confluence · Engineering / Architecture · last modified 3 November 2026_

This log holds the architecture decisions of the platform group.

## ADR-012: Use Postgres for the orders service

**Status:** Accepted
**Date:** 3 November 2026
**Approved by:** J. Smit, A. de Vries

### Context

The orders service needs transactions across several tables, and the team already runs Postgres for billing.

### Decision

We store orders in Postgres and drop the document store pilot.

### Consequences

- One database engine to operate 🚀
- Schema changes need migrations
- Reporting can query orders directly

## ADR-013: Adopt OpenTelemetry for tracing

**Status:** Proposed
**Date:** 10 November 2026

### Context

Each service logs traces in its own format, which makes incidents slow to follow.

### Decision

All services emit OpenTelemetry traces to the shared collector.

### Consequences

- Services need the SDK added
- Vendor lock-in is reduced

## ADR-014: Retire the legacy SOAP gateway

**Status:** Superseded
**Date:** 2026-09-14
**Approved by:** M. Jansen

### Context

The SOAP gateway has two remaining clients and no owner.

### Decision

The gateway is replaced by the REST API and switched off in March.

### Consequences

- The two clients must migrate first
- The gateway runbook is archived
