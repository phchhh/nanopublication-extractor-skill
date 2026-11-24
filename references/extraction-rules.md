# Extraction rules

## Atomicity test

An assertion is atomic when one proposition cannot be split and still leave two
meaningful claims that can be checked independently. Apply these tests in order:

1. **Independent truth.** If "A and B" can remain true when B is false, emit two
   assertions.
2. **Separate relation.** If the clause uses two causal, comparative or
   correlational verbs, normally emit one assertion per relation.
3. **Shared scope.** Repeat a shared population, material, exposure, assay,
   timepoint, model or control in each atom when omitting it changes the claim.
4. **Numeric atom.** Keep a reported statistic with the outcome and comparator
   needed to interpret it. A p-value, confidence interval or sample size is a
   separate assertion only when the source evaluates it as a result, not when
   it merely qualifies another assertion.
5. **Do not atomise metadata.** Authorship, journal, figure numbers and
   bibliographic details belong in provenance unless the task asks about them.

Good:

- "In adult mice, treatment X reduced tumour volume versus vehicle."
- "The reduction in tumour volume was 38% (p = 0.02)."

Bad:

- "Treatment X reduced tumour volume by 38% and was safe."  
  This contains two independently checkable outcomes and an unqualified safety
  claim.

## Faithfulness and scope

Preserve these qualifiers whenever present:

- organism, cell line, material, sample size and subgroup;
- dose, intervention, comparator, assay and model;
- timepoint, follow-up and experimental setting;
- effect direction, magnitude, precision and statistical test;
- "in vitro", "preclinical", "associated with" and other scope limits.

Do not convert:

- `associated with` into `causes`;
- `reduced X` into `eliminated X`;
- `in these samples` into a universal statement;
- a trend or non-significant change into a confirmed effect;
- a prediction or hypothesis into an observed result.

## Evidence selection

Choose the shortest contiguous span that independently tells a reader why the
assertion is true. Usually this is one sentence or a table caption plus the
relevant row. Retain a preceding sentence only when it defines the comparator
or study condition.

For every quote, copy the source text exactly. Whitespace differences are
normalised by the finaliser; wording, punctuation, signs and numbers are not.
Use direct evidence for a reported result and indirect evidence only for a
clearly labelled inference. Use contextual evidence for definitions,
limitations and study background.

When a figure is necessary:

1. bind the caption;
2. name the panel, axis, series or row;
3. state whether the text came from OCR, alt text or a visual reading;
4. record a page crop or figure identifier in `location.visual_anchor`;
5. keep visual readings `partial` if labels or error bars cannot be resolved.

## Numbers and comparisons

- Keep units and signs attached to the value.
- Do not recompute a rounded number unless the task asks for reproducibility.
- Record numerator and denominator when available.
- Treat "n.s.", `p > 0.05`, confidence intervals crossing zero, and absence of
  a reported test as different states.
- A percentage change and an absolute change are separate values.
- Mark inferred transformations with `inferred` and preserve the source value
  in the evidence quote.

## Claim quality flags

Use these controlled flags:

| Flag | Meaning |
|---|---|
| `overbroad` | Scope is wider than the sampled material or population. |
| `causal_overreach` | Associational evidence was stated causally. |
| `numeric_mismatch` | A sign, value, unit or comparator differs from evidence. |
| `negation_risk` | Negation or direction is ambiguous. |
| `compound` | More than one independently checkable proposition remains. |
| `figure_only` | Support depends on a visual element, not caption text alone. |
| `table_context` | A table header/caption is essential to interpret the quote. |
| `ocr` | Evidence contains OCR-derived text. |
| `translation` | Claim was translated; preserve the original-language quote. |
| `contradicted` | Credible source passages conflict. |
| `inferred` | Claim is a reasoning step beyond a direct statement. |

## Status policy

- `success`: requested output is complete, every assertion has verified direct
  or explicitly typed indirect evidence, and validation passes.
- `partial`: a useful result exists, but at least one requested item, page,
  panel or provenance field is unavailable or unresolved.
- `unable`: the source is unreadable/missing or the task asks for information
  the source cannot support.

The status describes the run, not whether the paper's hypothesis was true.
