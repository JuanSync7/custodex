---
cdm:
  audience: eng-guide
  fingerprint: fffbbe016bff82af
  fingerprint_tiers:
    composite: fffbbe016bff82af
    docstring: 86cf4fb46000afda
    signature: ac44468ce1131683
  region_anchors:
    symbols:
    - 029ad24ab0274f10
    - 02b23ad449ed3a49
    - 051af376199dec21
    - 051af376199dec21
    - 0a12e5898c92bfc6
    - 0a12e5898c92bfc6
    - 1a3df9c370de3541
    - 33a36310bd42eab3
    - 4480c844dbf4cd6b
    - 4a44f6b94fcbe363
    - 551e873b177b069b
    - 6633686edf47ec9e
    - 6c4f2a108d812565
    - 80dbdb9d6775c85a
    - 83996ef184f12b0b
    - 97c7edea22cdb3f3
    - 9cccb63fd41ac203
    - a0aac6e3dbd9712e
    - a120067e57c16791
    - b09bd2ff4cf1b8fe
    - bc8ebaa383846735
    - c6bcf0d16bc94e16
    - cac98654213bca94
    - d2236bbd2002e7c3
    - e73cb28aeb12c3e4
    - e7c5d58753cd719f
    - ea19528ca582fa92
    - eb45665f90f4aae7
    - ec56a3351cb8de96
    - f779aad38facd2db
    - f9bbc02317970115
  region_hashes:
    symbols: 86322c0a78bf7e08
  schema_version: 1.0.0
  symbol_sigs:
    029ad24ab0274f10: a8a5ac95061cd80c
    02b23ad449ed3a49: 27692661d83310fa
    051af376199dec21: e7ddc1e5f8554f01
    0a12e5898c92bfc6: 73646d29304739ea
    1a3df9c370de3541: c6a9fecc9fb8525c
    33a36310bd42eab3: f0f2bc1fe0c1a225
    4480c844dbf4cd6b: 6049c647794508d1
    4a44f6b94fcbe363: a03264f790d5db05
    551e873b177b069b: 4429f5ef22596d80
    6633686edf47ec9e: 130b6f36be152c49
    6c4f2a108d812565: a73aeaa7dae630b0
    80dbdb9d6775c85a: eaae9e1bc3ce7a51
    83996ef184f12b0b: 1d1947f11a1d1d74
    97c7edea22cdb3f3: d8a5dcfbb1b3736e
    9cccb63fd41ac203: 2dadf0fbc3461b27
    a0aac6e3dbd9712e: 98c3be92385d427e
    a120067e57c16791: 5c077259f77654fc
    b09bd2ff4cf1b8fe: 939743913db53f41
    bc8ebaa383846735: c72f4c8c45a348c2
    c6bcf0d16bc94e16: ec77e2b166953348
    cac98654213bca94: 413cd32c374e6e2e
    d2236bbd2002e7c3: f50ff622fe3caed7
    e73cb28aeb12c3e4: 82af278db8ab88fe
    e7c5d58753cd719f: 3a54f9b98b3718f6
    ea19528ca582fa92: c7dc981de07f5a52
    eb45665f90f4aae7: 68bb14a344333f67
    ec56a3351cb8de96: 88dba46ed3e97ece
    f779aad38facd2db: c0dde00c9ac6c742
    f9bbc02317970115: b5217e6b2308cf67
---
# learning

> EPIC F learning loop: detect near-duplicate gaps/records (`similar`) and
> promote recurring, human-approved waivers and fixes into reusable config
> suggestions (`promotion`).

<!-- CDM:BEGIN symbols -->
| symbol | kind | signature |
|--------|------|-----------|
| Exemplar | class | class Exemplar(BaseModel) |
| Exemplar.model_config | variable | model_config = _MODEL_CONFIG |
| Exemplar.record | variable | record: ReviewRecord |
| Exemplar.resolution | variable | resolution: ResolutionRecord |
| Exemplar.score | variable | score: float |
| FEATURE_WEIGHTS | variable | FEATURE_WEIGHTS: dict[str, float] = ... |
| PROMOTABLE_RESOLUTIONS | variable | PROMOTABLE_RESOLUTIONS: frozenset[Resolution] = ... |
| PromotionCandidate | class | class PromotionCandidate(BaseModel) |
| PromotionCandidate.audience | variable | audience: Audience |
| PromotionCandidate.count | variable | count: int |
| PromotionCandidate.doc_id | variable | doc_id: str |
| PromotionCandidate.drift_kind | variable | drift_kind: str |
| PromotionCandidate.model_config | variable | model_config = _MODEL_CONFIG |
| PromotionCandidate.resolution | variable | resolution: Resolution |
| PromotionRule | class | class PromotionRule(BaseModel) |
| PromotionRule.audience | variable | audience: Audience |
| PromotionRule.doc_id | variable | doc_id: str |
| PromotionRule.drift_kind | variable | drift_kind: str |
| PromotionRule.model_config | variable | model_config = _MODEL_CONFIG |
| PromotionRule.verdict | variable | verdict: Verdict |
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
