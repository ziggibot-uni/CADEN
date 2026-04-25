"""Scheduling, prediction emission, residual computation.

v0 scope (per spec):
  - scheduling picks any reasonable block within the deadline; no optimisation
  - a prediction bundle is emitted at scheduling time and stored
  - on completion, the paired event's end time is edited to "now" and
    residuals are computed from nearby ratings
"""
