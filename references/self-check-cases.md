# Reusable self-check question set

These synthetic checks test the Skill, not a hidden evaluation case. They may
be run against any paper with known text.

1. **Atomic split**  
   Find one sentence with two independent outcomes. Verify that the output has
   two assertions, each with its own evidence and no merged `and` result.

2. **Scope preservation**  
   Select a subgroup result. Verify that sample, comparator and setting appear in
   the assertion or `scope`.

3. **Exact quote**  
   Add one character to an evidence quote. `finalize` must reject it, emit an
   `EVIDENCE_QUOTE_NOT_FOUND` uncertainty and produce a partial/unable result.

4. **Numeric direction**  
   Change `18%` to `28%` while keeping the source quote. Verify a
   `numeric_mismatch` flag, an error and non-success status.

5. **Association versus causation**  
   Use an `associated with` source and a `caused` draft. Verify a
   `causal_overreach` flag and a handoff.

6. **Figure anchor**  
   Ask for a panel-specific value. Verify that `visual_anchor` names the panel
   and that unreadable axis values are not guessed.

Acceptance for every check:

- `result.json` retains `case_id`;
- every emitted assertion has a source, page/location, confidence reason and ID;
- a human can find each quote in `source_index.json`;
- failure cases identify their limits instead of emitting fabricated certainty.
