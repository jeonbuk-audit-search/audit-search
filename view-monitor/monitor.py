#!/usr/bin/env python3
"""Read public listing view counts without opening detail pages."""
import csv
import io
import os
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "https://www.jbe.go.kr/board/list.jbe"
ITEMS = [
    {"id":"1200294","name":"학교회계 운영지침·감사사례"},
    {"id":"1204144","name":"감사ON"},
    {"id":"1210880","name":"계약실무 길잡이"},
    {"id":"1212154","name":"늙크크 AI 공작소"}
]
ROOT = Path(__file__).resolve().parent
HISTORY = ROOT / "data" / "history.json"
CSV = ROOT / "data" / "history.csv"
IDS = {x["id"] for x in ITEMS}

class Rows(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.field = ""
        self.buf = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self.row = {}
        if tag == "td" and self.row is not None:
            self.field = a.get("data-cell-header", "").replace(" ", "")
            self.buf = []
        if tag == "a" and self.row is not None and "도구명" in self.field:
            m = re.search(r"(?:[?&])dataSid=(\d+)", a.get("href", ""))
            if m:
                self.row["id"] = m.group(1)

    def handle_data(self, value):
        if self.row is not None and self.field:
            self.buf.append(value)

    def handle_endtag(self, tag):
        if tag == "td" and self.row is not None:
            if "조회수" in self.field:
                m = re.search(r"\d[\d,]*", "".join(self.buf))
                if m:
                    self.row["views"] = int(m.group().replace(",", ""))
            self.field = ""
            self.buf = []
        if tag == "tr" and self.row is not None:
            if self.row.get("id") in IDS and isinstance(self.row.get("views"), int):
                self.rows.append(self.row)
            self.row = None

def fetch(page):
    q = {"boardId":"BBS_0000683", "menuCd":"DOM_000000106011002002",
         "listRow":50, "listCel":1, "paging":"ok",
         "searchOperation":"AND", "startPage":page}
    url = BASE + "?" + urlencode(q)
    req = Request(url, headers={
        "User-Agent":"Mozilla/5.0 (compatible; BigBowlViewMonitor/1.1; public-list-only)",
        "Accept":"text/html,application/xhtml+xml",
        "Accept-Language":"ko-KR,ko;q=0.9",
        "Cache-Control":"no-cache"})
    last_error = None
    for attempt in range(3):
        try:
            with urlopen(req, timeout=20) as res:
                data = res.read(2_000_000)
                encoding = res.headers.get_content_charset() or "utf-8"
                return data.decode(encoding, "replace")
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 + attempt * 2)
    raise RuntimeError(f"목록 {page}쪽 HTTP 접속 실패: {last_error}")

def main():
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule":
        # GitHub cron can be delayed/dropped. Retry at 15-minute offsets, but
        # record a fresh observation only after at least 25 minutes.
        try:
            previous = json.loads(HISTORY.read_text(encoding="utf-8"))
            now = datetime.now(timezone.utc)
            for prior in reversed(previous.get("records", [])):
                if prior.get("status") != "ok":
                    continue
                at = datetime.fromisoformat(prior["timestamp"])
                if at.tzinfo is None:
                    at = at.replace(tzinfo=timezone(timedelta(hours=9)))
                elapsed = (now - at.astimezone(timezone.utc)).total_seconds()
                if 0 <= elapsed < 25 * 60:
                    print("Recent successful observation", round(elapsed / 60, 1),
                          "minutes ago; scheduled retry skipped.", flush=True)
                    return 0
                break
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print("No valid history for cadence check:", exc, flush=True)
    values = {}
    errors = []
    for page in (1, 2, 3):
        if len(values) == 4:
            break
        try:
            p = Rows()
            p.feed(fetch(page))
            values.update({x["id"]:x["views"] for x in p.rows})
        except Exception as exc:
            errors.append(str(exc))
        if page < 3 and len(values) < 4:
            time.sleep(1.2)
    missing = IDS - values.keys()
    if missing:
        errors.append("게시판에서 찾지 못한 글: " + ", ".join(sorted(missing)))
    obj = json.loads(HISTORY.read_text(encoding="utf-8"))
    record = {
        "timestamp": datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds"),
        "counts": {x["id"]:values.get(x["id"]) for x in ITEMS},
        "status": "ok" if not missing else ("partial" if values else "error"),
        "source": os.environ.get("GITHUB_EVENT_NAME", "manual_run"),
        "errors": errors
    }
    obj["records"].append(record)
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    temp = HISTORY.with_suffix(".tmp")
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(HISTORY)
    with CSV.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(["확인시각(KST)"] + [x["name"] for x in ITEMS] + ["합계", "상태", "오류"])
        for r in obj["records"]:
            counts = r["counts"]
            nums = [counts.get(x["id"]) for x in ITEMS]
            total = sum(nums) if all(isinstance(v, int) for v in nums) else ""
            writer.writerow([r["timestamp"], *nums, total, r["status"], " / ".join(r.get("errors", []))])
    print(record["timestamp"], record["status"], record["counts"], errors, flush=True)
    return 0 if record["status"] == "ok" else 1

if __name__ == "__main__":
    sys.exit(main())
