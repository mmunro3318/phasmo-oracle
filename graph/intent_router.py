"""Deterministic intent router — no LLM needed for classification.

Parses player input into structured intents using regex/keyword matching.
Handles ~85% of inputs deterministically with zero latency.
Falls back to LLM for ambiguous inputs that no pattern matches.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ── Evidence patterns ────────────────────────────────────────────────────────
# These match evidence mentions in natural language. Order matters for
# disambiguation (e.g., "emf" must not match before "emf_5" is checked).

EVIDENCE_PATTERNS: dict[str, re.Pattern] = {
    "emf_5": re.compile(
        r"\b(?:emf\s*(?:level\s*)?5|emf5|emf\b)", re.IGNORECASE
    ),
    "dots": re.compile(
        r"\b(?:d\.?o\.?t\.?s\.?(?:\s*projector)?)\b", re.IGNORECASE
    ),
    "uv": re.compile(
        r"\b(?:uv|ultra\s*violet|finger\s*prints?|hand\s*prints?|foot\s*prints?|prints)\b",
        re.IGNORECASE,
    ),
    "freezing": re.compile(
        r"\b(?:freezing(?:\s*temp(?:erature)?s?)?|it(?:'s|\s+is)\s+freezing)\b",
        re.IGNORECASE,
    ),
    "orb": re.compile(
        r"\b(?:ghost\s*orbs?|orbs?)\b", re.IGNORECASE
    ),
    "writing": re.compile(
        r"\b(?:ghost\s*)?writing\b", re.IGNORECASE
    ),
    "spirit_box": re.compile(
        r"\b(?:spirit\s*box|spiritbox)\b", re.IGNORECASE
    ),
}

# ── Confirm/rule-out signal patterns ─────────────────────────────────────────

CONFIRM_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(?:we\s+)?(?:found|got|have|confirmed|detected)\b", re.IGNORECASE),
    re.compile(r"\bwe(?:'ve|\s+have)\s+got\b", re.IGNORECASE),
    re.compile(r"\b(?:there(?:'s|\s+is|'s))\b", re.IGNORECASE),
    re.compile(r"\b(?:picked\s+up|showing|seeing|see|showed)\b", re.IGNORECASE),
    re.compile(r"\b(?:it(?:'s|\s+is)\s+(?:showing|giving))\b", re.IGNORECASE),
    re.compile(r"\bconfirm\b", re.IGNORECASE),
    re.compile(r"\bgot\s+(?:a\s+)?(?:reading|response|hit)\b", re.IGNORECASE),
    re.compile(r"\bwent\s+to\s+5\b", re.IGNORECASE),  # "EMF went to 5!"
]

RULE_OUT_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(?:no|not|never|zero|negative)\b", re.IGNORECASE),
    re.compile(r"\b(?:ruled?\s*out|eliminate[ds]?|crossed?\s+off)\b", re.IGNORECASE),
    re.compile(r"\b(?:doesn't|doesn't|does\s+not|don't|don't|do\s+not)\s+have\b", re.IGNORECASE),
    re.compile(r"\b(?:isn't|isn't|is\s+not|aren't|are\s+not)\b", re.IGNORECASE),
    re.compile(r"\b(?:didn't|did\s+not|wasn't|was\s+not)\b", re.IGNORECASE),
    re.compile(r"\b(?:can't|cannot|couldn't)\s+(?:find|get|see)\b", re.IGNORECASE),
    re.compile(r"\b(?:nothing|none)\b", re.IGNORECASE),
    re.compile(r"\brule\s+out\b", re.IGNORECASE),
]

# ── Action patterns ──────────────────────────────────────────────────────────

INIT_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(?:new|start|begin|fresh|reset)\b.*\b(?:investigation|game|match|round)\b", re.IGNORECASE),
    re.compile(r"\b(?:investigation|game|match)\b.*\b(?:new|start|begin|fresh)\b", re.IGNORECASE),
]

STATE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(?:what(?:'s|'s|\s+is)\s+left|status|remaining)\b", re.IGNORECASE),
    re.compile(r"\b(?:how\s+many\s+ghosts?|which\s+ghosts?)\b", re.IGNORECASE),
    re.compile(r"\b(?:what\s+(?:do\s+we\s+(?:have|know)|evidence|ghosts?))\b", re.IGNORECASE),
    re.compile(r"\b(?:where\s+are\s+we|investigation\s+state)\b", re.IGNORECASE),
    re.compile(r"\b(?:what\s+have\s+we\s+(?:collected|found|got))\b", re.IGNORECASE),
]

ADVICE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(?:what\s+should\s+(?:we|i)\s+(?:do|test|check|try|look\s+for))\b", re.IGNORECASE),
    re.compile(r"\b(?:what(?:'s|'s|\s+is)\s+next|next\s+step)\b", re.IGNORECASE),
    re.compile(r"\b(?:what\s+evidence\s+should)\b", re.IGNORECASE),
    re.compile(r"\b(?:suggest|recommend|advice|help\s+me)\b", re.IGNORECASE),
    re.compile(r"\b(?:what\s+(?:else\s+)?(?:can|should)\s+we\s+(?:test|check|try))\b", re.IGNORECASE),
]

GHOST_EVIDENCE_QUERY_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bwhat\s+evidence\s+does\s+(?:the\s+)?(\w+)\s+(?:have|need|require|use)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+(?:are|is)\s+(?:the\s+)?(\w+)(?:'s|'s)?\s+evidence\b", re.IGNORECASE),
    re.compile(r"\b(\w+)\s+evidence\s+(?:types?|list)\b", re.IGNORECASE),
]

ENDGAME_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(?:it\s+was|the\s+ghost\s+was|ghost\s+was|turned\s+out\s+to\s+be)\b", re.IGNORECASE),
    re.compile(r"\b(?:game\s+over|investigation\s+(?:is\s+)?(?:over|done|complete|finished))\b", re.IGNORECASE),
    re.compile(r"\b(?:we\s+(?:got\s+it|lost)|round\s+over|match\s+(?:over|done))\b", re.IGNORECASE),
]

DIFFICULTY_PATTERN = re.compile(
    r"\b(amateur|intermediate|professional|nightmare|insanity)\b", re.IGNORECASE
)

# ── Behavioral observation eliminators ───────────────────────────────────────

BEHAVIORAL_PATTERNS: dict[str, re.Pattern] = {
    "ghost_stepped_in_salt": re.compile(
        r"\b(?:stepped?\s+(?:in|on|through)\s+salt|salt\s+(?:foot)?prints?|walked?\s+(?:through|over)\s+salt)\b",
        re.IGNORECASE,
    ),
    "ghost_is_male": re.compile(
        r"\bghost\s+is\s+(?:a\s+)?(?:male|man|guy|boy)\b", re.IGNORECASE
    ),
    "ghost_turned_breaker_on": re.compile(
        r"\b(?:turned?\s+(?:the\s+)?breaker\s+on|breaker\s+(?:turned|flipped|switched)\s+on)\b",
        re.IGNORECASE,
    ),
    "ghost_turned_breaker_off_directly": re.compile(
        r"\b(?:turned?\s+(?:the\s+)?breaker\s+off|breaker\s+(?:turned|flipped|switched)\s+off)\b",
        re.IGNORECASE,
    ),
    "airball_event_observed": re.compile(
        r"\b(?:airball|air\s*ball|smoke\s*ball)\b", re.IGNORECASE
    ),
    "ghost_changed_favorite_room": re.compile(
        r"\b(?:changed?\s+(?:its\s+)?(?:favorite|fav(?:ourite)?)\s+room|moved?\s+rooms?)\b",
        re.IGNORECASE,
    ),
    "ghost_stepped_in_salt": re.compile(
        r"\b(?:salt|stepped\s+in\s+salt)\b", re.IGNORECASE
    ),
}


@dataclass
class ParsedIntent:
    """Structured intent from deterministic parsing."""
    action: str
    evidence_id: str | None = None
    status: str | None = None
    difficulty: str | None = None
    ghost_name: str | None = None
    query_field: str | None = None  # For query_ghost_database: specific field to look up
    observation: str | None = None
    eliminator_key: str | None = None
    confidence: float = 1.0
    raw_text: str = ""
    extra_evidence: list[str] = field(default_factory=list)


def _find_evidence(text: str) -> list[str]:
    """Return all evidence IDs mentioned in the text, ordered by match position."""
    matches: list[tuple[int, str]] = []
    for eid, pattern in EVIDENCE_PATTERNS.items():
        m = pattern.search(text)
        if m:
            matches.append((m.start(), eid))
    matches.sort(key=lambda x: x[0])
    return [eid for _, eid in matches]


def _is_confirm(text: str) -> bool:
    return any(p.search(text) for p in CONFIRM_PATTERNS)


def _is_rule_out(text: str) -> bool:
    return any(p.search(text) for p in RULE_OUT_PATTERNS)


def _find_ghost_name(text: str) -> str | None:
    """Check if a known ghost name appears in the text."""
    from .deduction import all_ghost_names
    text_lower = text.lower()
    for name in all_ghost_names():
        if name.lower() in text_lower:
            return name
    return None


def parse_intent(text: str) -> ParsedIntent:
    """Parse player text into a structured intent.

    Returns action="llm_fallback" with confidence=0.0 when no pattern matches.
    The graph should route these to an LLM classifier.
    """
    text = text.strip()
    if not text:
        return ParsedIntent(action="null", raw_text=text)

    # 1. New investigation?
    for pattern in INIT_PATTERNS:
        if pattern.search(text):
            diff_match = DIFFICULTY_PATTERN.search(text)
            return ParsedIntent(
                action="init_investigation",
                difficulty=diff_match.group(1).lower() if diff_match else "professional",
                raw_text=text,
            )

    # 1b. Endgame — "it was a Wraith", "game over"
    for pattern in ENDGAME_PATTERNS:
        if pattern.search(text):
            ghost_name = _find_ghost_name(text)
            if ghost_name:
                return ParsedIntent(
                    action="confirm_true_ghost",
                    ghost_name=ghost_name,
                    raw_text=text,
                )
            # "game over" without ghost name — still endgame
            return ParsedIntent(
                action="confirm_true_ghost",
                raw_text=text,
            )

    # 2. Evidence mention?
    evidence_found = _find_evidence(text)
    if evidence_found:
        is_confirm = _is_confirm(text)
        is_rule_out = _is_rule_out(text)

        # Rule-out takes precedence when both signals match, because
        # negation phrases like "don't have" contain "have" (an affirmation
        # word). Negation + affirmation = negation.
        if is_rule_out:
            status = "ruled_out"
        elif is_confirm:
            status = "confirmed"
        else:
            # No clear signal — default to confirmed (players report
            # positive findings more often than negative)
            status = "confirmed"

        return ParsedIntent(
            action="record_evidence",
            evidence_id=evidence_found[0],
            status=status,
            raw_text=text,
            extra_evidence=evidence_found[1:],
        )

    # 3. Advice / "what should we do next?"
    for pattern in ADVICE_PATTERNS:
        if pattern.search(text):
            return ParsedIntent(
                action="suggest_next_evidence",
                raw_text=text,
            )

    # 4. Ghost evidence query — "what evidence does the Banshee have?"
    #    Must come BEFORE generic state queries because "what evidence does X have"
    #    contains "what...evidence" which would match state query patterns.
    for pattern in GHOST_EVIDENCE_QUERY_PATTERNS:
        m = pattern.search(text)
        if m:
            raw_name = m.group(1)
            ghost_name = _find_ghost_name(raw_name) or _find_ghost_name(text)
            if ghost_name:
                return ParsedIntent(
                    action="query_ghost_database",
                    ghost_name=ghost_name,
                    query_field="evidence",
                    raw_text=text,
                )

    # 5. State query?
    for pattern in STATE_PATTERNS:
        if pattern.search(text):
            return ParsedIntent(
                action="get_investigation_state",
                raw_text=text,
            )

    # 6. Behavioral observation?
    for key, pattern in BEHAVIORAL_PATTERNS.items():
        if pattern.search(text):
            return ParsedIntent(
                action="record_behavioral_event",
                observation=text,
                eliminator_key=key,
                raw_text=text,
            )

    # 7. Ghost database query (generic)?
    ghost_name = _find_ghost_name(text)
    if ghost_name:
        return ParsedIntent(
            action="query_ghost_database",
            ghost_name=ghost_name,
            raw_text=text,
        )

    # 6. No deterministic match — needs LLM
    return ParsedIntent(
        action="llm_fallback",
        confidence=0.0,
        raw_text=text,
    )
