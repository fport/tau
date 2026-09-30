#!/usr/bin/env python3
"""Roadmap board: status of every issue under roadmap/ and what can be picked up next.

    python3 roadmap/board.py             all issues, grouped by layer
    python3 roadmap/board.py --next      ready-for-agent issues whose blockers are all done
    python3 roadmap/board.py --human     ready-for-human issues whose blockers are all done
    python3 roadmap/board.py --layer L1  one layer only
    python3 roadmap/board.py --check     validate statuses, ids and blocker references

Stdlib only, so it runs with the system python3 before any tooling exists.
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ISSUE_FILE = re.compile(r"^(\d{3})-[a-z0-9-]+\.md$")
LAYER_DIR = re.compile(r"^L(\d+)-")
STATUSES = (
    "needs-triage", "needs-info", "ready-for-agent", "ready-for-human",
    "needs-hardware", "in-progress", "done", "wontfix",
)
CLOSED = ("done", "wontfix")


def header(text, name):
    match = re.search(rf"^{name}:[ \t]*(.*)$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def load():
    issues, problems = {}, []
    for path in sorted(ROOT.glob("*/*.md")):
        if path.name == "README.md":
            continue
        match = ISSUE_FILE.match(path.name)
        if not match:
            problems.append(f"{path.relative_to(ROOT)}: file name must be NNN-slug.md")
            continue
        issue_id = match.group(1)
        text = path.read_text(encoding="utf-8")
        title = re.search(r"^# (\d{3}) · (.+)$", text, re.MULTILINE)
        if issue_id in issues:
            problems.append(f"{issue_id}: duplicate id ({issues[issue_id]['path']} and {path.relative_to(ROOT)})")
        if not title or title.group(1) != issue_id:
            problems.append(f"{path.relative_to(ROOT)}: first line must be '# {issue_id} · <title>'")
        blocked = header(text, "Blocked by") or ""
        issues[issue_id] = {
            "id": issue_id,
            "layer": path.parent.name,
            "path": path.relative_to(ROOT),
            "title": title.group(2) if title else path.stem,
            "status": header(text, "Status") or "needs-triage",
            "blocked_by": re.findall(r"\b\d{3}\b", blocked),
        }
    for issue in issues.values():
        if issue["status"] not in STATUSES:
            problems.append(f"{issue['id']}: unknown status '{issue['status']}'")
        for blocker in issue["blocked_by"]:
            if blocker not in issues:
                problems.append(f"{issue['id']}: blocked by unknown issue {blocker}")
    return issues, problems


def layer_key(layer):
    """Numeric layer order: L0, L1, ..., L9, L10, then everything else (backlog) by name."""
    match = LAYER_DIR.match(layer)
    return (0, int(match.group(1)), layer) if match else (1, 0, layer)


def layer_matches(layer, wanted):
    """`--layer L1` names L1-agent only, never L10-guard; the full directory name works too."""
    wanted = wanted.lower()
    return wanted in (layer.lower(), layer.split("-")[0].lower())


def open_blockers(issue, issues):
    return [b for b in issue["blocked_by"] if issues.get(b, {}).get("status") != "done"]


def main():
    parser = argparse.ArgumentParser(description="tau roadmap board")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--next", action="store_true", help="unblocked ready-for-agent issues")
    group.add_argument("--human", action="store_true", help="unblocked ready-for-human issues")
    group.add_argument("--check", action="store_true", help="validate the tracker")
    parser.add_argument("--layer", help="filter by layer, e.g. L1, L10 or backlog")
    args = parser.parse_args()

    issues, problems = load()
    if args.check:
        for problem in problems:
            print(f"✗ {problem}")
        print(f"{len(issues)} issues, {len(problems)} problems")
        return 1 if problems else 0

    rows = sorted(issues.values(), key=lambda i: (layer_key(i["layer"]), i["id"]))
    if args.layer:
        rows = [i for i in rows if layer_matches(i["layer"], args.layer)]

    if args.next or args.human:
        wanted = "ready-for-agent" if args.next else "ready-for-human"
        rows = [i for i in rows if i["status"] == wanted and not open_blockers(i, issues)]
        for issue in rows:
            print(f"{issue['id']}  {issue['title']}\n     roadmap/{issue['path']}")
        if not rows:
            print("Nothing available.")
        return 0

    layer = None
    for issue in rows:
        if issue["layer"] != layer:
            layer = issue["layer"]
            print(f"\n{layer}")
        waiting = open_blockers(issue, issues) if issue["status"] not in CLOSED else []
        note = f"  (waiting on {', '.join(waiting)})" if waiting else ""
        print(f"  {issue['id']}  {issue['status']:<16} {issue['title']}{note}")
    done = sum(1 for i in issues.values() if i["status"] == "done")
    print(f"\n{done}/{len(issues)} done")
    if problems:
        print(f"{len(problems)} tracker problems, run with --check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
