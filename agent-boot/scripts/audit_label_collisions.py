#!/usr/bin/env python3
"""Check every declared LabelSet against the real names this system has crawled.

The unit guard (``relay/tests/test_fb_label_guard.py``) runs against a corpus of
Vietnamese name syllables committed to the repo. That corpus is a model of
reality, and models drift: Facebook shows names the corpus does not cover, and a
new token can be safe against the fixture while eating live candidates.

This script closes that loop. It reads `content_items.author` — the names this
farm has actually seen — and reports which declared tokens would swallow them.
Anything it finds is a syllable the committed corpus is missing.

The real names stay in the database. What comes back to the repo is the
syllable, never the person.

Usage::

    uv run python scripts/audit_label_collisions.py
    uv run python scripts/audit_label_collisions.py --dsn postgresql://...
    uv run python scripts/audit_label_collisions.py --names-file names.txt

Exit code is 1 when an undeclared collision is found, so it can gate a release.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from relay import u2_executor as _u2_executor  # noqa: E402,F401  (registers the sets)
from relay.fb_labels import MODE_EXACT, MODE_PHRASE, LabelSet, fold  # noqa: E402
from relay.fb_labels import registered_label_sets  # noqa: E402

_DEFAULT_QUERY = """
    SELECT DISTINCT author
    FROM content_items
    WHERE author IS NOT NULL AND author <> ''
    LIMIT %(limit)s
"""


def _load_names(args: argparse.Namespace) -> list[str]:
    if args.names_file:
        text = Path(args.names_file).read_text(encoding="utf-8")
        return [line.strip() for line in text.splitlines() if line.strip()]

    dsn = args.dsn or os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_DSN")
    if not dsn:
        raise SystemExit(
            "no --dsn, --names-file, DATABASE_URL or POSTGRES_DSN. This script "
            "is only useful against real crawled names."
        )
    try:
        import psycopg
    except ImportError:  # pragma: no cover - operator tooling
        raise SystemExit("psycopg is required: uv run --with psycopg <this script>")

    # psycopg3 rejects the SQLAlchemy dialect prefix.
    dsn = re.sub(r"^postgresql\+\w+://", "postgresql://", dsn)
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(_DEFAULT_QUERY, {"limit": args.limit})
            return [row[0] for row in cursor.fetchall() if row[0]]


# `content_items.author` is not a clean list of people. It also holds group
# titles, post metadata and accessibility strings that the crawler could not
# separate — "Công khai · 105k thành viên", "Nút. Nhấn đúp để trả lời bình
# luận.". Auditing against those produces dozens of "collisions" that are the
# tokens doing exactly their job, which is how a report stops being read.
#
# A Vietnamese display name is short, has no digits, no separator glyphs, and
# no URLs. Everything else is chrome.
_NOT_A_PERSON = re.compile(
    r"\d"                 # counts, dates, ids
    r"|[·:/@|]"           # metadata separators and handles
    r"|\.\.\."            # truncated sentences
    r"|\.(com|vn|me|net|org)\b"
)


def _looks_like_a_person(folded: str) -> bool:
    if not folded or _NOT_A_PERSON.search(folded):
        return False
    words = folded.split()
    # Vietnamese names run one to five syllables. Longer is a sentence.
    if not (1 <= len(words) <= 5) or folded.endswith("."):
        return False
    # And then ask the pipeline itself. A row it already rejects as chrome is
    # not a person whose loss we are trying to measure — counting those would
    # report every token as colliding with its own button. Reusing the
    # production predicates also means the audit and the flow cannot disagree
    # about what a candidate is.
    if _u2_executor._fb_has_non_person_marker(folded):
        return False
    return _u2_executor._fb_author_label_allowed(folded)


def _collisions(label_set: LabelSet, folded_names: list[str]) -> dict[str, list[str]]:
    """Which names each token of this set would match, in its declared mode."""
    hits: dict[str, list[str]] = {}
    for token in label_set.tokens:
        if label_set.mode == MODE_EXACT:
            matched = [name for name in folded_names if name == token]
        elif label_set.mode == MODE_PHRASE:
            matched = [name for name in folded_names if token in name]
        else:
            pattern = re.compile(rf"\b{re.escape(token)}\b")
            matched = [name for name in folded_names if pattern.search(name)]
        if matched:
            hits[token] = matched
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", help="Postgres DSN; defaults to $DATABASE_URL")
    parser.add_argument("--names-file", help="one name per line, instead of the DB")
    parser.add_argument("--limit", type=int, default=20000)
    parser.add_argument(
        "--show",
        type=int,
        default=5,
        help="how many colliding names to print per token",
    )
    parser.add_argument(
        "--include-chrome",
        action="store_true",
        help="do not filter out group titles and post metadata (noisy)",
    )
    args = parser.parse_args()

    names = _load_names(args)
    if not names:
        print("no names found — nothing to audit", file=sys.stderr)
        return 0
    folded_all = [f for f in (fold(name) for name in names) if f]
    folded_names = (
        folded_all
        if args.include_chrome
        else [f for f in folded_all if _looks_like_a_person(f)]
    )
    skipped = len(folded_all) - len(folded_names)
    print(
        f"auditing {len(registered_label_sets())} label sets against "
        f"{len(folded_names)} person-shaped names "
        f"({skipped} chrome rows skipped; --include-chrome to keep them)\n"
    )

    undeclared = 0
    syllable_suggestions: Counter[str] = Counter()

    for label_set in registered_label_sets():
        hits = _collisions(label_set, folded_names)
        for token, matched in sorted(hits.items()):
            accepted = token in label_set.collides_with_names
            marker = "accepted" if accepted else "UNDECLARED"
            sample = ", ".join(sorted(set(matched))[: args.show])
            print(
                f"[{marker}] {label_set.name} ({label_set.mode}) "
                f"{token!r} -> {len(matched)} names: {sample}"
            )
            if accepted:
                continue
            undeclared += 1
            # The syllable to add to the committed corpus is the word the token
            # is hiding in — not the person's full name.
            for name in matched:
                for word in name.split():
                    if token in word or word in token:
                        syllable_suggestions[word] += 1

    if not undeclared:
        print("no undeclared collisions")
        return 0

    print(f"\n{undeclared} undeclared collision(s).")
    print("Narrow the mode, or accept it at the declaration with "
          "collides_with_names + collision_reason.")
    print(
        "\nNote: a token that hits exactly one name, and that name is the "
        "token's own button text, is not a name collision — it is a UI string "
        "that leaked into content_items.author. Fix the crawler, not the token."
    )
    if syllable_suggestions:
        print("\nSyllables worth adding to "
              "relay/tests/fixtures/vietnamese_name_syllables.txt so the unit "
              "guard catches this without a database:")
        for syllable, count in syllable_suggestions.most_common(30):
            print(f"  {syllable}   ({count} names)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
