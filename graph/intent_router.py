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
    "ghost_turned_on_standard_light_switch": re.compile(
        r"\b(?:turned?\s+(?:the\s+)?(?:light|lights)\s+on|(?:light|lights)\s+(?:turned|switched|flipped)\s+on)\b",
        re.IGNORECASE,
    ),
    "dots_visible_with_naked_eye": re.compile(
        r"\b(?:dots?\s+(?:with(?:out)?\s+)?(?:naked\s+)?eye|saw\s+dots?\s+(?:without|directly|with\s+(?:my|the)\s+(?:naked\s+)?eye))\b",
        re.IGNORECASE,
    ),
    "ghost_hunted_from_same_room_as_player": re.compile(
        r"\b(?:hunted?\s+from\s+(?:our|my|the\s+same)\s+room|ghost\s+hunted?\s+(?:in|from)\s+(?:our|the)\s+room)\b",
        re.IGNORECASE,
    ),
}

# ── Soft fact patterns (record but don't auto-eliminate) ──────────────────

SOFT_FACT_PATTERNS: dict[str, re.Pattern] = {
    "banshee_scream": re.compile(
        r"\b(?:banshee\s+scream|shriek|parabolic\s+(?:mic\s+)?shriek)\b",
        re.IGNORECASE,
    ),
    "fusebox_emf": re.compile(
        r"\b(?:(?:emf|reading)\s+(?:at|on|near)\s+(?:the\s+)?(?:fuse\s*box|breaker)|fuse\s*box\s+(?:emf|reading))\b",
        re.IGNORECASE,
    ),
    "freezing_breath_during_hunt": re.compile(
        r"\b(?:freezing\s+breath|breath\s+(?:during|in)\s+(?:a\s+)?hunt|visible\s+breath)\b",
        re.IGNORECASE,
    ),
}

# ── Behavior query patterns ───────────────────────────────────────────────

BEHAVIOR_QUERY_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(?:what|which)\s+ghosts?\s+(?:can|will|would|could)\s+(\w+)\b", re.IGNORECASE),
    re.compile(r"\b(?:it|ghost)\s+(\w+)(?:ed|s)?\s*[!.]", re.IGNORECASE),
    re.compile(r"\b(?:can\s+(?:any|a)\s+ghost|which\s+ghost)\s+(\w+)\b", re.IGNORECASE),
]

# ── Test query patterns ──────────────────────────────────────────────────

TEST_QUERY_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bwhat\s+tests?\s+(?:can\s+(?:we|i)\s+(?:do|run|try|perform)|should\s+(?:we|i)\s+(?:do|try))\s+(?:for|on)\s+(?:the\s+)?(\w+)\b", re.IGNORECASE),
    re.compile(r"\bhow\s+(?:do\s+(?:we|i)|can\s+(?:we|i)|to)\s+test\s+(?:for\s+)?(?:the\s+)?(\w+)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+tests?\s+(?:should\s+(?:we|i)\s+(?:try|do|run)|can\s+(?:we|i)\s+(?:try|do|run))\b", re.IGNORECASE),
]

# ── Theory patterns ──────────────────────────────────────────────────────

THEORY_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(\w+)\s+(?:thinks?|suspects?|believes?)\s+(?:it(?:'s|\s+is)\s+(?:a\s+)?)?(?:the\s+)?(\w+)\b", re.IGNORECASE),
    re.compile(r"\b(?:i|my)\s+(?:think|suspect|believe)\s+(?:it(?:'s|\s+is)\s+(?:a\s+)?)?(?:the\s+)?(\w+)\b", re.IGNORECASE),
    re.compile(r"\bmy\s+theory\s+is\s+(?:a\s+)?(?:the\s+)?(\w+)\b", re.IGNORECASE),
]

# ── Player patterns ──────────────────────────────────────────────────────

PLAYER_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(?:add|register)\s+player\s+(\w+)\b", re.IGNORECASE),
    re.compile(r"\b(?:register|add)\s+(\w+(?:\s+and\s+\w+)*)\s+(?:as\s+)?players?\b", re.IGNORECASE),
]


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
    player_name: str | None = None
    player_names: list[str] = field(default_factory=list)
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

    # 2. Soft fact + specific behavioral observations — checked BEFORE evidence
    #    to prevent "freezing breath" matching as "freezing" evidence,
    #    "EMF at fusebox" matching as "emf_5", or "DOTS with naked eye" as "dots".
    #    These patterns are specific enough to not false-positive on real evidence inputs.
    _EARLY_BEHAVIORAL = {**SOFT_FACT_PATTERNS}
    # Also check behavioral patterns that contain evidence keywords
    for key in ("dots_visible_with_naked_eye", "ghost_turned_on_standard_light_switch",
                "ghost_hunted_from_same_room_as_player"):
        if key in BEHAVIORAL_PATTERNS:
            _EARLY_BEHAVIORAL[key] = BEHAVIORAL_PATTERNS[key]

    for key, pattern in _EARLY_BEHAVIORAL.items():
        if pattern.search(text):
            return ParsedIntent(
                action="record_behavioral_event",
                observation=text,
                eliminator_key=key,
                raw_text=text,
            )

    # 2b. Evidence mention?
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

    # 3. Theory — "Kayden thinks it's a Poltergeist"
    #    Must come before advice/state patterns to avoid matching "thinks" as a query
    for pattern in THEORY_PATTERNS:
        m = pattern.search(text)
        if m:
            groups = m.groups()
            if len(groups) == 2:
                # Pattern 1: "X thinks it's Y"
                player, ghost_raw = groups
                ghost_name = _find_ghost_name(ghost_raw) or _find_ghost_name(text)
                if ghost_name:
                    # Normalize first-person pronouns to "me"
                    player_clean = player.strip()
                    if player_clean.lower() in ("i", "my", "me"):
                        player_clean = "me"
                    return ParsedIntent(
                        action="record_theory",
                        player_name=player_clean,
                        ghost_name=ghost_name,
                        raw_text=text,
                    )
            elif len(groups) == 1:
                # Pattern 2/3: "I suspect Y" / "my theory is Y"
                ghost_raw = groups[0]
                ghost_name = _find_ghost_name(ghost_raw) or _find_ghost_name(text)
                if ghost_name:
                    return ParsedIntent(
                        action="record_theory",
                        player_name="me",
                        ghost_name=ghost_name,
                        raw_text=text,
                    )

    # 4. Player registration — "add player Kayden"
    for pattern in PLAYER_PATTERNS:
        m = pattern.search(text)
        if m:
            raw = m.group(1)
            names = [n.strip() for n in re.split(r"\s+and\s+|,\s*", raw) if n.strip()]
            if names:
                return ParsedIntent(
                    action="register_players",
                    player_names=names,
                    raw_text=text,
                )

    # 5. Test query — "what tests for Goryo?" / "what tests should we try?"
    for pattern in TEST_QUERY_PATTERNS:
        m = pattern.search(text)
        if m:
            groups = m.groups()
            if groups and groups[0]:
                ghost_name = _find_ghost_name(groups[0]) or _find_ghost_name(text)
                if ghost_name:
                    return ParsedIntent(
                        action="query_tests",
                        ghost_name=ghost_name,
                        raw_text=text,
                    )
            # General test query — no specific ghost
            return ParsedIntent(
                action="query_tests",
                raw_text=text,
            )

    # 6. Advice / "what should we do next?"
    for pattern in ADVICE_PATTERNS:
        if pattern.search(text):
            return ParsedIntent(
                action="suggest_next_evidence",
                raw_text=text,
            )

    # 7. Ghost evidence query — "what evidence does the Banshee have?"
    #    Must come BEFORE generic state queries because "what evidence does X have"
    #    contains "what...evidence" which would match state query patterns.
    for pattern in GHOST_EVIDENCE_QUERY_PATTERNS:
        m = pattern.search(text)
        if m:
            raw_name = m.group(1)
            ghost_name = _find_ghost_name(raw_name) or _find_ghost_name(text)
            if ghost_name:
                # Don't set query_field — let query_ghost_database return
                # the full contextualized summary with CONFIRMED/untested
                # markers and "Still need to test" breakdown.
                return ParsedIntent(
                    action="query_ghost_database",
                    ghost_name=ghost_name,
                    raw_text=text,
                )

    # 8. State query?
    for pattern in STATE_PATTERNS:
        if pattern.search(text):
            return ParsedIntent(
                action="get_investigation_state",
                raw_text=text,
            )

    # 9. Behavioral observation (with eliminator)?
    for key, pattern in BEHAVIORAL_PATTERNS.items():
        if pattern.search(text):
            return ParsedIntent(
                action="record_behavioral_event",
                observation=text,
                eliminator_key=key,
                raw_text=text,
            )

    # 10. Behavior query — "what ghosts can shapeshift?"
    for pattern in BEHAVIOR_QUERY_PATTERNS:
        m = pattern.search(text)
        if m:
            return ParsedIntent(
                action="query_behavior",
                observation=m.group(1) if m.groups() else text,
                raw_text=text,
            )

    # 12. Ghost database query (generic)?
    ghost_name = _find_ghost_name(text)
    if ghost_name:
        return ParsedIntent(
            action="query_ghost_database",
            ghost_name=ghost_name,
            raw_text=text,
        )

    # 13. No deterministic match — needs LLM
    return ParsedIntent(
        action="llm_fallback",
        confidence=0.0,
        raw_text=text,
    )
