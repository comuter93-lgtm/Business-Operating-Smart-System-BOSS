# Employee access review, 15 November 2026

The owner reports oneboss.in is live and the requested role controls are missing. In this review the browser inspection timed out. Anonymous Python requests to the homepage, health, bootstrap status, current-user and inventory-location endpoints returned HTTP 403 with Cloudflare code 1010. These observations do not identify the deployed commit or the signed-in user's role.

## Behavior in the repository

Reviewed main at 2d70f63 and inventory-owner-controls at 81356bd. The latter adds warehouse scoping to reports and Docker web serving. It does not add a delegated admin role.

| User action | Current behavior | Required change |
| --- | --- | --- |
| Open Team as Owner | Employee creation, employee selector, access preview, action buttons and audit log | Make role and warehouse assignment editable here |
| Open Team as Employee | My Tasks view | Offer management only with explicitly delegated authority |
| Create employee | Employee code, PIN and language; preset inventory/task permissions | Choose named role and allowed warehouses during setup |
| Change an action | Each click submits the full access profile immediately | Show proposed changes and reconcile concurrent edits |
| Inspect warehouse, page or export access | Values visible; UI preserves them during action toggles | Expose authorized controls and verify server enforcement |
| Delegate administration | Employee-management endpoints require Owner | Define delegation scope, block self-escalation and preserve owner-only approvals |

Local verification: all three tests in backend/tests/test_phase1_security.py passed. Live employee creation, revocation, permission saves and cross-business isolation are unverified.

## Next production check

Compare the hosting laptop's deployed frontend and API revisions with GitHub. Inspect the signed-in account's role and Team screen. Use isolated test identities for changes. Acceptance example: an Owner grants a Warehouse A supervisor permission to assign a receiving clerk there. Verify the clerk can submit a receipt only for Warehouse A, cannot approve it or promote themselves, and loses access after revocation. Verify the audit log identifies the grantor and recipient.
