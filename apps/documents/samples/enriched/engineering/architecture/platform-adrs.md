---
document_type: "presentation"
topic: "Engineering"
sensitivity: "internal"
summary: "Platform ADRs sets out how Engineering work is requested and approved. Managers approve within 5 working days."
keywords:
  - "engineering"
  - "presentation"
  - "approval"
  - "self-service"
related_documents:
  - "Architecture decisions 2026.pdf"
---

# Platform ADRs

_Source: SharePoint · Engineering / Architecture · last modified 27 October 2026_

## ADR-101: Use feature flags for risky releases

**Status:** Accepted
**Date:** 1 October 2026
**Approved by:** P. Bakker

### Context

Releases of the checkout flow caused two rollbacks this quarter.

### Decision

Risky changes ship behind a flag and are enabled per customer group.

### Consequences

- Flags need an owner and an expiry date
- Test runs cover both settings

## ADR-102: Move build agents to spot instances

**Status:** Rejected
**Date:** 12 October 2026
**Approved by:** P. Bakker, L. Visser

### Context

Build costs grew by 40% since spring.

### Decision

We keep on-demand agents because interrupted builds cost more than they save.

### Consequences

- Cost review stays on the agenda

## ADR-103: Standardise on TypeScript for new services

**Status:** Proposed
**Date:** 20 October 2026

### Context

New services use three languages, which splits the on-call pool.

### Decision

New services are written in TypeScript unless a review agrees otherwise.

### Consequences

- Existing services stay as they are
- A starter template is needed
