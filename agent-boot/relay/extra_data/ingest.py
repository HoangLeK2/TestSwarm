"""HTTP XML ingest for phone/APK extra-data snapshots."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
import time
from typing import Any

from relay.extra_data.writer import ContentItemWriter, build_content_item_row
from relay.extra_data.writer import compute_content_hash, scope_content_hash

logger = logging.getLogger("relay.extra_data")

_MULTI_PLATFORM_POST_STRATEGIES = {"ig_posts", "tiktok_posts", "linkedin_posts", "auto_posts"}
_MULTI_PLATFORM_COMMENT_STRATEGIES = {"ig_comments", "tiktok_comments", "linkedin_comments", "auto_comments"}
_SUPPORTED_CONTENT_STRATEGIES = (
    {"fb_posts", "fb_comments", "text_nodes"}
    | _MULTI_PLATFORM_POST_STRATEGIES
    | _MULTI_PLATFORM_COMMENT_STRATEGIES
)


def _text_node_items(xml: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml)
    items = [
        {"text": text, "body": text, "content_type": "text"}
        for node in root.iter()
        if (text := (node.get("text") or "").strip())
    ]
    return items, {"reason_code": "ok", "texts_returned": len(items)}


def _multi_platform_items(
    strategy: str,
    xml: str,
    context: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from lxml import etree

    from relay.extra_data.parsers.platform_detector import detect_from_hierarchy, detect_parser

    root = etree.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    is_comments = strategy in _MULTI_PLATFORM_COMMENT_STRATEGIES
    parser = None
    package_name = str(context.get("package_name") or context.get("current_package") or "").strip()
    if strategy.startswith("auto_"):
        parser = detect_parser(package_name) if package_name else None
        if parser is None:
            parser = detect_from_hierarchy(root)
    else:
        platform_code = strategy.split("_", 1)[0]
        pkg_map = {
            "ig": "com.instagram.android",
            "tiktok": "com.zhiliaoapp.musically",
            "linkedin": "com.linkedin.android",
        }
        parser = detect_parser(pkg_map.get(platform_code, ""))

    if parser is None:
        return [], {
            "reason_code": "platform_parser_not_found",
            "strategy": strategy,
            "package_name": package_name,
        }

    if is_comments:
        post_key = str(context.get("post_key") or context.get("parent_id") or context.get("parent_post_id") or "")
        parsed = parser.parse_comments(root, post_key)
    else:
        parsed = parser.parse_posts(root)
    items = [item.to_dict() for item in parsed]
    return items, {
        "reason_code": "ok",
        "platform": parser.platform,
        "items_returned": len(items),
    }


def _parse_items(strategy: str, xml: str, context: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if strategy == "fb_comment_filter_next":
        from relay.extra_data.parsers.facebook.comment_filter import resolve_comment_filter_next_tap

        return [], resolve_comment_filter_next_tap(xml, context)
    if strategy in {"fb_comment_target", "fb_comment_target_tap"}:
        from relay.extra_data.parsers.facebook import resolve_topmost_comment_target_from_xml

        post, bounds = resolve_topmost_comment_target_from_xml(xml)
        if not post or not bounds:
            return [], {"reason_code": "comment_button_not_found", "target": None}
        dedupe_field = str(context.get("dedupe_field") or "post_key")
        base_hash = compute_content_hash(post, dedupe_field=dedupe_field)
        scope = context.get("hash_scope") or context.get("execution_id")
        target = {
            "bounds": list(bounds),
            "pid": post.get("_pid"),
            "parent_base_hash": base_hash,
            "parent_id": scope_content_hash(base_hash, scope),
            "post_key": post.get("post_key"),
            "stable_post_id": post.get("stable_post_id"),
            "fb_post_id": post.get("fb_post_id"),
            "author": post.get("author"),
            "timestamp": post.get("timestamp"),
            "text_prefix": str(post.get("text") or "")[:220],
        }
        return [], {"reason_code": "ok", "target": target}
    if strategy == "fb_posts":
        from relay.extra_data.parsers.facebook import parse_fb_posts_from_xml_with_diagnostic

        return parse_fb_posts_from_xml_with_diagnostic(
            xml,
            source_index=int(context.get("source_index") or 0),
        )
    if strategy == "fb_comments":
        from relay.extra_data.parsers.facebook import parse_fb_comments_from_xml_with_diagnostic

        return parse_fb_comments_from_xml_with_diagnostic(
            xml,
            parent_post_id=context.get("parent_post_id") or context.get("parent_id"),
            max_items=int(context.get("max_items") or 50),
        )
    if strategy == "text_nodes":
        return _text_node_items(xml)
    if strategy in _MULTI_PLATFORM_POST_STRATEGIES or strategy in _MULTI_PLATFORM_COMMENT_STRATEGIES:
        return _multi_platform_items(strategy, xml, context)
    return [], {"reason_code": "unsupported_strategy", "strategy": strategy}


def _xml_snapshots_from_payload(payload: dict[str, Any], primary_xml: str) -> list[str]:
    snapshots: list[str] = []
    seen: set[str] = set()

    def add_snapshot(value: Any) -> None:
        if not isinstance(value, str) or "<hierarchy" not in value:
            return
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        if digest in seen:
            return
        seen.add(digest)
        snapshots.append(value)

    add_snapshot(primary_xml)
    raw_snapshots = payload.get("xml_snapshots")
    if isinstance(raw_snapshots, list):
        for snapshot in raw_snapshots:
            add_snapshot(snapshot)
    return snapshots


def _comment_dedupe_key(item: dict[str, Any]) -> str:
    explicit = str(item.get("comment_key") or item.get("id") or item.get("content_hash") or "").strip()
    if explicit:
        return explicit
    return "|".join(
        str(item.get(k) or "").strip().lower()
        for k in ("author", "text", "body", "timestamp")
    )


def _parse_fb_comment_snapshots(
    snapshots: list[str],
    context: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    max_items = int(context.get("max_items") or 50)
    merged_comments: list[dict[str, Any]] = []
    seen: set[str] = set()
    latest_stats: dict[str, Any] | None = None
    frame_codes: list[str] = []
    last_diagnostic: dict[str, Any] = {"reason_code": "no_snapshots"}

    for idx, snapshot in enumerate(snapshots):
        frame_context = {**context, "source_index": idx}
        items, diagnostic = _parse_items("fb_comments", snapshot, frame_context)
        last_diagnostic = diagnostic
        frame_codes.append(str(diagnostic.get("reason_code") or "unknown"))
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("_type") == "post_stats":
                latest_stats = item
                continue
            key = _comment_dedupe_key(item)
            if not key or key in seen:
                continue
            seen.add(key)
            merged_comments.append(item)
            if len(merged_comments) >= max_items:
                break
        if len(merged_comments) >= max_items:
            break

    merged: list[dict[str, Any]] = []
    if latest_stats is not None:
        merged.append(latest_stats)
    merged.extend(merged_comments[:max_items])
    diagnostic = {
        **last_diagnostic,
        "reason_code": "ok" if merged_comments or latest_stats else last_diagnostic.get("reason_code", "no_comments"),
        "snapshot_count": len(snapshots),
        "frame_reason_codes": frame_codes,
        "comments_returned": len(merged_comments[:max_items]),
        "has_header_stats": latest_stats is not None,
    }
    return merged, diagnostic


def _parse_payload_items(
    strategy: str,
    xml: str,
    context: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    snapshots = _xml_snapshots_from_payload(payload, xml)
    if strategy == "fb_comments" and len(snapshots) > 1:
        items, diagnostic = _parse_fb_comment_snapshots(snapshots, context)
        return items, diagnostic, snapshots
    items, diagnostic = _parse_items(strategy, xml, context)
    return items, diagnostic, snapshots


class ExtraDataIngestServer:
    def __init__(self) -> None:
        self._host = os.getenv("AGENT_BOOT_EXTRA_HOST", "0.0.0.0")
        self._port = int(os.getenv("AGENT_BOOT_EXTRA_PORT", "8765"))
        self._max_bytes = max(1024, int(os.getenv("AGENT_BOOT_XML_MAX_BYTES", str(8 * 1024 * 1024))))
        self._token = os.getenv("AGENT_BOOT_EXTRA_TOKEN", "").strip()
        self._allow_unauth = os.getenv("AGENT_BOOT_EXTRA_ALLOW_UNAUTH", "").strip().lower() in {"1", "true", "yes", "on"}
        self._writer = ContentItemWriter()
        default_workers = max(2, min(4, os.cpu_count() or 2))
        workers = max(1, int(os.getenv("AGENT_BOOT_XML_PARSE_WORKERS", str(default_workers))))
        self._parse_sem = asyncio.Semaphore(workers)
        self._serial_locks: dict[str, asyncio.Lock] = {}
        self._server: asyncio.AbstractServer | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle_client, self._host, self._port)
        logger.info("extra-data ingest listening on %s", self.base_url)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        await self._writer.close()

    def _lock_for_serial(self, serial: str) -> asyncio.Lock:
        lock = self._serial_locks.get(serial)
        if lock is None:
            lock = asyncio.Lock()
            self._serial_locks[serial] = lock
        return lock

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
            if len(header) > 64 * 1024:
                await self._send_response(writer, 431, {"ok": False, "error": "headers_too_large"})
                return
            header_text = header.decode("iso-8859-1", errors="replace")
            first = header_text.splitlines()[0] if header_text.splitlines() else ""
            parts = first.split()
            method, path = (parts[0], parts[1]) if len(parts) >= 2 else ("", "")
            headers: dict[str, str] = {}
            for line in header_text.splitlines()[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            length = int(headers.get("content-length") or "0")
            if method != "POST" or path != "/extra-data/xml":
                await self._send_response(writer, 404, {"ok": False, "error": "not_found"})
                return
            if length <= 0 or length > self._max_bytes:
                await self._send_response(writer, 413, {"ok": False, "error": "payload_too_large"})
                return
            body = await asyncio.wait_for(reader.readexactly(length), timeout=15)
            payload = json.loads(body.decode("utf-8"))
            auth = self._authorize(headers, payload)
            if auth is not None:
                await self._send_response(writer, auth[0], {"ok": False, "error": auth[1]})
                return
            result = await self.process_payload(payload)
            await self._send_response(writer, 200 if result.get("ok") else 500, result)
        except asyncio.TimeoutError:
            logger.warning("extra-data ingest request timed out while reading")
            try:
                await self._send_response(writer, 408, {"ok": False, "error": "request_timeout"})
            except Exception:
                pass
        except asyncio.LimitOverrunError:
            logger.warning("extra-data ingest request headers too large")
            try:
                await self._send_response(writer, 431, {"ok": False, "error": "headers_too_large"})
            except Exception:
                pass
        except asyncio.IncompleteReadError:
            logger.warning("extra-data ingest request ended before declared content-length")
            try:
                await self._send_response(writer, 400, {"ok": False, "error": "incomplete_request"})
            except Exception:
                pass
        except Exception as exc:
            logger.warning("extra-data ingest request failed: %s", exc)
            try:
                await self._send_response(writer, 500, {"ok": False, "error": str(exc)})
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _send_response(self, writer: asyncio.StreamWriter, status: int, data: dict[str, Any]) -> None:
        reason = "OK" if status < 400 else "ERROR"
        raw = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        writer.write(
            f"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\nConnection: close\r\n\r\n".encode("ascii")
            + raw
        )
        await writer.drain()

    def _authorize(self, headers: dict[str, str], payload: dict[str, Any]) -> tuple[int, str] | None:
        if not self._token:
            if self._allow_unauth:
                return None
            return 503, "extra_token_not_configured"
        provided = (
            headers.get("x-agent-boot-extra-token")
            or str(payload.get("extra_data_token") or "")
        ).strip()
        if provided != self._token:
            return 401, "unauthorized"
        return None

    async def process_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        serial = str(payload.get("serial") or context.get("device_serial") or "")
        strategy = str(payload.get("strategy") or context.get("strategy") or "fb_posts")
        xml = str(payload.get("xml") or "")
        if not serial:
            return {"ok": False, "error": "serial_required"}
        if not xml or "<hierarchy" not in xml:
            return {"ok": False, "error": "invalid_xml"}
        expected_sha = str(payload.get("xml_sha256") or "")
        actual_sha = hashlib.sha256(xml.encode("utf-8")).hexdigest()
        if expected_sha and expected_sha != actual_sha:
            return {"ok": False, "error": "xml_sha256_mismatch"}

        async with self._lock_for_serial(serial):
            async with self._parse_sem:
                loop = asyncio.get_running_loop()
                parse_started = time.perf_counter()
                # Route XML parsing to the dedicated CPU pool when available.
                # Falls back to the default pool when the relay runtime is
                # not initialised (tests / standalone use).
                try:
                    from relay.runtime import cpu_executor as _cpu_exec
                    _parse_ex = _cpu_exec()
                except Exception:
                    _parse_ex = None
                items, diagnostic, snapshots = await loop.run_in_executor(
                    _parse_ex,
                    _parse_payload_items,
                    strategy,
                    xml,
                    context,
                    payload,
                )
                parse_ms = int((time.perf_counter() - parse_started) * 1000)

            if strategy not in _SUPPORTED_CONTENT_STRATEGIES and strategy not in {
                "fb_comment_target",
                "fb_comment_target_tap",
                "fb_comment_filter_next",
            }:
                return {"ok": False, "error": "unsupported_strategy", "strategy": strategy}

            content_type = str(context.get("content_type") or ("comment" if strategy.endswith("_comments") or strategy == "fb_comments" else "post"))
            item_level = int(context.get("item_level") if context.get("item_level") is not None else (1 if strategy.endswith("_comments") or strategy == "fb_comments" else 0))
            parent_id = context.get("parent_id") if strategy.endswith("_comments") or strategy == "fb_comments" else None
            rows = [
                build_content_item_row(
                    item,
                    {**context, "device_serial": context.get("device_serial") or serial, "content_type": content_type},
                    parent_id=parent_id,
                    item_level=item_level,
                    captured_at=payload.get("captured_at") or payload.get("captured_at_ms"),
                )
                for item in items
                if isinstance(item, dict) and item.get("_type") != "post_stats"
            ]
            db_started = time.perf_counter()
            should_persist = bool(context.get("persist", True)) and bool(context.get("collection"))
            write = await self._insert_rows_with_retry(rows) if should_persist else {
                "attempted": 0,
                "inserted": 0,
                "duplicates": 0,
            }
            db_ms = int((time.perf_counter() - db_started) * 1000)

        result = {
            "ok": True,
            "serial": serial,
            "strategy": strategy,
            "parsed_count": len(items),
            "inserted_attempted": write.get("attempted", 0),
            "inserted_count": write.get("inserted", 0),
            "duplicate_count": write.get("duplicates", 0),
            "diagnostic": diagnostic,
            "xml_bytes": sum(len(snapshot.encode("utf-8")) for snapshot in snapshots),
            "snapshot_count": len(snapshots),
            "xml_sha256": actual_sha,
            "parse_ms": parse_ms,
            "db_ms": db_ms,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
        if bool(context.get("return_items", False)):
            result["items"] = [
                item
                for item in items
                if isinstance(item, dict) and item.get("_type") != "post_stats"
            ]
        return result

    async def _insert_rows_with_retry(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        attempts = max(1, int(os.getenv("AGENT_BOOT_CONTENT_DB_RETRIES", "3")))
        base_delay = max(0.01, float(os.getenv("AGENT_BOOT_CONTENT_DB_RETRY_BASE_DELAY", "0.2")))
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                return await self._writer.insert_rows(rows)
            except Exception as exc:
                last_exc = exc
                if attempt >= attempts - 1:
                    break
                delay = base_delay * (2 ** attempt) + random.uniform(0, base_delay)
                logger.warning("content_items insert failed, retrying in %.2fs: %s", delay, exc)
                await asyncio.sleep(delay)
        assert last_exc is not None
        raise last_exc
