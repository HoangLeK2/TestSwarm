"""Guard: scenario templates may not ship keywords that discard real people.

The seeded templates carry keyword lists that reach the device as plain tokens
and get matched as substrings against a folded suggestion row. A template is
therefore just as capable of the Vietnamese folding bug as the executor is —
and it happened here first.

``PROFILE_FORBIDDEN_KEYWORDS`` used to contain ``trang``, ``page``, ``nhóm``
and ``group``. Folded and matched as substrings, ``trang`` discarded 23 of
2,563 real crawled names — every Trang, one of the most common Vietnamese given
names — and ``nhóm`` discarded the shared-group signal, which for an account
with no friends is the *only* common context it can build. The flow reported
"no candidates" and looked healthy.

The corpus lives with the executor guard (agent-boot). One corpus, two callers:
a template keyword and an executor token fail in exactly the same way, so
splitting the evidence would mean fixing this twice.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pytest

from db.seeds.scenario_templates import BUILTIN_TEMPLATES

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AGENT_BOOT = _REPO_ROOT / "agent-boot"
_CORPUS = _AGENT_BOOT / "relay" / "tests" / "fixtures" / "vietnamese_name_syllables.txt"

# Keyword variables whose values are matched against a person's row. Lists that
# select posts or pages are matched against content, where a name collision
# costs nothing.
#
# Gates decide admit or reject outright, so they are checked against everything
# a display name can look like, including two adjacent syllables.
_GATE_KEYWORD_SUFFIXES = (
    "FORBIDDEN_KEYWORDS",
    "REQUIRED_KEYWORDS",
    "COMMON_KEYWORDS",
)

# Weights only add score. A collision there inflates a number rather than
# dropping a person, so they are held to the cheaper bar: they may not hide
# inside a single syllable or a standalone name. "AI" inside "Mai" fails that —
# it scores nearly every Vietnamese person for free. "tuyển dụng" landing on
# somebody named Tuyến Dung does not: it needs two specific syllables adjacent,
# and costs 20 points on one row.
_WEIGHT_KEYWORD_SUFFIXES = ("OPTIONAL_KEYWORDS",)

_PERSON_KEYWORD_SUFFIXES = _GATE_KEYWORD_SUFFIXES + _WEIGHT_KEYWORD_SUFFIXES


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text.casefold().replace("đ", "d")).strip()


def _load_corpus() -> tuple[tuple[str, ...], tuple[str, ...]]:
    section = ""
    buckets: dict[str, list[str]] = {"syllables": [], "standalone": []}
    for line in _CORPUS.read_text(encoding="utf-8").splitlines():
        clean = line.split("#", 1)[0].strip()
        if not clean:
            continue
        if clean.startswith("[") and clean.endswith("]"):
            section = clean[1:-1]
            continue
        if section in buckets:
            buckets[section].append(clean)
    return tuple(buckets["syllables"]), tuple(buckets["standalone"])


@pytest.fixture(scope="module")
def name_haystacks() -> dict[str, tuple[str, ...]]:
    if not _AGENT_BOOT.is_dir():
        pytest.skip("agent-boot tree not present; corpus lives with the executor guard")
    assert _CORPUS.is_file(), (
        f"the Vietnamese name corpus is missing at {_CORPUS}. It is the whole "
        f"basis of this guard — restore it rather than deleting the test."
    )
    syllables, standalone = _load_corpus()
    parts = syllables + standalone
    pairs = tuple(f"{a} {b}" for a in syllables for b in syllables)
    return {"weight": parts, "gate": parts + pairs}


def _person_keyword_lists() -> list[tuple[str, str, list[str]]]:
    """(template name, variable name, values) for every person-facing list."""
    out: list[tuple[str, str, list[str]]] = []
    for template in BUILTIN_TEMPLATES:
        variables = template.get("variables") or {}
        for key, value in variables.items():
            if not key.endswith(_PERSON_KEYWORD_SUFFIXES):
                continue
            if not isinstance(value, list):
                continue
            out.append((str(template.get("name") or "?"), key, [str(v) for v in value]))
    return out


def test_person_keyword_lists_exist() -> None:
    """Without this the guard could pass by finding nothing to check."""
    assert _person_keyword_lists(), (
        "no person-facing keyword lists found in BUILTIN_TEMPLATES — has the "
        "variable naming changed? Update _PERSON_KEYWORD_SUFFIXES."
    )


def test_template_keywords_do_not_swallow_vietnamese_names(
    name_haystacks: dict[str, tuple[str, ...]],
) -> None:
    failures: list[str] = []
    for template_name, variable, values in _person_keyword_lists():
        kind = "gate" if variable.endswith(_GATE_KEYWORD_SUFFIXES) else "weight"
        for raw in values:
            token = _fold(raw)
            if not token:
                continue
            hit = next((n for n in name_haystacks[kind] if token in n), "")
            if hit:
                failures.append(
                    f"{template_name} / {variable}: {raw!r} folds to {token!r} "
                    f"and swallows the Vietnamese name {hit!r}"
                )
    assert not failures, (
        "These template keywords are matched as substrings against a folded "
        "suggestion row, so they discard real people and the flow just reports "
        "'no candidates'. Use wording a name cannot contain — 'được tài trợ' "
        "rather than 'trang', 'thích trang' rather than 'page':\n  "
        + "\n  ".join(failures)
    )


def test_the_guard_itself_catches_the_original_bug(
    name_haystacks: dict[str, tuple[str, ...]],
) -> None:
    """The keywords that actually shipped in a seeded template.

    ``trang`` emptied the pipeline by discarding every person named Trang;
    ``ai`` filled it by qualifying every Mai, Hải and Thái on their name alone.
    Opposite symptoms, one cause.
    """
    for shipped in ("trang", "ai"):
        assert any(shipped in name for name in name_haystacks["weight"]), (
            f"the corpus no longer catches {shipped!r}, which is one of the "
            f"keywords that silently broke the candidate pipeline"
        )
    # And the wording that replaced them stays clean, even against the stricter
    # gate haystack.
    for safe in ("duoc tai tro", "thich trang", "cong nghe"):
        assert not any(safe in name for name in name_haystacks["gate"])
