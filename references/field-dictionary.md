# Field dictionary

The canonical machine contract is `output_schema.json`. This dictionary defines
the intended meaning; JSON Schema type validity alone does not prove semantic
validity.

## Top level

| Field | Type | Meaning and rule |
|---|---|---|
| `case_id` | string/number | Exact identifier from `case.json`; never replace with a filename unless the identifier is absent. |
| `status` | enum | `success`, `partial`, or `unable`. Status describes output completeness, not the paper's truth. |
| `task_output` | object | The task-specific answer, translation, extraction, comparison, or knowledge structure. Preserve requested nested fields. |
| `assertions` | array | Atomic, evidence-bound nanopublication records. A block of prose is not one assertion. |
| `sources` | array | Every source cited by an emitted assertion, with file identity and checksum. |
| `uncertainties` | array | Machine-readable gaps, conflicts and handoffs. Empty only when there are no known limits. |
| `change_log` | array | Reproducible provenance of finalisation actions; records that source text was not rewritten. |
| `validation` | object | Deterministic validation state: `valid`, `errors`, `warnings`. |
| `case_contract` | object | Original case contract and case-file path, retained for audit. |
| `generated_at` | ISO-8601 string | UTC generation time. |
| `generator` | object | Tool name/version and source-index path. |

Any key named by the case's original `output_contract` is copied to the top
level and inside `task_output` when task-specific data exists.

The finaliser also writes `assertions.jsonl` and `sources.jsonl` for streaming
downstream consumers and `evidence_audit.json` for a compact human review.

## Assertion record

| Field | Type | Meaning and rule |
|---|---|---|
| `assertion_id` | string | Stable per-result identifier such as `A001`. |
| `np_id` | URN string | Stable hash-derived ID bound to case, assertion text and source checksum. |
| `assertion.text` | string | One independently checkable proposition in the requested language. |
| `assertion.language` | string | `en`, `zh`, or another truthful language tag; `und` if undetermined. |
| `subject` | string | Entity, population, material or exposure being described. |
| `relation` | string | Predicate or controlled relation, e.g. `reduced relative to`, `associated with`, `did not alter`. |
| `relation_type` | enum | Normalised relation family from the controlled vocabulary below. |
| `object` | string | Outcome, comparator/value or target of the relation. |
| `scope` | object | Conditions that limit truth: model, sample, dose, time, comparator, setting, test. |
| `evidence` | array | One or more minimal source spans. At least one is required. |
| `provenance` | object | Primary source metadata plus all linked source records. |
| `confidence.score` | number | Tentative support confidence from 0 to 1. It is not a p-value. |
| `confidence.reason` | string | Why the score was assigned; mention directness and unresolved limits. |
| `quality_flags` | array | Controlled audit flags defined in `extraction-rules.md`. |

## Evidence record

| Field | Type | Meaning and rule |
|---|---|---|
| `quote` | string | Exact source text, with only whitespace normalised. |
| `source_id` | string | Must resolve to a `sources[].source_id`. |
| `relation` | enum | `supports`, `refutes`, `qualifies`, or `contextualizes`. |
| `evidence_type` | enum | `direct`, `indirect`, or `contextual`. |
| `location.page` | integer/null | One-based PDF page or `null` for a source without pagination. |
| `location.section` | string/null | Nearest explicit heading. `null` when unavailable. |
| `location.paragraph` | integer/null | One-based indexed paragraph/block on the page. |
| `location.char_start` | integer | Inclusive character offset in the extracted page text. |
| `location.char_end` | integer | Exclusive character offset in the extracted page text. |
| `location.visual_anchor` | string/null | Figure panel, table row, axis or OCR crop when visual evidence is used. |

Character offsets refer to the extraction stored in `work/source_index.json`.
This matters for exact audit; a later PDF extractor version can emit different
offsets. The source checksum and the text in the index pin that version.

## Uncertainty record

| Field | Type | Meaning |
|---|---|---|
| `code` | string | Stable machine-readable failure/limitation code. |
| `message` | string | What is missing, ambiguous or conflicting. |
| `handoff` | string/null | Concrete next check a person or stronger tool can perform. |

Core codes include `EVIDENCE_MISSING`, `EVIDENCE_QUOTE_NOT_FOUND`,
`EVIDENCE_LOCATION_AMBIGUOUS`, `EVIDENCE_SPAN_REVIEW`,
`TRIPLET_INCOMPLETE`, `ATOMICITY_REVIEW`, `CAUSAL_OVERREACH`,
`DUPLICATE_ASSERTION`, and author-declared domain limits.

## Change record

| Field | Type | Meaning |
|---|---|---|
| `change_id` | string | Stable sequence identifier such as `C001`. |
| `action` | string | Machine-readable action such as `evidence_locations_verified`. |
| `detail` | string | What changed and whether source/claim wording changed. |
| `timestamp` | ISO-8601 string | When the action was recorded. |

## Controlled relation vocabulary

| `relation_type` | Use when the assertion says |
|---|---|
| `increase` | X increased, rose, promoted, enhanced or upregulated Y. |
| `decrease` | X decreased, reduced, inhibited or downregulated Y. |
| `no_change` | X did not alter or did not differ from Y. |
| `positive_association` | Higher X corresponds to higher Y / direct association. |
| `negative_association` | Higher X corresponds to lower Y / inverse association. |
| `association` | Direction is unspecified or mixed. |
| `causal` | Evidence directly supports an intervention/mechanism effect. |
| `comparison` | A purely descriptive ordering or difference. |
| `prediction` | A forecast or model-derived tendency. |
| `method` | A procedure, measurement or availability statement. |
| `definition` | A term, class, scale or inclusion boundary. |
| `limitation` | A declared boundary or failure mode. |
| `other` | No controlled category applies; retain the literal predicate. |
