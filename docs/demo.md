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

If the browser tests (`pytest tests/e2e`) have run on this machine, reset the data first (see
"After a rehearsal"). Each run adds test players named "E2E ..." to the demo coach's squad and
duplicate cases to the integrity queue, and an audience would see them. The check below warns
when they are there.

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
   seconds). **It also names the demo player and what the coach types: name, date of birth,
   position and height.** It ends with `ready`,
   or says what to fix.

3. Once the check says `ready`, save the database as it is now:

   ```bash
   python docker/demo_snapshot.py save
   ```

   It takes a few seconds and writes `docker/snapshots/demo.dump` (git ignores the folder).
   From then on, `restore` puts this exact database back in seconds: after each rehearsal, and
   on the day if anything goes wrong. Save again only after a reset from the generator.

4. Have two terminals open at the repository root: one for the detector run in step 5,
   one spare.

5. Open Firefox at http://localhost:3000. Use a private window per account if you want to
   switch without signing out.

The player below is the first one the check offers, منير عصام فارس حجازي. If a rehearsal left
him registered a second time (it stopped before the merge, or the merge was undone), the check
offers the next one; use the name, date and position it prints, and everything below is the
same.

## The script

### 0. Why it exists (no account needed)

Open `http://localhost:3000/story`, or follow the link under the logo on the sign-in screen.
Press **Play**. One boy, small at 14: the red line is the day a size-based cut would have
released him, the blue box is what NorthStar said that same day, and the dashed green line is
how he went on to grow. Then the pattern across five datasets: about four in ten such boys
flagged when measured three times or more, one in five other small boys, and none measured less.
Say the last line out loud: the fix is not a better model, it is a tape measure.

The boy is synthetic and the footnote says so. His numbers and the pattern are the late-bloomer
figure's (`python -m ml.figure_late_bloomer`), so they always match `ml/README.md`.

### 1. Log a player (coach)

Sign in with the **Coach** button on the login screen: the coach at the club `demo_check.py`
named: the Egyptian club or academy with the most youth players.

- **Home** opens on measuring day: who is due a reading, each with a box to log a height right
  there. Under it, who is growing fastest, late bloomers in the squad, and the whole squad, with
  how stale each one's readings are.
- **Add player.** Full name `منير حجازي`, the date of birth the check printed, position **ST**.
  The date is not written here because it changes: the seed dates the whole dataset relative
  to the day it was loaded, so every reset gives each player a slightly different birthday.
  The date makes him a minor, so the form asks for the guardian's consent: type a guardian's
  name and tick the box. Continue stays locked until then.
- Height: the number the check printed, about 1 cm above his last reading.
  Save.

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

Sign out, then sign in with **Scout**: a scout at a different academy. The scout lands on their
own home: their shortlist, who stepped up this season, and late bloomers. Press **Search**.

- Type `Mounir Hegazy` in Latin and press Enter. **How this was read** shows `name: Mounir`,
  `name: Hegazy`, and the one result is in Arabic: the Latin spelling finds the Arabic name.
- Now type `منير حجازي`.

### 4. Find them (scout)

Two players: the one the coach just added at their club (one reading) and منير عصام فارس
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
  so is the one kept; **Keep record A / B** is already set to it. Record A and Record B open
  each profile in a new tab.
- Type a reason, for example `Same boy, registered at two academies. Spoke to both.` The
  buttons stay disabled until there is one: a decision without a reason teaches the detectors
  nothing.
- **Confirm and merge.** The case leaves the queue, and its history keeps who decided, what
  and why.

That is the sentence, end to end. Then show what the review did:

### 7. One player again (federation)

- Search `منير حجازي`: one result now, منير عصام فارس حجازي.
- Open him. His latest height is the coach's reading from step 1, added to his years of
  history, and **Merged into this record** names منير حجازي, who merged it and when. The
  growth chart now includes the new reading.
- Say: both academies still have him in their squads, nothing was averaged or invented, and
  a wrong merge can be undone. **Undo merge** is right there, and asks for a reason. Do not
  press it in the demo; if asked, describe it.

## If something goes wrong

| What you see | What to do |
| --- | --- |
| The login screen has no role buttons | The API is not up. `docker compose ... ps`, then wait for `northstar-api`. |
| Search finds only one record | The coach's save did not finish, or the date was typed differently. Look for the name in the squad table on the coach's Home. |
| `write_flags` raises 0 flags | The date of birth or the name does not match the original. Check both against what `demo_check.py` printed. |
| The profile shows no banner after the run | Reload the page: the profile was open before the flag was written. |
| The summary says the model is not running | The stack was started without `--profile llm`. The flow does not need it. |
| Ask says "Question read by fixed rules" | The model is not running or not reached. Ask still answers; the rules read fewer phrasings, so use the questions under "If there is time", which they read right. |
| Ask is slow on a machine with no GPU | Start the stack with `ASSISTANT_READER=rules` set in the shell (PowerShell: `$env:ASSISTANT_READER="rules"`), then `up -d`. Ask then never waits on the model. |
| The data is in a state you did not expect | `python docker/demo_snapshot.py restore`, then `python tests/e2e/demo_check.py`. About ten seconds, plus the check. |
| The stack will not start at all | Play the recording (below). |
| Every page is suddenly slow | Summaries are queued on the processor. `docker stats` shows `northstar-ollama` near 400% CPU. Wait a minute or two; it clears by itself. |
| A step looks wrong in a way that is not here | Run `pytest tests/e2e -k demo_flow_on_one_player` after the demo, not during it. |

## What not to claim

- **Merging is not automatic.** The detector only raises the case; a person decides, and the
  merge happens when they confirm. That is deliberate (docs/decisions/0006).
- **The detector run is a batch job,** run by hand here. Nothing schedules it yet.
- **The data is synthetic.** Every player, academy and account was generated. No real
  child's data is in the repository or in this database.

## After a rehearsal

Put the saved database back:

```bash
python docker/demo_snapshot.py restore
python tests/e2e/demo_check.py
```

The restore stops the API, replaces the database with the snapshot and starts the API again,
in under ten seconds on the team laptop. The models and their downloads are not touched. The
check afterwards writes the demo player's summary again, because summaries are kept in the
API's memory, not in the database. The demo player and the date of birth to type are the same
as when the snapshot was saved.

Without a snapshot, a rehearsal that ends with the merge leaves nothing in the way: the second
entry is merged, out of search, and the check offers the same player again. A rehearsal that
stops before the merge, or undoes it, leaves the second entry active, and the check moves on
to the next demo player. If all three are used up, reset the data from the generator:

```bash
docker compose -f docker/docker-compose.yml down
docker volume rm docker_pgdata
docker compose -f docker/docker-compose.yml -f docker/docker-compose.gpu.yml --profile llm up -d --build
```

This deletes the database volume only, and the seed container rebuilds it from the generator,
dated up to yesterday. Do not use `down -v`: it also deletes the downloaded language models.
After a reset, run the check and save a new snapshot: the old one is a different dataset.

A snapshot ages like its data. Readings in one saved weeks before the demo look weeks old on
the coach's home, so save it within a few days of presenting.

## A recording to fall back on

If the laptop, Docker or the projector fails on the day, play a recording instead. Make two,
and keep them off the repository (`out/` is ignored by git):

- **A narrated one, made by a person.** After `restore` and the check, follow the script above
  with a screen recorder running (Windows: Xbox Game Bar, Win+Alt+R, or OBS), speaking the
  "Say" lines. This is the one to show an audience.
- **An automatic one, as proof the flow runs.** The browser test of the same flow can record
  itself in Firefox:

  ```bash
  E2E_VIDEO=out/demo-video E2E_SLOW_MO=250 pytest tests/e2e -k demo_flow_on_one_player
  ```

  (PowerShell: `$env:E2E_VIDEO="out/demo-video"; $env:E2E_SLOW_MO="250"` first.) Each browser
  window is saved as a `.webm`: one for the coach and federation, one for the scout, about a
  minute and a half together. It is the test's own player at the test's pace, with no
  narration, so it shows that every step works, not the story. The test adds data, so run
  `python docker/demo_snapshot.py restore` afterwards.

## If there is time

Each of these works from the same accounts:

- **Table tennis** (scout or federation): search `table tennis` and open a result. The same
  profile screen, laid out by the table tennis module. Proof the engine is not football
  only.
- **Ask** (scout): `مين أحسن هداف تحت ١٦ سنة`, `who broke out this season?` or `show me the
  late bloomers`. The screen prints how it read the question and draws the answer as cards and
  bars; every number comes from the database, not the model. Click a question under **Ask
  next** to follow a player from the list into their own answer, and for a professional, the
  scouting report's verdict.
- **Compare** (scout): tick two results in Search, then **Compare 2**.
- **Home** (federation): what needs a decision today (the integrity queue, the academies to
  call, the national team), who stepped up, then coverage for all 27 governorates, including the
  ones the platform has not reached. The switch at the top moves it to table tennis.
- **Team gaps** (scout or federation): where a club is weak against its league and which players
  are strong there; or name a need for the national team.
- **Scouting report** (scout): open a pro player and press **Read the scouting report**. The
  verdict first, the evidence underneath, and what the data cannot see.
- **Home** (player): the player's own journey, against their own last season, and who can see
  their record. No verdicts about them.
