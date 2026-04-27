# CADEN Learning + Libbie Scientific Audit

Date: 2026-04-27

Scope audited:
- [CADEN_learning.md](CADEN_learning.md)
- [CADEN_libbie.md](CADEN_libbie.md)

Interpretation standard:
- Proven: implemented behavior + direct contract evidence exists in tests
- Partial: implemented scaffolding or backend-only path exists, but full doc claim is broader than currently proven
- Unproven: no direct implementation evidence found

Statistical framing used in this audit:
- Prediction quality uses residual reduction, with improvement $\Delta = R_{before} - R_{after}$
- Phase-shift detection uses binomial directional-bias testing over residual sign, with $p < \alpha$
- Optimization uses Pareto dominance, not fixed scalar objective

## Learning Claims

| Claim ID | Verdict | Evidence | Notes |
| --- | --- | --- | --- |
| DOC-034 | Proven | [caden/learning/engine.py](caden/learning/engine.py), [tests/test_contract_learning_engine.py](tests/test_contract_learning_engine.py) | Trigger requires residual pressure and weight plateau. |
| DOC-035 | Proven | [caden/learning/engine.py](caden/learning/engine.py), [tests/test_contract_learning_engine.py](tests/test_contract_learning_engine.py) | LLM proposal path exists and proposals are evaluated on historical residual windows with held-out scoring. |
| DOC-036 | Proven | [caden/learning/engine.py](caden/learning/engine.py), [tests/test_contract_learning_engine.py](tests/test_contract_learning_engine.py) | Accepted schema fields now materialize inferred per-event schema metadata during backfill and log held-out residual improvement. |
| DOC-037 | Proven | [caden/learning/engine.py](caden/learning/engine.py), [tests/test_contract_learning_engine.py](tests/test_contract_learning_engine.py) | Weak fields are decayed toward zero and not deleted. |
| DOC-038 | Proven | [caden/learning/engine.py](caden/learning/engine.py), [tests/test_contract_learning_adaptation.py](tests/test_contract_learning_adaptation.py) | Proposal, pending, and decision events now carry linked provenance metadata (proposal IDs, evaluation values, confidence, lookback window, decision reason). |
| DOC-039 | Proven | [caden/learning/engine.py](caden/learning/engine.py), [tests/test_contract_learning_engine.py](tests/test_contract_learning_engine.py) | Apply path now requires a valid pending proposal event; invalid/mismatched pending context fails loudly before commitment. |
| DOC-040 | Proven | [caden/learning/engine.py](caden/learning/engine.py), [tests/test_contract_learning_adaptation.py](tests/test_contract_learning_adaptation.py) | Directional bias detection and phase signal are tested. |
| DOC-041 | Proven | [caden/learning/engine.py](caden/learning/engine.py), [tests/test_contract_learning_engine.py](tests/test_contract_learning_engine.py), [tests/test_contract_learning_adaptation.py](tests/test_contract_learning_adaptation.py) | Recency bias now performs true recency-weighted residual aggregation before refit-derived retrieval weights are computed. |
| DOC-042 | Proven | [tests/test_contract_metadata.py](tests/test_contract_metadata.py) | Ratings append-only immutability is directly tested. |
| DOC-043 | Proven | [caden/learning/weights.py](caden/learning/weights.py), [tests/test_contract_learning.py](tests/test_contract_learning.py) | Ridge residual fitting and weight derivation tested. |
| DOC-044 | Proven | [caden/learning/optimize.py](caden/learning/optimize.py), [tests/test_contract_learning.py](tests/test_contract_learning.py) | Pareto frontier behavior tested. |
| DOC-045 | Proven | [caden/learning/engine.py](caden/learning/engine.py), [tests/test_contract_learning_engine.py](tests/test_contract_learning_engine.py) | Schedule-selection learning events are logged and tested. |
| DOC-046 | Proven | [caden/learning/optimize.py](caden/learning/optimize.py), [tests/test_contract_learning.py](tests/test_contract_learning.py) | Optimization no longer synthesizes fixed fallback weights without revealed signal; Pareto selection with learned preferences remains the only scalarization path. |

## Libbie Claims

| Claim ID | Verdict | Evidence | Notes |
| --- | --- | --- | --- |
| DOC-047 | Proven | [caden/libbie/db.py](caden/libbie/db.py), [tests/test_contract_db.py](tests/test_contract_db.py) | Single DB architecture verified. |
| DOC-048 | Proven | [caden/libbie/store.py](caden/libbie/store.py), [tests/test_contract_metadata.py](tests/test_contract_metadata.py), [tests/test_contract_retrieve.py](tests/test_contract_retrieve.py) | Raw provenance and curated-memory split verified. |
| DOC-049 | Proven | [caden/libbie/retrieve.py](caden/libbie/retrieve.py), [tests/test_contract_retrieve.py](tests/test_contract_retrieve.py) | Ligand is transient and not persisted. |
| DOC-050 | Proven | [caden/libbie/__init__.py](caden/libbie/__init__.py), [tests/test_contract_libbie_api.py](tests/test_contract_libbie_api.py) | Web lookup capture path tested. |
| DOC-051 | Proven | [caden/libbie/store.py](caden/libbie/store.py), [tests/test_contract_metadata.py](tests/test_contract_metadata.py), [tests/test_contract_why.py](tests/test_contract_why.py) | Baseline metadata keys are supported. |
| DOC-052 | Proven | [caden/libbie/__init__.py](caden/libbie/__init__.py), [tests/test_contract_libbie_api.py](tests/test_contract_libbie_api.py) | Libbie now exposes meaningful-context-change surfacing and contract tests prove unchanged contexts suppress proactive packets while changed contexts surface them. |
| DOC-053 | Proven | [tests/test_m6_rater.py](tests/test_m6_rater.py) | Self-knowledge is retrieved and influences rating context. |
| DOC-054 | Proven | [caden/project_manager/service.py](caden/project_manager/service.py), [tests/test_contract_project_manager.py](tests/test_contract_project_manager.py) | PM events persist via Libbie event pipeline. |
| DOC-055 | Proven | [caden/libbie/searxng.py](caden/libbie/searxng.py), [tests/test_contract_libbie_api.py](tests/test_contract_libbie_api.py) | Contract tests now assert upstream SearXNG failures raise loudly and produce no fallback `web_knowledge` writes. |
| DOC-056 | Proven | [caden/scheduler/predict.py](caden/scheduler/predict.py), [caden/scheduler/residual.py](caden/scheduler/residual.py), [tests/test_contract_predict.py](tests/test_contract_predict.py), [tests/test_contract_curate.py](tests/test_contract_curate.py) | Predict-observe-correct loop with Libbie retrieval/residual integration is tested. |

## Bottom Line

Quantitative confidence summary for current codebase:
- Learning: 13 Proven, 0 Partial, 0 Unproven
- Libbie: 10 Proven, 0 Partial, 0 Unproven

Therefore, the strict scientific statement is:
- Learning claims in this audited scope are now fully behavior-proven.
- Libbie claims in this audited scope are now fully behavior-proven.

## Closure Status

1. Learning + Libbie claim set in this audit is fully closed at current evidence grade.
2. Future work should be treated as scope expansion, not closure debt for DOC-034..056.
