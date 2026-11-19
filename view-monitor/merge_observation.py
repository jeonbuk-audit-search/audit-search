#!/usr/bin/env python3
"""Merge one validated observation with the newest repository history after fetch.

This prevents lost updates and git rebase conflicts when two workflow_dispatch
runs start near the same time. This script runs only in a GitHub Actions checkout.
"""
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HISTORY = ROOT / "data" / "history.json"
CSV = ROOT / "data" / "history.csv"

def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: merge_observation.py <observation.json>")
    obs = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    stamp = datetime.fromisoformat(obs["timestamp"])
    if stamp.tzinfo is None:
        raise ValueError("Observation timestamp must be timezone-aware")
    data = json.loads(HISTORY.read_text(encoding="utf-8"))
    ids = tuple(x["id"] for x in data["items"])
    counts = obs.get("counts")
    if not isinstance(counts, dict) or not set(ids).issubset(set(counts)):
        raise ValueError("All configured article IDs required")
    if any((v is not None and (not isinstance(v, int) or v < 0)) for v in counts.values()):
        raise ValueError("Invalid view count")
    if obs.get("status") not in ("ok", "partial", "error"):
        raise ValueError("Invalid collection status")
    records = data.get("records")
    if not isinstance(records, list):
        raise ValueError("History records must be a list")
    if not any(r.get("timestamp") == obs["timestamp"] for r in records):
        records.append(obs)
        records.sort(key=lambda r: r["timestamp"])
    HISTORY.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CSV.parent.mkdir(parents=True, exist_ok=True)
    with CSV.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(["확인시각(KST)"] + [x["name"] for x in data["items"]] + ["합계", "상태", "오류"])
        for r in records:
            values = [r.get("counts", {}).get(k) for k in ids]
            total = sum(values) if all(isinstance(v, int) for v in values) else ""
            writer.writerow([r["timestamp"], *values, total, r.get("status", ""),
                             " / ".join(r.get("errors", []))])
    print(f"Merged observation {obs['timestamp']}; total history rows={len(records)}")

if __name__ == "__main__":
    main()
