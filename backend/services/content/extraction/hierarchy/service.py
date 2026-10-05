"""Hierarchy extraction orchestrator (DF-T-06-006)."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from services.content.extraction.capture_service import ExtractionCaptureService
from services.content.extraction.hierarchy.parser import count_nodes, parse_hierarchy_root
from services.content.extraction.hierarchy.registry import get_strategy_registry
from services.content.extraction.hierarchy.strategies.screen_data import screen_data_strategy
from services.content.extraction.models import (
    ExecutionCaptureContext,
    HierarchyResult,
    StrategyMismatchError,
    StrategyNotFoundError,
)

log = logging.getLogger(__name__)

_registry = get_strategy_registry()
if "screen_data" not in _registry.list_names():
    _registry.register_fn("screen_data", screen_data_strategy)


class HierarchyService:
    def __init__(self, capture: ExtractionCaptureService | None = None) -> None:
        self._capture = capture or ExtractionCaptureService()

    async def extract(
        self,
        device: Any,
        strategy_name: str,
        config: dict[str, Any] | None = None,
        *,
        persist: bool = True,
        execution_ctx: ExecutionCaptureContext | None = None,
        db=None,
    ) -> HierarchyResult:
        started = time.perf_counter()
        loop = asyncio.get_running_loop()
        cfg = config or {}

        if execution_ctx is None and persist:
            execution_ctx = ExecutionCaptureContext(
                execution_id="direct",
                step_index=0,
                kind="hierarchy_snapshot",
                retention_class="direct_extract",
            )
            persist = False

        handle = await loop.run_in_executor(
            None,
            lambda: self._capture.capture_hierarchy(
                device,
                persist=persist,
                execution_ctx=execution_ctx,
                db=db,
            ),
        )

        if handle.root is None:
            root = parse_hierarchy_root(handle.xml_bytes.decode("utf-8"))
        else:
            root = handle.root

        node_count = count_nodes(root)
        try:
            strategy = _registry.get(strategy_name)
        except StrategyNotFoundError:
            raise

        data, raw_data = strategy.extract(root, cfg)
        if strategy_name == "screen_data" and isinstance(data, list) and not data:
            raise StrategyMismatchError(
                "no_text_found",
                details={"hierarchy_node_count": node_count},
            )

        elapsed_ms = (time.perf_counter() - started) * 1000
        try:
            from web.metrics import hierarchy_latency_ms, hierarchy_node_count as hierarchy_nodes

            hierarchy_latency_ms.observe(elapsed_ms)
            hierarchy_nodes.observe(node_count)
        except Exception:
            pass

        return HierarchyResult(
            data=data,
            raw_data={
                **raw_data,
                "xml_sha256_prefix": handle.xml_bytes[:16].hex(),
                "artifact_id": handle.artifact_id,
                "object_key": handle.object_key,
            },
            strategy_name=strategy_name,
            latency_ms=elapsed_ms,
            node_count=node_count,
        )

    def extract_from_xml(self, xml_str: str, strategy_name: str, config: dict[str, Any] | None = None) -> HierarchyResult:
        started = time.perf_counter()
        root = parse_hierarchy_root(xml_str)
        node_count = count_nodes(root)
        strategy = _registry.get(strategy_name)
        data, raw_data = strategy.extract(root, config or {})
        if strategy_name == "screen_data" and isinstance(data, list) and not data:
            raise StrategyMismatchError("no_text_found", details={"hierarchy_node_count": node_count})
        elapsed_ms = (time.perf_counter() - started) * 1000
        return HierarchyResult(
            data=data,
            raw_data=raw_data,
            strategy_name=strategy_name,
            latency_ms=elapsed_ms,
            node_count=node_count,
        )
