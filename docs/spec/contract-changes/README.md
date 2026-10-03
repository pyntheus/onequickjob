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
