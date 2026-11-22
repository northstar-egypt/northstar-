# 0011. Diaspora tier: players abroad are submitted, then verified by the federation

Status: first version built 2026-11-22 (see "What the build decided" at the end). Questions 1,
2 and 4 were answered on 2026-11-22, the proposed option each time; the build settled question
3. Not done yet: grading the checks on planted submissions (section 5).
Date: 2026-11-22

## Context

The diaspora tier is Egypt-eligible players in foreign leagues. Today it is only a tier value
on synthetic players (`docs/project-status.md`, "Where each data source stands"). It has no
outside source: Transfermarkt's terms forbid scraping, and FootyStats covers leagues, not who
is eligible for Egypt. The project status lists "a manual entry form with a source link" as one
way forward. The team plan settles on it:

> Diaspora tier submissions: a player, guardian or scout submits an Egypt-eligible player
> abroad; the federation verifies it in a queue, with duplicate and fraud checks on arrival.

What the platform already has that this builds on:

- **Players and consent.** `POST /players` will not add a player without the sign-up consent
  form, signed by a named guardian for a minor (`SignupConsentIn`).
- **The identity engine** (`ml/identity`, decision 0010) scores how likely two records are
  the same person, across scripts and without a date of birth.
- **The sport modules' checks**: a season's numbers are validated against its schema and
  invariants (`football.season_basic.v1`: more penalty goals than goals is refused), the same
  rule the fraud detector's arithmetic check uses.
- **The integrity board**, a federation-only queue where each decision has a reason and an
  audit trail. A case (`Flag`) must name a player record.
- **Accounts**: there is no sign-up, and no screen that makes an account: today every account
  comes from the seed (`data/pipelines/synthetic/accounts.py`). The roles are coach, scout,
  federation, player and admin. There is no guardian role, and no rate limiting
  (`docs/threat-model.md`).

What this must not break: no unverified record may reach search, the profile, the analytics or
the ML evaluations; a minor's data is not stored without a guardian's consent; nothing is
invented, so a claim the reviewer could not check is shown as a claim.

## Proposal

### 1. A submission is not a player until the federation approves it

A new table, `player_submission`, holds what was submitted and its review: the submitter, the
claimed identity (name, date of birth, gender, nationalities), the claimed basis for Egypt
eligibility, the current club and league abroad, a source link, optional basic seasons in the
`football.season_basic.v1` shape, the consent form, the checks' results, and the review
(status, reviewer, reason, the player record it became or was attached to).

Nothing in `player` changes until approval. Approval creates the player (tier `diaspora`,
`is_egypt_eligible` true) and their seasons through the same path as `POST /players`, or, when
the reviewer finds the person is already on record, attaches the new information to that
record instead. This keeps every existing query safe without auditing them all for a new
"pending" status.

### 2. Who submits

- **Scouts** submit players they have found abroad.
- **Players** with an account submit themselves.
- **Guardians** have no account and no role. See question 2.
- **Federation staff** can submit, and review, but never review their own submission.

A minor's submission carries the guardian's consent, named, as at sign-up. A scout cannot sign
it: their submission of a minor waits as "awaiting guardian consent" until the federation
records the guardian's signature, and until then only the submitter and federation reviewers
can see it.

### 3. Checks on arrival

They run when a submission is saved and again before approval. They inform the reviewer; only
the first one refuses anything.

| Check | What it does | Built on |
| --- | --- | --- |
| Validation | Required fields, a plausible date of birth, ISO country codes, an eligibility basis from a fixed list, a source link that is a web address. Seasons validated against the sport module. A failure is refused with the reason, at the form. | `app/sports.py` validation |
| Same person on record | The identity engine scores the submission against every player and every open submission. A likely match is shown with its probability and what agreed and disagreed, and the reviewer chooses: a new person, or the same as an existing one. | `ml/identity` (decision 0010) |
| Conflicting date of birth | A likely match whose date of birth differs by more than a typing slip is shown as possible age misrepresentation, the fraud that matters most in youth football (ml/detectors/fraud.py). | identity engine evidence |
| Numbers that do not add up | A season failing the module's invariants is refused; one that passes but sits far outside its league's range (talent estimate percentile from very few minutes) is shown, not refused. | sport module, `ml/estimates` |
| Submitter pattern | How many submissions this account made recently, and how many were rejected. No rate limiting exists, so this is the only brake. | `player_submission` |

### 4. The verification queue

A federation-only screen, "Submissions", beside the integrity board, not inside it: a case
there must name a player record, and a submission has none yet. Each submission shows the claims,
the source link, and each check's result. The reviewer approves, rejects with a reason the
submitter sees, or asks for more (the submitter can edit and resubmit). Every decision is in
the audit log. The submitter sees their own submissions and where each stands.

Documents (passports, birth certificates) are not uploaded in this version: uploads are their own
threat surface (`docs/threat-model.md`, malicious uploads). The reviewer checks eligibility
outside the platform and records in the reason what they checked.

### 5. How it is graded

Like the detectors: the synthetic generator plants submissions with a known answer (the same
person as an existing record, in the other script or without a date of birth; a conflicting date
of birth; numbers that do not add up; honest new players), and the checks are scored with
precision and recall against them, reported in `ml/README.md`. Tuned on seeds 101, 202 and 303,
reported on others.

## Questions, and the answers so far

1. **Where submissions live**: the new table above (a schema change and a migration), or a
   player record with a new status `pending`, which needs every query that reads players to
   exclude it. **Answered: the new table.**
2. **Guardians and players without an account**: leave them out of the first version (a scout
   or the federation submits for them), or add a public form with no account. A public form
   needs rate limiting and a way to reach the submitter, neither of which exists. **Answered:
   left out. Logged-in scouts and players submit; federation staff can too.**
3. **The source of a submitted season**: `self_submitted` for every submission, or a new
   `submitted` value that says who submitted it (player or scout). **Settled by the build:
   neither.** A submitted season never becomes a performance record at all. It stays on the
   submission and the profile reads it from there, so no analytics query has to know to skip
   it.
4. **Whether a submitted season counts in the league analytics** (talent estimates, gap
   analysis) once approved, or stays on the profile only, marked as submitted, until a trusted
   source confirms it. Counting it lets one submitter shift a league's peer group.
   **Answered: profile only, marked as submitted, until a trusted source confirms it.**

## What the build decided (2026-11-22)

Code: `apps/api/app/services/submissions.py` (the rules), `app/routers/submissions.py`,
`app/models/player_submission.py` (migration 0010), the `/submissions` screen, and a
"Submitted seasons abroad" card on the profile (`GET /players/{id}/submitted-seasons`). Tests:
`apps/api/tests/test_submissions.py`.

- **Consent.** Whoever submits records the sign-up form the way a coach does at `POST /players`,
  except a scout for a minor: that submission waits as `awaiting_consent` until the federation
  records the named guardian's signature. A submission with no form waits the same way, and
  nothing can be approved before the form is recorded.
- **A different date of birth is its own rule.** The identity engine reads a conflicting date of
  birth as strong evidence of two people (among 400 invented records, a pair agreeing on
  everything else scored 0.91 with the same date and 0.0 with one 30 days apart), so a
  re-registration with a younger date never reaches its link threshold. The check therefore
  looks for the pattern directly: the same full name and given name with a date of birth more
  than a week apart. A brother (a different given name) is not raised. Within a week it is
  shown as a likely match instead, a typing slip.
- **The engine's share of true pairs is floored.** Fitted on a register with no duplicates, the
  engine's estimate of how many records are duplicates falls to nothing (1e-12), and then no
  submission could ever match anyone. That estimate answers a different question ("how many of
  these records repeat each other"), so the check uses the engine's own starting value (a tenth
  of the records duplicated) when the estimate is lower.
- **The model is fitted once and kept.** Fitting it on every player takes about 6 s for 3,000
  records and 18 s for 6,000, so it is kept until the number of players moves by more than 2%,
  or for an hour; a submission is then scored against every record in about 0.04 s, with the
  engine's own blocking (checked on 30 random submissions: the same pairs every time). The first
  submission after the API starts waits for the fit.
- **Approval** creates the player through `writes.create_player` (tier `diaspora`,
  Egypt-eligible), affiliated to the club abroad, found by name and country or added. **Attach**
  links the submission to a player on record and changes nothing on the record.
- **Not done**: the planted-case evaluation (section 5), so the checks' precision and recall are
  not known yet. On generated data the identity engine is graded (ml/README.md, "Player
  identity"); this use of it is not.

## Consequences

- The diaspora tier gets real entries without scraping, each one checked by a person.
- It adds a table, a migration, one screen with a submit form and a review queue, and a profile
  card. The planted-case evaluation is still to come.
- The federation takes on a review workload. The queue shows how old each submission is.
