"""NEYOGI ML pipeline: GEE ingestion, spectral feature engineering, crop
classification and deterministic supply estimation.

Design rule enforced throughout this package: every value that reaches a user
is traceable to a measured observation or an operator-verified reference
constant. Nothing is synthesised to fill a gap. Where an input is missing the
pipeline raises a typed error that the API layer converts into an explicit UI
status badge.
"""

__version__ = "1.0.0"
