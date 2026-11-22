# 0011. Diaspora tier: players abroad are submitted, then verified by the federation

Status: proposed 2026-11-22. Nothing is built yet; the open questions at the end need answers
before any code, because the answer to the first is a schema change.
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

## Open questions (answer before building)

1. **Where submissions live**: the new table above (a schema change and a migration), or a
   player record with a new status `pending`, which needs every query that reads players to
   exclude it. The table is proposed.
2. **Guardians and players without an account**: leave them out of the first version (a scout
   or the federation submits for them), or add a public form with no account. A public form
   needs rate limiting and a way to reach the submitter, neither of which exists.
3. **The source of a submitted season**: `self_submitted` for every submission, or a new
   `submitted` value that says who submitted it (player or scout).
4. **Whether a submitted season counts in the league analytics** (talent estimates, gap
   analysis) once approved, or stays on the profile only, marked as submitted, until a trusted
   source confirms it. Counting it lets one submitter shift a league's peer group.

## Consequences

- The diaspora tier gets real entries without scraping, each one checked by a person.
- It adds a table, a migration, two screens (submit, review) and a planted-case evaluation.
- The federation takes on a review workload. The queue shows how old each submission is.
