"""Challenger models: the machine-learning methods the thesis names, run against the v1 models.

The thesis proposes gradient-boosted forecasting (XGBoost) and isolation-forest anomaly
detection. The v1 models in `ml/forecasting` and `ml/detectors` are transparent, standard
library only, and already beat the graded baselines. This package puts the two proposed
methods through the *same* evaluation, so the question "does the more complex model earn its
place?" is answered with numbers rather than assumed. See "Challenger models" in ml/README.md.

Kept apart from the v1 code on purpose:

- These need numpy, scikit-learn and xgboost. The v1 detectors and forecasters stay standard
  library only.
- XGBoost won its evaluation, so the API imports `xgb_forecast` for the profile's height
  forecast (under 18). It never imports the isolation forest, which did not win, or
  scikit-learn.
- Every hyperparameter was fixed before the first run and none was changed afterwards. Tuning
  a challenger on the seeds it is reported on would be the same mistake the README warns about
  for the detectors' thresholds.
"""


def available() -> bool:
    """True when the challengers' dependencies are installed."""
    try:
        import sklearn  # noqa: F401
        import xgboost  # noqa: F401
    except ImportError:
        return False
    return True
