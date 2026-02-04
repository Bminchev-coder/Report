#!/usr/bin/env python3

"""
Compute cumulative hours for a date range and post/update a GitHub Issue comment.

Behavior:
- If a tasks file is provided and contains ISO-dated lines (YYYY-MM-DD) with time markers
  (e.g. "2026-01-05 Worked 9 hours"), the script sums exact hours for dates in the range
  (respecting workdays_only if set).
- Otherwise it computes estimates for:
    min = days_count * 8.0
    avg = days_count * 8.5
    max = days_count * 9.0
  where days_count is the number of working days (Mon–Fri) in the inclusive range
  unless --calendar is passed to count all days.
- Posts a markdown comment to the target GitHub issue. If a prior comment created by this
  workflow exists (it uses an HTML marker), the script updates that comment instead.

Required environment:
- GITHUB_REPOSITORY (owner/repo) — provided automatically in GitHub Actions
- GITHUB_TOKEN — provided in Actions as well

Usage (CLI):
  python3 scripts/range_total_and_post.py --start 2026-01-05 --end 2026-01-30 --issue 3

Optional:
  --tasks-file tasks.txt          # parse exact hours from file
  --calendar                      # count all calendar days instead of workdays
  --repo owner/repo               # defaults to GITHUB_REPOSITORY env var
"""
from __future__ import annotations

import argparse
import os
import re
from datetime import date, datetime, timedelta
from typing import Dict, Optional

import requests

ISO_DATE_RE = re.compile(r"(?P<iso>\d{4}-\d{2}-\d{2})")
HOUR_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>h|hr|hrs|hour|hours|m|min|mins|minute|minutes)\b",
    re.IGNORECASE,
)

COMMENT_MARKER = "<!-- range-hours-summary -->"

def iterate_inclusive(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)

def count_days(start: date, end: date, workdays_only: bool) -> int:
    c = 0
    for d in iterate_inclusive(start, end):
        if workdays_only:
            if d.weekday() < 5:
                c += 1
        else:
            c += 1
    return c

def parse_tasks_file(path: str) -> Dict[date, float]:
    """
    Parse lines in tasks file for ISO dates and hour markers.
    Returns per-day totals as a dict: date -> hours
    """
    per_day: Dict[date, float] = {}
    if not os.path.exists(path):
        return per_day
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            m = ISO_DATE_RE.search(line)
            if not m:
                continue
            try:
                d = datetime.fromisoformat(m.group("iso")).date()
            except ValueError:
                continue
            hours = 0.0
            for hm in HOUR_RE.finditer(line):
                val = float(hm.group("value"))
                unit = hm.group("unit").lower()
                if unit.startswith("m"):
                    hours += val / 60.0
                else:
                    hours += val
            if hours > 0:
                per_day[d] = per_day.get(d, 0.0) + hours
    return per_day

def sum_using_tasks(start: date, end: date, per_day: Dict[date, float], workdays_only: bool) -> float:
    total = 0.0
    for d in iterate_inclusive(start, end):
        if workdays_only and d.weekday() >= 5:
            continue
        total += per_day.get(d, 0.0)
    return total

def build_comment(start: date, end: date, workdays_only: bool, days_count: int, exact_total: Optional[float], repo: str) -> str:
    header = f"Range hours summary: {start.isoformat()} → {end.isoformat()}\n\n"
    mode = "Working days (Mon–Fri)" if workdays_only else "All calendar days"
    if exact_total is not None:
        body = (
            f"{COMMENT_MARKER}\n\n"
            f"**{mode} counted between {start.isoformat()} and {end.isoformat()} (inclusive).**\n\n"
            f"Total counted days: {days_count}\n\n"
            f"**Exact total hours:** **{exact_total:.2f} hours**\n\n"
            f"_This comment is auto-updated by the repository workflow._"
        )
    else:
        min_total = days_count * 8.0
        avg_total = days_count * 8.5
        max_total = days_count * 9.0
        body = (
            f"{COMMENT_MARKER}\n\n"
            f"**{mode} counted between {start.isoformat()} and {end.isoformat()} (inclusive).**\n\n"
            f"Total counted days: {days_count}\n\n"
            f"Estimated totals (using your daily range 8–9 h/day):\n\n"
            f"- 8.0 h/day → **{min_total:.2f} hours**\n"
            f"- 8.5 h/day → **{avg_total:.2f} hours** (recommended midpoint)\n"
            f"- 9.0 h/day → **{max_total:.2f} hours**\n\n"
            f"_This comment is auto-updated by the repository workflow._"
        )
    return header + body

def find_existing_comment(session: requests.Session, api_base: str, owner: str, repo: str, issue_number: int, bot_login: str) -> Optional[dict]:
    # List comments and find one that contains our marker and was created by the bot (or by the token's user)
    url = f"{api_base}/repos/{owner}/{repo}/issues/{issue_number}/comments"
    resp = session.get(url)
    resp.raise_for_status()
    for c in resp.json():
        body = c.get("body", "")
        user = c.get("user", {}) or {}
        if COMMENT_MARKER in body and (user.get("login") == bot_login or bot_login is None):
            return c
    return None

def post_or_update_comment(repo_full: str, issue_number: int, comment: str, token: str):
    owner, repo = repo_full.split("/")
    api_base = "https://api.github.com"
    session = requests.Session()
    session.headers.update({"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"})
    # get token user
    user_resp = session.get(f"{api_base}/user")
    user_resp.raise_for_status()
    bot_login = user_resp.json().get("login")
    existing = find_existing_comment(session, api_base, owner, repo, issue_number, bot_login)
    if existing:
        url = f"{api_base}/repos/{owner}/{repo}/issues/comments/{existing['id']}"
        resp = session.patch(url, json={"body": comment})
        resp.raise_for_status()
        print(f"Updated comment id={existing['id']}")
    else:
        url = f"{api_base}/repos/{owner}/{repo}/issues/{issue_number}/comments"
        resp = session.post(url, json={"body": comment})
        resp.raise_for_status()
        print(f"Posted new comment id={resp.json().get('id')}")

def main():
    p = argparse.ArgumentParser(description="Compute range hours and post a GitHub issue comment.")
    p.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    p.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    p.add_argument("--issue", required=True, type=int, help="GitHub issue number to post the summary to")
    p.add_argument("--tasks-file", default=None, help="Optional tasks file path to parse exact hours (uses ISO dates in lines)")
    p.add_argument("--calendar", action="store_true", help="Count calendar days instead of workdays")
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"), help="owner/repo (defaults to GITHUB_REPOSITORY)")
    args = p.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN environment variable is required")

    repo = args.repo
    if not repo:
        raise SystemExit("Repository (owner/repo) must be specified via --repo or GITHUB_REPOSITORY env var")

    start = datetime.fromisoformat(args.start).date()
    end = datetime.fromisoformat(args.end).date()
    if end < start:
        raise SystemExit("End date must be >= start date")

    workdays_only = not args.calendar

    exact_total = None
    days_count = count_days(start, end, workdays_only)

    if args.tasks_file:
        per_day = parse_tasks_file(args.tasks_file)
        if per_day:
            exact_total = sum_using_tasks(start, end, per_day, workdays_only)
            # If the tasks file had data but none inside the range, exact_total will be 0.0.
            # We still post the exact total (0.0) so you know the file had entries but nothing in range.

    comment = build_comment(start, end, workdays_only, days_count, exact_total, repo)
    post_or_update_comment(repo, args.issue, comment, token)


if __name__ == "__main__":
    main()
