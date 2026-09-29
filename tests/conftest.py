import pytest

def pytest_configure(config):
    config.addinivalue_line("markers", "integration: marks tests as integration tests (deselect with '-m \"not integration\"')")
