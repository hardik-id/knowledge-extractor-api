---
document_type: "report"
topic: "Engineering"
sensitivity: "internal"
summary: "Engineering decisions of 2026 in full: nine decision records with context, decision, consequences and the review notes that came with them."
keywords:
  - "engineering"
  - "architecture"
  - "decisions"
related_documents:
  - "Platform ADRs.pdf"
---

# Engineering decision log 2026

_Source: SharePoint · Engineering / Architecture · last modified 18 November 2026_

This log holds every architecture decision record of the year, in the order the decisions were made. Each record has a status, a date and the people who approved it. Older records are kept even when a later one replaces them.

## ADR-201: Adopt a shared message queue for order events

**Status:** Accepted
**Date:** 3 March 2026
**Approved by:** N. Okafor, J. Lindqvist

### Context

Order events were sent by direct calls between four services, and a slow service held up checkout for everyone.

The working group met four times and read the incident notes from the last two quarters before writing this record. Most of the discussion was about who would carry the cost of the change and how long the old and new ways would have to run side by side.

### Decision

Order events go through one shared queue. Each service reads its own copy and acknowledges when done.

We compared three options. The first was to leave things as they are, which costs nothing now but repeats the problems we have already seen. The second was a small change that fixes the most common case. The third was the change described below, which is larger but removes the cause.

### Consequences

- Teams plan the change in their next planning round
- The platform group reports on progress each month
- A review is held six months after the change

### Review notes

The people who run the affected services were asked for their view before the decision was written down. Their questions were about training, about the order of the rollout and about who is called when something breaks during the change. A short trial ran for two weeks on one team's services. The numbers from the trial were within ten percent of what we expected, and no incident was caused by the change itself.

## ADR-202: Keep the monthly release train

**Status:** Rejected
**Date:** 17 March 2026
**Approved by:** N. Okafor

### Context

Teams asked to release when ready, because the fixed monthly date made small fixes wait for weeks.

We compared three options. The first was to leave things as they are, which costs nothing now but repeats the problems we have already seen. The second was a small change that fixes the most common case. The third was the change described below, which is larger but removes the cause.

### Decision

We keep the monthly release train. Urgent fixes use a separate, documented hot-fix path.

The people who run the affected services were asked for their view before the decision was written down. Their questions were about training, about the order of the rollout and about who is called when something breaks during the change.

### Consequences

- Teams plan the change in their next planning round
- The platform group reports on progress each month
- A review is held six months after the change

### Review notes

A short trial ran for two weeks on one team's services. The numbers from the trial were within ten percent of what we expected, and no incident was caused by the change itself. The working group met four times and read the incident notes from the last two quarters before writing this record. Most of the discussion was about who would carry the cost of the change and how long the old and new ways would have to run side by side.

## ADR-203: Store uploaded files in object storage

**Status:** Accepted
**Date:** 2 April 2026
**Approved by:** J. Lindqvist, M. Duarte

### Context

Uploads filled the application servers' disks twice and slowed down backups.

The people who run the affected services were asked for their view before the decision was written down. Their questions were about training, about the order of the rollout and about who is called when something breaks during the change.

### Decision

Uploads are written to object storage and the database keeps only the file's address.

A short trial ran for two weeks on one team's services. The numbers from the trial were within ten percent of what we expected, and no incident was caused by the change itself.

### Consequences

- Teams plan the change in their next planning round
- The platform group reports on progress each month
- A review is held six months after the change

### Review notes

The working group met four times and read the incident notes from the last two quarters before writing this record. Most of the discussion was about who would carry the cost of the change and how long the old and new ways would have to run side by side. We compared three options. The first was to leave things as they are, which costs nothing now but repeats the problems we have already seen. The second was a small change that fixes the most common case. The third was the change described below, which is larger but removes the cause.

## ADR-204: Use one logging format across services

**Status:** Accepted
**Date:** 21 April 2026
**Approved by:** M. Duarte

### Context

Searching logs meant knowing four formats, and incident reviews lost time on translating them.

A short trial ran for two weeks on one team's services. The numbers from the trial were within ten percent of what we expected, and no incident was caused by the change itself.

### Decision

Every service writes one JSON line per event with the same five base fields.

The working group met four times and read the incident notes from the last two quarters before writing this record. Most of the discussion was about who would carry the cost of the change and how long the old and new ways would have to run side by side.

### Consequences

- Teams plan the change in their next planning round
- The platform group reports on progress each month
- A review is held six months after the change

### Review notes

We compared three options. The first was to leave things as they are, which costs nothing now but repeats the problems we have already seen. The second was a small change that fixes the most common case. The third was the change described below, which is larger but removes the cause. The people who run the affected services were asked for their view before the decision was written down. Their questions were about training, about the order of the rollout and about who is called when something breaks during the change.

## ADR-205: Retire the nightly export job

**Status:** Superseded
**Date:** 6 May 2026
**Approved by:** A. Tanaka

### Context

The nightly export locked tables for twenty minutes and customers saw stale numbers each morning.

The working group met four times and read the incident notes from the last two quarters before writing this record. Most of the discussion was about who would carry the cost of the change and how long the old and new ways would have to run side by side.

### Decision

The export job is replaced by a continuous feed. The old job stays until the feed covers every report.

We compared three options. The first was to leave things as they are, which costs nothing now but repeats the problems we have already seen. The second was a small change that fixes the most common case. The third was the change described below, which is larger but removes the cause.

### Consequences

- Teams plan the change in their next planning round
- The platform group reports on progress each month
- A review is held six months after the change

### Review notes

The people who run the affected services were asked for their view before the decision was written down. Their questions were about training, about the order of the rollout and about who is called when something breaks during the change. A short trial ran for two weeks on one team's services. The numbers from the trial were within ten percent of what we expected, and no incident was caused by the change itself.

## ADR-206: Require a second reviewer for database changes

**Status:** Accepted
**Date:** 19 May 2026
**Approved by:** A. Tanaka, N. Okafor

### Context

Two schema changes this spring dropped a column that another team still read.

We compared three options. The first was to leave things as they are, which costs nothing now but repeats the problems we have already seen. The second was a small change that fixes the most common case. The third was the change described below, which is larger but removes the cause.

### Decision

A database change needs a second reviewer from the team that owns the affected table.

The people who run the affected services were asked for their view before the decision was written down. Their questions were about training, about the order of the rollout and about who is called when something breaks during the change.

### Consequences

- Teams plan the change in their next planning round
- The platform group reports on progress each month
- A review is held six months after the change

### Review notes

A short trial ran for two weeks on one team's services. The numbers from the trial were within ten percent of what we expected, and no incident was caused by the change itself. The working group met four times and read the incident notes from the last two quarters before writing this record. Most of the discussion was about who would carry the cost of the change and how long the old and new ways would have to run side by side.

## ADR-207: Move the search index to a managed service

**Status:** Proposed
**Date:** 2 June 2026

### Context

Running the search cluster by hand takes about one engineer day each week, mostly for upgrades.

The people who run the affected services were asked for their view before the decision was written down. Their questions were about training, about the order of the rollout and about who is called when something breaks during the change.

### Decision

Move the index to a managed service after a four week trial on the reporting data.

A short trial ran for two weeks on one team's services. The numbers from the trial were within ten percent of what we expected, and no incident was caused by the change itself.

### Consequences

- Teams plan the change in their next planning round
- The platform group reports on progress each month
- A review is held six months after the change

### Review notes

The working group met four times and read the incident notes from the last two quarters before writing this record. Most of the discussion was about who would carry the cost of the change and how long the old and new ways would have to run side by side. We compared three options. The first was to leave things as they are, which costs nothing now but repeats the problems we have already seen. The second was a small change that fixes the most common case. The third was the change described below, which is larger but removes the cause.

## ADR-208: Cache product pages at the edge

**Status:** Accepted
**Date:** 16 June 2026
**Approved by:** J. Lindqvist

### Context

Product pages are read about two hundred times for each change, and the origin servers peak every evening.

A short trial ran for two weeks on one team's services. The numbers from the trial were within ten percent of what we expected, and no incident was caused by the change itself.

### Decision

Product pages are cached at the edge for five minutes and cleared when a product changes.

The working group met four times and read the incident notes from the last two quarters before writing this record. Most of the discussion was about who would carry the cost of the change and how long the old and new ways would have to run side by side.

### Consequences

- Teams plan the change in their next planning round
- The platform group reports on progress each month
- A review is held six months after the change

### Review notes

We compared three options. The first was to leave things as they are, which costs nothing now but repeats the problems we have already seen. The second was a small change that fixes the most common case. The third was the change described below, which is larger but removes the cause. The people who run the affected services were asked for their view before the decision was written down. Their questions were about training, about the order of the rollout and about who is called when something breaks during the change.

## ADR-209: Limit the size of API request bodies

**Status:** Accepted
**Date:** 30 June 2026
**Approved by:** M. Duarte, A. Tanaka

### Context

One client sent bodies of several hundred megabytes and starved the other clients.

The working group met four times and read the incident notes from the last two quarters before writing this record. Most of the discussion was about who would carry the cost of the change and how long the old and new ways would have to run side by side.

### Decision

Request bodies are limited to ten megabytes. Larger uploads use the upload path.

We compared three options. The first was to leave things as they are, which costs nothing now but repeats the problems we have already seen. The second was a small change that fixes the most common case. The third was the change described below, which is larger but removes the cause.

### Consequences

- Teams plan the change in their next planning round
- The platform group reports on progress each month
- A review is held six months after the change

### Review notes

The people who run the affected services were asked for their view before the decision was written down. Their questions were about training, about the order of the rollout and about who is called when something breaks during the change. A short trial ran for two weeks on one team's services. The numbers from the trial were within ten percent of what we expected, and no incident was caused by the change itself.
