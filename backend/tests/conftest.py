"""
Pytest configuration and shared fixtures for BEG_Work backend tests.
"""
import os
import pytest

# Set BASE_URL environment variable for all tests
# This reads from frontend/.env and makes it available to test modules
def pytest_configure(config):
    """Set up environment variables before tests run."""
    # Try to read from frontend/.env if not already set
    if not os.environ.get('REACT_APP_BACKEND_URL'):
        frontend_env_path = os.path.join(os.path.dirname(__file__), '../../frontend/.env')
        if os.path.exists(frontend_env_path):
            with open(frontend_env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('REACT_APP_BACKEND_URL='):
                        value = line.split('=', 1)[1].strip()
                        os.environ['REACT_APP_BACKEND_URL'] = value
                        break
    
    # Fallback to localhost if still not set
    if not os.environ.get('REACT_APP_BACKEND_URL'):
        os.environ['REACT_APP_BACKEND_URL'] = 'http://localhost:8001'


@pytest.fixture(scope="session")
def base_url():
    """Provide the base URL for API tests."""
    return os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8001').rstrip('/')
