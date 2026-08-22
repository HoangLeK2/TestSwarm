"""Guard: no label token may silently discard a Vietnamese person.

Two rules, both mechanical, both failing the build:

1. Every token in every :class:`LabelSet`, matched the way that set declares,
   must match zero names built from ``fixtures/vietnamese_name_syllables.txt``.
   A collision is either fixed by narrowing the mode, or accepted in writing via
   ``collides_with_names`` + ``collision_reason``.

2. ``u2_executor.py`` may not do ad-hoc substring matching on folded text with
   string literals. That construct is where every instance of this bug started,
   because it puts the matching mode at the call site where nobody adding a
   token can see it.

Why this is a test and not a review checklist: the failure mode is silent. A
token that eats every person named Trang produces a flow that reports "no
candidates" and looks like Facebook simply had nothing to show.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

# Importing the executor is what registers every LabelSet — see
# LabelSet.__post_init__. Without this import the guard would pass vacuously.
from relay import u2_executor as _u2_executor  # noqa: F401
from relay.fb_labels import MODE_EXACT, MODE_PHRASE, MODE_WORD, registered_label_sets

_FIXTURE = Path(__file__).parent / "fixtures" / "vietnamese_name_syllables.txt"
_EXECUTOR_SOURCE = Path(_u2_executor.__file__)


class Corpus:
    """The name vocabulary, split the way the three matching modes need it.

    ``syllables``
        building blocks. A substring token that fits inside one of these is
        unsafe — that is the whole class of bug.
    ``standalone``
        syllables that are also complete display names. Only these can be equal
        to an ``exact`` token.
    ``full_names``
        standalone names plus every adjacent pair of syllables, i.e. what a
        display name actually looks like. Used for ``word`` and ``exact``.
    """

    def __init__(self, syllables: tuple[str, ...], standalone: tuple[str, ...]):
        self.syllables = syllables
        self.standalone = standalone
        self.full_names = standalone + tuple(
            f"{a} {b}" for a in syllables for b in syllables
        )

    def collision(self, token: str, mode: str) -> str:
        """The first name this token would swallow, or ``""``."""
        if mode == MODE_EXACT:
            # Only a whole label can equal the token, so only real display
            # names count — a bare syllable is not a name by itself.
            return next((n for n in self.full_names if n == token), "")
        if mode == MODE_WORD:
            pattern = re.compile(rf"\b{re.escape(token)}\b")
            return next((n for n in self.full_names if pattern.search(n)), "")
        # phrase: a substring can hide inside a single syllable, which is
        # exactly how "go" got inside "ngoc". A token containing a space can
        # only span two syllables, never hide inside one.
        haystacks = self.full_names if " " in token else self.syllables
        return next((n for n in haystacks if token in n), "")


def _load_corpus() -> Corpus:
    section = ""
    buckets: dict[str, list[str]] = {"syllables": [], "standalone": []}
    for line in _FIXTURE.read_text(encoding="utf-8").splitlines():
        clean = line.split("#", 1)[0].strip()
        if not clean:
            continue
        if clean.startswith("[") and clean.endswith("]"):
            section = clean[1:-1]
            continue
        if section in buckets:
            buckets[section].append(clean)
    return Corpus(
        tuple(dict.fromkeys(buckets["syllables"])),
        tuple(dict.fromkeys(buckets["standalone"])),
    )


@pytest.fixture(scope="module")
def corpus() -> Corpus:
    return _load_corpus()


def test_corpus_is_folded_and_non_trivial(corpus: Corpus) -> None:
    from relay.fb_labels import fold

    assert len(corpus.syllables) >= 100, "the corpus is the whole basis of this guard"
    assert corpus.standalone, "exact-mode tokens have nothing to be checked against"
    unfolded = [
        entry
        for entry in corpus.syllables + corpus.standalone
        if entry != fold(entry)
    ]
    assert not unfolded, f"corpus entries must already be folded: {unfolded[:5]}"


def test_corpus_still_contains_the_syllables_that_cost_us_candidates(
    corpus: Corpus,
) -> None:
    """Regression on the corpus itself.

    If somebody trims this file, the guard keeps passing while protecting
    nothing. These four syllables are the ones measured against 2,563 real
    author names, so they are not allowed to quietly disappear.
    """
    for syllable in ("ngoc", "trang", "chanh", "xoan"):
        assert syllable in corpus.syllables, (
            f"{syllable!r} was removed from the name corpus — it is one of the "
            f"syllables that real Facebook accounts actually collide with"
        )


def test_every_label_set_token_is_safe_against_vietnamese_names(
    corpus: Corpus,
) -> None:
    label_sets = registered_label_sets()
    assert label_sets, "no LabelSet registered — is relay.u2_executor imported?"

    failures: list[str] = []
    for label_set in label_sets:
        for token in label_set.tokens:
            hit = corpus.collision(token, label_set.mode)
            if not hit:
                continue
            if token in label_set.collides_with_names:
                continue  # accepted, with a reason, at the declaration
            failures.append(
                f"{label_set.name}: token {token!r} (mode={label_set.mode}) "
                f"matches the Vietnamese name {hit!r}"
            )
    assert not failures, (
        "These tokens would silently discard real people. Narrow the mode "
        "(phrase -> word -> exact), or accept the collision at the declaration "
        "with collides_with_names + collision_reason:\n  "
        + "\n  ".join(failures)
    )


def test_accepted_collisions_are_real(corpus: Corpus) -> None:
    """An acceptance that no longer collides is stale documentation.

    Left alone it teaches the next reader that a safe token is dangerous, which
    is how a list of exceptions turns into noise nobody reads.
    """
    stale: list[str] = []
    for label_set in registered_label_sets():
        for token in label_set.collides_with_names:
            if not corpus.collision(token, label_set.mode):
                stale.append(f"{label_set.name}: {token!r} no longer collides")
    assert not stale, "remove these from collides_with_names:\n  " + "\n  ".join(stale)


def test_every_label_set_explains_its_mode() -> None:
    missing = [
        label_set.name
        for label_set in registered_label_sets()
        if not label_set.why.strip()
    ]
    assert not missing, (
        "a LabelSet without `why` is a tuple with extra steps; say what makes "
        f"this mode the right one for: {missing}"
    )


# ── rule 2: no ad-hoc substring matching in the executor ────────────────────

# Sites where a literal substring test is the right call, each with the reason
# it is safe. Keyed by the enclosing function name.
_SUBSTRING_APPROVED: dict[str, str] = {}


def _looks_like_ui_token(value: object) -> bool:
    """A folded UI label: lowercase letters and spaces, two chars or more.

    Deliberately narrow. It should not fire on resource ids, class names, XML
    attributes or format strings — only on the kind of literal that belongs in
    a LabelSet.
    """
    return (
        isinstance(value, str)
        and len(value) >= 2
        and bool(re.fullmatch(r"[a-z]+(?: [a-z]+)*", value))
    )


# `"spec" in selector` is a dict lookup, not a label match, and the AST cannot
# tell them apart. What it can tell is what the haystack is called: folded UI
# text is held in variables named after labels and rows, never `selector` or
# `kwargs`. Naming is load-bearing here, which is worth knowing before renaming
# one of these variables to something vague.
_FOLDED_TEXT_HINTS = ("label", "folded", "row_text", "context", "title", "caption")


def _is_folded_text(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        identifier = node.id
    elif isinstance(node, ast.Attribute):
        identifier = node.attr
    elif isinstance(node, ast.Call):
        # `"x" in _fb_fold(label)`
        function = node.func
        identifier = getattr(function, "id", "") or getattr(function, "attr", "")
    else:
        return False
    identifier = identifier.casefold()
    return any(hint in identifier for hint in _FOLDED_TEXT_HINTS)


def _enclosing_functions(tree: ast.AST) -> dict[int, str]:
    """Map every line in the module to the function that owns it."""
    owner: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                owner[line] = node.name
    return owner


def _substring_violations(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        # `"xem them" in folded`
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            if isinstance(node.ops[0], (ast.In, ast.NotIn)) and isinstance(
                node.left, ast.Constant
            ):
                if _looks_like_ui_token(node.left.value) and _is_folded_text(
                    node.comparators[0]
                ):
                    found.append((node.lineno, f'"{node.left.value}" in <text>'))

        # `any(token in folded for token in ("a", "b"))`
        if isinstance(node, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
            for generator in node.generators:
                iterable = generator.iter
                if not isinstance(iterable, (ast.Tuple, ast.List)):
                    continue
                literals = [
                    element.value
                    for element in iterable.elts
                    if isinstance(element, ast.Constant)
                ]
                if len(literals) != len(iterable.elts) or len(literals) < 2:
                    continue
                if not any(_looks_like_ui_token(value) for value in literals):
                    continue
                uses_in = any(
                    isinstance(inner, ast.Compare)
                    and any(isinstance(op, (ast.In, ast.NotIn)) for op in inner.ops)
                    for inner in ast.walk(node.elt)
                )
                if uses_in:
                    found.append(
                        (node.lineno, f"inline token tuple {tuple(literals)!r}")
                    )
    return found


def test_executor_declares_label_tokens_instead_of_matching_them_inline() -> None:
    tree = ast.parse(_EXECUTOR_SOURCE.read_text(encoding="utf-8"))
    owners = _enclosing_functions(tree)

    violations = [
        f"{_EXECUTOR_SOURCE.name}:{line} in {owners.get(line, '<module>')}: {what}"
        for line, what in _substring_violations(tree)
        if owners.get(line, "<module>") not in _SUBSTRING_APPROVED
    ]
    assert not violations, (
        "Substring matching on folded text with inline literals is how "
        '"Gỡ" discarded 107 real people. Declare a LabelSet in '
        "relay/fb_labels.py with an explicit mode instead:\n  "
        + "\n  ".join(sorted(violations))
    )


def test_the_guard_itself_catches_the_original_bug(corpus: Corpus) -> None:
    """A guard that cannot fail proves nothing.

    Reproduces both defects against the guard's own machinery: the tokens that
    actually shipped, and the construct that carried them.
    """
    assert corpus.collision("trang", MODE_PHRASE), (
        "the corpus no longer catches the token that discarded 23 real people"
    )
    assert corpus.collision("go", MODE_PHRASE)
    assert corpus.collision("chan", MODE_PHRASE)
    assert corpus.collision("xoa", MODE_PHRASE)
    # Narrowing the mode is what makes them safe again — this is the fix the
    # failure message tells the next person to apply.
    assert not corpus.collision("go", MODE_EXACT)
    assert not corpus.collision("xoa", MODE_EXACT)
    assert not corpus.collision("gio", MODE_WORD)

    offending = ast.parse(
        'def f(folded):\n'
        '    return any(token in folded for token in ("trang", "nhom"))\n'
    )
    assert _substring_violations(offending), (
        "the AST rule no longer recognises the inline-token-tuple construct"
    )
    assert _substring_violations(ast.parse('x = "xem them" in folded\n'))
    # And it stays quiet on the safe shapes.
    assert not _substring_violations(ast.parse('x = folded in {"dang", "post"}\n'))
    assert not _substring_violations(ast.parse('x = "spec" in selector\n'))
    assert not _substring_violations(
        ast.parse("x = any(t in folded for t in forbidden_tokens)\n")
    )
