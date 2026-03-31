"""Tests for evidence synonym normalization."""
import yaml
from pathlib import Path

from graph.tools import normalize_evidence_id, VALID_EVIDENCE, _load_synonyms


def test_every_synonym_maps_to_valid_evidence():
    """Every synonym in the YAML must map to a canonical EvidenceID."""
    synonyms = _load_synonyms()
    for synonym, canonical in synonyms.items():
        assert canonical in VALID_EVIDENCE, (
            f"Synonym '{synonym}' maps to '{canonical}' which is not a valid evidence ID. "
            f"Valid IDs: {VALID_EVIDENCE}"
        )


def test_no_synonym_maps_to_multiple_ids():
    """Each synonym key should appear only once in the YAML."""
    path = Path(__file__).parent.parent / "config" / "evidence_synonyms.yaml"
    with open(path) as f:
        content = f.read()
    # YAML naturally deduplicates keys, but let's verify by counting occurrences
    lines = [
        line.split(":")[0].strip()
        for line in content.splitlines()
        if line.strip() and not line.strip().startswith("#") and ":" in line
    ]
    seen = set()
    for key in lines:
        assert key not in seen, f"Duplicate synonym key: '{key}'"
        seen.add(key)


def test_canonical_ids_resolve_to_themselves():
    """The canonical evidence IDs should pass through normalization unchanged."""
    for eid in VALID_EVIDENCE:
        assert normalize_evidence_id(eid) == eid


def test_common_synonyms():
    """Spot-check common synonym mappings."""
    assert normalize_evidence_id("ghost_orb") == "orb"
    assert normalize_evidence_id("fingerprints") == "uv"
    assert normalize_evidence_id("freezing_temperatures") == "freezing"
    assert normalize_evidence_id("ghost_writing") == "writing"
    assert normalize_evidence_id("emf") == "emf_5"


def test_normalization_is_case_insensitive():
    """Synonyms should match regardless of case."""
    assert normalize_evidence_id("Ghost_Orb") == "orb"
    assert normalize_evidence_id("FINGERPRINTS") == "uv"
    assert normalize_evidence_id("EMF") == "emf_5"


def test_unknown_input_passes_through():
    """An unknown string should pass through unchanged for downstream validation."""
    assert normalize_evidence_id("totally_bogus") == "totally_bogus"
