"""Shared test fixtures and configuration.

Resets module-level caches between tests to prevent state leaks.
Registers custom pytest markers.
"""
import pytest


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "integration: requires real audio/GPU hardware")
    config.addinivalue_line("markers", "slow: timing-sensitive tests")


@pytest.fixture(autouse=True)
def _reset_deduction_cache():
    """Reset the deduction module's cached ghost database between tests."""
    yield
    try:
        from oracle.deduction import reset_db
        reset_db()
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def _reset_engine_caches():
    """Reset engine module-level caches (synonyms, ghost tests) between tests."""
    yield
    try:
        import oracle.engine as eng
        eng._SYNONYMS = None
        eng._GHOST_TESTS = None
    except (ImportError, AttributeError):
        pass


@pytest.fixture
def fresh_engine():
    """Provide a fresh InvestigationEngine with a professional game started.

    Named fresh_engine to avoid colliding with local engine fixtures
    in individual test files.
    """
    from oracle.engine import InvestigationEngine
    e = InvestigationEngine()
    e.new_game("professional")
    return e
