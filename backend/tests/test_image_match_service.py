"""Backend side of tap_image: capability gate, agent errors, ambiguity check."""
from __future__ import annotations

import pytest

from services.content.extraction.image_match_service import (
    ImageMatchError,
    ImageMatchService,
)


class _Device:
    serial = "dev-im"

    def __init__(self, *, supported: bool = True, reply: dict | None = None) -> None:
        self._supported = supported
        self._reply = reply if reply is not None else {"ok": True, "found": False}
        self.calls: list[dict] = []

    def image_match_supported(self) -> bool:
        return self._supported

    def request_image_match(self, **kwargs):
        self.calls.append(kwargs)
        return self._reply


class TestImageMatchService:
    async def test_returns_coordinates_on_hit(self):
        device = _Device(reply={
            "ok": True, "found": True,
            "x": 100, "y": 200, "w": 60, "h": 40, "cx": 130, "cy": 220, "conf": 0.97,
        })
        hit = await ImageMatchService().find(device, b"template-bytes")
        assert hit.found
        assert (hit.x, hit.y, hit.cx, hit.cy) == (100, 200, 130, 220)
        assert hit.confidence == pytest.approx(0.97)

    async def test_no_match_is_a_result_not_an_error(self):
        """A missing element is a normal outcome — the step decides what to do."""
        hit = await ImageMatchService().find(_Device(reply={"ok": True, "found": False}), b"t")
        assert hit.found is False

    async def test_unsupported_agent_fails_fast(self):
        """Must not fall through to a relay timeout on every step.

        The agent-side capability is reported per device in the heartbeat; if it
        never reaches the backend the gate is what turns that into a clear error
        instead of a 20s stall.
        """
        device = _Device(supported=False)
        with pytest.raises(ImageMatchError) as exc:
            await ImageMatchService().find(device, b"t")
        assert exc.value.code == "IMAGE_MATCH_AGENT_UNSUPPORTED"
        assert device.calls == [], "should not reach the relay"

    async def test_agent_error_surfaces(self):
        device = _Device(reply={"ok": False, "error": "screenshot_unavailable"})
        with pytest.raises(ImageMatchError) as exc:
            await ImageMatchService().find(device, b"t")
        assert exc.value.code == "IMAGE_MATCH_AGENT_ERROR"
        assert "screenshot_unavailable" in str(exc.value)

    async def test_empty_template_rejected_before_the_relay(self):
        device = _Device()
        with pytest.raises(ImageMatchError) as exc:
            await ImageMatchService().find(device, b"")
        assert exc.value.code == "IMAGE_TEMPLATE_EMPTY"
        assert device.calls == []

    async def test_defaults_reach_the_agent(self):
        """0.25 scale is the measured 20-30x win; it must not be lost in wiring."""
        device = _Device()
        await ImageMatchService().find(device, b"t", template_screen_w=1260)
        call = device.calls[0]
        assert call["scale"] == 0.25
        assert call["threshold"] == 0.8
        assert call["template_screen_w"] == 1260


cv2 = pytest.importorskip("cv2", reason="OpenCV not installed")


class TestAmbiguityCheck:
    """A flat crop matches everywhere at 1.000, so it is caught at crop time."""

    @staticmethod
    def _png(img) -> bytes:
        ok, buf = cv2.imencode(".png", img)
        assert ok
        return buf.tobytes()

    def test_flat_crop_is_flagged(self):
        import numpy as np

        from runtime.image_quality import looks_ambiguous

        ambiguous, reason = looks_ambiguous(self._png(np.full((80, 200, 3), 240, np.uint8)))
        assert ambiguous and reason

    def test_detailed_crop_is_not_flagged(self):
        import numpy as np

        from runtime.image_quality import looks_ambiguous

        rng = np.random.default_rng(42)
        noise = (rng.random((80, 200, 3)) * 255).astype(np.uint8)
        ambiguous, reason = looks_ambiguous(self._png(noise))
        assert not ambiguous, reason

    def test_undecodable_input_is_not_flagged(self):
        from runtime.image_quality import looks_ambiguous

        # Advisory check only — it must never block an upload on its own error.
        assert looks_ambiguous(b"not-an-image") == (False, "")
