---
cdm:
  audience: eng-guide
  fingerprint: 93ad666b19d8ff9b
  fingerprint_tiers:
    composite: 93ad666b19d8ff9b
    docstring: c11480ba5c086afc
    signature: 5ddbb2bcc208cac9
  region_anchors:
    symbols:
    - 02b23ad449ed3a49
    - 051af376199dec21
    - 051af376199dec21
    - 0a12e5898c92bfc6
    - 0a12e5898c92bfc6
    - 4480c844dbf4cd6b
    - 4a44f6b94fcbe363
    - 551e873b177b069b
    - a0aac6e3dbd9712e
    - a120067e57c16791
    - bc8ebaa383846735
    - c6bcf0d16bc94e16
    - cac98654213bca94
    - ea19528ca582fa92
    - ec56a3351cb8de96
    - f779aad38facd2db
  region_hashes:
    symbols: 8a0fa893750738cb
  schema_version: 1.0.0
---
# learning

> EPIC F learning loop: detect near-duplicate gaps/records (`similar`) and
> promote recurring, human-approved waivers and fixes into reusable config
> suggestions (`promotion`).

<!-- CDM:BEGIN symbols -->
| symbol | kind | signature |
|--------|------|-----------|
| Exemplar | class | class Exemplar(BaseModel) |
| FEATURE_WEIGHTS | variable | FEATURE_WEIGHTS: dict[str, float] = ... |
| PROMOTABLE_RESOLUTIONS | variable | PROMOTABLE_RESOLUTIONS: frozenset[Resolution] = ... |
| PromotionCandidate | class | class PromotionCandidate(BaseModel) |
| PromotionRule | class | class PromotionRule(BaseModel) |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _MODEL_CONFIG | variable | _MODEL_CONFIG = ConfigDict(extra='forbid', frozen=True) |
| _RESOLUTION_VERDICT | variable | _RESOLUTION_VERDICT: dict[Resolution, Verdict] = ... |
| __all__ | variable | __all__ = ['Exemplar', 'rank_similar', 'FEATURE_WEIGHTS'] |
| __all__ | variable | __all__ = ... |
| _neg_iso | function | def _neg_iso(value: str) -> tuple[int, ...] |
| _score | function | def _score(target: ReviewRecord, candidate: ReviewRecord) -> float |
| detect_promotions | function | def detect_promotions(records: list[ReviewRecord], resolutions: list[ResolutionRecord], *, min_count: int = 3) -> list[PromotionCandidate] |
| rank_similar | function | def rank_similar(target: ReviewRecord, records: list[ReviewRecord], resolutions: list[ResolutionRecord], *, top_n: int = 3) -> list[Exemplar] |
| rule_for | function | def rule_for(drift: Drift, rules: tuple[PromotionRule, ...]) -> PromotionRule \| None |
| rule_from_candidate | function | def rule_from_candidate(candidate: PromotionCandidate) -> PromotionRule |
<!-- CDM:END symbols -->
