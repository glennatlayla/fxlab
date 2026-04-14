"""Root conftest for pytest - ensures project root is in sys.path."""

import sys
from pathlib import Path

# Add project root to sys.path so 'libs' and 'services' are importable
PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
