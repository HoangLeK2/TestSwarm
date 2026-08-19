"""Template matching on the relay — engine and the image_match handler.

OCR moved here because the farm has no video frame of its own since media went
media-adapter -> go2rtc; image matching moves for the same reason, and returns a
coordinate (a few hundred bytes) instead of a ~800 KB screenshot.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
from collections import OrderedDict

import pytest

from relay import image_match
from relay.agent import RelayAgent
from relay.runtime import init_executors, init_semaphores, loads

requires_cv2 = pytest.mark.skipif(
    not image_match.available(), reason="OpenCV not installed"
)


def _screen(w: int = 400, h: int = 600):
    """Noise screen with one distinctive block — noise so it is not ambiguous."""
    import cv2
    import numpy as np

    rng = np.random.default_rng(1234)
    img = (rng.random((h, w, 3)) * 255).astype(np.uint8)
    # A structured patch: gradient + border, so it has real features to match.
    patch = np.zeros((80, 120, 3), np.uint8)
    patch[:, :, 0] = np.linspace(0, 255, 120, dtype=np.uint8)[None, :]
    patch[:, :, 1] = np.linspace(0, 255, 80, dtype=np.uint8)[:, None]
    cv2.rectangle(patch, (0, 0), (119, 79), (255, 255, 255), 3)
    img[200:280, 100:220] = patch
    return img, (100, 200, 120, 80)


def _encode(img, ext: str = ".png") -> bytes:
    import cv2

    ok, buf = cv2.imencode(ext, img)
    assert ok
    return buf.tobytes()


class TestMatchTemplate:
    @requires_cv2
    def test_finds_template_in_original_screen_coordinates(self):
        """Coordinates must be in screen pixels, not the downscaled space.

        The caller taps these numbers, so a value left in the 0.25-scaled frame
        would tap a quarter of the way into the screen.
        """
        img, (x, y, w, h) = _screen()
        hit = image_match.match_template(_encode(img), _encode(img[y:y + h, x:x + w]))
        assert hit is not None
        assert abs(hit["x"] - x) <= 4 and abs(hit["y"] - y) <= 4
        assert abs(hit["w"] - w) <= 4 and abs(hit["h"] - h) <= 4
        assert hit["cx"] == hit["x"] + hit["w"] // 2
        assert hit["conf"] >= 0.9

    @requires_cv2
    def test_default_scale_agrees_with_full_resolution(self):
        """0.25 is the default because it is 20-30x faster at no measured cost.

        If that ever stops holding, this test is where it shows up.
        """
        img, (x, y, w, h) = _screen()
        screen, tpl = _encode(img), _encode(img[y:y + h, x:x + w])
        fast = image_match.match_template(screen, tpl, scale=0.25)
        full = image_match.match_template(screen, tpl, scale=1.0)
        assert fast and full
        assert abs(fast["x"] - full["x"]) <= 4
        assert abs(fast["y"] - full["y"]) <= 4

    @requires_cv2
    def test_absent_template_returns_none(self):
        import numpy as np

        img, _ = _screen()
        rng = np.random.default_rng(999)
        other = (rng.random((40, 60, 3)) * 255).astype(np.uint8)
        assert image_match.match_template(_encode(img), _encode(other)) is None

    @requires_cv2
    def test_template_larger_than_screen_returns_none(self):
        import cv2

        img, _ = _screen()
        bigger = cv2.resize(img, (img.shape[1] * 2, img.shape[0] * 2))
        assert image_match.match_template(_encode(img), _encode(bigger)) is None

    @requires_cv2
    def test_rescales_template_for_a_different_device_resolution(self):
        """A template cut on one phone must still match on a wider screen.

        Uncorrected this scored 0.986 on real screenshots versus 0.998
        corrected — close enough to pass a threshold but drifting.
        """
        import cv2

        img, (x, y, w, h) = _screen()
        tpl = _encode(img[y:y + h, x:x + w])
        wide = cv2.resize(img, (img.shape[1] * 2, img.shape[0] * 2))
        hit = image_match.match_template(
            _encode(wide), tpl, template_screen_w=img.shape[1]
        )
        assert hit is not None
        assert abs(hit["x"] - x * 2) <= 8 and abs(hit["y"] - y * 2) <= 8

    def test_bad_input_returns_none_not_raises(self):
        assert image_match.match_template(b"", b"") is None
        assert image_match.match_template(b"nope", b"nope") is None


class TestAmbiguityCheck:
    """A flat crop scores 1.000 everywhere — no threshold catches that.

    It has to be flagged when the user crops, which is why this is a separate
    entry point rather than something match_template does at run time.
    """

    @requires_cv2
    def test_flat_template_is_flagged(self):
        import numpy as np

        flat = np.full((80, 200, 3), 240, np.uint8)
        ambiguous, reason = image_match.looks_ambiguous(_encode(flat))
        assert ambiguous and reason

    @requires_cv2
    def test_tiny_template_is_flagged(self):
        img, _ = _screen()
        ambiguous, reason = image_match.looks_ambiguous(_encode(img[0:10, 0:10]))
        assert ambiguous and reason

    @requires_cv2
    def test_distinctive_template_is_not_flagged(self):
        img, (x, y, w, h) = _screen()
        ambiguous, reason = image_match.looks_ambiguous(
            _encode(img[y:y + h, x:x + w]), _encode(img)
        )
        assert not ambiguous, reason


class _FakeU2Executor:
    def __init__(self, shot_b64: str | None, *, ok: bool = True) -> None:
        self.shot_b64, self.ok = shot_b64, ok

    async def run_batch(self, *, serial, actions, **kwargs):
        if not self.ok:
            return {"ok": False, "results": [{"ok": False, "error": "device offline"}],
                    "error": "device offline"}
        return {"ok": True, "results": [{"ok": True, "value": self.shot_b64, "error": None}]}


def _agent(u2) -> RelayAgent:
    agent = RelayAgent.__new__(RelayAgent)
    agent._u2_executor = u2
    agent._image_match_tasks = {}
    agent._image_match_cancel_events = {}
    agent._template_cache = OrderedDict()
    return agent


async def _handle(agent, **overrides):
    init_executors()
    init_semaphores()
    queue: asyncio.Queue = asyncio.Queue()
    msg = {"type": "image_match", "id": "req-1", "serial": "dev-1"}
    cancel = overrides.pop("cancel_event", None)
    msg.update(overrides)
    await agent._handle_image_match(msg, queue, cancel)
    return loads(await queue.get())


class TestImageMatchHandler:
    @requires_cv2
    async def test_returns_coordinate_not_screenshot(self):
        img, (x, y, w, h) = _screen()
        shot = base64.b64encode(_encode(img)).decode()
        tpl_bytes = _encode(img[y:y + h, x:x + w])

        reply = await _handle(
            _agent(_FakeU2Executor(shot)),
            template_b64=base64.b64encode(tpl_bytes).decode(),
            template_sha256=hashlib.sha256(tpl_bytes).hexdigest(),
        )
        assert reply["ok"] and reply["found"]
        assert abs(reply["x"] - x) <= 4 and abs(reply["y"] - y) <= 4
        # The point of running here: pixels stay on the host.
        assert "image_b64" not in reply and "screenshot" not in reply

    @requires_cv2
    async def test_template_is_cached_by_hash(self):
        """A scenario looping over one image should ship the bytes once."""
        img, (x, y, w, h) = _screen()
        shot = base64.b64encode(_encode(img)).decode()
        tpl_bytes = _encode(img[y:y + h, x:x + w])
        digest = hashlib.sha256(tpl_bytes).hexdigest()
        agent = _agent(_FakeU2Executor(shot))

        first = await _handle(
            agent, template_b64=base64.b64encode(tpl_bytes).decode(), template_sha256=digest
        )
        assert first["ok"]
        # Second call sends only the hash.
        second = await _handle(agent, template_sha256=digest)
        assert second["ok"] and second["found"]

    async def test_unknown_hash_asks_for_the_bytes(self):
        agent = _agent(_FakeU2Executor("ignored"))
        reply = await _handle(agent, template_sha256="never-seen")
        assert reply["ok"] is False
        assert reply["need_template"] is True

    @requires_cv2
    async def test_no_match_is_not_an_error(self):
        import numpy as np

        img, _ = _screen()
        rng = np.random.default_rng(7)
        other = _encode((rng.random((40, 60, 3)) * 255).astype(np.uint8))
        reply = await _handle(
            _agent(_FakeU2Executor(base64.b64encode(_encode(img)).decode())),
            template_b64=base64.b64encode(other).decode(),
            template_sha256="other",
        )
        assert reply["ok"] is True
        assert reply["found"] is False

    async def test_screenshot_failure_is_reported(self):
        reply = await _handle(
            _agent(_FakeU2Executor(None, ok=False)),
            template_b64=base64.b64encode(b"x").decode(),
            template_sha256="x",
        )
        assert reply["ok"] is False
        assert "device offline" in reply["error"]

    async def test_missing_serial(self):
        reply = await _handle(_agent(_FakeU2Executor("x")), serial="")
        assert reply["ok"] is False
        assert reply["error"] == "serial_required"

    async def test_reports_unavailable_engine_instead_of_hanging(self, monkeypatch):
        monkeypatch.setattr(image_match, "available", lambda: False)
        reply = await _handle(
            _agent(_FakeU2Executor("x")), template_b64="eA==", template_sha256="x"
        )
        assert reply["ok"] is False
        assert reply["error"] == "image_match_unavailable"
