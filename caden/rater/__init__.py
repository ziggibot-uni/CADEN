"""Rater — assigns mood / energy / productivity to an event using the LLM.

Per spec: the rater is CADEN's estimator. It does not use hand-written
features. The only inputs are:
  - the event itself
  - relevant past events + their ratings, retrieved by Libbie
  - relevant self-knowledge from Sean, retrieved by Libbie

Ratings are immutable once stored. When retrieval is thin, the rater returns
None (unknown) for that axis — it never fakes a number.
"""
