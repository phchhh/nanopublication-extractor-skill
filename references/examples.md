# Examples and 20 assertion samples

These are illustrative, not prepared answers for evaluation cases. All quotes
are synthetic.

## Minimal draft

```json
{
  "status": "success",
  "task_output": {
    "answer": "At 24 h, treatment reduced the measured marker relative to vehicle."
  },
  "assertions": [
    {
      "assertion": {
        "text": "At 24 h, treatment reduced the measured marker relative to vehicle.",
        "language": "en"
      },
      "subject": "treatment",
      "relation": "reduced relative to",
      "object": "measured marker",
      "scope": {
        "timepoint": "24 h",
        "comparator": "vehicle"
      },
      "evidence": [
        {
          "quote": "At 24 h, treatment reduced the measured marker by 18% relative to vehicle (n = 12; p = 0.03).",
          "source_id": "src-abc123",
          "relation": "supports",
          "evidence_type": "direct"
        }
      ],
      "confidence": {
        "score": 0.96,
        "reason": "The result and comparator are stated directly in the evidence."
      },
      "quality_flags": []
    }
  ]
}
```

The finaliser adds IDs, exact locations, metadata and validation fields.

## Twenty atomicity/evidence patterns

1. **Direct effect**  
   Claim: "Compound C reduced apoptosis in treated cultures."  
   Evidence: "Compound C reduced the fraction of annexin-V-positive cells."  
   Keep the assay and direction.

2. **Split conjunction**  
   Source: "Compound C reduced apoptosis and increased proliferation."  
   Emit two claims because either result can be checked independently.

3. **Comparator scope**  
   Claim: "The treated group had lower mean weight than the vehicle group."  
   Do not drop `than the vehicle group`.

4. **Non-significance**  
   Claim: "The reported difference was not statistically significant."  
   Evidence: "The difference was not statistically significant (p = 0.08)."  
   Do not turn this into evidence that the groups were equivalent.

5. **Association only**  
   Source: "Higher exposure was associated with shorter survival."  
   Preserve association; flag `causal_overreach` if a draft says exposure caused
   shorter survival.

6. **Preclinical scope**  
   Claim: "In mice, the treatment reduced tumour growth."  
   Do not generalise to humans.

7. **Numeric precision**  
   Claim: "The inhibition was 42%."  
   Keep `42%`, its comparator and assay; do not silently substitute `approximately
   40%`.

8. **Confidence interval**  
   Claim: "The hazard ratio was 0.71 (95% CI 0.55-0.92)."  
   Keep the interval; it is part of the reported result.

9. **Sample size**  
   Claim: "The analysis included 128 participants."  
   Bind to the analysis population, not merely the recruited sample.

10. **Negative result**  
    Claim: "No measurable change was detected under condition X."  
    Preserve the detection assay and condition; do not infer biological absence.

11. **Trend language**  
    Source: "Values tended to increase over time."  
    Do not state a confirmed increase without a reported test.

12. **Mechanism claim**  
    Claim: "Knockdown reduced pathway activity through loss of protein P."  
    Require evidence for both the effect and the mediating mechanism; split if
    the source reports two experimentally distinct findings.

13. **Contrasting groups**  
    Claim: "Effect X was larger in subgroup A than subgroup B."  
    Include both subgroup labels and any interaction-test status.

14. **Time-dependent result**  
    Claim: "The marker remained elevated at day 7."  
    Keep day 7 and the baseline/comparison needed for `elevated`.

15. **Table result**  
    Claim: "Condition B had the highest observed yield."  
    Bind the table caption and row; record `table_context`.

16. **Figure-only result**  
    Claim: "Panel b shows an increase in channel Y."  
    Use an explicit visual anchor and `figure_only`; keep status partial if the
    axis values cannot be read.

17. **Contradiction**  
    Two passages report opposite directions. Emit separately evidenced claims
    and a `contradicted` uncertainty; do not average them.

18. **Translation**  
    Translate the assertion for the requested output, but preserve the exact
    original-language quote as evidence and add `translation`.

19. **Definition/context**  
    Claim: "The score ranges from 0 to 10."  
    Mark contextual evidence; do not present it as an experimental result.

20. **Unsupported request**  
    Question asks for a human outcome in a cell-culture paper. Return `unable`
    or `partial`, quote the source scope, and state the missing evidence.

## Quality review

Before finalising, read every claim without its source. Ask:

- Could a reader identify the population, condition and comparator?
- Does each verb accurately reflect observation versus inference?
- Is every number and direction identical to the quote?
- Can each evidence span stand alone?
- Would removing one evidence sentence make the claim unsupported?
- Does the top-level answer add any fact absent from the assertions?
