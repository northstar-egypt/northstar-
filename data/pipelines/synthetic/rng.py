"""Seeded randomness.

Every source of randomness in the generator goes through one `Rng` instance so a
run is fully determined by its seed. Nothing calls the module-level `random.*`
functions or an unseeded `Faker()`: those pull from global state, which is what
made the previous pass impossible to regenerate.

Deterministic UUIDs matter as much as deterministic values. The ORM models let
Postgres fill `id` with `gen_random_uuid()`, but the generator needs ids *before*
the insert in order to wire foreign keys and, more importantly, to write a
ground-truth file whose player ids match the data. So ids are generated here,
from the seeded stream, and set explicitly.
"""

from __future__ import annotations

import random
import uuid

from faker import Faker

from . import names


class Rng:
    """A seeded random source: numbers, choices, uuids and Faker, all reproducible."""

    def __init__(self, seed: int, locale: str = "ar_EG") -> None:
        self.seed = seed
        self.random = random.Random(seed)
        self.faker = Faker(locale)
        # Faker.seed_instance seeds this instance only, leaving the shared class
        # level generator alone.
        self.faker.seed_instance(seed)
        # Faker's ar_EG locale has no person provider and falls back to en_US.
        # See names.py; this is what actually makes the names Egyptian.
        names.register(self.faker)
        # A separate stream for uuids, so adding a call that draws a number
        # elsewhere does not shift every id in the dataset.
        self._uuid_random = random.Random(seed + 1)

    # -- numbers ---------------------------------------------------------
    def uniform(self, a: float, b: float) -> float:
        return self.random.uniform(a, b)

    def gauss(self, mu: float, sigma: float) -> float:
        return self.random.gauss(mu, sigma)

    def randint(self, a: int, b: int) -> int:
        return self.random.randint(a, b)

    def chance(self, p: float) -> bool:
        """True with probability p."""
        return self.random.random() < p

    def choice(self, seq):
        return self.random.choice(list(seq))

    def choices(self, seq, weights=None, k: int = 1):
        return self.random.choices(list(seq), weights=weights, k=k)

    def sample(self, seq, k: int):
        pool = list(seq)
        k = min(k, len(pool))
        return self.random.sample(pool, k)

    def shuffled(self, seq):
        pool = list(seq)
        self.random.shuffle(pool)
        return pool

    def poisson(self, lam: float) -> int:
        """Small-lambda Poisson draw by Knuth's method.

        numpy would do this, but the pipeline requirements deliberately stay
        light and the lambdas here are all well under 20.
        """
        if lam <= 0:
            return 0
        import math

        target = math.exp(-lam)
        k, p = 0, 1.0
        while True:
            p *= self.random.random()
            if p <= target:
                return k
            k += 1
            if k > 200:  # guard, unreachable for the lambdas used here
                return k

    def binomial(self, n: int, p: float) -> int:
        if n <= 0 or p <= 0:
            return 0
        return sum(1 for _ in range(n) if self.random.random() < p)

    # -- identity --------------------------------------------------------
    def uuid(self) -> uuid.UUID:
        """A deterministic UUID4-shaped value drawn from the seeded stream."""
        return uuid.UUID(int=self._uuid_random.getrandbits(128), version=4)
