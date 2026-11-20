"""The player identity engine: one person, one record, across every source (team plan 7.2).

engine.py finds, scores and groups records that are the same person, and proposes the links a
person should review; hard.py builds the hard duplicates it is graded on; m_probabilities.json
is what a true pair looks like, measured on the calibration seeds; ml/run_identity_eval.py
grades it against the duplicate detector v1 (ml/README.md, "Player identity");
ml/write_flags.py puts its proposals on the integrity board.
"""
