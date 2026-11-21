# Labelling identity pairs

The identity engine (`ml/identity`) decides whether two player records are the same person. It
is graded on generated data, where the answer is known. On real data nobody has checked its
answers yet. This task is that check: a person looks at about 190 pairs of real records and
says, for each, whether they are the same player. From those answers we measure how often the
engine is right on real players (precision) and how many real pairs it misses (recall).

It takes about an hour. No coding.

## Before you start

You need the file `pairs.csv` from the team lead. It holds real professional players' names, so:

- it **never goes into the repository**, not in a branch, not as a test file;
- keep it in a folder outside the repo, for example `D:/northstar-data/identity-labels/`;
- send it back the same way you got it, not through a public channel.

Do not open the engine's output while you label. The file deliberately does not say what the
engine thought, so your answer is yours and not the engine's.

## What you see

One row per pair: record **a** and record **b**. For each record:

| column | what it is |
| --- | --- |
| `name`, `known_as` | the full name, and a shorter name if the source has one |
| `born` | date of birth; StatsBomb records have none |
| `nationality` | country codes. StatsBomb records the national team, FootyStats usually the birth country, so a dual national can differ between the two |
| `position` | where the source lists one |
| `source` | where the record came from and its id there: `statsbomb 3463`, `footystats 4241`, or `register` |
| `clubs`, `seasons` | the clubs, and the season start year with the team |

## What to write

In `same_person`, one of:

- `yes`: the same person;
- `no`: two different people;
- `unsure`: you cannot tell. That is a fine answer. Unsure pairs are left out of the scores and
  counted, so it is better than a guess.

Use `notes` for anything worth knowing: "brothers", "same name, different generation",
"checked on Transfermarkt".

## How to decide

1. **Read both records in full.** Most pairs are decided by the seasons and clubs: a player at
   Bournemouth in 2015 and a player at Bournemouth from 2018, with the same unusual surname, is
   one person.
2. **Check what cannot both be true.** The same season at two clubs in different countries,
   careers that would start at age 12 or end at 45, a goalkeeper and a striker across
   overlapping seasons: usually two people.
3. **Look a player up** on a public site (Transfermarkt, Wikipedia) when the records alone do
   not settle it. Note it in `notes`.
4. **Common names need more.** "Mohamed Ali" or "Danilo Silva" in two sources says little.
   Decide on the seasons and the dates, or write `unsure`.
5. **Relatives.** Brothers and cousins share the family name, and Egyptian names share the
   father's and grandfather's names. A different first name with the rest the same is usually a
   relative, not the same person.
6. **Two records from the same source can still be one person.** FootyStats sometimes gives a
   player two ids. If both records are FootyStats with the same date of birth and name, that is
   usually a `yes`.

## When you are done

Save the file in the same place, with the same name, as CSV, and tell the team lead. They run:

```bash
python -m ml.run_identity_labels score --labels D:/northstar-data/identity-labels
```

which prints precision and recall on real data with their uncertainty. The result goes in
`ml/README.md`, "Player identity", whatever it says.
