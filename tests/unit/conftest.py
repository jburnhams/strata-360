"""Unit-suite only: the hypothesis profile (isolated home and no network are autouse in tests/conftest.py for every suite)."""
from hypothesis import HealthCheck, settings

settings.register_profile('unit', deadline=None, max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
settings.load_profile('unit')


import pytest


@pytest.fixture(autouse=True)
def limits_on(monkeypatch):
    """CI sets STRATA_NO_RESOURCE_LIMITS (the guards are for local machines); the unit tests of the guards and of the resource rules need them on."""
    monkeypatch.delenv('STRATA_NO_RESOURCE_LIMITS', raising=False)


@pytest.fixture(autouse=True)
def no_repo_profiles(monkeypatch):
    """A developer's own face profile in the repository's profiles/ folder must not decide what a test finds: none is looked in unless the test sets the list."""
    from strata360.pipeline import config
    monkeypatch.setattr(config, 'LEGACY_PROFILE_DIRS', [])
