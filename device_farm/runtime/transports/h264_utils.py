"""
h264_utils.py — H.264 bitstream utility functions for the device farm server.

Used to relay H.264 from Android Agent APK → Server → Browser (WebCodecs).
The server does zero decode; it only reformats NAL unit packaging when needed.

Annex B format:   [00 00 00 01] NAL ... [00 00 00 01] NAL ...
AVCC format:      [4-byte BE length] NAL [4-byte BE length] NAL ...
AVCDecoderConfigurationRecord: ISO 14496-15 §5.3.3.1
"""
from __future__ import annotations

import struct


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _split_annexb(data: bytes) -> list[bytes]:
    """
    Split Annex B byte stream into individual raw NAL units (without start codes).
    Handles both 3-byte (00 00 01) and 4-byte (00 00 00 01) start codes.
    Returns a list of NAL unit bytes; empty NALs are discipped.
    """
    nals: list[bytes] = []
    i = 0
    n = len(data)
    start = -1

    while i < n:
        # Look for 00 00 01 (3-byte) or 00 00 00 01 (4-byte)
        if (
            i + 2 < n
            and data[i] == 0x00
            and data[i + 1] == 0x00
            and data[i + 2] == 0x01
        ):
            if start >= 0:
                nal = data[start:i]
                # Strip trailing zero padding added before the start code
                while nal and nal[-1] == 0x00:
                    nal = nal[:-1]
                if nal:
                    nals.append(nal)
            start = i + 3
            i += 3
        elif (
            i + 3 < n
            and data[i] == 0x00
            and data[i + 1] == 0x00
            and data[i + 2] == 0x00
            and data[i + 3] == 0x01
        ):
            if start >= 0:
                nal = data[start:i]
                while nal and nal[-1] == 0x00:
                    nal = nal[:-1]
                if nal:
                    nals.append(nal)
            start = i + 4
            i += 4
        else:
            i += 1

    # Flush the last NAL
    if start >= 0 and start < n:
        nal = data[start:]
        while nal and nal[-1] == 0x00:
            nal = nal[:-1]
        if nal:
            nals.append(nal)

    return nals


def _is_annexb(data: bytes) -> bool:
    """Return True if data starts with a 3-byte or 4-byte Annex B start code."""
    if len(data) >= 4 and data[:4] == b"\x00\x00\x00\x01":
        return True
    if len(data) >= 3 and data[:3] == b"\x00\x00\x01":
        return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def annexb_to_avcc(data: bytes) -> bytes:
    """
    Convert Annex B byte stream to AVCC format (4-byte big-endian length prefix
    before each NAL unit).

    Both 3-byte (00 00 01) and 4-byte (00 00 00 01) start codes are handled.
    If data contains no recognised start codes the input is returned unchanged.
    """
    nals = _split_annexb(data)
    if not nals:
        return data
    parts: list[bytes] = []
    for nal in nals:
        parts.append(struct.pack(">I", len(nal)))
        parts.append(nal)
    return b"".join(parts)


def annexb_to_avcc_maybe(data: bytes) -> bytes:
    """
    Return AVCC-formatted data.
    - If *data* starts with an Annex B start code → convert via annexb_to_avcc().
    - Otherwise assume it is already in AVCC format and return as-is.
    """
    if _is_annexb(data):
        return annexb_to_avcc(data)
    return data


def extract_sps_pps(annexb_config: bytes) -> tuple[bytes, bytes]:
    """
    Extract raw SPS and PPS NAL units from Annex B config data.

    NAL unit type is encoded in the 5 low bits of the first byte:
      type 7 = Sequence Parameter Set (SPS)
      type 8 = Picture Parameter Set (PPS)

    Returns (sps_bytes, pps_bytes) — both WITHOUT start codes.
    Raises ValueError if SPS or PPS cannot be found.
    """
    nals = _split_annexb(annexb_config)
    sps: bytes | None = None
    pps: bytes | None = None
    for nal in nals:
        if not nal:
            continue
        nal_type = nal[0] & 0x1F
        if nal_type == 7 and sps is None:
            sps = nal
        elif nal_type == 8 and pps is None:
            pps = nal
        if sps is not None and pps is not None:
            break
    if sps is None:
        raise ValueError("SPS NAL unit not found in Annex B config data")
    if pps is None:
        raise ValueError("PPS NAL unit not found in Annex B config data")
    return sps, pps


def build_avcc_record(sps: bytes, pps: bytes) -> bytes:
    """
    Build an AVCDecoderConfigurationRecord (ISO 14496-15 §5.3.3.1) from
    raw SPS and PPS bytes (without start codes).

    Layout:
        [0x01]              configurationVersion
        [sps[1]]            AVCProfileIndication
        [sps[2]]            profile_compatibility
        [sps[3]]            AVCLevelIndication
        [0xFF]              lengthSizeMinusOne = 3 → 4-byte length prefix
        [0xE1]              numSequenceParameterSets = 1
        [sps_len : 2B BE]   length of SPS
        [sps]               SPS bytes
        [0x01]              numPictureParameterSets = 1
        [pps_len : 2B BE]   length of PPS
        [pps]               PPS bytes
    """
    if len(sps) < 4:
        raise ValueError(f"SPS too short ({len(sps)} bytes), need at least 4")
    record = (
        bytes([0x01, sps[1], sps[2], sps[3], 0xFF, 0xE1])
        + struct.pack(">H", len(sps))
        + sps
        + bytes([0x01])
        + struct.pack(">H", len(pps))
        + pps
    )
    return record


def annexb_to_avcc_record_maybe(data: bytes) -> bytes:
    """
    Ensure *data* is an AVCDecoderConfigurationRecord.

    - If *data* already looks like an AVCDecoderConfigurationRecord
      (first byte == 0x01 AND does NOT start with an Annex B start code):
      return as-is.
    - If *data* starts with Annex B start codes: extract SPS+PPS and build
      a proper AVCDecoderConfigurationRecord.

    Raises ValueError if Annex B data does not contain both SPS and PPS.
    """
    if _is_annexb(data):
        sps, pps = extract_sps_pps(data)
        return build_avcc_record(sps, pps)
    # Heuristic: first byte 0x01 = configurationVersion → treat as AVCC record
    if data and data[0] == 0x01:
        return data
    # Unknown format — return unchanged and let the browser handle it
    return data
