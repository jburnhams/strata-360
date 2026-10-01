import pytest


@pytest.fixture(autouse=True)
def no_resource_waits(monkeypatch):
    """The pipeline waits for free memory and an idle machine before a stage (pipeline/resources.py). A CI runner or a busy laptop may never have 4 GB free: the end-to-end tests must not wait for it."""
    monkeypatch.setenv('STRATA_NO_RESOURCE_LIMITS', '1')
