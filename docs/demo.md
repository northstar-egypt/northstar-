# The demo, step by step

The system target we are graded on is one sentence: *log a player, see the profile, search,
find them, a flag surfaces, the federation reviews it.* This is that sentence as a script, on
one player, in three accounts, about ten minutes. Every step is also run by the browser test
`test_the_demo_flow_on_one_player` in `tests/e2e/test_demo_flow.py`, so if the script stops
working, the test goes red before anyone stands in front of an audience.

## The story

A boy who already plays at one academy is registered again by a coach at another. The coach
types only his first and family names, which is how most duplicate records in Egyptian
football get made: a second clerk, a shorter name, the same date of birth. A scout finds both
records. The nightly detector run notices they are the same boy and raises a flag, and the
federation looks at the evidence and decides.

It shows the parts of the platform that matter: a coach logging on a phone-sized form, a
profile that says what it does not know, search across Arabic and Latin spellings, a detector
working on data that just arrived, and a human deciding with a reason that is kept.

## Before you present

1. Start the full stack, with the models:

   ```bash
   docker compose -f docker/docker-compose.yml -f docker/docker-compose.gpu.yml --profile llm up -d --build
   ```

   (Without an NVIDIA GPU, leave out the `docker-compose.gpu.yml` file. Everything works, and
   Ask takes longer.)

2. Run the check, from the repository root, with the Python environment from the README:

   ```bash
   python tests/e2e/demo_check.py
   ```

   It checks the services, the three accounts, the detector run (dry, nothing written) and
   both local models. It warms Ask and writes one summary, which is the slow part (about 80
   seconds). **It also names the demo player and what the coach types.** It ends with `ready`,
   or says what to fix.

3. Have two terminals open at the repository root: one for the detector run in step 5,
   one spare.

4. Open Firefox at http://localhost:3000. Use a private window per account if you want to
   switch without signing out.

The player below is the first one the check offers, منير عصام فارس حجازي. If a rehearsal has
already registered him a second time, the check offers the next one; use the name, date and
position it prints, and everything below is the same.

## The script

### 1. Log a player (coach)

Sign in with the **Coach** button on the login screen. That is an academy coach at المصري.

- **Squad** shows the coach's own players, with how stale each one's readings are.
- **Add player.** Full name `منير حجازي`, date of birth `2010-06-09`, position **ST**.
  The date makes him a minor, so the form asks for the guardian's consent: type a guardian's
  name and tick the box. Continue stays locked until then.
- Height `165`, Save.

Say: consent is signed at sign-up, by a guardian, before anything is stored.

### 2. See the profile (coach)

The profile opens on the new record.

- One height reading, so the growth chart draws no forecast, and says it needs at least
  two. **Point this out.** The platform never draws a number it cannot back.
- The written summary appears last, a minute or more for a new player, because a local model
  writes it and a checker reads it before it is shown. Carry on; it is not part of the flow.

**Open as few new profiles as you can.** Each profile not opened before starts a summary,
written by the larger model on the processor, not the graphics card (that is kept for Ask).
One at a time is fine. Several opened in quick succession queue up and take the whole
machine for minutes: on an 8 GB laptop, pages then load slowly or time out. The script opens
the new player's profile twice and nothing else on purpose.

### 3. Search (scout)

Sign out, then sign in with **Scout**: a scout at a different academy.

- Type `Mounir Hegazy` in Latin and press Enter. **How this was read** shows `name: Mounir`,
  `name: Hegazy`, and the one result is in Arabic: the Latin spelling finds the Arabic name.
- Now type `منير حجازي`.

### 4. Find them (scout)

Two players: the one the coach just added at المصري (one reading, 165 cm) and منير عصام فارس
حجازي at البنك الأهلي with years of history. Same boy, two records.

Say: nothing has flagged this yet. A person might spot it in a search; the platform should
not rely on that.

### 5. A flag surfaces (detector run)

In a terminal:

```bash
python -m ml.write_flags --from-database
```

It prints `flags raised 1` or more. Say: in production this is the nightly batch job. The
detectors read every record, including the one added a minute ago.

Back in the browser, open the new player's profile again (as the scout, from the search). The
banner **What the models are saying** now shows **possible duplicate**, with the reason: the
names match after normalising Arabic spelling, and the dates of birth are the same. Under it:
*a flag is a claim, not a verdict.*

### 6. The federation reviews it (federation)

Sign in with **Federation**. Open **Integrity**.

- The queue lists open cases, newest first. Pick the newest **duplicate** (0d). It is listed
  under one of the two records' names, منير حجازي or منير عصام فارس حجازي.
- **Why this was raised**, then **Field by field**: the two records side by side, the
  differences highlighted. The note under the table says which record has more history, and
  so is the one to keep. Record A and Record B open each profile in a new tab.
- Type a reason, for example `Same boy, registered at two academies. Spoke to both.` The
  buttons stay disabled until there is one: a decision without a reason teaches the detectors
  nothing.
- **Confirm duplicate.** The case leaves the queue, and its history keeps who decided, what
  and why.

That is the sentence, end to end.

## If something goes wrong

| What you see | What to do |
| --- | --- |
| The login screen has no role buttons | The API is not up. `docker compose ... ps`, then wait for `northstar-api`. |
| Search finds only one record | The coach's save did not finish, or the date was typed differently. Search the coach's name in Squad. |
| `write_flags` raises 0 flags | The date of birth or the name does not match the original. Check both against what `demo_check.py` printed. |
| The profile shows no banner after the run | Reload the page: the profile was open before the flag was written. |
| The summary says the model is not running | The stack was started without `--profile llm`. The flow does not need it. |
| Every page is suddenly slow | Summaries are queued on the processor. `docker stats` shows `northstar-ollama` near 400% CPU. Wait a minute or two; it clears by itself. |
| A step looks wrong in a way that is not here | Run `pytest tests/e2e -k demo_flow_on_one_player` after the demo, not during it. |

## What not to claim

- **Confirm duplicate does not merge the records yet.** It records the decision. Merging
  (moving the history onto one record and pointing the other at it with `merged_into`) is the
  next step, and the schema supports it.
- **The detector run is a batch job,** run by hand here. Nothing schedules it yet.
- **The data is synthetic.** Every player, academy and account was generated. No real
  child's data is in the repository or in this database.

## After a rehearsal

Each rehearsal leaves one second entry behind, and the check moves on to the next demo
player. After the third, reset the data:

```bash
docker compose -f docker/docker-compose.yml down -v
docker compose -f docker/docker-compose.yml -f docker/docker-compose.gpu.yml --profile llm up -d --build
```

`down -v` deletes the database volume; the seed container rebuilds it from the generator.

## If there is time

Each of these works from the same accounts:

- **Table tennis** (scout or federation): search `table tennis` and open a result. The same
  profile screen, laid out by the table tennis module. Proof the engine is not football
  only.
- **Ask** (scout): `مين أحسن هداف تحت ١٦ سنة` or `top 5 strikers for goals under 16`. The
  screen prints how it read the question; every number comes from the database, not the
  model.
- **Compare** (scout): tick two results in Search, then **Compare 2**.
- **Oversight** (federation): coverage for all 27 governorates, including the ones the
  platform has not reached.
