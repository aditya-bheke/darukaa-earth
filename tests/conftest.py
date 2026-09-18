import os
import sys
import tempfile
from pathlib import Path

# Deterministic, offline test configuration — must be set before `darukaa` is imported.
os.environ["LLM_PROVIDER"] = "none"
os.environ["GEO_ENABLED"] = "false"
os.environ["DARUKAA_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "test.db")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
