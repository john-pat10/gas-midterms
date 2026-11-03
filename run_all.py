"""Run the full pipeline: download -> build dataset -> analysis -> dashboard."""
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).parent / "src"
for step in ["fetch_data.py", "build_dataset.py", "approval_analysis.py", "analysis.py",
             "forecast_2026.py", "score_2026.py", "build_dashboard.py"]:
    print(f"\n=== {step} ===")
    subprocess.run([sys.executable, str(SRC / step)], check=True, cwd=SRC)
