---
document_type: "runbook"
topic: "Engineering"
sensitivity: "internal"
summary: "Operations skills describes four routine tasks of the platform team, each with when to use it, what is needed first and the steps."
keywords:
  - "engineering"
  - "operations"
  - "skills"
  - "runbook"
related_documents:
  - "Incident runbook.md"
---

# Operations skills

_Source: Confluence · Engineering / Operations · last modified 12 November 2026_

The platform team keeps these tasks short and repeatable, so that anyone on call can do them without waiting for a colleague. Each one has been run in production at least twice.

## Skill: Restart the orders service

**Name:** Restart the orders service
**Description:** Restarts the orders service without losing queued orders, for when it stops answering.

### When to use

- The orders health check fails for more than five minutes
- Orders pile up in the queue and nothing is processed

### Prerequisites

- Access to the production cluster
- The on-call role for the current week

### Steps

1. Pause the order intake in the admin console.
2. Wait until the queue has stopped growing.
3. Restart the orders deployment with the cluster tool.
4. Check that the health check is green.
5. Resume the order intake.

## Skill: Rotate the payment API key

**Name:** Rotate the payment API key
**Description:** Replaces the key used to talk to the payment provider before it expires.

### When to use

- The key expires within 14 days
- The key may have been exposed

### Prerequisites

- Admin access to the payment provider portal
- Write access to the secrets vault

### Steps

1. Create a new key in the provider portal.
2. Store the new key in the secrets vault under a new version.
3. Redeploy the checkout service so that it reads the new version.
4. Make one test payment.
5. Revoke the old key in the provider portal.

## Skill: Restore a database from backup

**Name:** Restore a database from backup
**Description:** Brings a database back to the state of the last nightly backup.

### When to use

- Data was deleted or changed by mistake
- A migration left the database in a broken state

### Prerequisites

- Approval from the data owner
- A free restore server

### Steps

1. Pick the backup you need from the backup list.
2. Restore it to the restore server, never over the live database.
3. Compare the row counts of the main tables with the live database.
4. Copy back only the rows that are missing.

## Skill: Add a new engineer to the on-call rota

**Name:** Add a new engineer to the on-call rota
**Description:** Puts a new engineer on the rota after their first month.

### When to use

- A new engineer has finished onboarding

### Prerequisites

- Agreement of the team lead
- A completed shadow shift

### Steps

1. Add the engineer to the paging tool.
2. Add them to the rota, starting in the next full week.
3. Send them the incident runbook.
