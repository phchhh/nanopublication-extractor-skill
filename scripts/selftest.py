#!/usr/bin/env python3
"""Run an isolated positive and negative smoke test for nanopub.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path


HERE = Path(__file__).resolve().parent
CLI = HERE / "nanopub.py"


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(*args: str, expect: int = 0) -> dict:
    process = subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if process.returncode != expect:
        raise AssertionError(
            f"Expected exit {expect}, got {process.returncode}\n"
            f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}"
        )
    return json.loads(process.stdout)


def main() -> int:
    configured_root = os.environ.get("NANOPUB_SELFTEST_DIR")
    if configured_root:
        temp_root = Path(configured_root)
    elif Path("/app/work").is_dir():
        temp_root = Path("/app/work")
    else:
        temp_root = Path.cwd() / "work"
    temp_root.mkdir(parents=True, exist_ok=True)
    run_root = temp_root / f".nanopub-selftest-{os.getpid()}"
    run_root.mkdir(parents=True, exist_ok=True)
    with nullcontext(str(run_root)) as temp:
        root = Path(temp)
        input_dir = root / "input"
        output_dir = root / "output"
        input_dir.mkdir()
        case_path = input_dir / "case.json"
        write_json(case_path, {
            "case_id": "selftest",
            "output_contract": {
                "answer": "string",
                "assertions": "array",
                "source_notes": "array",
            },
        })
        (input_dir / "task.md").write_text(
            "Extract the principal result as an atomic assertion.\n", encoding="utf-8"
        )
        (input_dir / "paper.txt").write_text(
            "Results\n\nAt 24 h, treatment reduced the measured marker by 18% "
            "relative to vehicle (n = 12; p = 0.03). Treatment did not alter "
            "body weight.\n",
            encoding="utf-8",
        )
        draft_path = root / "claims.json"
        write_json(draft_path, {
            "status": "success",
            "task_output": {"answer": "The treatment reduced the marker at 24 h.", "source_notes": []},
            "assertions": [{
                "assertion": {
                    "text": "At 24 h, treatment reduced the measured marker by 18% relative to vehicle.",
                    "language": "en",
                },
                "subject": "treatment",
                "relation": "reduced relative to",
                "object": "measured marker (18%)",
                "scope": {"timepoint": "24 h", "comparator": "vehicle"},
                "evidence": [{
                    "quote": "At 24 h, treatment reduced the measured marker by 18% relative to vehicle (n = 12; p = 0.03).",
                    "relation": "supports",
                    "evidence_type": "direct",
                }],
                "confidence": {"score": 0.98, "reason": "Direct result with comparator."},
                "quality_flags": [],
            }],
        })
        prepared = run(
            "prepare", "--case", str(case_path), "--input", str(input_dir),
            "--out", str(output_dir), "--work", str(root / "work"),
        )
        index_path = root / "work" / "source_index.json"
        finalized = run(
            "finalize", "--case", str(case_path), "--draft", str(draft_path),
            "--index", str(index_path), "--out", str(output_dir),
        )
        validated = run("validate", "--result", str(output_dir / "result.json"))
        result = json.loads((output_dir / "result.json").read_text(encoding="utf-8"))
        assert prepared["sources"] == 1
        assert finalized["status"] == "success"
        assert validated["valid"] is True
        assert result["assertions"][0]["relation_type"] == "decrease"
        assert result["change_log"]
        assert (output_dir / "assertions.jsonl").exists()
        assert (output_dir / "sources.jsonl").exists()
        assert (output_dir / "evidence_audit.json").exists()

        broken_path = root / "broken.json"
        broken_assertions = json.loads(json.dumps(result["assertions"]))
        broken_assertions[0]["evidence"][0]["quote"] += " altered"
        write_json(broken_path, {
            "status": "success",
            "task_output": result["task_output"],
            "assertions": broken_assertions,
        })
        negative = run(
            "finalize", "--case", str(case_path), "--draft", str(broken_path),
            "--index", str(index_path), "--out", str(root / "negative"),
            expect=1,
        )
        assert negative["valid"] is False

    print(json.dumps({
        "status": "pass",
        "positive_case": "decrease / exact quote / valid result",
        "negative_case": "altered quote rejected",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
