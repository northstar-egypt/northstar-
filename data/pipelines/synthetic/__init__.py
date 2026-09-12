"""Synthetic data generation for NorthStar.

No real player data, ever. Everything here is fabricated, and the point of it is
to be a labelled evaluation set: see planted.py and ground_truth.py.
"""

from .config import DEFAULT_SEED, GeneratorConfig
from .dataset import Dataset, build_dataset

__all__ = ["DEFAULT_SEED", "GeneratorConfig", "Dataset", "build_dataset"]
