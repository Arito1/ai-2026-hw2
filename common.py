"""Shared plumbing for the three sublabs: the client, the data files, one call.

Nothing in here is a design decision about prompts or memory - those live in
the sublab files. This is the HW1 plumbing, kept in one place.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUTPUTS = ROOT / "outputs"

load_dotenv(ROOT / ".env")

# The instructor allowed Groq instead of OpenAI. Groq speaks the OpenAI
# chat-completions protocol, so only the base URL, the key and the model change.
# Whichever key is set picks the provider; MODEL in .env overrides the default.
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
if os.getenv("GROQ_API_KEY"):
    PROVIDER = "groq"
    MODEL = os.getenv("MODEL", "openai/gpt-oss-120b")
else:
    PROVIDER = "openai"
    MODEL = os.getenv("MODEL", "gpt-5.6-luna")


def use_groq_model(name: str) -> str:
    """Pin a sublab to one Groq model (unless MODEL in .env overrides it).

    Groq's free tier caps each model at 200k tokens a day. Easy used up
    gpt-oss-120b's budget, Medium then used up gpt-oss-20b's, so Hard runs on
    qwen3.8-27b. Within a sublab every compared run uses the same model.
    """
    global MODEL
    if PROVIDER == "groq" and not os.getenv("MODEL"):
        MODEL = name
    return MODEL

# Windows consoles default to a legacy code page; Kazakh text must still print.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        # max_retries: Groq's free tier answers 429 under its per-minute token
        # limit; the SDK backs off and retries those on its own.
        if PROVIDER == "groq":
            _client = OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url=GROQ_BASE_URL, max_retries=8)
        elif os.getenv("OPENAI_API_KEY"):
            _client = OpenAI(max_retries=8)
        else:
            sys.exit("No API key. Put GROQ_API_KEY (or OPENAI_API_KEY) in .env - see .env.example.")
    return _client


def load_json(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def save_output(name: str, obj) -> Path:
    OUTPUTS.mkdir(exist_ok=True)
    path = OUTPUTS / name
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


@dataclass
class Reply:
    text: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    seconds: float
    finish_reason: str = ""


# gpt-oss models reason before they answer, and the reasoning counts against the
# completion budget. Groq's default budget is 2048 tokens; a long JSON summary
# behind ~1800 reasoning tokens gets cut off mid-string (finish_reason "length").
MAX_COMPLETION_TOKENS = 8192


def call(messages: list[dict], *, json_mode: bool = False) -> Reply:
    """One stateless call. Whatever is in `messages` is everything the model sees."""
    kwargs = {"model": MODEL, "messages": messages, "max_completion_tokens": MAX_COMPLETION_TOKENS}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    started = time.perf_counter()
    resp = client().chat.completions.create(**kwargs)
    elapsed = time.perf_counter() - started
    usage = resp.usage
    return Reply(
        text=resp.choices[0].message.content or "",
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        total_tokens=usage.total_tokens if usage else 0,
        seconds=elapsed,
        finish_reason=resp.choices[0].finish_reason or "",
    )


def parse_json(text: str):
    """Parse a reply as JSON. Returns (obj, error). Tolerates a ```json fence, nothing else."""
    s = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()   # reasoning models may inline it
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else ""
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    try:
        return json.loads(s), None
    except json.JSONDecodeError as e:
        return None, str(e)


def md_table(headers: list[str], rows: list[list]) -> str:
    def cell(v):
        return str(v).replace("|", "\\|").replace("\n", " ")
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def call_json(messages: list[dict]):
    """Ask for JSON: JSON mode first, then (if the provider rejects the generation) plain.

    Returns (reply_or_None, obj_or_None, error_or_None, failures). Groq answers a
    malformed JSON-mode generation with HTTP 400 instead of returning it.
    """
    from openai import APIStatusError

    failures = []
    for json_mode in (True, False):
        try:
            reply = call(messages, json_mode=json_mode)
        except APIStatusError as e:
            if e.status_code == 429:      # a rate limit is not a bad generation: stop, don't mask it
                raise
            failures.append(f"json_mode={json_mode}: HTTP {e.status_code} {getattr(e, 'code', '') or ''}".strip())
            continue
        obj, err = parse_json(reply.text)
        if obj is None:
            failures.append(f"json_mode={json_mode}: did not parse ({err}; finish_reason={reply.finish_reason})")
            continue
        return reply, obj, None, failures
    return None, None, "; ".join(failures), failures
