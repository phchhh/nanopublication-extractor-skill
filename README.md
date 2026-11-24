# Nanopublication Extractor Skill

An installable Codex Skill for converting scientific papers, reports, and
extracted research materials into atomic, source-traceable nanopublication
assertions.

The Skill combines semantic claim decomposition with deterministic evidence
verification:

- page-aware PDF, text, DOCX, HTML, and JSON indexing;
- exact quote matching with page, paragraph, and character offsets;
- subject-relation-object records and a controlled relation vocabulary;
- source metadata and checksum provenance;
- direct, indirect, and contextual evidence types;
- numeric, causal, scope, negation, duplication, and atomicity checks;
- `result.json`, JSONL exports, an evidence audit, honest uncertainty records,
  and a revision log;
- explicit handling for scanned pages, figure panels, unsupported requests, and
  incomplete evidence.

## Start here

- [Skill instructions](SKILL.md)
- [Field dictionary](references/field-dictionary.md)
- [Extraction rules](references/extraction-rules.md)
- [20 assertion examples](references/examples.md)
- [Self-check cases](references/self-check-cases.md)
- [Output JSON Schema](references/output_schema.json)
- [Workflow diagram](assets/workflow.png)

## Quick check

```bash
python scripts/selftest.py
```

The self-test creates isolated synthetic material, verifies a successful
extraction, and confirms that a corrupted evidence quote is rejected.

## Scope

This repository contains the reusable Skill and its supporting resources. It
does not contain hidden evaluation papers, prepared evaluation answers, or
unreported benchmark scores.
