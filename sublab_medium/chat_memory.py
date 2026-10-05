"""Sublab Medium - memory you choose: the `compress` command.

A call is stateless. The session below decides, on every call, what to send:

  * uncompressed: system message + every turn so far (grows forever);
  * compressed:   when the applicant's turn is the command `compress`, the model
    summarises the conversation into ONE state object, the program validates it
    against data/memory_state.schema.json, throws the turns away, and from then
    on sends system message + state + the turns since the compression.

A summary that does not parse or does not validate never replaces the history.

    python -m sublab_medium.chat_memory                  # scripted run, A vs B
    python -m sublab_medium.chat_memory --interactive    # a real chat
    python -m sublab_medium.chat_memory --break-compress # show the failure path
"""
from __future__ import annotations

import argparse
import json
import re

import openai
import tiktoken
from jsonschema import Draft202012Validator

from common import PROVIDER, call, load_json, md_table, parse_json, save_output, use_groq_model

MODEL = use_groq_model("openai/gpt-oss-20b")

POLICY = load_json("policy.json")
SCRIPT = load_json("chat_script.json")
STATE_SCHEMA = load_json("memory_state.schema.json")
STATE_VALIDATOR = Draft202012Validator(STATE_SCHEMA)
COMPRESS_MARKER = "<compress>"

# Local count, to set beside the provider's usage.prompt_tokens. o200k_base is the
# GPT-4o/gpt-oss family encoding; the provider's count also includes the chat
# template's role and separator tokens, so the two never match exactly.
ENC = tiktoken.get_encoding("o200k_base")

# The assistant gets the rule but NOT the records: everything it knows about the
# applicant has to come from the conversation (or from the state). Otherwise a
# probe like "which document is missing?" could be answered from the record
# block, and the probes would stop measuring memory.
SYSTEM = f"""\
You are the assistant of a university grant office, chatting with one applicant.

The grant rule: {POLICY["rule_human"]}

You do not have the applicant records in front of you. Work only from what the
applicant has told you in this conversation (or from the conversation state, if
you are given one) and from the rule. Never invent a fact the applicant did not
state. If you do not know something, say so. Reply in the language of the
applicant's latest message. Keep every answer short: two or three sentences."""

COMPRESSOR = f"""\
You compress a conversation between a grant-office assistant and an applicant
into one JSON object, so that the conversation can continue from that object
alone. The original turns will be deleted after you answer, so anything you
leave out is lost for good.

Return one JSON object with exactly these seven fields and no others:
- "applicant_id": the applicant's id as they stated it (e.g. "A-123"), or null if it was never stated.
- "topic": one short line - what the conversation is about.
- "facts": every fact the APPLICANT stated, one per item, with names, ids, numbers,
  bands, documents and dates exactly as said. Include things said only once.
  Only things the applicant said - not things the assistant worked out.
- "decisions": what the assistant has already told the applicant (an amount, an
  eligibility conclusion, a document still needed), one per item, with the numbers.
- "constraints": conditions the applicant set on how or when something can happen
  (a day they can come, a deadline, a requirement). Keep each one even if it was
  mentioned only once and never discussed again.
- "open_questions": questions the applicant asked that have not been fully
  answered yet, with enough detail to answer them later.
- "language": the language(s) the applicant writes in.

Arrays are empty [] rather than omitted. Nothing may be invented: a fact that was
never said is not a fact. Reply with the JSON object only.

The JSON Schema the object is checked against:
{json.dumps(STATE_SCHEMA, ensure_ascii=False)}"""


def count_local(messages: list[dict]) -> int:
    return sum(len(ENC.encode(m["content"])) for m in messages)


class Session:
    def __init__(self, break_compress: bool = False):
        self.state: dict | None = None
        self.turns: list[dict] = []          # turns since the last successful compression
        self.calls: list[dict] = []          # one entry per API call
        self.break_compress = break_compress

    def messages(self) -> list[dict]:
        msgs = [{"role": "system", "content": SYSTEM}]
        if self.state is not None:
            msgs.append({"role": "system", "content":
                         "Conversation state so far (the earlier turns were compressed into this "
                         "and deleted):\n" + json.dumps(self.state, ensure_ascii=False, indent=1)})
        return msgs + self.turns

    def _record(self, kind: str, text: str, messages: list[dict], reply) -> None:
        self.calls.append({
            "kind": kind, "text": text,
            "messages_sent": len(messages),
            "prompt_tokens": reply.prompt_tokens,
            "local_tokens": count_local(messages),
            "completion_tokens": reply.completion_tokens,
            "reply": reply.text,
        })

    def ask(self, text: str) -> str:
        self.turns.append({"role": "user", "content": text})
        msgs = self.messages()
        reply = call(msgs)
        self.turns.append({"role": "assistant", "content": reply.text})
        self._record("turn", text, msgs, reply)
        return reply.text

    def probe(self, question: str):
        """Ask without keeping the question or the answer: every probe sees the same context."""
        msgs = self.messages() + [{"role": "user", "content": question}]
        reply = call(msgs)
        return reply, count_local(msgs)

    def compress(self) -> tuple[bool, str]:
        transcript = []
        if self.state is not None:
            transcript.append("Earlier state (from a previous compression):\n"
                              + json.dumps(self.state, ensure_ascii=False))
        for m in self.turns:
            who = "Applicant" if m["role"] == "user" else "Assistant"
            transcript.append(f"{who}: {m['content']}")
        msgs = [{"role": "system", "content": COMPRESSOR},
                {"role": "user", "content": "The conversation:\n\n" + "\n\n".join(transcript)}]
        # Groq's JSON mode rejects a malformed generation with a 400 instead of
        # returning it. That is a failed summary like any other: retry once with
        # JSON mode off (we parse it ourselves), and if that fails too, keep the history.
        reply, failures = None, []
        for json_mode in (True, False):
            try:
                reply = call(msgs, json_mode=json_mode)
                break
            except openai.APIStatusError as e:
                failures.append(f"json_mode={json_mode}: HTTP {e.status_code} {getattr(e, 'code', '') or ''}".strip())
        if reply is None:
            self.calls.append({"kind": "compress", "text": COMPRESS_MARKER, "messages_sent": len(msgs),
                               "prompt_tokens": None, "local_tokens": count_local(msgs),
                               "completion_tokens": None, "reply": None})
            return False, f"summary call failed ({'; '.join(failures)}); history kept"
        self._record("compress", COMPRESS_MARKER, msgs, reply)
        self.calls[-1]["failures"] = failures

        text = reply.text
        if self.break_compress:              # demo of the failure path: cut the JSON in half
            text = text[: len(text) // 2]
        obj, err = parse_json(text)
        if obj is None:
            return False, (f"summary did not parse ({err}; finish_reason={reply.finish_reason}); "
                           f"history kept, {len(self.turns)} turns still sent")
        errors = [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in STATE_VALIDATOR.iter_errors(obj)]
        if errors:
            return False, f"summary did not validate ({'; '.join(errors)}); history kept"
        dropped = len(self.turns)
        self.state, self.turns = obj, []
        retried = f" (after a failed first attempt: {failures[0]})" if failures else ""
        return True, f"compressed: {dropped} messages replaced by the state object{retried}"


# --- probes ------------------------------------------------------------------

def _norm(s: str) -> str:
    # Only typography is normalised, never meaning: the model writes "A‑202" with a
    # non-breaking hyphen (U+2011) and "150 000" with a narrow space (U+202F).
    s = re.sub(r"[‐‑‒–—−]", "-", s.lower())
    s = re.sub(r"[  ]", " ", s)
    return re.sub(r"(?<=\d)[ ,](?=\d{3}\b)", "", s)


def needles(probe: dict) -> list[str]:
    """expect_contains minus any string the question already contains.

    Q-5 asks "What did I ask you about my employer?" and accepts "employer": an
    answer that just echoes the question ("you never mentioned your employer")
    would pass. A needle the question hands over proves nothing, so it is dropped.
    """
    q = _norm(probe["question"])
    kept = [e for e in probe["expect_contains"] if _norm(e) not in q]
    return kept or probe["expect_contains"]


def retrieved(answer: str, expect: list[str]) -> bool:
    a = _norm(answer)
    return any(_norm(e) in a for e in expect)


# --- scripted comparison -------------------------------------------------------

def scripted_run(compress: bool, break_compress: bool = False) -> dict:
    label = "B (compressed)" if compress else "A (never compressed)"
    print(f"\n=== Run {label} ===")
    s = Session(break_compress=break_compress)
    rows = []
    for i, turn in enumerate(SCRIPT["conversation"], start=1):
        if turn == COMPRESS_MARKER:
            if not compress:
                rows.append({"call": i, "kind": "skipped", "prompt_tokens": None, "local_tokens": None})
                print(f"  {i:2d}. <compress> skipped")
                continue
            ok, msg = s.compress()
            c = s.calls[-1]
            rows.append({"call": i, "kind": "compress", "ok": ok, "message": msg,
                         "prompt_tokens": c["prompt_tokens"], "local_tokens": c["local_tokens"]})
            print(f"  {i:2d}. <compress> sent {c['prompt_tokens']} tokens -> {msg}")
            continue
        answer = s.ask(turn)
        c = s.calls[-1]
        rows.append({"call": i, "kind": "turn", "text": turn, "answer": answer,
                     "messages_sent": c["messages_sent"],
                     "prompt_tokens": c["prompt_tokens"], "local_tokens": c["local_tokens"]})
        print(f"  {i:2d}. sent {c['prompt_tokens']:5d} tokens ({c['messages_sent']} messages)  {turn[:60]}")

    probes = []
    for p in SCRIPT["probes"]:
        reply, local = s.probe(p["question"])
        ok = retrieved(reply.text, needles(p))
        probes.append({"id": p["id"], "tests": p["tests"], "question": p["question"],
                       "needles": needles(p), "answer": reply.text, "retrieved": ok,
                       "prompt_tokens": reply.prompt_tokens, "local_tokens": local})
        print(f"  probe {p['id']}: {'RETRIEVED' if ok else 'LOST'}  ({reply.prompt_tokens} tokens)  {reply.text[:90]!r}")
    return {"rows": rows, "probes": probes, "state": s.state, "final_messages": s.messages()}


def report(a: dict, b: dict) -> None:
    print("\n### Tokens per call (usage.prompt_tokens from the provider; tiktoken o200k count in brackets)\n")
    table = []
    for ra, rb in zip(a["rows"], b["rows"]):
        def cell(r):
            if r["kind"] == "skipped":
                return "— (`compress` skipped)"
            if r["prompt_tokens"] is None:
                return f"compress call failed, history kept (~{r['local_tokens']} by tiktoken)"
            extra = " — the compress call" if r["kind"] == "compress" else ""
            return f"{r['prompt_tokens']} ({r['local_tokens']}){extra}"
        table.append([ra["call"], cell(ra), cell(rb)])

    def nums(run):
        return [r["prompt_tokens"] for r in run["rows"] if r["prompt_tokens"] is not None]
    table.append(["**peak**", max(nums(a)), max(nums(b))])
    table.append(["**total for the run**", sum(nums(a)), sum(nums(b))])
    table.append(["probes (5 calls, total)", sum(p["prompt_tokens"] for p in a["probes"]),
                  sum(p["prompt_tokens"] for p in b["probes"])])
    print(md_table(["Call", "A — never compressed", "B — compressed at the `compress` turn"], table))

    # Peak over the turns after the compress point, where the two runs differ.
    after = lambda run: [r["prompt_tokens"] for r in run["rows"][10:] if r["prompt_tokens"] is not None]
    print(f"\nAfter the compress point (calls 11-12): A {after(a)}  B {after(b)}")

    print("\n### Probes after the conversation\n")
    table = []
    for pa, pb in zip(a["probes"], b["probes"]):
        table.append([pa["id"], pa["tests"],
                      "yes" if pa["retrieved"] else "**no**", pa["answer"],
                      "yes" if pb["retrieved"] else "**no**", pb["answer"]])
    table.append(["**retrieved**", "", f"{sum(p['retrieved'] for p in a['probes'])}/5", "",
                  f"{sum(p['retrieved'] for p in b['probes'])}/5", ""])
    print(md_table(["Probe", "Tests", "A retrieved?", "A answer", "B retrieved?", "B answer"], table))
    print("\nNeedles checked (case-insensitive, after dropping any the question itself contains): "
          + "; ".join(f"{p['id']} {p['needles']}" for p in a["probes"]))

    print("\n### The state the compression produced\n")
    print(json.dumps(b["state"], ensure_ascii=False, indent=2) if b["state"] is not None
          else "(no state - the compression failed and the history was kept)")


# --- interactive ---------------------------------------------------------------

HELP = """Commands: compress · tokens · state · sent · help · quit. Anything else is a message."""


def interactive() -> None:
    s = Session()
    print(f"Provider: {PROVIDER}   Model: {MODEL}\n{HELP}\n")
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        cmd = text.lower()
        if cmd in ("quit", "exit"):
            break
        if cmd == "help":
            print(HELP)
        elif cmd == "tokens":
            if not s.calls:
                print("  no call yet")
            else:
                c = s.calls[-1]
                print(f"  last call ({c['kind']}): sent {c['prompt_tokens']} tokens in {c['messages_sent']} "
                      f"messages (tiktoken {c['local_tokens']}), got {c['completion_tokens']} back")
                print(f"  next call would send ~{count_local(s.messages())} tokens before your message "
                      f"({len(s.turns)} turns{' + state' if s.state else ''})")
                print(f"  session so far: {sum(c['prompt_tokens'] for c in s.calls)} tokens sent over {len(s.calls)} calls")
        elif cmd == "state":
            print(json.dumps(s.state, ensure_ascii=False, indent=2) if s.state else "  no state yet - nothing compressed")
        elif cmd == "sent":
            for m in s.messages():
                print(f"  [{m['role']}] {m['content'][:200]}{'…' if len(m['content']) > 200 else ''}")
        elif cmd == "compress":
            ok, msg = s.compress()
            print(f"  {msg}  (the compress call sent {s.calls[-1]['prompt_tokens']} tokens)")
            if ok:
                print(json.dumps(s.state, ensure_ascii=False, indent=2))
        else:
            answer = s.ask(text)
            print(f"assistant> {answer}\n  [sent {s.calls[-1]['prompt_tokens']} tokens]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interactive", action="store_true", help="a real chat with compress / tokens")
    ap.add_argument("--break-compress", action="store_true",
                    help="cut the summary in half before parsing, to show the history is kept")
    args = ap.parse_args()
    if args.interactive:
        interactive()
        return
    print(f"Provider: {PROVIDER}   Model: {MODEL}")
    if args.break_compress:
        b = scripted_run(compress=True, break_compress=True)
        save_output("medium_break_compress.json", b)
        print(f"\nState after the broken compression: {b['state']}  "
              f"(messages still sent at the end: {len(b['final_messages'])})")
        return
    a = scripted_run(compress=False)
    b = scripted_run(compress=True)
    save_output("medium_results.json", {"A": a, "B": b})
    report(a, b)
    print("\nFull replies saved to outputs/medium_results.json")


if __name__ == "__main__":
    main()
