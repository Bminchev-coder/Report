#!/usr/bin/env python3
"""
Issue summarizer: extract hours and categorize text from an issue and post/update a summary comment.

Behavior:
- Reads the GitHub event payload (GITHUB_EVENT_PATH).
- If triggered by an issue_comment the script will only proceed when the comment contains "/summarize".
- Extracts hours and assigns paragraphs to categories (Bulgarian + English keywords).
- Posts or updates a single issue comment containing the summary. The script uses the HTML marker
  "<!-- range-hours-summary -->" to find & update the previous generated comment.

Environment:
- GITHUB_EVENT_PATH : path to event JSON (provided by GitHub Actions)
- GITHUB_REPOSITORY : owner/repo
- GITHUB_TOKEN : token with permission to write issue comments (Actions' default token is sufficient if workflow has issues: write)

Usage:
  (run in GitHub Actions)
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests

# --- Config: categories & keywords (Bulgarian + English) ---
CATEGORIES = [
    "Project Management and Administrative Management",
    "Design and Project Documentation",
    "Construction Documentation",
    "Construction Process Management",
]

CATEGORY_KEYWORDS = {
    CATEGORIES[0]: [
        "управление на проекта",
        "административ",
        "координация",
        "координиране",
        "meeting",
        "meetings",
        "project management",
        "организация",
        "среща",
        "срещи",
        "админ",
        "финанси",
    ],
    CATEGORIES[1]: [
        "проектиране",
        "дизайн",
        "проектна документация",
        "design",
        "drawing",
        "concept",
        "schematic",
        "архитектур",
        "архитектура",
        "детайли",
        "layout",
        "specification",
    ],
    CATEGORIES[2]: [
        "строителна документация",
        "изпълнителна документация",
        "чертеж",
        "чертежи",
        "documentation",
        "as-built",
        "рабочи чертежи",
        "рабочи",
        "детайли",
        "boq",
        "bill of quantities",
    ],
    CATEGORIES[3]: [
        "управление в процеса на строителството",
        "управление на строителния процес",
        "строителство",
        "на място",
        "site",
        "site supervision",
        "инспекция",
        "контрол на изпълнението",
        "надзор",
        "supervision",
        "inspection",
        "бригади",
        "изпълнение",
        "монтаж",
        "строй",
    ],
}

# Regex to find numbers with optional unit (hours/minutes) - supports comma decimals
HOURS_RE = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>(?:h|hr|hrs|hour|hours|м|min|mins|minute|minutes|ч|час|часа|часове)?)",
    re.IGNORECASE,
)
RANGE_HYPHEN_RE = re.compile(r"(?P<a>\d+(?:[.,]\d+)?)\s*[-–]\s*(?P<b>\d+(?:[.,]\d+)?)")
RANGE_TO_RE = re.compile(r"(?:(?:от|from)\s*)(?P<a>\d+(?:[.,]\d+)?)\s*(?:до|to)\s*(?P<b>\d+(?:[.,]\d+)?)", re.IGNORECASE)
MINUTE_UNITS = {"m", "min", "mins", "minute", "minutes", "мин", "минути"}

COMMENT_MARKER = "<!-- range-hours-summary -->"

def parse_number(s: str) -> float:
    return float(s.replace(",", "."))

def extract_hours_from_text(text: str) -> float:
    text_l = text.lower()
    total = 0.0
    found = False

    # ranges like 8-10 or 'от 8 до 10'
    for m in RANGE_HYPHEN_RE.finditer(text_l):
        a = parse_number(m.group("a"))
        b = parse_number(m.group("b"))
        total += (a + b) / 2.0
        found = True
    for m in RANGE_TO_RE.finditer(text_l):
        a = parse_number(m.group("a"))
        b = parse_number(m.group("b"))
        total += (a + b) / 2.0
        found = True

    for m in HOURS_RE.finditer(text):
        val_s = m.group("value")
        unit = (m.group("unit") or "").strip().lower()
        try:
            val = parse_number(val_s)
        except Exception:
            continue
        if unit and any(mu in unit for mu in MINUTE_UNITS):
            total += val / 60.0
            found = True
        elif unit:
            total += val
            found = True
        else:
            # no unit: if nearby keywords indicate hours, treat as hours; otherwise be conservative
            if re.search(r"\b(hour|hours|ч|час|часа|часове|h|hr|hrs)\b", text_l):
                total += val
                found = True
            else:
                # if reasonable hour value, accept it
                if 0 < val <= 24:
                    total += val
                    found = True

    return round(total, 2)

def split_paragraphs(text: str) -> List[str]:
    parts = re.split(r"\n\s*\n", text.strip())
    return [p.strip() for p in parts if p.strip()]

def choose_category(text: str) -> str:
    t = text.lower()
    scores: Dict[str, int] = {}
    for cat, kws in CATEGORY_KEYWORDS.items():
        cnt = 0
        for kw in kws:
            if " " in kw or len(kw) > 3:
                if kw in t:
                    cnt += t.count(kw)
            else:
                if re.search(rf"\b{{re.escape(kw)}}\b", t):
                    cnt += len(re.findall(rf"\b{{re.escape(kw)}}\b", t))
        scores[cat] = cnt
    best_cat, best_score = max(scores.items(), key=lambda kv: kv[1])
    if best_score == 0:
        return "Uncategorized"
    return best_cat

def analyze_text(text: str) -> Tuple[Dict[str, float], Dict[str, List[Tuple[str, float]]], float]:
    paragraphs = split_paragraphs(text)
    totals: Dict[str, float] = defaultdict(float)
    entries: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
    grand_total = 0.0
    for p in paragraphs:
        hrs = extract_hours_from_text(p)
        cat = choose_category(p)
        totals[cat] += hrs
        entries[cat].append((p, hrs))
        grand_total += hrs
    # round totals
    for k in list(totals.keys()):
        totals[k] = round(totals[k], 2)
    grand_total = round(grand_total, 2)
    return totals, entries, grand_total

def build_comment(issue_number: int, totals: Dict[str, float], entries: Dict[str, List[Tuple[str, float]]], grand_total: float, repo: str) -> str:
    lines = []
    lines.append(COMMENT_MARKER)
    lines.append("")
    lines.append(f"### Автоматично извлечено резюме — Issue #{issue_number}")
    lines.append(f"_Repo: {repo} — generated: {datetime.utcnow().isoformat()}Z_")
    lines.append("")
    lines.append(f"**Общо (гранд тотал): {grand_total:.2f} ч**")
    lines.append("")
    for cat in CATEGORIES + ["Uncategorized"]:
        cat_total = totals.get(cat, 0.0)
        if cat_total == 0.0 and not entries.get(cat):
            continue
        lines.append(f"#### {cat}")
        lines.append(f"- Total: **{cat_total:.2f} ч**")
        lines.append("")
        for text, hrs in entries.get(cat, []):
            short = text.replace("\n", " ").strip()
            if len(short) > 240:
                short = short[:237] + "..."
            lines.append(f"- {hrs:.2f} ч — {short}")
        lines.append("")
    lines.append("_Бележка: часовете са извлечени автоматично от текста на задачата/отчета. За по-точни резултати използвайте per-day записи._")
    return "\n".join(lines)

def find_existing_comment(session: requests.Session, api_base: str, owner: str, repo: str, issue_number: int, bot_login: Optional[str]) -> Optional[dict]:
    url = f"{api_base}/repos/{{owner}}/{{repo}}/issues/{{issue_number}}/comments"
    resp = session.get(url)
    resp.raise_for_status()
    for c in resp.json():
        body = c.get("body", "")
        user = c.get("user") or {}
        if COMMENT_MARKER in body and (bot_login is None or user.get("login") == bot_login):
            return c
    return None

def post_or_update_comment(repo_full: str, issue_number: int, comment: str, token: str):
    owner, repo = repo_full.split("/")
    api_base = "https://api.github.com"
    session = requests.Session()
    session.headers.update({"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"})
    user_resp = session.get(f"{api_base}/user")
    user_resp.raise_for_status()
    bot_login = user_resp.json().get("login")
    existing = find_existing_comment(session, api_base, owner, repo, issue_number, bot_login)
    if existing:
        url = f"{api_base}/repos/{{owner}}/{{repo}}/issues/comments/{{existing['id']}}"
        resp = session.patch(url, json={"body": comment})
        resp.raise_for_status()
        print(f"Updated comment id={{existing['id']}}")
    else:
        url = f"{api_base}/repos/{{owner}}/{{repo}}/issues/{{issue_number}}/comments"
        resp = session.post(url, json={"body": comment})
        resp.raise_for_status()
        print(f"Posted new comment id={{resp.json().get('id')}}")

def main() -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN")
    if not event_path or not repo or not token:
        print("Required env vars: GITHUB_EVENT_PATH, GITHUB_REPOSITORY, GITHUB_TOKEN", file=sys.stderr)
        return 1

    with open(event_path, "r", encoding="utf-8") as fh:
        ev = json.load(fh)

    # Determine issue and controlling comment
    issue_number = None
    issue_body = ""
    actor_trigger = None  # who invoked summarize

    # If triggered by issue events
    if ev.get("issue"):
        issue = ev["issue"]
        issue_number = issue.get("number")
        issue_body = issue.get("body", "") or ""
        actor_trigger = ev.get("sender", {}).get("login")
        # Run for opened, edited, reopened
        # (workflow triggered only on those types)
    # If triggered by issue_comment event, check comment content
    if ev.get("comment") and ev.get("issue"):
        comment = ev["comment"]
        comment_body = (comment.get("body") or "").strip()
        issue = ev["issue"]
        issue_number = issue.get("number")
        issue_body = issue.get("body", "") or ""
        actor_trigger = comment.get("user", {}).get("login")
        # Only proceed if the comment contains the command '/summarize' (case-insensitive)
        if "/summarize" not in comment_body.lower():
            print("issue_comment created but does not contain /summarize — exiting")
            return 0

    if not issue_number:
        print("Could not determine issue number from event payload — exiting", file=sys.stderr)
        return 1

    print(f"Processing issue #{{issue_number}} in {{repo}} (trigger: {{actor_trigger}})")

    totals, entries, grand_total = analyze_text(issue_body)
    comment_md = build_comment(issue_number, totals, entries, grand_total, repo)
    post_or_update_comment(repo, issue_number, comment_md, token)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
