# NorthStar threat model (placeholder)

Owner: security workstream. This is a stub to be filled in. It exists so the structure and
the highest-priority concerns are visible from day one. Do not treat the empty sections as
"nothing to do"; treat them as "not written yet."

## Why this matters here

NorthStar holds data about athletes, many of them minors, and exposes it to scouts and
federations. The data has real-world value (talent is money) and real-world sensitivity
(children's records). That combination makes both fraud and privacy first-order concerns,
not compliance checkboxes.

## Assets to protect

- Player personal data, especially minors' identities and biometrics.
- Integrity of performance data (self-submitted data is a fraud surface).
- Account credentials and session tokens.
- The audit log (must stay trustworthy and append-only).

## Actors and roles

- coach, scout, federation, player, admin. Each has a different legitimate scope. See the
  User table in [schema.md](schema.md).

## Top threats (to expand)

1. **Broken access control.** A scout reading a minor's profile without consent, or a coach
   editing players outside their org. Mitigation: RBAC enforced in the API, consent checks
   before exposing minors. Every RBAC case is a test that must pass.
2. **Self-submission fraud.** Players inflating their own stats. Mitigation: anomaly-based
   fraud detection (crosses over with the ML workstream), validation on ingest, audit trail.
3. **Duplicate / spoofed identities.** Mitigation: duplicate detection, canonical player
   records with merge tracking.
4. **Credential compromise.** Mitigation: hashed passwords, JWT/session handling, TODO on
   the specifics (library, rotation, rate limiting).
5. **Malicious uploads.** Bulk import and document uploads. Mitigation: upload validation,
   type and size checks.

## To be written

- Full data-flow diagram with trust boundaries.
- STRIDE pass per component.
- Minors' privacy safeguards in detail (consent enforcement, visibility rules, retention).
- Auth design (library, token lifetime, refresh, rate limiting).
- Audit log integrity guarantees (append-only enforcement).
- Incident response notes.

TODO: security workstream to flesh this out before auth implementation begins.
