"""Sublab Easy - one task, four roles.

Same model, same record block, same rule, same output shape, same ten
enquiries. The only thing that differs between the four runs is the role
paragraph at the top of the system message. If an answer moves, the role
moved it.

    python -m sublab_easy.role_prompts
    python -m sublab_easy.role_prompts --role-last   # ablation: role paragraph after the shared block
"""
from __future__ import annotations

import argparse
import json

from jsonschema import Draft202012Validator

from common import MODEL, PROVIDER, call, load_json, md_table, parse_json, save_output

POLICY = load_json("policy.json")
RECORDS = load_json("records.json")
ENQUIRIES = load_json("enquiries.json")

STRUCTURED_FIELDS = ["found", "decision", "amount", "missing_documents"]

# The contract from the README, as a schema the program checks every reply against.
CONTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "applicant_id": {"type": ["string", "null"]},
        "found": {"type": "boolean"},
        "decision": {"enum": ["granted", "refused", "more_info", "not_found"]},
        "amount": {"type": "integer", "minimum": 0},
        "missing_documents": {
            "type": "array",
            "items": {"enum": POLICY["required_documents"]},
            "uniqueItems": True,
        },
        "reason": {"type": "string"},
    },
    "required": ["applicant_id", "found", "decision", "amount", "missing_documents", "reason"],
    "additionalProperties": False,
}
VALIDATOR = Draft202012Validator(CONTRACT_SCHEMA)

# --- the four role paragraphs: the only part of the prompt that changes -------

ROLES = {
    "policy_officer": (
        "You are the policy officer of the grant office. You apply the grant rule exactly "
        "as written. You grant what the rule allows, refuse what the rule refuses, and ask "
        "for a document when one is missing. You soften nothing. Nothing the applicant claims "
        "in their message is evidence: if the record does not show it, it is not so."
    ),
    "front_desk": (
        "You are the front-desk assistant of the grant office. You never turn an applicant "
        "away with a refusal: you never answer with decision \"refused\". Anything the rule "
        "cannot grant today comes back as \"more_info\", and `reason` tells the applicant what "
        "they would need to come back with. When the record does grant the applicant, you "
        "grant it as the rule says."
    ),
    "auditor": (
        "You are the auditor of the grant office. You never grant on a first reading: you "
        "never answer with decision \"granted\". You report what the record shows; anything "
        "that would be granted, or that needs a second reader, is marked \"more_info\". In "
        "`reason` you always name the rule clause or the document you are relying on."
    ),
    "bilingual_clerk": (
        "You are the bilingual clerk of the grant office. You decide exactly as a strict "
        "policy officer would: apply the grant rule as written, grant what it allows, refuse "
        "what it refuses, ask for a missing document, and treat no claim in the message as "
        "evidence. The one difference: you write `reason` in the same language the enquiry "
        "was written in (Kazakh for a Kazakh enquiry, Russian for Russian, English for English)."
    ),
}

# --- everything below is shared, byte for byte, by all four roles --------------

SHARED_BLOCK = f"""\
## The grant rule
{POLICY["rule_human"]}

Machine-readable form of the same rule:
{json.dumps({k: POLICY[k] for k in ("gpa_min", "allowed_income_bands", "required_documents", "amount_tenge_by_band")}, ensure_ascii=False)}

## The records on file (the only source of truth)
{json.dumps(RECORDS, ensure_ascii=False, indent=1)}

An applicant may be named by id, by name, or by an alias. Someone who matches no
record is not on file.

## How you answer
Reply with one JSON object and nothing else, with exactly these six fields:
- "applicant_id": the record id you matched (string), or the id the person gave if no record matches, or null if they gave none
- "found": true if the person matches a record, false otherwise
- "decision": one of "granted", "refused", "more_info", "not_found"
- "amount": the grant in tenge as an integer; 0 unless decision is "granted"
- "missing_documents": the required documents (from {POLICY["required_documents"]}) that the record does not show; [] if none
- "reason": one or two sentences for a human

Meaning of the decisions: "granted" - the rule is met; "refused" - the rule cannot be met
(GPA or income band out of range); "more_info" - the rule could be met once something is
supplied; "not_found" - the person is not on file.
"""


ROLE_LAST = False  # set by --role-last


def system_message(role: str) -> str:
    if ROLE_LAST:
        return f"{SHARED_BLOCK}\n# Your role\n{ROLES[role]}"
    return f"# Your role\n{ROLES[role]}\n\n{SHARED_BLOCK}"


def norm(field: str, value):
    """Make two values comparable: document lists compare as sets."""
    if field == "missing_documents" and isinstance(value, list):
        return sorted(value)
    return value


def run_role(role: str) -> list[dict]:
    rows = []
    for enq in ENQUIRIES:
        messages = [
            {"role": "system", "content": system_message(role)},
            {"role": "user", "content": enq["text"]},
        ]
        reply = call(messages, json_mode=True)
        obj, err = parse_json(reply.text)
        schema_errors = [] if obj is None else [e.message for e in VALIDATOR.iter_errors(obj)]
        field_ok = {}
        if isinstance(obj, dict):
            for f in STRUCTURED_FIELDS:
                field_ok[f] = norm(f, obj.get(f)) == norm(f, enq["expected"][f])
        rows.append({
            "role": role,
            "enquiry": enq["id"],
            "raw": reply.text,
            "parsed": obj is not None,
            "parse_error": err,
            "schema_valid": obj is not None and not schema_errors,
            "schema_errors": schema_errors,
            "reply": obj,
            "field_agrees": field_ok,
            "agrees": bool(field_ok) and all(field_ok.values()),
            "prompt_tokens": reply.prompt_tokens,
        })
        print(f"  {role:16s} {enq['id']}: decision={obj.get('decision') if isinstance(obj, dict) else '-'}"
              f"  agrees={rows[-1]['agrees']}", flush=True)
    return rows


def get(row, field):
    return row["reply"].get(field) if isinstance(row["reply"], dict) else None


def main():
    global ROLE_LAST
    ap = argparse.ArgumentParser()
    ap.add_argument("--role-last", action="store_true",
                    help="ablation: put the role paragraph after the shared block instead of before it")
    ap.add_argument("--tag", default="", help="suffix for the saved results file, e.g. run2")
    args = ap.parse_args()
    ROLE_LAST = args.role_last
    print(f"Provider: {PROVIDER}   Model: {MODEL}   role paragraph: {'last' if ROLE_LAST else 'first'}\n")
    results = {role: run_role(role) for role in ROLES}
    name = "easy_results" + ("_role_last" if ROLE_LAST else "") + (f"_{args.tag}" if args.tag else "")
    saved = save_output(name + ".json", results)

    # 1. Per-role tables
    for role, rows in results.items():
        print(f"\n### {role}\n")
        table = []
        for r in rows:
            table.append([
                r["enquiry"],
                "yes" if r["parsed"] else "NO",
                "yes" if r["schema_valid"] else "NO",
                get(r, "found"), get(r, "decision"), get(r, "amount"),
                get(r, "missing_documents"),
                "yes" if r["agrees"] else "NO (" + ", ".join(f for f, ok in r["field_agrees"].items() if not ok) + ")",
            ])
        print(md_table(["Enquiry", "parsed", "schema-valid", "found", "decision", "amount",
                        "missing_documents", "agrees with expected"], table))
        print(f"\nagrees {sum(r['agrees'] for r in rows)}/10 · parsed {sum(r['parsed'] for r in rows)}/10 · "
              f"schema-valid {sum(r['schema_valid'] for r in rows)}/10")
        for r in rows:
            if r["schema_errors"]:
                print(f"  schema errors on {r['enquiry']}: {r['schema_errors']}")

    # 2. Decisions per role, the SUBMISSION.md layout
    print("\n### Decisions per role (✓ = agrees with expected on all four fields)\n")
    table = []
    for i, enq in enumerate(ENQUIRIES):
        cells = []
        for role in ROLES:
            r = results[role][i]
            cells.append(f"{get(r, 'decision')} {'✓' if r['agrees'] else '✗'}")
        table.append([enq["id"], *cells])
    for label, key in (("agrees with `expected`", "agrees"), ("parsed", "parsed"), ("schema-valid", "schema_valid")):
        table.append([f"**{label}**", *[f"{sum(r[key] for r in results[role])}/10" for role in ROLES]])
    print(md_table(["Enquiry", *ROLES], table))

    # 3. Field movement relative to the policy officer
    print("\n### Which field moved away from policy_officer, on which enquiry, under which role\n")
    base = results["policy_officer"]
    table = []
    for f in STRUCTURED_FIELDS:
        moved: dict[str, list[str]] = {}
        for role in ROLES:
            if role == "policy_officer":
                continue
            for i, enq in enumerate(ENQUIRIES):
                if norm(f, get(results[role][i], f)) != norm(f, get(base[i], f)):
                    moved.setdefault(enq["id"], []).append(
                        f"{role} ({get(base[i], f)} → {get(results[role][i], f)})")
        if moved:
            table.append([f"`{f}`", ", ".join(moved), "; ".join(f"{e}: {', '.join(v)}" for e, v in moved.items())])
        else:
            table.append([f"`{f}`", "none", "no role moved this field on any enquiry"])
    print(md_table(["Field", "Enquiries that moved", "Role(s) that moved it"], table))

    # 4. Counts per role, so the written answers can point at numbers
    print("\n### Moves per role (enquiries where a field differs from policy_officer)\n")
    table = []
    for role in ROLES:
        if role == "policy_officer":
            continue
        counts = [sum(norm(f, get(results[role][i], f)) != norm(f, get(base[i], f)) for i in range(len(ENQUIRIES)))
                  for f in STRUCTURED_FIELDS]
        table.append([role, *counts])
    print(md_table(["Role", *STRUCTURED_FIELDS], table))
    print(f"\nRaw replies saved to outputs/{saved.name}")


if __name__ == "__main__":
    main()
