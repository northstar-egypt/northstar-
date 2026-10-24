"""Set the governorate of synthetic clubs and academies that have none (regions.py).

A module of its own so `python -m` can run it: regions.py is imported by the generator
package itself, and running a module the package already imported makes Python warn.

    python -m data.pipelines.synthetic.backfill_regions --database-url postgresql+psycopg://...
"""

from __future__ import annotations

import argparse

from .regions import backfill


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    updated = backfill(args.database_url)
    print(f"regions: set for {updated} organizations" if updated else "regions: nothing to set")


if __name__ == "__main__":
    main()
