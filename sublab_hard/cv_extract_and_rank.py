"""Sublab Hard - stories in, CVs out, the best candidate by code.

Part 1  the model extracts one CV record per story, under rules written in the prompt;
        the code validates it and checks what it can check (quotes, arithmetic, traps).
Part 2  the model scores each record 0-5 on the three rubric criteria - and nothing else;
        the code computes the weighted totals, the ranking and the winner.
        A separate call asks the model, in prose, who should win.

    python -m sublab_hard.cv_extract_and_rank
    python -m sublab_hard.cv_extract_and_rank --base-rules-only   # without the rules I had to add
"""
from __future__ import annotations

import argparse
import json
import re

from jsonschema import Draft202012Validator

from common import (DATA, OUTPUTS, PROVIDER, call, call_json, load_json, md_table, save_output,
                    use_groq_model)

MODEL = use_groq_model("qwen/qwen3.8-27b")

RUBRIC = load_json("candidate_rubric.json")
WEIGHTS = {c["id"]: c["weight"] for c in RUBRIC["criteria"]}
STORIES = {p.stem: p.read_text(encoding="utf-8") for p in sorted((DATA / "candidates").glob("story-*.md"))}

# --- Part 1: the record --------------------------------------------------------

NUM_OR_NULL = {"type": ["number", "null"]}
INT_OR_NULL = {"type": ["integer", "null"]}
STR_OR_NULL = {"type": ["string", "null"]}

CV_SCHEMA = {
    "type": "object",
    "properties": {
        "candidate_id": {"type": "string"},
        "full_name": STR_OR_NULL,
        "degree": STR_OR_NULL,
        "graduation_year": INT_OR_NULL,
        "gpa_4_scale": NUM_OR_NULL,
        "gpa_original": NUM_OR_NULL,
        "gpa_original_scale": NUM_OR_NULL,
        "languages": {"type": "array", "items": {"type": "string"}},
        "published_outputs": {"type": "array", "items": {
            "type": "object",
            "properties": {"title": STR_OR_NULL, "venue": STR_OR_NULL, "year": INT_OR_NULL,
                           "peer_reviewed": {"type": ["boolean", "null"]}},
            "required": ["title", "venue", "year", "peer_reviewed"]}},
        "published_count": {"type": "integer", "minimum": 0},
        "unpublished_outputs": {"type": "array", "items": {
            "type": "object",
            "properties": {"title": STR_OR_NULL, "status": {"type": "string"}},
            "required": ["title", "status"]}},
        "experience_periods": {"type": "array", "items": {
            "type": "object",
            "properties": {"role": STR_OR_NULL, "start": STR_OR_NULL, "end": STR_OR_NULL,
                           "months": INT_OR_NULL, "countable": {"type": "boolean"}},
            "required": ["role", "start", "end", "months", "countable"]}},
        "experience_months_countable": INT_OR_NULL,
        "ambiguities": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "object", "additionalProperties": STR_OR_NULL},
    },
    "required": ["candidate_id", "full_name", "degree", "graduation_year", "gpa_4_scale", "gpa_original",
                 "gpa_original_scale", "languages", "published_outputs", "published_count",
                 "unpublished_outputs", "experience_periods", "experience_months_countable",
                 "ambiguities", "evidence"],
    "additionalProperties": False,
}
CV_VALIDATOR = Draft202012Validator(CV_SCHEMA)

# The four rules the README requires. They go in the prompt word for word.
BASE_RULES = [
    "A fact the story does not state is null. Never estimated. No GPA means no GPA - not an inferred one.",
    "A GPA on another scale is converted to a 4.0 scale (gpa_4_scale = gpa_original / gpa_original_scale * 4, "
    "rounded to two decimals), and the original value and scale are recorded beside it in gpa_original and "
    "gpa_original_scale. A GPA already on a 4.0 scale has gpa_original_scale 4.",
    "A paper is published only when the story says published or accepted. Submitted, under review, in "
    "preparation, planned and in press are NOT published: record them in unpublished_outputs with their "
    "status, and do not count them in published_count.",
    "Contradictions are not resolved and not averaged: if the story gives two different values for a field, "
    "that field is null, and the contradiction is recorded in ambiguities with both values quoted.",
]

# The rules I had to add. Each one is here because a base-rules-only run broke on a
# story (outputs/hard_base_rules.log); rules that changed nothing were left out.
EXTRA_RULES = [
    # story-06: "I graduated in 2024 ... I am currently a final-year student graduating in 2026".
    # With the base rules the model listed this contradiction in ambiguities and still wrote 2024.
    "The contradiction rule applies to EVERY field, not only the GPA - dates included. A story that says "
    "the candidate graduated in one year and also that they are still graduating in another year has "
    "graduation_year null, with both years in ambiguities. Listing a contradiction in ambiguities while "
    "filling the field with one of its values is not allowed.",
    # Base-rules-only runs over-applied the contradiction rule to month counts:
    #  - qwen, story-01: "October 2023 to May 2024, eight months in total" - 7 by subtraction, 8 stated;
    #    the model called that ambiguous and marked the period not countable: 0 months, experience 0.
    #  - gpt-oss-20b, story-06: "since February 2023, which is about forty months" - "about" was
    #    treated as a contradiction: months null, total null.
    "An approximate figure is not a contradiction. A period with a stated start and a stated approximate "
    "length ('about forty months') is countable: use the stated number of months and note the "
    "approximation in ambiguities. When the story states the number of months for a period, use it; "
    "compute from dates only when no number is given. A period marked countable must have its months filled, "
    "and experience_months_countable is the sum of the countable periods (overlaps counted once).",
]

RECORD_SHAPE = """\
Return one JSON object with exactly these fields:
- candidate_id (string, given to you)
- full_name, degree (strings or null)
- graduation_year (integer or null)
- gpa_4_scale, gpa_original, gpa_original_scale (numbers or null)
- languages (array of strings)
- published_outputs: array of {title, venue, year, peer_reviewed (true/false/null)} - published or accepted only
- published_count (integer) - the length of published_outputs
- unpublished_outputs: array of {title, status} - submitted, under review, in preparation, planned, in press...
- experience_periods: array of {role, start, end, months, countable}; start/end as written (e.g. "2023-10") or null
- experience_months_countable (integer or null)
- ambiguities: array of strings - every contradiction, approximation or thing you could not decide
- evidence: object mapping each field you filled (full_name, degree, graduation_year, gpa, languages,
  published_count, experience_months_countable) to a word-for-word quote from the story, or null if the field is null
Reply with the JSON object only."""


def extraction_prompt(base_only: bool) -> str:
    rules = BASE_RULES + ([] if base_only else EXTRA_RULES)
    numbered = "\n".join(f"{i}. {r}" for i, r in enumerate(rules, 1))
    return ("You turn a scholarship candidate's written story into a structured CV record.\n\n"
            f"Rules - follow every one:\n{numbered}\n\n{RECORD_SHAPE}")


# What I read in the stories myself: the answer key the trap check compares against.
# None means "must be null". This is the human reading, not a model output.
ANSWER_KEY = {
    "story-01": {"traps": [], "gpa_4_scale": 3.8, "published_count": 2, "months": 8},
    "story-02": {"traps": ["no GPA stated"], "gpa_4_scale": None, "published_count": 1, "months": 36},
    "story-03": {"traps": ["GPA on another scale", "unpublished paper"], "gpa_4_scale": 3.68,
                 "published_count": 1, "months": 14},
    "story-04": {"traps": ["unpublished paper"], "gpa_4_scale": 3.6, "published_count": 1, "months": 24},
    "story-05": {"traps": ["unpublished paper", "story in Kazakh"], "gpa_4_scale": 3.9,
                 "published_count": 1, "months": 6},
    # "about forty months" since February 2023: the stated approximate figure.
    "story-06": {"traps": ["contradicts itself"], "gpa_4_scale": None, "published_count": 1,
                 "graduation_year": None, "months": 40},
}


def _squash(s: str) -> str:
    s = re.sub(r"[*_`#>]", "", s)                  # markdown emphasis is not part of the words
    s = s.replace("’", "'").replace("—", "-").replace("–", "-")
    # A quote may end on a full stop where the story has a comma; the words are what is checked.
    return re.sub(r"\s+", " ", s).strip(" .,;:!?").lower()


def code_checks(story_id: str, rec: dict) -> dict:
    """What the code can verify without trusting the model."""
    story = _squash(STORIES[story_id])
    bad_quotes = [k for k, q in (rec.get("evidence") or {}).items()
                  if isinstance(q, str) and q.strip() and _squash(q) not in story]

    gpa_issue = None
    g4, go, gs = rec.get("gpa_4_scale"), rec.get("gpa_original"), rec.get("gpa_original_scale")
    if go is not None and gs:
        expected = round(go / gs * 4, 2)
        if g4 is None or abs(g4 - expected) > 0.011:
            gpa_issue = f"gpa_4_scale {g4} but {go}/{gs}*4 = {expected}"
    elif g4 is not None and go is None:
        gpa_issue = "gpa_4_scale without the original value"

    pubs = rec.get("published_outputs") or []
    count_issue = None if rec.get("published_count") == len(pubs) else \
        f"published_count {rec.get('published_count')} but {len(pubs)} listed"

    months = sum(p.get("months") or 0 for p in rec.get("experience_periods") or [] if p.get("countable"))
    months_issue = None
    if rec.get("experience_months_countable") is not None and rec["experience_months_countable"] != months:
        months_issue = f"experience_months_countable {rec['experience_months_countable']} but countable periods sum to {months}"

    key = ANSWER_KEY[story_id]
    trap_results = []
    if "gpa_4_scale" in key:
        got = rec.get("gpa_4_scale")
        want = key["gpa_4_scale"]
        ok = (got is None) if want is None else (got is not None and abs(got - want) <= 0.011)
        trap_results.append(("gpa_4_scale", want, got, ok))
    trap_results.append(("published_count", key["published_count"], rec.get("published_count"),
                         rec.get("published_count") == key["published_count"]))
    trap_results.append(("experience months", key["months"], rec.get("experience_months_countable"),
                         rec.get("experience_months_countable") == key["months"]))
    if "graduation_year" in key:
        got = rec.get("graduation_year")
        trap_results.append(("graduation_year", None, got, got is None))
    if story_id == "story-06":
        amb = " | ".join(rec.get("ambiguities") or [])
        flagged = "3.2" in amb and "3.5" in amb
        trap_results.append(("GPA contradiction in ambiguities", True, flagged, flagged))

    return {"bad_quotes": bad_quotes, "gpa_issue": gpa_issue, "count_issue": count_issue,
            "months_issue": months_issue, "trap_results": trap_results}


def extract_all(base_only: bool) -> dict:
    system = extraction_prompt(base_only)
    out = {}
    for sid, story in STORIES.items():
        msgs = [{"role": "system", "content": system},
                {"role": "user", "content": f"candidate_id: {sid}\n\nThe story:\n\n{story}"}]
        reply, rec, err, failures = call_json(msgs)
        errors = [] if rec is None else \
            [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in CV_VALIDATOR.iter_errors(rec)]
        entry = {"parsed": rec is not None, "parse_error": err, "failures": failures,
                 "valid": rec is not None and not errors, "schema_errors": errors, "record": rec,
                 "prompt_tokens": reply.prompt_tokens if reply else None}
        if isinstance(rec, dict):
            entry["checks"] = code_checks(sid, rec)
            entry["null_fields"] = [k for k in CV_SCHEMA["required"] if rec.get(k) is None]
        out[sid] = entry
        print(f"  {sid}: parsed={entry['parsed']} valid={entry['valid']}"
              f"{'  retried: ' + '; '.join(failures) if failures else ''}", flush=True)
    return out


def extraction_report(ex: dict) -> None:
    rows = []
    for sid, e in ex.items():
        if not e["parsed"]:
            rows.append([sid, "NO", "-", "-", "-", e["parse_error"]])
            continue
        c = e["checks"]
        traps = ANSWER_KEY[sid]["traps"] or ["none (control)"]
        handled = [f"{name}: want {want}, got {got} {'✓' if ok else '✗'}" for name, want, got, ok in c["trap_results"]]
        problems = [p for p in (c["gpa_issue"], c["count_issue"], c["months_issue"]) if p]
        if c["bad_quotes"]:
            problems.append("quote not in story: " + ", ".join(c["bad_quotes"]))
        rows.append([sid, "yes", "yes" if e["valid"] else "NO: " + "; ".join(e["schema_errors"][:2]),
                     ", ".join(e["null_fields"]) or "none", "; ".join(traps),
                     "; ".join(handled) + (" · CODE FLAGS: " + "; ".join(problems) if problems else "")])
    print(md_table(["Story", "Parsed?", "Valid?", "Fields that came back null", "Traps in the story",
                    "Trap checks (✓ handled / ✗ hit) and code flags"], rows))


# --- Part 2: scores from the model, everything else in code ---------------------

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "candidate_id": {"type": "string"},
        "academic": {"type": "integer", "minimum": 0, "maximum": 5},
        "research": {"type": "integer", "minimum": 0, "maximum": 5},
        "experience": {"type": "integer", "minimum": 0, "maximum": 5},
        "notes": {"type": "string"},
    },
    "required": ["candidate_id", "academic", "research", "experience", "notes"],
    "additionalProperties": False,
}
SCORE_VALIDATOR = Draft202012Validator(SCORE_SCHEMA)

SCORER = f"""\
You score one scholarship candidate against a rubric, from their extracted CV record.

The rubric (criteria, weights and anchors):
{json.dumps(RUBRIC["criteria"], ensure_ascii=False, indent=1)}

Counting rules:
{json.dumps(RUBRIC["counting_rules"], ensure_ascii=False, indent=1)}

How to score:
- Give an integer from 0 to 5 for each of the three criteria. 0 and 5 mean what the anchors say; place
  everything else between them in proportion.
- Score only from the record. A null field counts as not stated.
- A field that is null because the story contradicts itself (see ambiguities) is not stated: do not pick
  one of the contradicting values and do not average them. Say in notes that you did this.
- Do not compute a weighted total, a rank or a winner. Return the three scores only.

Return one JSON object: {{"candidate_id": ..., "academic": int, "research": int, "experience": int,
"notes": one or two sentences on how you placed each score}}."""


def score_all(ex: dict) -> dict:
    out = {}
    for sid, e in ex.items():
        if not e["valid"]:
            out[sid] = {"error": "no valid record to score"}
            continue
        msgs = [{"role": "system", "content": SCORER},
                {"role": "user", "content": json.dumps(e["record"], ensure_ascii=False, indent=1)}]
        reply, obj, err, failures = call_json(msgs)
        errors = [] if obj is None else [e2.message for e2 in SCORE_VALIDATOR.iter_errors(obj)]
        out[sid] = {"scores": obj, "error": err or ("; ".join(errors) if errors else None), "failures": failures}
        print(f"  {sid}: {obj and {k: obj.get(k) for k in WEIGHTS}}", flush=True)
    return out


def weighted_total(s: dict) -> float:
    """The rubric's rule, computed here and nowhere else."""
    return round(sum(WEIGHTS[c] * s[c] for c in WEIGHTS), 2)


def enforce_rules(record: dict, s: dict) -> tuple[dict, list[str]]:
    """The rubric's counting rules that leave no room for judgement, applied in code.

    The model places everything between the anchors; where the rubric states the
    score outright, the code checks it and overrides a score that breaks it.
    """
    final = {c: s[c] for c in WEIGHTS}
    overrides = []

    def force(criterion, value, why):
        if final[criterion] != value:
            overrides.append(f"{criterion} {final[criterion]}→{value} ({why})")
            final[criterion] = value

    if record.get("gpa_4_scale") is None:
        force("academic", 0, "no usable GPA: 'a story with no GPA scores 0 on academic'")
    pubs = record.get("published_count")
    if pubs == 0:
        force("research", 0, "none published")
    elif pubs is not None and pubs >= 2:
        force("research", 5, "two or more published")
    months = record.get("experience_months_countable")
    if not months:
        force("experience", 0, "no countable months")
    elif months >= 24:
        force("experience", 5, f"{months} months >= 24")
    return final, overrides


def rank(final_scores: dict) -> list[tuple[str, float, dict]]:
    ranked = [(sid, weighted_total(f), f) for sid, f in final_scores.items()]
    # Ties broken by academic, then research (the heavier weights first), then id - stated, not hidden.
    ranked.sort(key=lambda t: (-t[1], -t[2]["academic"], -t[2]["research"], t[0]))
    return ranked


def prose_verdict() -> str:
    stories = "\n\n".join(f"=== {sid} ===\n{text}" for sid, text in STORIES.items())
    msgs = [{"role": "system", "content": "You advise a scholarship committee. Answer in prose, not JSON."},
            {"role": "user", "content":
                f"One funded place, six candidates. The rubric:\n{json.dumps(RUBRIC['criteria'], ensure_ascii=False)}\n"
                f"Counting rules:\n{json.dumps(RUBRIC['counting_rules'], ensure_ascii=False)}\n\n"
                f"The six stories:\n\n{stories}\n\n"
                "Which candidate should win the funded place, and why? Name one candidate, then give your "
                "reasons in a short paragraph, and say who came second."}]
    return call(msgs).text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-rules-only", action="store_true",
                    help="extract with only the four README rules, to see what breaks without the added ones")
    ap.add_argument("--reuse-extraction", action="store_true",
                    help="skip Part 1 calls and score the records saved in outputs/hard_extraction.json")
    args = ap.parse_args()
    print(f"Provider: {PROVIDER}   Model: {MODEL}   rules: {'base only' if args.base_rules_only else 'base + added'}")

    print("\n=== Part 1 - extraction ===")
    saved = OUTPUTS / "hard_extraction.json"
    if args.reuse_extraction and saved.exists():
        ex = json.loads(saved.read_text(encoding="utf-8"))
        for sid, e in ex.items():          # re-run the code checks: they are code, not calls
            if isinstance(e.get("record"), dict):
                e["checks"] = code_checks(sid, e["record"])
        print(f"  (reusing {saved.name})")
    else:
        ex = extract_all(args.base_rules_only)
    print()
    extraction_report(ex)

    if args.base_rules_only:
        save_output("hard_extraction_base_rules.json", ex)
        print("\nSaved outputs/hard_extraction_base_rules.json (scoring skipped in this mode)")
        return
    save_output("hard_extraction.json", ex)

    print("\n### Extraction for story-06 (the one that contradicts itself)\n")
    print(json.dumps(ex["story-06"]["record"], ensure_ascii=False, indent=2))

    print("\n=== Part 2 - scores (model) and totals (code) ===")
    scores = score_all(ex)
    final, overrides = {}, {}
    for sid, v in scores.items():
        if v.get("scores") and not v.get("error"):
            final[sid], overrides[sid] = enforce_rules(ex[sid]["record"], v["scores"])
    ranked = rank(final)
    if not ranked:
        print("\nNo candidate could be scored - no winner. Errors:")
        for sid, v in scores.items():
            print(f"  {sid}: {v.get('error')}")
        return
    print()
    rows = []
    for sid in STORIES:
        s = scores[sid].get("scores")
        if sid not in final:
            rows.append([sid, "-", "-", "-", "-", f"not scored: {scores[sid].get('error')}"])
            continue
        f = final[sid]
        cell = lambda c: f"{f[c]}" if f[c] == s[c] else f"{f[c]} (model: {s[c]})"
        rows.append([sid, cell("academic"), cell("research"), cell("experience"),
                     f"{weighted_total(s):.2f}", f"{weighted_total(f):.2f}"])
    print(md_table(["Candidate", "academic (0–5)", "research (0–5)", "experience (0–5)",
                    "total on the model's scores", "weighted total (code, rules enforced)"], rows))
    print("\nOverrides made by the code (counting rules the model broke):")
    for sid, o in overrides.items():
        print(f"  {sid}: {'; '.join(o) if o else 'none'}")

    raw_rank = sorted(final, key=lambda sid: -weighted_total(scores[sid]["scores"]))
    print("\nRanking on the model's raw scores: "
          + " > ".join(f"{sid} {weighted_total(scores[sid]['scores']):.2f}" for sid in raw_rank))
    print("Ranking (code, rules enforced):   " + " > ".join(f"{sid} {t:.2f}" for sid, t, _ in ranked))
    winner, top = ranked[0][0], ranked[0][1]
    gap = round(top - ranked[1][1], 2) if len(ranked) > 1 else None
    print(f"\n**Winner, computed by my code:** {winner} "
          f"({ex[winner]['record'].get('full_name')}), weighted total {top:.2f}")
    if gap is not None:
        print(f"Gap to second ({ranked[1][0]}): {gap:.2f}"
              + ("  ← within 0.05: too close to call on these scores alone" if gap <= 0.05 else ""))
    for (a, ta, _), (b, tb, _) in zip(ranked, ranked[1:]):
        if ta == tb:
            print(f"Tie: {a} and {b} both {ta:.2f}; order decided by academic, then research, then id.")
    print("\nModel notes per candidate:")
    for sid in STORIES:
        s = scores[sid].get("scores") or {}
        print(f"  {sid}: {s.get('notes')}")

    print("\n=== The model's prose answer, asked separately ===\n")
    prose = prose_verdict()
    print(prose)

    save_output("hard_results.json", {"model": MODEL, "extraction": ex, "scores": scores,
                                      "final_scores": final, "overrides": overrides,
                                      "ranking": [(sid, t) for sid, t, _ in ranked], "winner": winner,
                                      "gap_to_second": gap, "prose": prose})
    print("\nSaved outputs/hard_results.json")


if __name__ == "__main__":
    main()
