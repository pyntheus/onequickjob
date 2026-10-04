# Contract changes

Lanes don't edit files they don't own (`docs/spec/lanes.md`). When you need a change to a
shared model, repository, service, endpoint or doc, write a request in your lane's file here
(`L1.md`, `L2.md`, `L3.md`) and work around it with an additive change inside your own
package if you can. Integration (I) resolves every request.

Each request:

    ## <short title>
    - What: the exact change (file, field, function, endpoint).
    - Why: the screen or rule that needs it.
    - Workaround now: what you did inside your own package meanwhile.
    - Breaking? yes/no, and who else is affected.

Session S (shared fixes, after the three lanes) marked every request with a **Status** line:
resolved, with the commit on `s/shared-fixes` that did it, or declined, with the reason. New
requests go below them in the same format.

**Closed by integration (I).** Every request is resolved or deferred, with its reason (a
**Status (session I)** line where I changed or confirmed S's verdict). With the lanes finished,
ownership works by area (`lanes.md`); this folder is the record, and the format to reuse if
sessions run in parallel again.
