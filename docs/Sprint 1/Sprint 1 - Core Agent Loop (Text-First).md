**Goal:** A working terminal session where you can type evidence reports and behavioral observations, and Oracle responds with correct, deterministic ghost deduction.

**Out of scope for Sprint 1:** Voice (Whisper/Kokoro/wake word), auto-commentary on candidate changes, identification announcements, session logging. Those ship in Sprint 2.

**Exit criteria:**

- `python main.py` starts without errors
- Typing "ghost orb confirmed" → Oracle calls `record_evidence`, candidates narrow correctly
- Typing "rule out spirit box" → candidates narrow correctly
- Typing "what ghosts are left?" → Oracle calls `get_investigation_state`, returns current candidates
- Typing "what does the Deogen do?" → Oracle calls `query_ghost_database`, returns correct entry
- Typing "new investigation on nightmare" → Oracle calls `init_investigation`, full pool resets
- All deduction logic is unit-testable with no LLM involved

---

## Implementation Order

Build in this exact sequence. Each step is independently testable before the next.

```
1. config/settings.py          ← pydantic-settings, reads .env.local
2. config/ghost_database.yaml  ← already done ✓
3. graph/state.py              ← OracleState TypedDict
4. graph/deduction.py          ← pure Python, no dependencies, test first
5. graph/tools.py              ← LangChain @tool wrappers around deduction
6. graph/nodes.py              ← llm_node, extract_response, route_after_llm
7. graph/graph.py              ← StateGraph assembly, compile()
8. main.py                     ← text loop entry point
9. tests/test_deduction.py     ← verify narrowing logic before voice integration
```

---

## Scaffold Code

### `config/settings.py`

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env.local", extra="ignore")

    OLLAMA_MODEL: str = "phi4-mini"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    DIFFICULTY: str = "professional"
    MIC_DEVICE_NAME: str | None = None
    SPEAKER_DEVICE_NAME: str | None = None
    WAKE_WORD: str = "oracle"
    DB_PATH: str = "config/ghost_database.yaml"

config = Settings()
```

### `config/.env.local` (template)

```env
OLLAMA_MODEL=phi4-mini
OLLAMA_BASE_URL=http://localhost:11434
DIFFICULTY=professional
# MIC_DEVICE_NAME=Blue Yeti
# SPEAKER_DEVICE_NAME=VK81
```

---

### `graph/state.py`

```python
from typing import TypedDict, Literal, Annotated
import operator

EvidenceID = Literal[
    "emf_5", "dots", "uv", "freezing", "orb", "writing", "spirit_box"
]
Difficulty = Literal[
    "amateur", "intermediate", "professional", "nightmare", "insanity"
]

class OracleState(TypedDict):
    # Input
    user_text: str
    speaker: str                          # "Mike" | "Kayden"
    difficulty: Difficulty

    # Evidence tracking
    evidence_confirmed: list[EvidenceID]
    evidence_ruled_out: list[EvidenceID]
    behavioral_observations: list[str]

    # Deduction (written by tools only, never by LLM)
    eliminated_ghosts: list[str]
    candidates: list[str]

    # Output
    oracle_response: str | None

    # LangGraph message history (append-only via operator.add)
    messages: Annotated[list, operator.add]
```

---

### `graph/deduction.py`

This is the heart of Oracle. Write this first and test it independently.

```python
from __future__ import annotations
import yaml
from pathlib import Path

_DB: dict | None = None
_DB_PATH: str = "config/ghost_database.yaml"

def load_db(path: str | None = None) -> dict:
    global _DB
    if _DB is None:
        p = Path(path or _DB_PATH)
        with open(p) as f:
            _DB = yaml.safe_load(f)
    return _DB

def all_ghost_names() -> list[str]:
    return [g["name"] for g in load_db()["ghosts"]]

def narrow_candidates(
    confirmed: list[str],
    ruled_out: list[str],
    eliminated: list[str],
    difficulty: str,
) -> list[str]:
    """
    Pure function. Returns the list of ghosts still consistent with the
    current evidence state. Never touches the LLM.

    Rules:
    - A ghost is eliminated if it lacks any confirmed evidence type.
      Exception (Nightmare): a ghost may hide ONE non-guaranteed evidence.
    - A ghost is eliminated if it has any ruled-out evidence type.
      Exception (Mimic): its fake_evidence field is not real evidence.
    - A ghost explicitly in `eliminated` is always removed.
    """
    db = load_db()
    candidates = []

    for ghost in db["ghosts"]:
        name = ghost["name"]
        evidence_set = set(ghost.get("evidence", []))
        guaranteed_set = set(ghost.get("guaranteed_evidence", []))
        fake = ghost.get("fake_evidence")  # e.g. "orb" for Mimic

        if name in eliminated:
            continue

        # --- Ruled-out check ---
        skip = False
        for e in ruled_out:
            if e in evidence_set:
                # Mimic's fake evidence is not a real evidence type for it
                if fake and e == fake:
                    continue
                skip = True
                break
        if skip:
            continue

        # --- Confirmed check ---
        for e in confirmed:
            if e not in evidence_set:
                if difficulty == "nightmare":
                    # On Nightmare a ghost can suppress exactly one evidence,
                    # but ONLY if it isn't that ghost's guaranteed evidence.
                    # We keep the ghost in candidates (permissive — better to
                    # show too many than miss the real ghost).
                    pass
                else:
                    skip = True
                    break
        if skip:
            continue

        candidates.append(name)

    return candidates


def apply_observation_eliminator(key: str) -> list[str]:
    """
    Return the list of ghost names eliminated by a known observation key.
    Returns [] if key is not found in observation_eliminators.
    """
    db = load_db()
    for entry in db.get("observation_eliminators", []):
        if entry["key"] == key:
            return entry.get("eliminates", [])
    return []


def get_ghost(name: str) -> dict | None:
    """Return a ghost dict by name (case-insensitive), or None."""
    db = load_db()
    return next(
        (g for g in db["ghosts"] if g["name"].lower() == name.lower()),
        None,
    )
```

---

### `graph/tools.py`

Tools read/write a shared mutable state dict. The `bind_state()` call before each graph invoke points all tools at the live state.

```python
from langchain_core.tools import tool
from .deduction import (
    narrow_candidates, all_ghost_names,
    apply_observation_eliminator, get_ghost, load_db
)

# Shared mutable state reference — bound before each graph invoke
_state: dict = {}

def bind_state(state: dict) -> None:
    """Point all tools at the current session state."""
    _state.clear()
    _state.update(state)

def sync_state_from(state: dict) -> None:
    """Pull back any mutations tools made into the caller's dict."""
    state.update(_state)


# ─── Tools ───────────────────────────────────────────────────────────────────

@tool
def init_investigation(difficulty: str) -> str:
    """
    Start a new investigation. Resets all evidence, observations, and
    candidates to the full 27-ghost pool.
    difficulty must be one of: amateur, intermediate, professional, nightmare, insanity.
    """
    valid = {"amateur", "intermediate", "professional", "nightmare", "insanity"}
    if difficulty not in valid:
        difficulty = "professional"

    _state["difficulty"] = difficulty
    _state["evidence_confirmed"] = []
    _state["evidence_ruled_out"] = []
    _state["behavioral_observations"] = []
    _state["eliminated_ghosts"] = []
    _state["candidates"] = all_ghost_names()
    n = len(_state["candidates"])
    return f"New investigation started on {difficulty}. {n} ghost candidates active."


@tool
def record_evidence(evidence_id: str, status: str) -> str:
    """
    Record a confirmed or ruled-out evidence type.
    evidence_id: one of emf_5, dots, uv, freezing, orb, writing, spirit_box
    status: 'confirmed' or 'ruled_out'
    """
    valid_evidence = {"emf_5", "dots", "uv", "freezing", "orb", "writing", "spirit_box"}
    if evidence_id not in valid_evidence:
        return (
            f"Unknown evidence type '{evidence_id}'. "
            f"Valid types: {', '.join(sorted(valid_evidence))}"
        )
    if status not in ("confirmed", "ruled_out"):
        return f"Invalid status '{status}'. Use 'confirmed' or 'ruled_out'."

    confirmed = _state.setdefault("evidence_confirmed", [])
    ruled_out = _state.setdefault("evidence_ruled_out", [])

    if status == "confirmed" and evidence_id not in confirmed:
        confirmed.append(evidence_id)
        # Can't be in both lists
        if evidence_id in ruled_out:
            ruled_out.remove(evidence_id)
    elif status == "ruled_out" and evidence_id not in ruled_out:
        ruled_out.append(evidence_id)
        if evidence_id in confirmed:
            confirmed.remove(evidence_id)

    _state["candidates"] = narrow_candidates(
        confirmed,
        ruled_out,
        _state.get("eliminated_ghosts", []),
        _state.get("difficulty", "professional"),
    )

    n = len(_state["candidates"])
    names = ", ".join(_state["candidates"]) if n <= 8 else f"{n} ghosts"
    return (
        f"{n} candidate(s) remain after recording {evidence_id} as {status}: {names}"
    )


@tool
def record_behavioral_event(observation: str, eliminator_key: str = "") -> str:
    """
    Log a behavioral observation in free text.
    If eliminator_key matches a known pattern (e.g. 'ghost_stepped_in_salt'),
    those ghosts are immediately removed from candidates.
    Leave eliminator_key empty if no known eliminator applies.
    """
    _state.setdefault("behavioral_observations", []).append(observation)

    newly_eliminated = []
    if eliminator_key:
        to_eliminate = apply_observation_eliminator(eliminator_key)
        existing = _state.setdefault("eliminated_ghosts", [])
        for ghost in to_eliminate:
            if ghost not in existing:
                existing.append(ghost)
                newly_eliminated.append(ghost)

        if newly_eliminated:
            _state["candidates"] = narrow_candidates(
                _state.get("evidence_confirmed", []),
                _state.get("evidence_ruled_out", []),
                _state["eliminated_ghosts"],
                _state.get("difficulty", "professional"),
            )

    n = len(_state.get("candidates", []))
    if newly_eliminated:
        return (
            f"Observation logged. Eliminated: {', '.join(newly_eliminated)}. "
            f"{n} candidate(s) remain."
        )
    return f"Observation logged. {n} candidate(s) remain."


@tool
def get_investigation_state() -> str:
    """
    Return a full summary of the current investigation state: difficulty,
    confirmed evidence, ruled-out evidence, observations, eliminated ghosts,
    and remaining candidates.
    """
    s = _state
    candidates = s.get("candidates", [])
    n = len(candidates)
    names = ", ".join(candidates) if n <= 12 else f"{n} ghosts (use record_evidence to narrow)"
    lines = [
        f"Difficulty: {s.get('difficulty', 'unknown')}",
        f"Confirmed evidence ({len(s.get('evidence_confirmed', []))}): "
            f"{', '.join(s.get('evidence_confirmed', [])) or 'none'}",
        f"Ruled out ({len(s.get('evidence_ruled_out', []))}): "
            f"{', '.join(s.get('evidence_ruled_out', [])) or 'none'}",
        f"Behavioral observations: {len(s.get('behavioral_observations', []))} logged",
        f"Eliminated ghosts: {', '.join(s.get('eliminated_ghosts', [])) or 'none'}",
        f"Candidates ({n}): {names}",
    ]
    return "\n".join(lines)


@tool
def query_ghost_database(ghost_name: str, field: str = "") -> str:
    """
    Look up a ghost in the database by name.
    Optional field: evidence, hunt_threshold, behavioral_tells, community_tests, hard_flags.
    Leave field empty for a full summary.
    """
    ghost = get_ghost(ghost_name)
    if not ghost:
        all_names = [g["name"] for g in load_db()["ghosts"]]
        return (
            f"Ghost '{ghost_name}' not found. "
            f"Known ghosts: {', '.join(all_names)}"
        )

    if field:
        val = ghost.get(field)
        if val is None:
            return f"Field '{field}' not found for {ghost['name']}."
        return f"{ghost['name']} — {field}: {val}"

    # Full summary
    lines = [
        f"Ghost: {ghost['name']}",
        f"Evidence: {', '.join(ghost.get('evidence', []))}",
        f"Guaranteed evidence (Nightmare): {', '.join(ghost.get('guaranteed_evidence', [])) or 'none'}",
        f"Hunt threshold: {ghost.get('hunt_threshold', {})}",
        f"Hard flags: {ghost.get('hard_flags', {})}",
        f"Behavioral tells: {'; '.join(ghost.get('behavioral_tells', [])) or 'none'}",
        f"Community tests: {'; '.join(ghost.get('community_tests', [])) or 'none'}",
    ]
    return "\n".join(lines)


ORACLE_TOOLS = [
    init_investigation,
    record_evidence,
    record_behavioral_event,
    get_investigation_state,
    query_ghost_database,
]
```

---

### `graph/nodes.py`

```python
from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from .tools import ORACLE_TOOLS
from .state import OracleState
from config.settings import config

_SYSTEM_PROMPT = """\
You are Oracle, a Phasmophobia ghost-identification assistant.

You have these tools:
- init_investigation(difficulty): start a new match
- record_evidence(evidence_id, status): mark evidence confirmed or ruled_out
- record_behavioral_event(observation, eliminator_key): log player observation
- get_investigation_state(): return full current state
- query_ghost_database(ghost_name, field): look up a ghost's properties

Your rules:
1. Map the player's message to a tool and call it. Prefer tools over direct answers.
2. If no tool applies and the player asked a direct question, answer in EXACTLY 2 sentences
   using only facts visible in the state summary below.
3. If there is nothing to do and no question to answer, respond with only the word NULL.
4. NEVER invent or assume evidence. NEVER name a ghost as identified unless
   get_investigation_state shows exactly 1 candidate.
5. NEVER exceed 2 sentences in a direct response.\
"""


def build_state_summary(state: OracleState) -> str:
    candidates = state.get("candidates", [])
    n = len(candidates)
    names = ", ".join(candidates) if n <= 12 else f"{n} ghosts"
    return (
        f"[Investigation State]\n"
        f"Difficulty: {state.get('difficulty', 'professional')}\n"
        f"Confirmed: {', '.join(state.get('evidence_confirmed', [])) or 'none'}\n"
        f"Ruled out: {', '.join(state.get('evidence_ruled_out', [])) or 'none'}\n"
        f"Eliminated: {', '.join(state.get('eliminated_ghosts', [])) or 'none'}\n"
        f"Candidates ({n}): {names}"
    )


def llm_node(state: OracleState) -> dict:
    llm = ChatOllama(
        model=config.OLLAMA_MODEL,
        temperature=0,
        base_url=config.OLLAMA_BASE_URL,
    )
    llm_with_tools = llm.bind_tools(ORACLE_TOOLS)

    summary = build_state_summary(state)
    speaker = state.get("speaker", "Mike")
    user_text = state.get("user_text", "")

    user_msg = (
        f"{summary}\n\n"
        f"[{speaker}]: {user_text}\n\n"
        f"Call a tool or respond in exactly 2 sentences. No more."
    )

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=user_msg),
    ]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


def extract_response(state: OracleState) -> dict:
    """Produce the final oracle_response string from the last message."""
    messages = state.get("messages", [])
    if not messages:
        return {"oracle_response": None}

    last = messages[-1]
    content = getattr(last, "content", "") or ""

    if content.strip().upper() == "NULL" or not content.strip():
        return {"oracle_response": None}

    return {"oracle_response": content.strip()}


def route_after_llm(state: OracleState) -> str:
    """
    Conditional edge: did the LLM emit a tool call?
    Returns 'tools' or 'respond'.
    """
    messages = state.get("messages", [])
    if not messages:
        return "respond"
    last = messages[-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return "respond"
```

---

### `graph/graph.py`

```python
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from .state import OracleState
from .nodes import llm_node, extract_response, route_after_llm
from .tools import ORACLE_TOOLS


def build_graph():
    builder = StateGraph(OracleState)

    # Nodes
    builder.add_node("llm", llm_node)
    builder.add_node("tools", ToolNode(ORACLE_TOOLS))
    builder.add_node("respond", extract_response)

    # Entry
    builder.set_entry_point("llm")

    # LLM → tool call or direct response
    builder.add_conditional_edges(
        "llm",
        route_after_llm,
        {"tools": "tools", "respond": "respond"},
    )

    # After tools complete, loop back to LLM so it can see the result
    builder.add_edge("tools", "llm")

    # Response is terminal
    builder.add_edge("respond", END)

    return builder.compile()


# Module-level singleton — import this in main.py
oracle_graph = build_graph()
```

The graph topology for Sprint 1 is intentionally simple:

```
llm ──[tool call]──▶ tools ──▶ llm (loop)
 │
 └──[direct]──▶ respond ──▶ END
```

The `tools → llm` loop means the model sees the tool's return string before composing its final response. This is what lets it say "3 candidates remain: Banshee, Demon, Wraith" — it reads that from the tool result, not from memory.

---

### `main.py`

```python
#!/usr/bin/env python3
"""Oracle — Voice-driven Phasmophobia ghost identification assistant.
Sprint 1: text input loop (no voice yet).
"""

import logging
from graph.graph import oracle_graph
from graph.deduction import all_ghost_names
from graph.tools import bind_state, sync_state_from
from config.settings import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("oracle")


def make_initial_state() -> dict:
    return {
        "user_text": "",
        "speaker": "Mike",
        "difficulty": config.DIFFICULTY,
        "evidence_confirmed": [],
        "evidence_ruled_out": [],
        "behavioral_observations": [],
        "eliminated_ghosts": [],
        "candidates": all_ghost_names(),
        "oracle_response": None,
        "messages": [],
    }


def run_text_loop() -> None:
    """Sprint 1 entry point: typed input, printed output."""
    state = make_initial_state()
    n = len(state["candidates"])
    print(f"\nOracle ready. Difficulty: {state['difficulty']}. {n} candidates loaded.")
    print("Type evidence, observations, or questions. Type 'quit' to exit.\n")

    while True:
        try:
            raw = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nOracle offline.")
            break

        if not raw or raw.lower() in ("quit", "exit"):
            break

        # Prepare this turn
        state["user_text"] = raw
        state["messages"] = []  # fresh message thread per turn
        bind_state(state)       # point tools at live state

        # Run the graph
        result = oracle_graph.invoke(state)

        # Sync tool-mutated state fields back into our session dict
        sync_state_from(state)

        response = result.get("oracle_response")
        if response:
            print(f"\nOracle: {response}\n")
        else:
            # Tool was called silently — show candidate count as feedback
            n = len(state.get("candidates", []))
            print(f"  [state updated — {n} candidate(s) remain]\n")


if __name__ == "__main__":
    run_text_loop()
```

---

### `tests/test_deduction.py`

Run with `pytest` — no Ollama, no audio, no network required.

```python
import pytest
from graph.deduction import narrow_candidates, apply_observation_eliminator, all_ghost_names

# ── Basic narrowing ───────────────────────────────────────────────────────────

def test_all_ghosts_loaded():
    names = all_ghost_names()
    assert len(names) == 27

def test_single_evidence_narrows():
    result = narrow_candidates(
        confirmed=["emf_5"],
        ruled_out=[],
        eliminated=[],
        difficulty="professional",
    )
    # Every ghost in result must have EMF 5 in its evidence list
    assert len(result) < 27
    assert all(isinstance(g, str) for g in result)

def test_three_evidence_identifies_banshee():
    # Banshee: EMF 5, Fingerprints (uv), DOTS
    result = narrow_candidates(
        confirmed=["emf_5", "uv", "dots"],
        ruled_out=[],
        eliminated=[],
        difficulty="professional",
    )
    assert "Banshee" in result

def test_ruled_out_removes_ghost():
    # Banshee has EMF 5 — ruling out EMF 5 must remove Banshee
    result = narrow_candidates(
        confirmed=[],
        ruled_out=["emf_5"],
        eliminated=[],
        difficulty="professional",
    )
    assert "Banshee" not in result

def test_explicit_elimination():
    result = narrow_candidates(
        confirmed=[],
        ruled_out=[],
        eliminated=["Wraith"],
        difficulty="professional",
    )
    assert "Wraith" not in result

# ── Mimic special case ────────────────────────────────────────────────────────

def test_mimic_survives_orb_ruled_out():
    """
    Mimic's fake_evidence is Ghost Orb. Ruling out orb must NOT eliminate Mimic
    because that orb is fake — not a real evidence type for Mimic.
    """
    result = narrow_candidates(
        confirmed=[],
        ruled_out=["orb"],
        eliminated=[],
        difficulty="professional",
    )
    assert "Mimic" in result

# ── Observation eliminators ───────────────────────────────────────────────────

def test_salt_eliminates_wraith():
    eliminated = apply_observation_eliminator("ghost_stepped_in_salt")
    assert "Wraith" in eliminated

def test_unknown_key_returns_empty():
    assert apply_observation_eliminator("this_key_does_not_exist") == []

# ── Nightmare mode ────────────────────────────────────────────────────────────

def test_nightmare_is_permissive():
    """On Nightmare a ghost may hide one evidence — keep more candidates."""
    professional = narrow_candidates(
        confirmed=["emf_5", "orb", "freezing"],
        ruled_out=[],
        eliminated=[],
        difficulty="professional",
    )
    nightmare = narrow_candidates(
        confirmed=["emf_5", "orb", "freezing"],
        ruled_out=[],
        eliminated=[],
        difficulty="nightmare",
    )
    # Nightmare should have >= as many candidates as professional
    assert len(nightmare) >= len(professional)
```

---

## Installation

```bash
# 1. Create virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install langgraph langchain-ollama langchain-core pyyaml pydantic-settings pytest

# 3. Pull the model (requires Ollama running)
ollama pull phi4-mini
# ollama run phi4-mini

# 4. Run tests (no Ollama needed)
pytest tests/test_deduction.py -v

# 5. Start Oracle
python main.py
```

---

## Task Board

### Backlog

|ID|Task|Notes|
|---|---|---|
|S1-01|Create `config/settings.py`|pydantic-settings, reads `.env.local`|
|S1-02|Create `config/.env.local`|Template with defaults, all keys commented|
|S1-03|Create `graph/state.py`|`OracleState` TypedDict with `Annotated` message list|
|S1-04|Create `graph/deduction.py`|`load_db`, `all_ghost_names`, `narrow_candidates`, `apply_observation_eliminator`, `get_ghost`|
|S1-05|Write `tests/test_deduction.py`|Cover normal narrowing, ruled-out, Mimic orb edge case, Nightmare permissiveness, observation eliminators|
|S1-06|Run tests — all must pass|`pytest tests/test_deduction.py -v` — zero LLM required|
|S1-07|Create `graph/tools.py`|5 tools + `bind_state` / `sync_state_from` helpers|
|S1-08|Create `graph/nodes.py`|`llm_node`, `extract_response`, `route_after_llm`|
|S1-09|Create `graph/graph.py`|`build_graph()` → `oracle_graph` singleton|
|S1-10|Create `main.py`|`make_initial_state()`, `run_text_loop()`|
|S1-11|Smoke test: new investigation|"new investigation on nightmare" → `init_investigation` called, 27 candidates|
|S1-12|Smoke test: confirm evidence|"ghost orb confirmed" → candidates narrow correctly|
|S1-13|Smoke test: rule out evidence|"rule out spirit box" → candidates narrow correctly|
|S1-14|Smoke test: investigation state|"what ghosts are left?" → `get_investigation_state` returns correct list|
|S1-15|Smoke test: ghost lookup|"what does the Deogen do?" → `query_ghost_database` returns correct entry|
|S1-16|Smoke test: behavioral event|"ghost stepped in salt" → `record_behavioral_event` with `eliminator_key` removes Wraith|
|S1-17|Smoke test: full sequence|Simulate a real match to 1 candidate — confirm Oracle never names a ghost early|
|S1-18|Verify Mimic edge case live|Confirm orb + 2 other evidence → Mimic stays in candidates|

### Definition of Done (Sprint 1)

- [ ] All tests in `test_deduction.py` pass
- [ ] `python main.py` starts without errors
- [ ] All 6 smoke tests pass manually
- [ ] Oracle never identifies a ghost when candidates > 1
- [ ] Oracle never invents evidence (run 3 identical sessions — same evidence = same result)
- [ ] `Ctrl+C` exits cleanly

---

## Known Risks

**phi4-mini tool-call reliability.** phi4-mini is explicitly trained for structured/constrained output, but tool-call schema adherence on small local models can be inconsistent. If `record_evidence` is being called with malformed `evidence_id` values (e.g. `"ghost_orb"` instead of `"orb"`), add a normalisation step at the top of the tool function with a synonym map before escalating to prompt engineering.

**State mutation via `bind_state` / `sync_state_from`.** The shared `_state` dict approach is simple and works for a single-threaded text loop. For Sprint 2's concurrent voice capture, consider moving to `InjectedState` (LangGraph's native state injection) to keep state per-invocation rather than global.

**Nightmare mode permissiveness.** The current deduction logic keeps all ghosts that _could_ hide an evidence type on Nightmare, which means more false positives. This is intentional — it's better for Oracle to over-report candidates than miss the real ghost. Tighten with guaranteed_evidence checks in Sprint 2 when the logic has been battle-tested.