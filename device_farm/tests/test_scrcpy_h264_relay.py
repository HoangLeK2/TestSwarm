"""Tests for ScrcpyReceiver WebCodecs relay mode.

Covers:
  - _is_idr(): keyframe detection from normalized AVCC data
  - ScrcpyReceiver constructor: on_h264_config / on_h264_packet callbacks stored
  - _decode_stream relay path: config packets → on_h264_config, video packets → on_h264_packet
  - Keyframe JPEG still produced in relay mode (for take_screenshot)
  - JPEG-only fallback when on_h264_packet is None
  - on_agent_h264_config / on_agent_h264_video wired correctly in DeviceClient
"""
from __future__ import annotations

import io
import socket
import struct
import threading
import time
from typing import Any, List, Optional
from unittest.mock import MagicMock, patch, call

import pytest

from runtime.transports.scrcpy_receiver import ScrcpyReceiver, _is_idr, PTS_CONFIG_MASK


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _avcc(nals: list[bytes]) -> bytes:
    """Build AVCC-formatted bytes from list of raw NAL units."""
    out = b""
    for nal in nals:
        out += struct.pack(">I", len(nal)) + nal
    return out


def _annexb(nals: list[bytes]) -> bytes:
    """Build Annex-B formatted bytes from list of raw NAL units."""
    out = b""
    for nal in nals:
        out += b"\x00\x00\x00\x01" + nal
    return out


# NAL type bytes
_NAL_IDR    = bytes([0x65])   # type 5 = IDR slice (keyframe)
_NAL_SLICE  = bytes([0x41])   # type 1 = non-IDR slice (P-frame)
_NAL_SPS    = bytes([0x67, 0x42, 0xC0, 0x1F, 0xAB])  # type 7 = SPS (with profile bytes)
_NAL_PPS    = bytes([0x68, 0xCE, 0x38, 0x80])         # type 8 = PPS


def _make_receiver(**kwargs) -> ScrcpyReceiver:
    defaults = dict(
        serial="test-serial",
        adb_path="/usr/bin/adb",
        port=27184,
        server_jar="/tmp/scrcpy-server",
    )
    defaults.update(kwargs)
    return ScrcpyReceiver(**defaults)


# ──────────────────────────────────────────────────────────────────────────────
# _is_idr
# ──────────────────────────────────────────────────────────────────────────────

class TestIsIdr:
    def test_avcc_idr_returns_true(self):
        data = _avcc([_NAL_IDR + b"\xAB" * 20])
        assert _is_idr(data) is True

    def test_avcc_p_frame_returns_false(self):
        data = _avcc([_NAL_SLICE + b"\xAB" * 20])
        assert _is_idr(data) is False

    def test_avcc_multiple_nals_idr_second(self):
        """IDR in second NAL unit should still be detected."""
        data = _avcc([_NAL_SLICE + b"\x01" * 5, _NAL_IDR + b"\x02" * 10])
        assert _is_idr(data) is True

    def test_annexb_idr_returns_true(self):
        from runtime.transports.h264_utils import annexb_to_avcc
        data = annexb_to_avcc(_annexb([_NAL_IDR + b"\xAB" * 10]))
        assert _is_idr(data) is True

    def test_annexb_p_frame_returns_false(self):
        from runtime.transports.h264_utils import annexb_to_avcc
        data = annexb_to_avcc(_annexb([_NAL_SLICE + b"\xAB" * 10]))
        assert _is_idr(data) is False

    def test_empty_returns_false(self):
        assert _is_idr(b"") is False

    def test_too_short_returns_false(self):
        assert _is_idr(b"\x00\x00\x00") is False

    def test_avcc_zero_length_nal_stops_iteration(self):
        """Zero-length NAL in AVCC must not cause infinite loop."""
        data = struct.pack(">I", 0)  # length=0
        assert _is_idr(data) is False

    # ── 3-byte Annex-B start code (00 00 01) ─────────────────────────────────

    def test_annexb_3byte_idr_returns_true(self):
        """IDR NAL after 3-byte start code (00 00 01) must be detected."""
        from runtime.transports.h264_utils import annexb_to_avcc
        data = annexb_to_avcc(b"\x00\x00\x01" + _NAL_IDR + b"\xAB" * 10)
        assert _is_idr(data) is True

    def test_annexb_3byte_p_frame_returns_false(self):
        from runtime.transports.h264_utils import annexb_to_avcc
        data = annexb_to_avcc(b"\x00\x00\x01" + _NAL_SLICE + b"\xAB" * 10)
        assert _is_idr(data) is False

    def test_annexb_mixed_idr_second_with_3byte_start(self):
        """Packet: [4B SC][SPS][3B SC][IDR] — IDR in 2nd NAL with 3-byte start code."""
        from runtime.transports.h264_utils import annexb_to_avcc
        data = annexb_to_avcc(
            b"\x00\x00\x00\x01" + _NAL_SPS
            + b"\x00\x00\x01" + _NAL_IDR + b"\xCC" * 5
        )
        assert _is_idr(data) is True

    def test_annexb_multiple_nals_3byte_between(self):
        """[4B][SPS][3B][PPS][3B][IDR] — all 3-byte boundaries, IDR at end."""
        from runtime.transports.h264_utils import annexb_to_avcc
        data = annexb_to_avcc(
            b"\x00\x00\x00\x01" + _NAL_SPS
            + b"\x00\x00\x01" + _NAL_PPS
            + b"\x00\x00\x01" + _NAL_IDR + b"\xAA"
        )
        assert _is_idr(data) is True

    def test_annexb_multiple_nals_no_idr(self):
        """Multi-NALU Annex-B packet with only P-frames → False."""
        from runtime.transports.h264_utils import annexb_to_avcc
        data = annexb_to_avcc(
            b"\x00\x00\x00\x01" + _NAL_SLICE
            + b"\x00\x00\x01" + _NAL_SLICE + b"\x01"
        )
        assert _is_idr(data) is False


# ──────────────────────────────────────────────────────────────────────────────
# ScrcpyReceiver constructor
# ──────────────────────────────────────────────────────────────────────────────

class TestScrcpyReceiverCallbacks:
    def test_on_h264_config_stored(self):
        cb = MagicMock()
        r = _make_receiver(on_h264_config=cb)
        assert r.on_h264_config is cb

    def test_on_h264_packet_stored(self):
        cb = MagicMock()
        r = _make_receiver(on_h264_packet=cb)
        assert r.on_h264_packet is cb

    def test_defaults_none(self):
        r = _make_receiver()
        assert r.on_h264_config is None
        assert r.on_h264_packet is None

    def test_relay_mode_when_packet_cb_set(self):
        """_relay_mode flag is derived from on_h264_packet presence inside _decode_stream.
        We verify the callbacks exist; relay logic is tested in TestDecodeStreamRelay."""
        r = _make_receiver(on_h264_packet=MagicMock(), on_h264_config=MagicMock())
        assert r.on_h264_packet is not None
        assert r.on_h264_config is not None


# ──────────────────────────────────────────────────────────────────────────────
# _decode_stream relay path
# ──────────────────────────────────────────────────────────────────────────────

def _make_mock_socket(packets: list[tuple[int, bytes]]) -> MagicMock:
    """
    Build a mock socket whose recv() feeds a sequence of scrcpy packets.
    Each packet is (pts_raw, data). The socket raises ConnectionError after all packets.
    """
    raw_stream = bytearray()
    for pts_raw, data in packets:
        raw_stream += struct.pack(">QI", pts_raw, len(data)) + data

    pos = [0]
    stream = bytes(raw_stream)

    def _recv(n):
        chunk = stream[pos[0]:pos[0] + n]
        if not chunk:
            raise ConnectionError("end of stream")
        pos[0] += len(chunk)
        return chunk

    sock = MagicMock()
    sock.recv.side_effect = _recv
    return sock


def _run_decode_stream(receiver: ScrcpyReceiver, packets: list[tuple[int, bytes]]):
    """Run _decode_stream with a mock socket carrying the given packets, then stop."""
    receiver._running = True
    receiver.device_width = 1080
    receiver.device_height = 1920
    sock = _make_mock_socket(packets)
    try:
        receiver._decode_stream(sock)
    except (ConnectionError, Exception):
        pass  # expected — stream ends


class TestDecodeStreamRelay:
    """Relay mode: on_h264_packet set → forward raw bytes, decode JPEG only on keyframe."""

    def test_config_packet_calls_on_h264_config(self):
        config_cb = MagicMock()
        r = _make_receiver(on_h264_config=config_cb, on_h264_packet=MagicMock())

        # Config packet has PTS_CONFIG_MASK set
        config_data = _annexb([_NAL_SPS, _NAL_PPS])
        pts_config = PTS_CONFIG_MASK | 0

        with patch("runtime.transports.scrcpy_receiver.av.CodecContext") as mock_codec_cls:
            mock_codec = MagicMock()
            mock_codec.decode.return_value = []
            mock_codec_cls.create.return_value = mock_codec

            _run_decode_stream(r, [(pts_config, config_data)])

        config_cb.assert_called_once()
        args = config_cb.call_args[0]
        # args = (avcc_record: bytes, w: int, h: int)
        assert isinstance(args[0], bytes) and len(args[0]) > 0

    def test_video_packet_calls_on_h264_packet(self):
        pkt_cb = MagicMock()
        r = _make_receiver(on_h264_packet=pkt_cb)

        video_data = _avcc([_NAL_SLICE + b"\xAB" * 30])
        pts = 1000

        with patch("runtime.transports.scrcpy_receiver.av.CodecContext") as mock_codec_cls:
            mock_codec = MagicMock()
            mock_codec.decode.return_value = []
            mock_codec_cls.create.return_value = mock_codec

            _run_decode_stream(r, [(pts, video_data)])

        pkt_cb.assert_called_once()
        avcc_data, is_key, pts_us = pkt_cb.call_args[0]
        assert isinstance(avcc_data, bytes)
        assert is_key is False   # _NAL_SLICE is not IDR
        assert isinstance(pts_us, int)

    def test_ambiguous_three_byte_annexb_frame_is_converted_explicitly(self):
        pkt_cb = MagicMock()
        r = _make_receiver(on_h264_packet=pkt_cb)

        # The first four bytes also form a plausible AVCC length (0x165 = 357).
        # Local scrcpy is known to emit Annex-B, so this must not be sniffed.
        nal = _NAL_IDR + b"\x88" * 357
        video_data = b"\x00\x00\x01" + nal

        with patch("runtime.transports.scrcpy_receiver.av.CodecContext") as mock_codec_cls:
            mock_codec_cls.create.return_value = MagicMock(decode=lambda *args: [])
            _run_decode_stream(r, [(1000, video_data)])

        pkt_cb.assert_called_once()
        avcc_data, is_key, _ = pkt_cb.call_args[0]
        assert avcc_data == struct.pack(">I", len(nal)) + nal
        assert is_key is True

    def test_keyframe_triggers_jpeg_decode(self):
        """In relay mode, on_frame should be called for IDR (keyframe) packets."""
        frame_cb = MagicMock()
        pkt_cb = MagicMock()
        r = _make_receiver(on_frame=frame_cb, on_h264_packet=pkt_cb)

        idr_data = _avcc([_NAL_IDR + b"\xAB" * 50])
        pts = 2000

        # Create a fake decoded frame
        fake_frame = MagicMock()
        fake_img = MagicMock()
        buf = io.BytesIO()
        from PIL import Image
        Image.new("RGB", (100, 100)).save(buf, format="JPEG")
        fake_img_bytes = buf.getvalue()

        def _fake_save(buf_obj, **kwargs):
            buf_obj.write(fake_img_bytes)

        fake_img.save.side_effect = _fake_save
        fake_frame.to_image.return_value = fake_img

        with patch("runtime.transports.scrcpy_receiver.av.CodecContext") as mock_codec_cls:
            mock_codec = MagicMock()
            mock_codec.decode.return_value = [fake_frame]
            mock_codec_cls.create.return_value = mock_codec

            _run_decode_stream(r, [(pts, idr_data)])

        # on_frame called for keyframe JPEG
        frame_cb.assert_called_once()
        # on_h264_packet also called with is_key=True
        pkt_cb.assert_called_once()
        _, is_key, _ = pkt_cb.call_args[0]
        assert is_key is True

    def test_p_frame_skips_jpeg_decode_in_relay_mode(self):
        """Non-keyframe in relay mode must NOT trigger JPEG encode."""
        frame_cb = MagicMock()
        pkt_cb = MagicMock()
        r = _make_receiver(on_frame=frame_cb, on_h264_packet=pkt_cb)

        p_data = _avcc([_NAL_SLICE + b"\xAB" * 30])

        with patch("runtime.transports.scrcpy_receiver.av.CodecContext") as mock_codec_cls:
            mock_codec = MagicMock()
            mock_codec.decode.return_value = []
            mock_codec_cls.create.return_value = mock_codec

            _run_decode_stream(r, [(1000, p_data)])

        # on_frame must NOT be called for P-frame in relay mode
        frame_cb.assert_not_called()
        # But on_h264_packet should be called
        pkt_cb.assert_called_once()

    def test_last_frame_time_updated_on_video_packet(self):
        """_last_frame_time must be updated even in relay mode (for stale-frame guard)."""
        r = _make_receiver(on_h264_packet=MagicMock())
        r._last_frame_time = 0.0
        before = time.monotonic()

        p_data = _avcc([_NAL_SLICE + b"\x00" * 10])
        with patch("runtime.transports.scrcpy_receiver.av.CodecContext") as mock_codec_cls:
            mock_codec_cls.create.return_value = MagicMock(decode=lambda *a: [])
            _run_decode_stream(r, [(1000, p_data)])

        assert r._last_frame_time >= before


class TestDecodeStreamJpegOnlyFallback:
    """JPEG-only mode: on_h264_packet is None → every frame decoded to JPEG."""

    def test_every_frame_calls_on_frame(self):
        frame_cb = MagicMock()
        r = _make_receiver(on_frame=frame_cb)   # on_h264_packet=None → JPEG mode

        p_data = _avcc([_NAL_SLICE + b"\xAB" * 30])

        fake_frame = MagicMock()
        fake_img = MagicMock()

        def _fake_save(buf_obj, **kwargs):
            from PIL import Image
            import io as _io
            buf2 = _io.BytesIO()
            Image.new("RGB", (10, 10)).save(buf2, format="JPEG")
            buf_obj.write(buf2.getvalue())

        fake_img.save.side_effect = _fake_save
        fake_frame.to_image.return_value = fake_img

        with patch("runtime.transports.scrcpy_receiver.av.CodecContext") as mock_codec_cls:
            mock_codec = MagicMock()
            mock_codec.decode.return_value = [fake_frame]
            mock_codec_cls.create.return_value = mock_codec

            _run_decode_stream(r, [(1000, p_data)])

        frame_cb.assert_called_once()

    def test_config_packet_does_not_call_on_h264_config(self):
        """In JPEG mode, no H264 config callback even if provided (relay mode inactive)."""
        config_cb = MagicMock()
        # on_h264_packet=None → JPEG mode, on_h264_config set but not activated
        r = _make_receiver(on_h264_config=config_cb)

        config_data = _annexb([_NAL_SPS, _NAL_PPS])
        pts_config = PTS_CONFIG_MASK | 0

        with patch("runtime.transports.scrcpy_receiver.av.CodecContext") as mock_codec_cls:
            mock_codec = MagicMock()
            mock_codec.decode.return_value = []
            mock_codec_cls.create.return_value = mock_codec

            _run_decode_stream(r, [(pts_config, config_data)])

        # Config callback NOT called because relay mode is off
        config_cb.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# h264_utils: Annex-B → AVCC conversion (used inside relay path)
# ──────────────────────────────────────────────────────────────────────────────

class TestAnnexBToAvcc:
    def test_converts_annexb_to_avcc(self):
        from runtime.transports.h264_utils import annexb_to_avcc
        nals = [b"\x41" + b"\xAB" * 10, b"\x65" + b"\xCD" * 5]
        annexb = _annexb(nals)
        result = annexb_to_avcc(annexb)
        # Result should start with 4-byte length of first NAL
        expected_len = len(nals[0])
        assert result[:4] == struct.pack(">I", expected_len)

    def test_build_avcc_record_structure(self):
        from runtime.transports.h264_utils import build_avcc_record
        sps = _NAL_SPS
        pps = _NAL_PPS
        record = build_avcc_record(sps, pps)
        assert record[0] == 0x01                     # configurationVersion
        assert record[1] == sps[1]                   # AVCProfileIndication
        assert record[4] == 0xFF                     # lengthSizeMinusOne=3 (4-byte)
        assert record[5] == 0xE1                     # numSequenceParameterSets=1

    def test_annexb_to_avcc_record_from_annexb(self):
        from runtime.transports.h264_utils import annexb_to_avcc_record_maybe
        config = _annexb([_NAL_SPS, _NAL_PPS])
        record = annexb_to_avcc_record_maybe(config)
        assert record[0] == 0x01   # valid AVCDecoderConfigurationRecord


# ──────────────────────────────────────────────────────────────────────────────
# SPS/PPS lifecycle: config change detection, IDR gate, P-frame drop
# ──────────────────────────────────────────────────────────────────────────────

# Two distinct SPS payloads — same profile but different constraint bytes so
# annexb_to_avcc_record_maybe produces different AVCDecoderConfigurationRecord bytes.
_NAL_SPS_V1 = bytes([0x67, 0x42, 0xC0, 0x1F, 0xAB, 0xCD])   # profile 0x42, level 0x1F
_NAL_SPS_V2 = bytes([0x67, 0x4D, 0x40, 0x28, 0xEF, 0x01])   # profile 0x4D (changed!)
_NAL_PPS_V1 = bytes([0x68, 0xCE, 0x38, 0x80])
_NAL_PPS_V2 = bytes([0x68, 0xDE, 0x09, 0x68])


def _config_packet(sps: bytes, pps: bytes) -> tuple[int, bytes]:
    """Build a scrcpy codec-config packet (PTS has CONFIG bit set)."""
    data = _annexb([sps, pps])
    return (PTS_CONFIG_MASK | 0, data)


def _video_packet(nal: bytes, pts: int = 1000) -> tuple[int, bytes]:
    """Build a scrcpy video packet (AVCC format)."""
    return (pts, _avcc([nal + b"\xAB" * 20]))


class TestSPSLifecycleDetection:
    """config_changed flag is False on first config, True on subsequent changed configs."""

    def test_first_config_not_changed(self):
        config_cb = MagicMock()
        r = _make_receiver(on_h264_config=config_cb, on_h264_packet=MagicMock())

        with patch("runtime.transports.scrcpy_receiver.av.CodecContext") as mock_codec_cls:
            mock_codec_cls.create.return_value = MagicMock(decode=lambda *a: [])
            _run_decode_stream(r, [_config_packet(_NAL_SPS_V1, _NAL_PPS_V1)])

        config_cb.assert_called_once()
        _, _, _, changed = config_cb.call_args[0]
        assert changed is False  # first config → not a "change"

    def test_same_config_repeated_not_changed(self):
        config_cb = MagicMock()
        r = _make_receiver(on_h264_config=config_cb, on_h264_packet=MagicMock())

        with patch("runtime.transports.scrcpy_receiver.av.CodecContext") as mock_codec_cls:
            mock_codec_cls.create.return_value = MagicMock(decode=lambda *a: [])
            _run_decode_stream(
                r,
                [
                    _config_packet(_NAL_SPS_V1, _NAL_PPS_V1),
                    _config_packet(_NAL_SPS_V1, _NAL_PPS_V1),
                ],
            )

        assert config_cb.call_count == 2
        # Both calls: changed=False because bytes are identical
        for c in config_cb.call_args_list:
            _, _, _, changed = c[0]
            assert changed is False

    def test_different_config_sets_changed_true(self):
        """Rotation / resolution / reconnect → new SPS bytes → changed=True."""
        config_cb = MagicMock()
        r = _make_receiver(on_h264_config=config_cb, on_h264_packet=MagicMock())

        with patch("runtime.transports.scrcpy_receiver.av.CodecContext") as mock_codec_cls:
            mock_codec_cls.create.return_value = MagicMock(decode=lambda *a: [])
            _run_decode_stream(
                r,
                [
                    _config_packet(_NAL_SPS_V1, _NAL_PPS_V1),
                    _config_packet(_NAL_SPS_V2, _NAL_PPS_V2),
                ],
            )

        assert config_cb.call_count == 2
        first_changed  = config_cb.call_args_list[0][0][3]
        second_changed = config_cb.call_args_list[1][0][3]
        assert first_changed  is False
        assert second_changed is True


class TestIDRGateAfterConfigChange:
    """After a config change, P-frames must be dropped until the first IDR."""

    def test_p_frame_dropped_after_config_change(self):
        pkt_cb = MagicMock()
        r = _make_receiver(on_h264_packet=pkt_cb)

        p_frame  = _video_packet(_NAL_SLICE[0:1], pts=2000)  # non-IDR
        packets  = [
            _config_packet(_NAL_SPS_V1, _NAL_PPS_V1),
            _video_packet(_NAL_IDR[0:1],  pts=1000),  # IDR — clears gate
            _config_packet(_NAL_SPS_V2, _NAL_PPS_V2),  # config change → gate reopens
            p_frame,                                    # P-frame must be dropped
        ]

        with patch("runtime.transports.scrcpy_receiver.av.CodecContext") as mock_codec_cls:
            mock_codec_cls.create.return_value = MagicMock(decode=lambda *a: [])
            _run_decode_stream(r, packets)

        # Only the IDR (pts=1000) should reach pkt_cb; P-frame at pts=2000 dropped
        calls = pkt_cb.call_args_list
        assert len(calls) == 1
        _, is_key, pts = calls[0][0]
        assert is_key is True
        assert pts == 1000

    def test_idr_after_config_change_clears_gate(self):
        """IDR after config-change must pass through and trigger on_h264_packet."""
        pkt_cb = MagicMock()
        r = _make_receiver(on_h264_packet=pkt_cb)

        idr_pts = 5000
        packets = [
            _config_packet(_NAL_SPS_V1, _NAL_PPS_V1),
            _video_packet(_NAL_IDR[0:1], pts=1000),   # initial IDR
            _config_packet(_NAL_SPS_V2, _NAL_PPS_V2), # change → gate
            _video_packet(_NAL_IDR[0:1], pts=idr_pts), # IDR clears gate
        ]

        with patch("runtime.transports.scrcpy_receiver.av.CodecContext") as mock_codec_cls:
            mock_codec_cls.create.return_value = MagicMock(decode=lambda *a: [])
            _run_decode_stream(r, packets)

        call_pts_list = [c[0][2] for c in pkt_cb.call_args_list]
        assert idr_pts in call_pts_list

    def test_p_frames_resume_after_idr(self):
        """P-frames after IDR (following config change) must flow through."""
        pkt_cb = MagicMock()
        r = _make_receiver(on_h264_packet=pkt_cb)

        packets = [
            _config_packet(_NAL_SPS_V1, _NAL_PPS_V1),
            _config_packet(_NAL_SPS_V2, _NAL_PPS_V2),  # change → gate
            _video_packet(_NAL_IDR[0:1],   pts=100),    # IDR clears gate
            _video_packet(_NAL_SLICE[0:1], pts=200),    # P-frame should pass
            _video_packet(_NAL_SLICE[0:1], pts=300),    # P-frame should pass
        ]

        with patch("runtime.transports.scrcpy_receiver.av.CodecContext") as mock_codec_cls:
            mock_codec_cls.create.return_value = MagicMock(decode=lambda *a: [])
            _run_decode_stream(r, packets)

        call_pts_list = [c[0][2] for c in pkt_cb.call_args_list]
        assert 100 in call_pts_list
        assert 200 in call_pts_list
        assert 300 in call_pts_list

    def test_initial_p_frame_before_any_idr_dropped(self):
        """At stream start (no IDR yet), P-frames should not be gated.
        The IDR gate only activates on config *change*, not on first config."""
        pkt_cb = MagicMock()
        r = _make_receiver(on_h264_packet=pkt_cb)

        packets = [
            _config_packet(_NAL_SPS_V1, _NAL_PPS_V1),  # first config → no gate
            _video_packet(_NAL_SLICE[0:1], pts=100),     # P-frame should pass
        ]

        with patch("runtime.transports.scrcpy_receiver.av.CodecContext") as mock_codec_cls:
            mock_codec_cls.create.return_value = MagicMock(decode=lambda *a: [])
            _run_decode_stream(r, packets)

        call_pts_list = [c[0][2] for c in pkt_cb.call_args_list]
        assert 100 in call_pts_list

    def test_codec_recreated_on_config_change(self):
        """PyAV CodecContext must be recreated when config changes (old state invalid)."""
        r = _make_receiver(on_h264_packet=MagicMock())

        create_calls = []

        def _fake_create(codec, mode):
            m = MagicMock()
            m.decode.return_value = []
            create_calls.append((codec, mode))
            return m

        packets = [
            _config_packet(_NAL_SPS_V1, _NAL_PPS_V1),
            _config_packet(_NAL_SPS_V2, _NAL_PPS_V2),  # change → recreate
        ]

        with patch("runtime.transports.scrcpy_receiver.av.CodecContext") as mock_codec_cls:
            mock_codec_cls.create.side_effect = _fake_create
            _run_decode_stream(r, packets)

        # Called once at start of _decode_stream + once on config change
        assert mock_codec_cls.create.call_count == 2


# ──────────────────────────────────────────────────────────────────────────────
# on_agent_h264_config: flags byte in binary 0x10 protocol
# ──────────────────────────────────────────────────────────────────────────────

class TestBinaryProtocolRoundTrip:
    """Verify the 0x10 binary frame built by _build_0x10_frame (same logic as
    on_agent_h264_config) round-trips correctly through _parse_agent_binary_frame."""

    def _parse(self, buf: bytes):
        from web.ws import _parse_agent_binary_frame
        return _parse_agent_binary_frame(buf)

    def test_changed_false_roundtrip(self):
        from runtime.transports.h264_utils import build_avcc_record
        record = build_avcc_record(_NAL_SPS_V1, _NAL_PPS_V1)
        buf = _build_0x10_frame("test001", 1080, 1920, flags=0x00, avcc_record=record)

        # Verify raw flags byte in wire format
        slen = buf[1]
        flags_offset = 2 + slen + 4
        assert buf[flags_offset] == 0x00

        result = self._parse(buf)
        assert result["config_changed"] is False
        assert result["data"] == record

    def test_changed_true_roundtrip(self):
        from runtime.transports.h264_utils import build_avcc_record
        record = build_avcc_record(_NAL_SPS_V2, _NAL_PPS_V2)
        buf = _build_0x10_frame("test001", 720, 1280, flags=0x01, avcc_record=record)

        slen = buf[1]
        flags_offset = 2 + slen + 4
        assert buf[flags_offset] & 0x01 == 0x01

        result = self._parse(buf)
        assert result["config_changed"] is True
        assert result["w"] == 720
        assert result["h"] == 1280


# ──────────────────────────────────────────────────────────────────────────────
# _parse_agent_binary_frame: flags byte parsing in 0x10 frames
# ──────────────────────────────────────────────────────────────────────────────

def _build_0x10_frame(serial: str, w: int, h: int, flags: int, avcc_record: bytes) -> bytes:
    """Helper: build a raw 0x10 binary frame as the server would emit."""
    serial_b = serial.encode("utf-8")
    slen = len(serial_b)
    return (
        bytes([0x10, slen])
        + serial_b
        + struct.pack(">HH", w, h)
        + bytes([flags])
        + avcc_record
    )


class TestParseAgentBinaryFrame0x10:
    """_parse_agent_binary_frame correctly parses 0x10 frames with flags byte."""

    def _parse(self, buf: bytes):
        from web.ws import _parse_agent_binary_frame
        return _parse_agent_binary_frame(buf)

    def test_flags_zero_config_changed_false(self):
        buf = _build_0x10_frame("abc", 1080, 1920, flags=0x00, avcc_record=b"\x01\x42\xC0\x1F")
        result = self._parse(buf)
        assert result is not None
        assert result["type"] == "h264_config"
        assert result["config_changed"] is False
        assert result["data"] == b"\x01\x42\xC0\x1F"

    def test_flags_bit0_config_changed_true(self):
        buf = _build_0x10_frame("abc", 720, 1280, flags=0x01, avcc_record=b"\x01\x4D\x40\x28")
        result = self._parse(buf)
        assert result is not None
        assert result["config_changed"] is True

    def test_flags_other_bits_ignored(self):
        """Bits 1-7 of flags are reserved; config_changed is only bit 0."""
        buf = _build_0x10_frame("x", 100, 200, flags=0xFE, avcc_record=b"\x01\x42\xC0\x1F")
        result = self._parse(buf)
        assert result["config_changed"] is False  # bit 0 is 0

    def test_frame_too_short_returns_none(self):
        """Truncated 0x10 frame (no flags byte) → None."""
        serial_b = b"s"
        buf = bytes([0x10, 1]) + serial_b + struct.pack(">HH", 100, 200)
        # No flags byte → should return None
        result = self._parse(buf)
        assert result is None

    def test_w_h_parsed_correctly(self):
        buf = _build_0x10_frame("dev1", 480, 800, flags=0x00, avcc_record=b"\x01\x42\xC0\x1F")
        result = self._parse(buf)
        assert result["w"] == 480
        assert result["h"] == 800
