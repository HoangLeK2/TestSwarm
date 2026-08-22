# ADR: Reasoning about the Facebook UI

## Status

Accepted. Enforced by three build-failing guards, listed under *Enforcement*.

## Context

One session on a real device produced seven serious defects while all 951 unit
tests were green. The defects were not independent. They fall into two classes,
each of which recurred in several unrelated places, and each of which fails in
the dangerous direction: the flow reports success, or acts on the wrong person,
rather than raising an error.

The tests were green because both classes are invisible to a test that supplies
its own fixture. A hierarchy fixture written by the same person who wrote the
matcher agrees with the matcher by construction.

### Class 1 — reasoning about position on a UI that moves

| Site | What it did |
|---|---|
| `_fb_visible_person_row_labels` | grouped labels within a 200px band, welding two people into `'Anh Bui Nguyễn Hoài Sơn'` |
| `_fb_pending_request_near` | verified around the tap point, so a request that really was sent reported as a failure |
| tap in `_flow_fb_connect_visible_people` | reused coordinates from an earlier dump; a banner shifted the page underneath |
| `_fb_nearby_labels(y_padding=760)` | pulled the next post's text into this post's context |
| `len(action_buttons) == 1` | counted buttons on screen — a profile page always carries more than one |
| "take the topmost Add Friend" (considered) | stops being the owner's the moment the page is scrolled: friends a stranger |

The screen is not stable between the dump and the tap. Facebook inserts
banners, loads images, and expands cards asynchronously. Any answer computed
from a position is only true for the frame it was computed from.

### Class 2 — substring matching on folded Vietnamese

Every label comparison folds first: NFKD, strip combining marks, `đ` → `d`,
casefold. Folding is necessary — Facebook's Vietnamese is inconsistently
accented — and it is also what makes substring matching catastrophic, because
after folding a button word and a name syllable are the same characters.

Measured against 2,563 real author names collected by this system:

| Token | Folds to | Real people it discarded |
|---|---|---|
| `gỡ` | `go` | **107** — Võ Ngọc Trầm, Sài Gòn, Nguyễn Văn Giới |
| `tham gia` | `tham gia` | 31 |
| `trang` | `trang` | **23** — Minh Trang Đoàn, Trang Anh, Cá Trắng |
| `chặn` | `chan` | 7 — Huy Chan, Trần Hữu Chánh |
| `nhóm` | `nhom` | 6 — and it killed the shared-group signal a cold account depends on |
| `xóa` | `xoa` | 3 — Xoan, Xoàii Lùn's |

The same rule cuts the other way. `AI`, in a template's
`PROFILE_REQUIRED_KEYWORDS`, folds to `ai` and matches Mai, Hải and Thái —
qualifying nearly every candidate on their name alone.

The structural cause is that the matching mode lived at the **call site**, in
`any(token in folded for token in TOKENS)`, while the tokens lived somewhere
else. Whoever adds a token to the list cannot see how it will be matched. That
is precisely how `trang` ended up in a substring list.

## Decision

**1. Verify by identity, not by position.**
Ask "what state is this specific person in", not "what is near where I
tapped". `_fb_profile_owner_connection` anchors to the owner's name;
`_fb_still_offering_add_friend` re-reads the target by name after the tap;
`_fb_person_row_scope` reads a row from the card's subtree instead of a pixel
band.

Position may **order** candidates that identity has already selected — nearest
control below the owner's name is fine. Position may not **select** them.

**2. Label tokens declare their own matching mode.**
`relay/fb_labels.py` defines `LabelSet(name, tokens, mode, why)` with
`mode ∈ {phrase, word, exact}`. There is no way to construct one without
choosing. Short syllables that are also names take `exact`; a button's label is
the whole label, a person's row never is.

A token that genuinely must collide with a name is declared with
`collides_with_names` plus a `collision_reason` — accepted in writing at the
declaration, with the trade stated. Two exist today: `bao cao` (refusing to tap
a person named Bảo Cao is cheaper than reporting a stranger's post) and
`tham gia` (a group's Join button entering the person pipeline means
friend-requesting a group).

**3. When the screen is ambiguous, refuse the action.**
A skipped candidate costs one friend request. A wrong tap can unfollow, report,
unfriend, or permanently remove the account's suggestion source —
`_fb_guarded_click` exists because a screenshot from a real run showed
"Ẩn những người bạn có thể biết" one tap away from Add Friend.

## Enforcement

These are not review conventions. Each is a test that fails the build.

| Guard | Rule |
|---|---|
| `agent-boot/relay/tests/test_fb_label_guard.py` | Every `LabelSet` token, matched in its declared mode, matches zero names in the corpus — or is an accepted collision with a reason. Also forbids ad-hoc substring matching with string literals in `u2_executor.py`. |
| `agent-boot/relay/tests/test_fb_geometry_guard.py` | AST scan for pixel arithmetic. Any function doing it must be in `_GEOMETRY_APPROVED` with a stated reason. Pixels are not banned — undeclared pixels are. |
| `device_farm/tests/test_template_label_guard.py` | Seeded template keyword lists are held to the same standard. This is where `trang` and `AI` actually shipped. |

The corpus is
`agent-boot/relay/tests/fixtures/vietnamese_name_syllables.txt`: Vietnamese
name syllables, not the 2,563 real names, which belong to living people. It
splits *syllables* (what a substring can hide inside) from *standalone names*
(what an exact match can equal), because the three modes fail differently.

Each guard carries a `test_the_guard_itself_catches_the_original_bug` case that
reproduces the shipped defect against the guard's own machinery. A guard that
cannot fail proves nothing, and these will keep passing long after everyone has
forgotten why they exist.

`agent-boot/scripts/audit_label_collisions.py` re-checks every declared
`LabelSet` against the live `content_items.author` column, which is how new
syllables reach the corpus.

## Consequences

`_GEOMETRY_APPROVED` currently lists eleven functions as `DEBT:` — the
band-based readers the six failures came from. They are tolerated, not
endorsed, and the list is the migration backlog. A guard test asserts the two
worst still carry the `DEBT:` prefix, so a rewrite has to remove the entry
rather than quietly relabel it.

The label guard depends on variable naming: it identifies folded UI text by
identifiers containing `label`, `folded`, `row_text`, `context`, `title` or
`caption`. Renaming one of those to something vague turns the guard off for
that line. This is stated in the test.

`device_farm/tests/test_template_label_guard.py` reads a fixture from
`agent-boot/`. One corpus, two callers: a template keyword and an executor
token fail identically, and splitting the evidence would mean fixing this
twice. It skips when the `agent-boot/` tree is absent and fails loudly when the
tree is present but the corpus is not.
