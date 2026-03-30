_Why a tool-calling agent beats a raw LLM for a deterministic rules engine — and how to build it._

---

## The Core Problem With Raw LLM Generation

A raw LLM fed ghost evidence and asked "what ghost is this?" will produce plausible-sounding answers — but it has no memory of what changed, no authoritative source of truth, and no guarantee of consistency. The same evidence state asked twice may yield different candidates. More critically, it has no way to say "I have confirmed 3 evidence types and 1 candidate remains" as a computable fact — it must _reason_ to that conclusion every time, which introduces failure modes:

- Hallucinating a ghost type not supported by the confirmed evidence
- Ignoring a ruled-out evidence type from an earlier utterance
- Forgetting behavioral eliminators mentioned 3 messages ago
- Returning different candidate counts depending on prompt phrasing

The fix is to move all deterministic reasoning _out_ of the LLM and into code. The LLM then has a single, well-scoped job: understand what the player just said, call the right tool, and optionally produce one or two sentences of contextual commentary.

---

## Architecture: Tool-Calling Agent via LangGraph

Oracle is a **LangGraph `StateGraph`** — a directed graph where nodes are Python functions and edges are conditional routing decisions. The LLM sits at one node and can call tools; the results of those tool calls update a shared typed state object. The graph loops until the LLM decides it has nothing more to do, then the final `oracle_response` field is read and spoken.

This gives us:

- **Deterministic ghost deduction** — all candidate narrowing happens in Python, not in the model
- **Persistent session state** — evidence, eliminators, and candidates live in a TypedDict that survives across turns
- **Auditability** — every state transition is logged; you can replay a session
- **Replaceability** — swap phi4-mini for claude-haiku-4-5 by changing one config value; the graph stays the same

---

## State: `OracleState`

```python
from typing import TypedDict, Literal

EvidenceID = Literal[
    "emf_5", "dots", "uv", "freezing", "orb", "writing", "spirit_box"
]

class OracleState(TypedDict):
    # Input
    user_text: str                          # Raw transcription from Whisper
    speaker: str                            # "Mike" | "Kayden"
    difficulty: str                         # "amateur" | "intermediate" | "professional" | "nightmare" | "insanity"

    # Evidence tracking
    evidence_confirmed: list[EvidenceID]    # Confirmed by player
    evidence_ruled_out: list[EvidenceID]    # Ruled out by player
    behavioral_observations: list[str]      # Free-text soft signals

    # Deduction state (computed, never set by LLM)
    eliminated_ghosts: list[str]            # Ghost names removed from pool
    candidates: list[str]                   # Remaining ghost names

    # Output
    oracle_response: str | None             # What Oracle will speak aloud
    tool_calls_made: list[str]              # For loop-exit logic
```

The LLM **reads** this state (summarised in its context window) but **never writes it directly**. All writes go through tool functions, which the graph runs as a separate node after the LLM emits a tool call.

---

## Tools (the 6 Oracle instruments)

Each tool takes arguments from the LLM call and returns a human-readable confirmation string that feeds back into the LLM context.

### `init_investigation`

```
Args: difficulty (str)
Effect: Resets evidence_confirmed, evidence_ruled_out, behavioral_observations,
        eliminated_ghosts, candidates (full 27-ghost pool)
Returns: "New investigation started on {difficulty}. 27 ghost candidates active."
```

### `record_evidence`

```
Args: evidence_id (EvidenceID), status ("confirmed" | "ruled_out")
Effect: Appends to evidence_confirmed or evidence_ruled_out.
        Runs deduction engine → updates candidates + eliminated_ghosts.
Returns: "{n} candidates remain after recording {evidence_id} as {status}:
          [list of candidate names]"
```

### `record_behavioral_event`

```
Args: observation (str), eliminates (list[str] | None)
Effect: Appends free text to behavioral_observations.
        If observation matches a known observation_eliminator key, adds those
        ghosts to eliminated_ghosts and re-runs candidate filter.
Returns: "Observation logged. {n} candidates remain." (or lists eliminated ghosts)
```

### `get_investigation_state`

```
Args: (none)
Effect: Read-only — no state mutation.
Returns: Full summary of current evidence, ruled-out, observations, candidates.
         Used when the player asks "where are we?" or "what do we have so far?"
```

### `query_ghost_database`

```
Args: ghost_name (str), field (str | None)
Effect: Read-only — loads ghost_database.yaml, returns requested field(s).
Returns: Structured data for the named ghost (evidence, hunt threshold, tells, etc.)
         Used when the player asks "what does the Deogen do?" or "how fast does
         the Revenant hunt?"
```

### `identify_ghost` _(called automatically, not triggered by LLM)_

```
Condition: len(candidates) == 1 AND len(evidence_confirmed) >= 3
Effect: Sets oracle_response to the identification announcement.
        Logged to session.jsonl.
Returns: Identification string (also fed back into LLM context for any follow-up)
```

`identify_ghost` is invoked by the graph's conditional edge logic, not by an LLM tool call. This prevents the LLM from prematurely "identifying" a ghost before the deduction engine agrees.

---

## Deduction Engine (pure Python, no LLM)

Runs inside `record_evidence` and `record_behavioral_event`. The logic:

```
1. Start with all 27 ghosts as candidates
2. For each confirmed evidence:
   - Remove any ghost whose evidence[] list does not include it
   - Exception: on Nightmare, a ghost missing one evidence is still valid
     IF that ghost has guaranteed_evidence[] matching another confirmed type
3. For each ruled-out evidence:
   - Remove any ghost whose evidence[] list contains it
   - Exception: The Mimic — ruled-out "orb" still keeps Mimic if its fake_evidence == "orb"
4. For each eliminated_ghost (from behavioral events):
   - Remove from candidates regardless of evidence state
5. Return updated candidates list
```

The deduction engine never touches the LLM. It loads `ghost_database.yaml` once at startup and holds it in memory.

---

## Graph Layout

```
          ┌─────────────┐
          │  parse_user  │  ← Whisper transcript arrives
          └──────┬──────┘
                 │
          ┌──────▼──────┐
          │  llm_node    │  ← LLM sees: state summary + user_text
          │  (phi4-mini) │    Emits: tool_call OR oracle_response
          └──────┬──────┘
                 │
        ┌────────┴────────┐
        │                 │
  [tool_call]       [direct_response]
        │                 │
 ┌──────▼──────┐   ┌──────▼──────┐
 │  tool_node  │   │  check_auto  │
 │  (executes) │   │  _comment   │
 └──────┬──────┘   └──────┬──────┘
        │                 │
        │    ┌────────────┘
        │    │
 ┌──────▼────▼──────┐
 │  post_tool_check  │  ← Did candidates change?
 └──────────┬────────┘
            │
     ┌──────┴──────┐
     │             │
 [≤5 candidates] [>5 or no change]
     │             │
 ┌───▼───┐   ┌────▼────┐
 │ auto_ │   │  done   │ → oracle_response → TTS
 │comment│   └─────────┘
 └───┬───┘
     │
 ┌───▼────────────┐
 │ exactly 1 AND  │
 │ ≥3 confirmed?  │
 └───┬────────────┘
     │
  [yes] → identify_ghost → oracle_response → TTS
  [no]  → oracle_response (commentary) → TTS
```

### Auto-comment trigger rules

|Condition|Oracle behaviour|
|---|---|
|Candidates changed AND count ≤ 5|Oracle names current candidates unprompted|
|Candidates == 1 AND evidence_confirmed ≥ 3|Oracle announces identification|
|Candidates == 1 AND evidence_confirmed < 3|Oracle flags the single candidate but notes evidence is incomplete|
|No change to candidates|Oracle stays silent (NULL) unless player asked a direct question|

---

## Library Stack

|Purpose|Library|Notes|
|---|---|---|
|Graph orchestration|`langgraph`|`StateGraph`, `ToolNode`, conditional edges|
|LLM binding|`langchain-ollama`|`ChatOllama` with `bind_tools()`|
|Tool definitions|`langchain-core`|`@tool` decorator, schema auto-generation|
|Local model|`phi4-mini` via Ollama|Temperature 0, structured output, tool-call support|
|API fallback|`langchain-anthropic`|`ChatAnthropic` with `claude-haiku-4-5`, Sprint 4|
|Game database|`PyYAML`|Load `ghost_database.yaml` at startup|
|Config|`pydantic-settings`|Same `.env.local` pattern as Demonic Tutor|

Install target (Sprint 1):

```
pip install langgraph langchain-ollama langchain-core pyyaml pydantic-settings
```

---

## LLM Prompt Design

The LLM at `llm_node` receives a tightly scoped system prompt and a user message that includes the current state summary. It is **not** asked to reason about ghost identity — it is asked to route the player's words to the right tool.

### System prompt (abridged)

```
You are Oracle, a Phasmophobia ghost-identification assistant.
You have access to tools for recording evidence, logging observations, querying the ghost database, and retrieving investigation state.

Your only jobs are:
1. Identify which tool the player's message maps to and call it.
2. If the player asks a direct question with no tool match, answer in exactly 2 sentences using only the facts in the current state.
3. If the message maps to no tool and contains no answerable question, respond with NULL.

NEVER invent evidence. NEVER name a ghost unless the deduction engine confirms it as the only candidate. NEVER exceed 2 sentences.
```

### User message structure

```
[State Summary]
Difficulty: professional
Confirmed evidence: Ghost Orb, Freezing Temperatures
Ruled out: EMF Level 5
Behavioral observations: ghost stepped in salt (→ eliminated Wraith)
Candidates (8): Banshee, Demon, Goryo, Hantu, Mimic, Moroi, Raiju, Shade

[Player ({speaker})]
{user_text}

Respond in exactly 2 sentences or call a tool. No more.
```

The state summary is regenerated at every node entry — it is always current, never stale.

---

## Sprint 1 Scope vs Sprint 2

### Sprint 1 — Simple tool-calling loop

Build the minimum viable graph: `parse_user → llm_node → tool_node → done`. No auto-commentary. No conditional edges beyond "did LLM call a tool or not?". Deduction engine runs inside `record_evidence`. Voice loop (Whisper → graph → Kokoro) wires around the graph as a thin shell.

Deliverable: You can say "ghost orb confirmed", "rule out spirit box", "what ghost is this?" and Oracle responds correctly with the deduction engine doing the narrowing.

### Sprint 2 — Full conditional graph

Add `post_tool_check` node and the auto-comment edges. Wire the `≤5 candidates` commentary and the `1 candidate + 3 evidence` identification announcement. Add `query_ghost_database` tool for behavioural queries. Add `get_investigation_state` for "where are we?" queries.

---

## File Layout (Sprint 1 target)

```
oracle/
├── main.py                  # Entry point: voice loop shell
├── config/
│   ├── settings.py          # pydantic-settings config
│   ├── .env.local           # MIC, SPEAKER, MODEL, DIFFICULTY
│   └── ghost_database.yaml  # The source of truth
├── graph/
│   ├── state.py             # OracleState TypedDict
│   ├── tools.py             # All 6 tool definitions
│   ├── deduction.py         # Pure Python candidate narrowing
│   ├── nodes.py             # parse_user, llm_node, post_tool_check, etc.
│   └── graph.py             # StateGraph assembly + compile()
└── voice/
    ├── wake_word.py         # openwakeword listener
    ├── speech_to_text.py    # faster-whisper wrapper
    └── text_to_speech.py    # kokoro-onnx wrapper (from Demonic Tutor)
```

The `voice/` layer is a thin shell. It calls `graph.invoke({"user_text": transcript, "speaker": "Mike", **current_state})` and speaks whatever comes back in `oracle_response`. No business logic lives in voice code.

---

## Why This Architecture Wins

The key insight is that **evidence deduction is a set intersection problem**, not a language modelling problem. Given 7 possible evidence types and a matrix of which ghosts require which, narrowing 27 ghosts to 1 is trivially computable. The LLM is overqualified for that task and unreliable when forced to do it unaided.

By separating concerns — LLM handles _intent parsing_ and _natural language response_, Python handles _state and deduction_ — we get both the flexibility of a language interface and the reliability of a rules engine. Oracle can never hallucinate a ghost that the deduction engine hasn't confirmed, because it doesn't have that power.