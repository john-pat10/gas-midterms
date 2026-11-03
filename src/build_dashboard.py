"""Inject dashboard/data.json (+ 2026 forecast and score, if present) into
dashboard/template.html -> dashboard/index.html.

The result is a single self-contained file: open it in a browser, or host it on
GitHub Pages.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "dashboard"
REPORTS = ROOT / "reports"


def main() -> None:
    template = (DASH / "template.html").read_text(encoding="utf-8")
    data = json.loads((DASH / "data.json").read_text(encoding="utf-8"))
    for key, path in [("forecast", REPORTS / "forecast_2026.json"), ("score", REPORTS / "score_2026.json"),
                      ("approval", DASH / "approval.json")]:
        data[key] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    html = template.replace("/*__DATA__*/null", json.dumps(data))
    (DASH / "index.html").write_text(html, encoding="utf-8")
    print(f"Wrote {DASH / 'index.html'} ({len(html) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
