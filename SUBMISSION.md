# HW2 submission

**Name:**
**Student ID:**
**Group:**
**Repository:** https://github.com/Arito1/ai-2026-hw2

## AI tool disclosure

State which AI tools you used and for what. Expected and fine; undisclosed use
is not. If you used a model to help you draft a prompt, say which prompt.

> I used **Claude Code (Claude Opus 5.5)** as a coding assistant for this homework. It wrote the
> code of all three sublabs (`common.py`, `sublab_easy/role_prompts.py`,
> `sublab_medium/chat_memory.py`, `sublab_hard/cv_extract_and_rank.py`), including every
> prompt in them: the four role paragraphs and the shared block (Easy), the assistant
> and compressor prompts (Medium), the extraction rules, scorer and prose prompts (Hard).
> It ran the programs, debugged them (rate limits, truncated JSON, schema mistakes),
> and drafted the tables and the written answers below from the outputs of these runs.
> Every number below was printed by a program run; the logs are committed in `runs/`.

### Provider and models (allowed by the instructor)

The instructor allowed **Groq** instead of OpenAI (`gpt-5.6-luna`). Groq speaks the OpenAI
chat-completions protocol, so the code only changes the base URL, key and model
(`common.py`; set `GROQ_API_KEY` in `.env`, or `OPENAI_API_KEY` to run on OpenAI).
Groq's free tier caps every model at **200k tokens per day**, and I ran out twice, so the
three sublabs run on three models. **Within each sublab every compared run uses one model**,
so each comparison still changes only what the program sends:

| Sublab | Model (Groq) | Why |
|---|---|---|
| Easy | `openai/gpt-oss-120b` | first choice, closest to the assignment's small OpenAI model |
| Medium | `openai/gpt-oss-20b` | Easy (4 runs × 40 calls) used up the 120b daily budget |
| Hard | `qwen/qwen3.8-27b` | Medium (several runs, see below) used up the 20b daily budget |

Logs of every run quoted here are in `runs/` (the full JSON replies go to `outputs/`, which is
gitignored).

---

## Sublab Easy — one task, four roles

Model `openai/gpt-oss-120b`. The system message is `# Your role` + one role paragraph + one shared
block (rule in prose and as JSON, all six records, the six-field contract, the meaning of each
decision). The shared block is byte-for-byte the same for all four roles; JSON mode is on. The code
checks every reply with `json.loads` and a JSON Schema of the contract (enum for `decision`,
integer `amount`, `missing_documents` drawn from the required documents, no extra fields).

I ran the whole sublab three times with the same prompts (`runs/easy_run1.log`, `easy_run2.log`,
`easy_run3.log`) plus one ablation with the role paragraph moved after the shared block
(`runs/easy_role_last.log`, `--role-last`). The tables below are **run 1**; runs 2 and 3 are
discussed under them.

### Decisions per role

One row per enquiry. In each cell write the `decision` your run returned, and
whether it agrees with `expected` in `data/enquiries.json`:

| Enquiry | policy_officer | front_desk | auditor | bilingual_clerk |
|---|---|---|---|---|
| E-01 | granted ✓ | granted ✓ | more_info ✗ | granted ✓ |
| E-02 | more_info ✓ | more_info ✓ | more_info ✓ | more_info ✓ |
| E-03 | refused ✓ | refused ✓ | refused ✓ | refused ✓ |
| E-04 | refused ✓ | refused ✓ | refused ✓ | refused ✓ |
| E-05 | granted ✓ | granted ✓ | more_info ✗ | granted ✓ |
| E-06 | granted ✓ | granted ✓ | more_info ✗ | granted ✓ |
| E-07 | granted ✓ | granted ✓ | more_info ✗ | granted ✓ |
| E-08 | not_found ✓ | not_found ✓ | not_found ✓ | not_found ✓ |
| E-09 | refused ✓ | refused ✓ | refused ✓ | refused ✓ |
| E-10 | more_info ✓ | more_info ✓ | more_info ✓ | more_info ✓ |
| **agrees with `expected`** | 10/10 | 10/10 | 6/10 | 10/10 |
| **parsed** | 10/10 | 10/10 | 10/10 | 10/10 |
| **schema-valid** | 10/10 | 10/10 | 10/10 | 10/10 |

(✓ = all four structured fields — `found`, `decision`, `amount`, `missing_documents` — equal `expected`.
The auditor's four ✗ are `decision` and `amount`; its `found` and `missing_documents` agree.)

**Across runs.** Run 2 printed exactly the same table. Run 3 differed in one cell: front_desk
answered E-03 `more_info` ("Please provide an updated GPA that meets the threshold"), so front_desk
scored 9/10. **Role paragraph last** (ablation): front_desk turned all three refusals into
`more_info` (E-03, E-04, E-09 → 7/10). The other three roles were identical in all four runs.

### Which field moved, on which enquiry, under which role

Compared with the policy officer's reply to the same enquiry, run 1:

| Field | Enquiries that moved | Role(s) that moved it |
|---|---|---|
| `found` | **none** | no role moved `found` on any enquiry (also none in runs 2, 3 and role-last) |
| `decision` | E-01, E-05, E-06, E-07 | auditor, `granted → more_info` on all four (front_desk: none in runs 1–2; E-03 in run 3; E-03, E-04, E-09 `refused → more_info` with the role paragraph last) |
| `amount` | E-01, E-05, E-06, E-07 | auditor, `250000/250000/150000/250000 → 0` (follows `decision`: the contract says 0 unless granted) |
| `missing_documents` | **none** | no role moved it on any enquiry in any run — even front_desk's "more_info" for a low GPA came back with `[]` |

Moves per role (run 1): front_desk 0 · auditor 4 `decision` + 4 `amount` · bilingual_clerk 0.
`reason` is free text and not counted above, but bilingual_clerk is the only role whose `reason`
changed language: Kazakh on E-07, English on the other nine.

### Raw replies

Paste the full reply for **one enquiry where a role changed the decision** away
from the policy officer's:

```
E-01, policy_officer (run 1):
{"applicant_id":"A-201","found":true,"decision":"granted","amount":250000,"missing_documents":[],"reason":"Applicant meets GPA, income band, and required documents; grant approved."}

E-01, auditor (run 1):
{"applicant_id":"A-201","found":true,"decision":"more_info","amount":0,"missing_documents":[],"reason":"Applicant meets GPA, income band, and document requirements per the grant rule; further review is required before granting."}

E-03, front_desk with the role paragraph last (runs/easy_role_last.log):
{"applicant_id":"A-203","found":true,"decision":"more_info","amount":0,"missing_documents":[],"reason":"Your GPA is below the required minimum of 2.67. Please provide an updated GPA that meets the threshold to be considered for the grant."}
```

Paste the full reply for **E-07 (the Kazakh enquiry)** from the bilingual
clerk, so the `reason` language is visible:

```
{"applicant_id":"A-201","found":true,"decision":"granted","amount":250000,"missing_documents":[],"reason":"Сіздің GPA-ңыз 2.67-ден жоғары, табыс деңгейіңіз 1 және қажетті құжаттар (транскрипт, жеке куәлік) бар. Сондықтан грант беріледі, сомасы 250 000 теңге."}
```

(The policy officer answered the same E-07 with an English `reason`: "Applicant meets GPA, income
band, and required documents; grant of 250,000 tenge approved.")

### Written answers

**1. Which fields are role-sensitive and which are not?** Point at rows in your
tables.

> `decision` and `amount` are role-sensitive; `found` and `missing_documents` are not. In the
> field-movement table `found` and `missing_documents` are "none" in all four runs: no role ever
> changed who the applicant is or which document the record lacks. `decision` moved on E-01, E-05,
> E-06 and E-07, all under the **auditor** (`granted → more_info`), and `amount` moved on exactly
> the same four rows, because the contract ties `amount` to `decision` (0 unless granted). So
> `amount` is not separately role-sensitive: it moves with `decision`. The role that moves
> `decision` is the auditor (4/10 in every run). The role that moves **only `reason`** is the
> **bilingual clerk**: its four structured fields are identical to the policy officer's on 10/10
> enquiries, and only E-07's `reason` changed language. front_desk was meant to move `decision` on
> the refusals but in runs 1–2 it moved nothing (0/10), in run 3 one row (E-03), and only with its
> paragraph placed after the shared block did it move all three (E-03, E-04, E-09) — see answer 4.

**2. Which enquiries are most sensitive to the role, and why those?** Say what
E-03, E-04, E-07 and E-10 are each testing.

> The most sensitive rows are the ones where the rule gives a clear-cut answer that a role is told
> to soften or delay: the four grants (E-01, E-05, E-06, E-07) for the auditor and the three
> refusals (E-03, E-04, E-09) for front_desk. The rows that never moved are E-02, E-08 and E-10.
> **E-03** tests a refusal on GPA (2.4 < 2.67): it is the refusal front_desk tries to turn into
> `more_info`, and when it did, it gave false hope ("provide an updated GPA") while
> `missing_documents` stayed `[]` — there is no document that fixes a GPA. **E-04** tests a refusal on
> income band (band 3): front_desk's "more_info" again has nothing the applicant can bring. **E-07**
> tests language: a Kazakh enquiry for the same applicant as E-01. Every role decided E-07 exactly
> as it decided E-01 (granted, granted, more_info, granted), so language changed nothing except the
> bilingual clerk's `reason`. **E-10** tests a claim in the message against the record ("I uploaded
> my id card yesterday"): all four roles kept `more_info` with `["id_card"]` in every run — the
> "the record is the only source of truth" sentence in the shared block held even for the roles whose
> paragraph does not repeat it.

**3. Where does discretion belong — the role paragraph, or code that reads
`decision` afterwards?** Say what a downstream program can and cannot tell
about which role produced a record.

> In code. A downstream program receives only the six fields. It can see `decision = more_info`,
> but it cannot tell *why*: the auditor's E-01 record (`more_info`, `missing_documents: []`, a
> qualifying applicant) and the policy officer's E-02 record (`more_info`, `["id_card"]`) have the
> same type and the same decision. An empty `missing_documents` next to `more_info` is a hint, not
> a guarantee — front_desk's E-03 in run 3 has the same shape for the opposite reason (a refusal
> renamed). Nothing in the record says which role wrote it unless the program stores the role or a
> prompt version beside it. So I would let the model only apply the rule (the policy officer), and
> put the discretion in code that reads `decision` afterwards: "every grant goes to a second reader"
> is one line (`if decision == "granted": status = "pending_review"`), it works on every record,
> it is logged, and it cannot be skipped by a model that ignored its paragraph, as front_desk did.

**4. Is a role a boundary?** Say in Week 2 terms what the role paragraph is
made of, and what you would put in code — not in the prompt — if a wrong
`decision` were expensive.

> No. The role paragraph is a few dozen tokens at the top of the context, in the same stream as
> the records, the rule and the applicant's text; the model continues that document, and the
> paragraph only shifts the probabilities of what comes next. My runs show it directly:
> front_desk's paragraph says in plain words "you never answer with decision "refused"", yet in
> runs 1–2 it answered `refused` on all three refusals, because the much longer shared block after it
> defines `refused` and the rule says the applicant does not qualify. Moving the same paragraph to
> the end of the system message (closer to the generation point) changed 3 decisions; run 3 changed
> 1 by chance. A control that depends on its position in the prompt and on sampling is not a boundary,
> and an enquiry could contain text pushing the other way. If a wrong `decision` were expensive I
> would put in code: (1) schema validation and an enum check (already there); (2) recompute the
> decision deterministically from the record — it is a pure function (GPA ≥ 2.67, band ∈ {1,2},
> both documents) — and reject or escalate any reply that disagrees; (3) take `amount` from the band
> table in code, never from the model; (4) require human approval before any `granted` is acted on,
> and log the role/prompt version with each record.

---

## Sublab Medium — memory you choose

Model `openai/gpt-oss-20b`. The assistant's system message has the rule but **not** the records:
everything it knows about the applicant must come from the conversation or from the state, so the
probes measure memory and not the record block. The state is sent as a second system message
("Conversation state so far …"); after `compress` the program sends system + state + the turns
since compression. Every probe is asked separately against the same final context (it is not kept
in the conversation). Tokens are `usage.prompt_tokens` from Groq; the tiktoken `o200k_base` count of
the message texts is in brackets (the gap is the chat template's role/separator tokens).

The tables are from `runs/medium_run4.log`. Earlier runs are discussed in the answers:
run 1 (`runs/medium_run1_no_language_rule.log`, on gpt-oss-120b before I ran out of its budget,
and before I added "reply in the language of the latest message"), and runs 2–3
(`runs/medium_run2_compress_failed.log`), where the compression failed and the program kept the
history (the model's reasoning used up Groq's default 2048-token completion budget, so the JSON was
cut off; fixed by `max_completion_tokens=8192`).

### Tokens per call

| Call | A — never compressed | B — compressed at the `compress` turn |
|---|---|---|
| 1 | 294 (220) | 294 (220) |
| 2 | 388 (304) | 369 (285) |
| 3 | 462 (368) | 446 (352) |
| 4 | 525 (421) | 514 (410) |
| 5 | 597 (483) | 586 (472) |
| 6 | 681 (557) | 667 (543) |
| 7 | 752 (618) | 739 (605) |
| 8 | 846 (702) | 822 (678) |
| 9 | 926 (772) | 906 (752) |
| 10 | — (`compress` skipped) | 1357 (1255) — the compress call itself |
| 11 | 994 (830) | 722 (641) |
| 12 | 1077 (903) | 771 (680) |
| **peak** | 1077 | 1357 (the compress call); 906 among the chat calls |
| **total for the run** | 7542 | 8193 (incl. 1357 for compress) |
| five probes, total | 5670 | 4055 |

### Probes after the conversation

Retrieved = the answer contains one of `expect_contains` (case-insensitive; typography normalised:
the model writes "A‑202" with a non-breaking hyphen and "150 000" with a narrow space). A string that
the probe question already contains is not accepted ("employer" for Q-5), because an answer that only
echoes the question would pass — in run 1 exactly that happened: B answered "You haven't mentioned
anything about your employer" and the naive check said retrieved.

| Probe | Tests | A retrieved? | A answer | B retrieved? | B answer |
|---|---|---|---|---|---|
| Q-1 identity | turn 1 | yes | You are Daniyar Qoshan, and your applicant number is A‑202. | yes | You are Daniyar Qoshan, applicant A‑202. |
| Q-2 missing document | turn 5 | yes | The documents still missing are your GPA record and a copy of your ID card. Once we have those we can confirm your eligibility and finalize the grant. | yes | Your file is still missing your ID card. Once that is uploaded, we'll check your GPA and confirm eligibility. |
| Q-3 band and amount | turns 3–4 | yes | Your income band is 2. For band 2, the grant amount is 150 000 tenge. | yes | Your income band is 2, which corresponds to a grant of 150,000 tenge. |
| Q-4 the constraint | turn 6 | yes | You mentioned you can come to the office only on Thursdays. So the only available day for you to submit your ID card and other documents is Thursday. | yes | You mentioned you can only come to the office on **Thursday**. That is the day we can meet to verify your documents and finalize the decision. |
| Q-5 the open question | turn 7 | **no** (by the string check) | Сіз сұрағаныңыз – жұмыс берушіден алынған хат сканшоты қабылданатыны немесе оригинал қажет екендігі. | yes | You asked whether a scanned letter from your employer is acceptable, or if it has to be the original. |
| **retrieved** | | 4/5 | | 5/5 | |

A's Q-5 is a **language** failure, not a memory failure: the answer is correct ("хат" = letter,
"жұмыс беруші" = employer) but came back in Kazakh although the probe and the system rule were in
English — the conversation opened with "Сәлеметсіз бе!". By the README's string rule it is lost; by
reading it, A retrieved 5/5 too.

### The state my compression produced

```json
{
  "applicant_id": "A-202",
  "topic": "application for study grant eligibility and documentation",
  "facts": [
    "My name is Daniyar Qoshan, applicant A-202.",
    "I sent my transcript last week.",
    "My income band is 2 - my family's certificate says so.",
    "I could not upload my id card because the scanner at home broke.",
    "I can only come to the office on Thursdays, I have lab all week otherwise.",
    "my sister Aruzhan applied last year and she is on file too."
  ],
  "decisions": [
    "I can’t calculate the grant amount until I confirm you meet all the criteria.",
    "I can’t confirm eligibility or calculate an award.",
    "Please upload the ID card (once your scanner is fixed) and let me know your GPA, and I’ll tell you the exact grant amount.",
    "Please bring both documents to the office on Thursday, and then we can confirm whether you qualify and what the grant amount would be.",
    "I don’t have any record of an employer letter for you, so I can’t confirm whether a scanned copy would be accepted.",
    "I’m not sure we can finalize a decision on the spot, because we’ll still need to verify your GPA and confirm the ID card is in our system. Once all documents are on file, we’ll let you know the result and grant amount as soon as possible.",
    "I can determine if you qualify once I have your GPA, income band, and ID card uploaded."
  ],
  "constraints": [
    "I can only come to the office on Thursdays, I have lab all week otherwise."
  ],
  "open_questions": [
    "So how much would that come to, if it goes through?",
    "Does a scanned letter from my employer count, or does it have to be the original?",
    "If I bring the id card on Thursday, will the decision be made the same day?"
  ],
  "language": "English"
}
```

It validated against `data/memory_state.schema.json` on the first try in this run. For comparison,
the run-1 state (gpt-oss-120b) had **`"open_questions": []`** and no mention of the employer letter
anywhere — it also validated.

### Written answers

**1. What did compression buy?** Peak tokens both ways, probes retrieved both
ways, and — if a probe was lost — which one and which turn it came from.

> Peak: A 1077, B 1357 — compression *raised* the peak, because the compress call sends the whole
> conversation plus the compressor instructions and the schema (1357 tokens). What it bought is
> every call after it: call 11 went from 994 to 722 tokens and call 12 from 1077 to 771 (−28%), and
> the five probes cost 4055 instead of 5670. Over the twelve calls B is still more expensive
> (8193 vs 7542), so on a conversation this short compression only pays for itself after a few more
> turns; the point is that A grows with every turn forever, while B restarts from ~720 tokens.
> Probes: A 4/5 by the string check (5/5 by reading), B 5/5. Nothing was lost in this run. In run 1
> (gpt-oss-120b, `runs/medium_run1_no_language_rule.log`) the compressed run **lost Q-5** — the
> employer-letter question from **turn 7**: the state had `"open_questions": []` and did not mention
> the letter at all, and B answered "You haven't mentioned anything about your employer". The
> assistant had given a vague reply at turn 7, so the summariser treated the question as answered
> and dropped it — exactly the "unanswered question goes first" failure the script was built for.

**2. Why must the state be structured rather than a paragraph?** You could have
asked for "a summary". Say what changes when the summary is an object with
named fields.

> Three things change. (1) The program can check it: `jsonschema` tells me whether all seven fields
> are there with the right types, and a reply that does not parse or validate is refused instead of
> silently replacing the history — runs 2 and 3 failed exactly like that (a cut-off JSON) and the
> program kept all 18 messages and continued. A paragraph can be checked by nothing. (2) The named
> fields are a checklist for the summariser: `constraints` and `open_questions` force it to look
> for "only Thursdays" and the employer letter, which a fluent paragraph drops first because they
> are not about the decision; the run with the list fields filled kept both. (3) The program can
> use fields directly — `applicant_id` can be looked up, `open_questions` can be shown to a human,
> a missing `applicant_id` is `null` rather than a sentence. The limit: the schema checks shape, not
> truth — run 1's state with an empty `open_questions` was perfectly valid.

**3. What is missing from your state that you would add?** Name what you would
add and what you would drop to pay for it.

> I would add (a) **`documents`**: `{on_file_claimed: ["transcript"], missing: ["id_card"]}` — the
> one thing the office acts on is buried in free-text facts and in a long `decisions` sentence;
> (b) **`claims_vs_record`**: what the applicant *says* (band 2 from a family certificate, transcript
> sent) marked as claims, so a later turn cannot treat them as verified — the same trap as E-10;
> (c) a **turn number** on each fact, so an answer can say where it came from; and (d) **answers
> already given**, kept short (e.g. "amount if approved: 150,000 for band 2"). In my state
> `decisions` holds seven long quoted sentences that contradict the later answer ("I can't calculate
> the grant amount" — yet B then answered 150,000 from the rule). To pay for it I would drop `topic`
> (one line nobody reads), the sister Aruzhan (irrelevant to this file), and cut `decisions` to short
> items with numbers instead of verbatim assistant sentences.

**4. When is compression the wrong choice?** Name a conversation where it would
lose something that cannot be recovered, and say whether your program would
notice.

> When the exact words are the record. Example: an applicant appealing a refusal who says in turn 3
> "I submitted the id card on 12 September at the front desk, the clerk was Aliya" and in turn 9
> "actually it may have been the 13th". The appeal depends on the exact claims, their order and the
> change between them; a summary keeps one date ("submitted id card in September") or quietly picks
> one, and after `compress` the turns are deleted, so the original wording cannot be recovered. The
> same holds for consent ("yes, you may share my income certificate") and for numbers being
> negotiated. My program would **not** notice: it checks that the state parses and matches the
> schema, not that it is faithful — run 1's state was schema-valid with the open question gone. To
> notice, I would need a content check (e.g. extract ids, dates, numbers and weekdays from the turns
> with a regex and require each to appear in the state) or keep the raw turns in storage and send
> only the state.

---

## Sublab Hard — stories in, CVs out, the best candidate by code

Model `qwen/qwen3.8-27b` (`runs/hard_run.log`). The extraction prompt contains the four rules from
the README word for word (`BASE_RULES`) plus two rules I had to add (`EXTRA_RULES`, answer 1);
`--base-rules-only` runs without them (`runs/hard_base_rules.log`). The record has the fields asked
for plus `gpa_original`, `published_outputs` / `unpublished_outputs` with status and
`peer_reviewed`, `experience_periods` with `countable`, `ambiguities`, and an `evidence` quote per
field. The code then checks what it can without trusting the model: schema; that every evidence
quote occurs word for word in the story; GPA conversion arithmetic; `published_count` = length of
the list; months = sum of the countable periods; and the traps against my own reading of the
stories (`ANSWER_KEY`).

### Part 1 — extraction

| Story | Parsed? | Valid? | Fields that came back `null` | Traps hit |
|---|---|---|---|---|
| story-01 | yes | yes | none | none (control story) — all checks ✓ (GPA 3.8, 2 published, 8 months). Code flag: `published_count` evidence "this is published... that was published" is two quotes stitched with "..." — not verbatim |
| story-02 | yes | yes | `graduation_year`, `gpa_4_scale`, `gpa_original`, `gpa_original_scale` | **no GPA stated** — handled: GPA null, "diploma with distinction" not turned into a number; `graduation_year` null because the story only says "last year"; paper in "student conference proceedings" counted as published with `peer_reviewed: null` |
| story-03 | yes | yes | none | **GPA on another scale** — handled: 4.6/5.0 → 3.68 with scale 5 recorded; **unpublished paper** — handled: "under review" recorded, not counted (1 published). Code flag: months evidence stitched with "..." |
| story-04 | yes | yes | none | **unpublished paper** — handled: 1 published; "under review" + 2 × "in preparation" recorded separately |
| story-05 | yes | yes | none | **unpublished paper** — handled ("жазылып жатыр", not sent anywhere → in preparation, not counted); Kazakh story extracted fully (GPA 3.9, 6 months). Side effect: its `ambiguities` contain mixed-language debris ("alto六个月", "ин в прогрессе") |
| story-06 | yes | yes | `graduation_year`, `gpa_4_scale`, `gpa_original` | **story contradicts itself** — handled: GPA 3.2 vs 3.5 → null, graduation 2024 vs 2026 → null, both recorded in `ambiguities`; poster not counted; "about forty months" counted as 40 and noted |

The four traps, for reference: no GPA stated · a GPA on another scale · a paper
that is not published · a story that contradicts itself.

Without my two added rules (`runs/hard_base_rules_rechecked.log`) every story parsed and validated,
but **qwen hit a trap on story-01**: experience 0 months instead of 8 (answer 1), and
**gpt-oss-20b hit two on story-06**: `graduation_year` 2024 instead of null, experience null
instead of 40.

Paste the extraction for **story-06**, the one that contradicts itself:

```json
{
  "candidate_id": "story-06",
  "full_name": "Nurzhan Abilov",
  "degree": "BSc in Statistics",
  "graduation_year": null,
  "gpa_4_scale": null,
  "gpa_original": null,
  "gpa_original_scale": 4.0,
  "languages": ["Kazakh", "Russian", "English"],
  "published_outputs": [
    {"title": null, "venue": "peer-reviewed proceedings", "year": null, "peer_reviewed": true}
  ],
  "published_count": 1,
  "unpublished_outputs": [
    {"title": null, "status": "not_a_publication"}
  ],
  "experience_periods": [
    {"role": "insurance analytics team", "start": "February 2023", "end": null, "months": 40, "countable": true}
  ],
  "experience_months_countable": 40,
  "ambiguities": [
    "GPA contradiction: story states 'My GPA was 3.2' but also 'I think it was 3.5'",
    "Graduation year contradiction: story states 'I graduated in 2024' but also 'graduating in 2026'",
    "Duration approximation: story states the work period is 'about forty months'"
  ],
  "evidence": {
    "full_name": "Nurzhan Abilov",
    "degree": "BSc in Statistics",
    "graduation_year": null,
    "gpa": null,
    "languages": "Kazakh, Russian, English.",
    "published_count": "one paper published",
    "experience_months_countable": "about forty months"
  }
}
```

(One small inconsistency the code does not catch yet: `gpa_original_scale` is 4.0 while both GPA
values are null.)

### Part 2 — scores and the winner

The scorer sees the extracted record (not the story), the rubric and the counting rules, and returns
three integers 0–5 plus a note — no total. The code then applies the counting rules that leave no
room for judgement (no GPA → academic 0; 0 published → research 0, ≥ 2 → 5; no countable months →
experience 0, ≥ 24 → 5), overrides a score that breaks them and says so, and computes
`0.5·academic + 0.3·research + 0.2·experience`, rounded to two decimals. Ties are broken by academic,
then research, then id.

| Candidate | academic (0–5) | research (0–5) | experience (0–5) | weighted total (code) |
|---|---|---|---|---|
| story-01 | 5 | 5 | 3 | **4.60** |
| story-02 | 0 (model said 2; code: no GPA → 0) | 1 | 5 (model said 4; code: 36 months ≥ 24 → 5) | 1.30 (2.10 on the model's raw scores) |
| story-03 | 4 | 3 | 4 | 3.70 |
| story-04 | 4 | 2 | 5 | 3.60 |
| story-05 | 5 | 3 | 2 | 3.80 |
| story-06 | 0 | 2 | 5 | 1.60 |

Ranking (code): story-01 4.60 > story-05 3.80 > story-03 3.70 > story-04 3.60 > story-06 1.60 >
story-02 1.30. On the model's raw scores story-02 (2.10) would have been above story-06 (1.60).

**Winner, computed by my code:** **story-01 — Aziza Bekova, 4.60.** Gap to second (story-05, Aisha
Nurlanqyzy): 0.80.

**The model's prose answer, asked separately ("who should win?"):**

> (Abridged; full text in `runs/hard_run.log`.) It opens: "Based on the strict application of the
> provided rubric and counting rules, **Lyazzat Omarova** (story-03) is the winner." It then works
> through every candidate with its own estimated scores — Aziza 4.4, Tamerlan 3.9, Aisha 3.8,
> Lyazzat 4.0 or 3.5, Nurzhan 3.4, Dias 1.9 — concludes "Therefore, **Aziza Bekova** is the
> strongest candidate", and recommends: "The funded place should be awarded to **Aziza Bekova** …
> **Tamerlan Saparov** comes second … his research profile contains only one published paper."
```
Prose winner: Aziza Bekova (story-01) — after first naming Lyazzat Omarova (story-03)
Prose second: Tamerlan Saparov (story-04), its own estimate 3.9
Code winner:  story-01 4.60   Code second: story-05 3.80 (story-04 is fourth, 3.60)
```

### Part 3 — written answers

**1. Which rule did you have to add, and what broke without it?** Name the
story that forced it.

> Two rules, both about over-applying the README's contradiction rule.
> **(a) "An approximate figure is not a contradiction; when the story states the number of months,
> use it"** — forced by **story-01**. With only the four README rules, qwen read "from October 2023
> to May 2024, eight months in total", computed 7 by subtraction, called the difference an
> ambiguity and marked the period `countable: false`: **0 months**. The rubric would then give
> story-01 experience 0, and its total would drop from 4.60 to 4.00 — the clear winner would only
> just stay ahead. The same rule was forced on gpt-oss-20b by **story-06**, where "about forty
> months" was treated as a contradiction and the months came back `null`.
> **(b) "The contradiction rule applies to every field, dates included"** — forced by **story-06**
> on gpt-oss-20b: it listed "Graduation year stated as 2024 and also 2026" in `ambiguities` and still
> wrote `graduation_year: 2024`. (qwen got this one right without the rule.)
> I also had to loosen my own schema twice: story titles and the role in the Kazakh story-05 are not
> stated, the model correctly returned `null`, and my schema demanded strings — in one gpt-oss-20b
> run story-05 failed validation and was silently dropped from the ranking. A schema stricter than
> the "null when not stated" rule punishes the model for following it.

**2. Where did the model guess, and where did your code have to decide?** One
example of each, from your run.

> **The model guessed** between the anchors. The rubric defines only 0 ("none published") and 5
> ("two or more"), so one published paper has no defined score — and the model gave it **3** for
> story-03 and story-05, **2** for story-04 and story-06, and **1** for story-02, five calls, the same
> fact, three different numbers (its notes call all of them "halfway"). Similarly story-02's 36
> months got experience 4 "because the part-time nature slightly reduces the weight", a rule that
> is not in the rubric. **The code had to decide** where the rubric is explicit: story-02 has no GPA,
> and the counting rules say "a story with no GPA scores 0 on academic", but the model gave academic
> 2 — the code overrode it to 0 (and experience 4 → 5, since 36 ≥ 24 months). That moved story-02 from
> 5th (2.10) to 6th (1.30). The code also decided the totals, the order, the tie-break rule, and
> flagged two evidence "quotes" (story-01, story-03) that are not in the story word for word.

**3. Did your prose ranking and your computed ranking agree?** Say which one
you trust and why — and if they agreed, what you would need to see before
trusting the prose one alone.

> They agreed on the winner (Aziza Bekova) and disagreed on second place: the prose says Tamerlan
> (story-04, "3.9" by its own arithmetic), my code says Aisha (story-05, 3.80) with Tamerlan fourth
> (3.60). The prose is not even consistent with itself: it first names Lyazzat as the winner and
> reverses a few paragraphs later; it gives Tamerlan research 3 where the scoring call gave him 2;
> and for Nurzhan it "takes the higher value" / assumes "low threes" → academic 3, which is exactly
> resolving the contradiction that the rules forbid. I trust the computed ranking: every input score
> is a field I can see, the rules that are mechanical are enforced, and the arithmetic is code.
> Before trusting a prose answer alone I would need it to name the same winner and order over several
> runs, to state per-criterion scores that match a separate scoring call, and to follow the counting
> rules — at which point I would have rebuilt the structured pipeline.

**4. The rubric has no anchor for a contradicted field.** The stories say 3.2
and then 3.5; the rubric defines a 0 and a 5 and nothing in between for this
case. Say what you did and what the rule should be.

> What I did: extraction keeps the contradiction — `gpa_4_scale` is `null` and both values are in
> `ambiguities` — and the scoring prompt says a field that is null because of a contradiction is
> "not stated": do not pick a value, do not average. The model followed it (academic 0, note: "the
> story contradicts itself regarding GPA (3.2 vs 3.5), making that field null"), and the code would
> have forced 0 anyway because the GPA is null. Story-06 ends at 1.60, fifth. I do not think that is
> the right rule: it scores a candidate who honestly reports an uncertain GPA the same as one who
> gives no academic information at all, while both stated values are below 3.7 and close together.
> The rule should be: score a contradicted numeric field on the **lower** stated value (3.2 here),
> mark the score as provisional, and send the record to a human to check the transcript — "the marker
> decides" should be an actual step in the pipeline, not a silent 0.

**5. How close were your top two candidates?** If they were within 0.05, say
what you would tell the committee and what you would change in the extraction
to make that call defensible.

> Not close: story-01 4.60 vs story-05 3.80, a gap of 0.80, and the winner was the same in the
> earlier gpt-oss-20b run (story-01, 4.40, gap 0.40 — although story-05 was missing from that run
> because of my schema bug, `runs/hard_run1_20b.log`). But places 2–4 are within 0.20 of each other
> (3.80, 3.70, 3.60), and the differences come from the guessed interpolations in answer 2 — had
> story-04's one paper got research 3 like story-03's, it would score 3.90 and be second. If the top
> two were within 0.05 I would tell the committee that the scores cannot separate them: the gap is
> smaller than the run-to-run variation of one interpolated score (one point of research = 0.30). To
> make the call defensible I would stop letting the model interpolate: extract only facts (GPA on
> 4.0, published count, countable months) with verified quotes, map them to 0–5 with a fixed table
> in code (e.g. 1 paper = 2.5, months/24·5), score several times and report the spread, and resolve
> contradicted fields with the candidate before ranking.

---

## Reflection (optional, one short paragraph)

Having now written a role prompt, compressed a conversation, and ranked six
extractions — what will you do differently the next time you build something
that has to get reliable structured output out of a model?

> Treat the model's output as untrusted input. In all three sublabs the JSON was almost always
> valid, and that was the least of it: the front-desk role ignored a direct instruction, a
> schema-valid summary dropped an open question, and a schema-valid score broke an explicit rubric
> rule. Next time I would decide up front which values code can compute itself (the grant decision,
> the totals, the rubric's fixed points) and never ask the model for those; check content, not only
> shape (quotes against the source, numbers against arithmetic); budget the provider's limits
> (reasoning tokens, daily caps) before running; and run everything more than once, because one run
> hid the front-desk effect that the third run and the ablation showed.
