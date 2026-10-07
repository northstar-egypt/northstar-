# NorthStar threat model

Owner: security workstream. Partly written: authentication and sessions are designed in full
below; the sections under "To be written" are not done yet. Do not treat an empty section as
"nothing to do"; treat it as "not written yet."

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
4. **Credential compromise.** Mitigation: argon2id password hashes, short signed sessions in
   an HttpOnly cookie, forgery checks. Designed in full under "Authentication and sessions"
   below, including the gaps that are still open (rate limiting, early revocation).
5. **Malicious uploads.** Bulk import and document uploads. Mitigation: upload validation,
   type and size checks.

## Authentication and sessions

Built 2026-09-29. Code: `apps/api/app/security.py` (passwords, tokens), `apps/api/app/deps.py`
(reading the session, forgery check), `apps/api/app/routers/auth.py` (sign in, sign out,
`/me`). Tests: `apps/api/tests/test_auth.py` and the sign-in tests in `tests/e2e`.

### How it works

1. `POST /auth/login` takes an email and password. The password is checked against an
   **argon2id** hash (the current OWASP first choice). It is never stored or logged in plain
   text.
2. On success the API signs a token (a JWT, HS256) holding only the user id, issue time and an
   8 hour expiry, and sets it as a cookie that is **HttpOnly** (page scripts cannot read it),
   **SameSite=Lax**, and **Secure** everywhere except local development.
3. Every request re-checks the signature and the expiry, then loads the account **from the
   database**. Role, organization and whether the account is active come from there, never
   from the token, so deactivating an account or changing a role applies on the next request.
4. Scripts and tests can send the same token as `Authorization: Bearer` instead of a cookie.

### Threats and what stops them

| Threat | What stops it | Tested by |
| --- | --- | --- |
| A script injected into the page steals the session | The cookie is HttpOnly; nothing about the session is in localStorage | `test_the_session_cookie_is_invisible_to_page_scripts` (e2e) |
| Another website makes a signed-in user's browser change data (CSRF) | SameSite=Lax, plus every state-changing request with an `Origin` outside the web app's origins is refused with 403 | `test_a_cross_site_write_with_the_cookie_is_refused`, `test_a_cross_site_sign_in_is_refused` |
| Forged or altered token | HS256 signature with a server secret; the algorithm is pinned, so `alg: none` is refused | `test_an_altered_token_is_refused`, `test_an_unsigned_token_is_refused`, `test_a_token_naming_another_user_cannot_be_made_without_the_key` |
| The published development key used against a real deployment | Outside development the API refuses to start unless `JWT_SECRET` is set and at least 32 characters | `test_outside_development_a_weak_signing_key_stops_startup`, `test_a_token_signed_with_another_key_is_refused` |
| Finding out which emails have accounts | One message for wrong email, wrong password and deactivated account; a dummy hash check keeps the timing the same | `test_every_failed_sign_in_looks_the_same` |
| A stolen password database | argon2id, memory-hard; weaker hashes are upgraded at the next sign-in | `test_passwords_are_stored_as_argon2id`, `test_a_cheap_hash_is_upgraded_at_sign_in` |
| A departed staff member keeps access | The account is re-checked on every request | `test_deactivating_an_account_ends_its_session_at_once` |
| Oversized password used to make hashing expensive | Passwords over 1024 characters are refused before hashing | `test_an_oversized_password_is_refused_before_hashing` |
| Sign-ins nobody can account for | Every sign-in, failed sign-in (with the email tried, never the password) and sign-out is in the audit log | `test_sign_ins_are_audited_and_the_password_never_is` |

### Known gaps (open, and said out loud)

- **No rate limiting on sign-in.** Password guessing is slowed only by the cost of argon2.
  Next step: limit failed attempts per email and per address, and lock briefly after
  repeated failures.
- **A stolen token cannot be revoked early.** Signing out deletes the cookie, but a copy of
  the token stays valid until it expires (8 hours). Deactivating the account does stop it at
  once. A server-side session table would close this, at the cost of a lookup per request.
- **No password reset or change flow**, and no second factor. Accounts are created by the
  seed or by an admin.
- **Demo accounts.** Every synthetic account shares one published password
  (`northstar-demo`), listed on the login screen by the development-only `/dev/identities`.
  That is safe only because the data is synthetic and local. Never seed these accounts
  anywhere real.

## The profile summary (local language model)

The player profile carries a few sentences written by a local model (Ollama,
`apps/api/app/services/summary.py`). What could go wrong, and what stops it:

| Threat | What stops it | Tested by |
| --- | --- | --- |
| The summary tells a caller something the page hides from them, such as a flag | The model is given a fact sheet built from the profile after the role and consent filters, so it never sees what the caller may not; a reply that names any kind of flag the sheet does not hold is withheld | `test_a_player_reading_their_own_summary_gets_no_flags` |
| The model invents a number about a child | Every number in the reply, digits or words, must be on the fact sheet or a rounding of one; otherwise the whole summary is withheld and the page says so | `test_a_summary_with_an_invented_number_is_withheld`, `test_any_number_that_gets_through_is_on_the_sheet` |
| The model compares a child with others in words the check cannot test ("faster than most") | The sheet gives every comparison as a percentage; a reply that compares in words instead ("most", "above average", "out of", "top N%") is withheld | `test_a_comparison_in_words_is_caught`, `test_the_other_mistakes_the_model_made_are_caught` |
| The model says a flag is absent when it is open, or judges a child ("not impressive"), or forecasts something other than height | Each is withheld: the sheet never says a flag is absent, never judges, and forecasts only height | `test_the_other_mistakes_the_model_made_are_caught` |
| Finding out a hidden player exists through the summary endpoint | The same 404 as the profile, before the model is asked anything | `test_a_player_the_caller_may_not_see_is_404` |
| Player data leaving the machine | The model runs locally in docker-compose; no hosted LLM is called | (configuration: `OLLAMA_URL`) |

Known gaps. The checks prove that every number is on the sheet and that a set of known
mistakes is absent. They do not prove each sentence is true: a real number attached to the
wrong fact (the season rate given as the match rate) passes, and so does a wrong sentence that
trips no pattern. Every pattern above comes from a mistake the model made in an evaluation
where each reply was read against its sheet by hand; the PR that added this reports how many
shown summaries were still wrong on a sample the checks were not built from. The screen
labels the text as generated, and the reply is shown as plain text, never as HTML.

## Opponents and the table tennis rating

A table tennis match row names the other player (`performance_entry.opponent_player_id`), and
the profile rates each player from who they played (`apps/api/app/services/rating.py`, decision
0004). Opponents are often children. What could go wrong, and what stops it:

| Threat | What stops it | Tested by |
| --- | --- | --- |
| A profile reveals a child to someone who may not see that child | The opponent's name and profile link are sent only when the caller could open that opponent's own profile (`may_view`); otherwise the row says "a registered player". A player looking at their own record sees no opponent's name at all | `test_an_opponent_is_named_only_to_someone_who_may_open_their_profile` |
| Storing data about a child who never joined | An opponent who is not on the platform leaves nothing in the row: no name, no id, only the result | generator tests: `test_about_a_third_of_matches_are_against_outsiders` |
| Rating a child whose guardian withdrew analytics consent, or using their points to rate others | They get no rating, and every match involving them is left out of everyone's rating | `test_withdrawn_analytics_consent_takes_a_player_out_of_every_rating` |
| Faking strength by claiming wins over strong players | A self-submitted result counts only once the opponent logs the same match or it comes from a trusted source; until then it shows on the record, marked "not counted" | `test_an_unconfirmed_self_submitted_win_does_not_count` |
| A merged duplicate splits a person's record, or keeps an old spelling on screen | Matches against a merged record are attributed to the record it was merged into, under the current name | `test_a_match_against_a_merged_duplicate_belongs_to_the_surviving_record` |

Known gaps. An opponent's strength going into a month is sent even when their name is not,
because it is what makes a result readable and it does not say who they were. With very few
players in a gender and age band, a strength next to a date could narrow down who it was; at
national scale that is unlikely, but it has not been measured. Two players who both
self-submit the same invented match confirm each other; the planned mirrored-row fraud check
(decision 0004, open decision 3) is what would catch that.

## To be written

- Full data-flow diagram with trust boundaries.
- STRIDE pass per component.
- Minors' privacy safeguards in detail (consent enforcement, visibility rules, retention).
- Audit log integrity guarantees (append-only enforcement).
- Incident response notes.

