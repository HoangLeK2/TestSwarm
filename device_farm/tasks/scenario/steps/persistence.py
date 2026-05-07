"""Step handler: save_extraction."""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Any, Dict

from tasks.scenario.steps import register_step
from tasks.scenario.context import ScenarioContext

log = logging.getLogger(__name__)


@register_step("save_extraction")
def handle_save_extraction(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    data_var = step.get("data_var", "")
    if not data_var:
        result["ok"] = False
        result["message"] = "save_extraction: missing data_var"
        return

    try:
        from services.content_store import save_content_item

        data = sc.var_ctx._runtime_vars.get(data_var)
        if data is None:
            data = sc.ctx.get(data_var)
        if data is None:
            result["ok"] = False
            result["message"] = f"save_extraction: variable '{data_var}' not found"
            return

        items: list = []
        if isinstance(data, str):
            items = [{"text": data}]
        elif isinstance(data, dict):
            items = [data]
        elif isinstance(data, list):
            if not data:
                items = []
            else:
                items = [item for item in data if isinstance(item, dict)]
                if not items:
                    result["ok"] = False
                    result["message"] = f"save_extraction: variable '{data_var}' is a list but has no object items"
        else:
            result["ok"] = False
            result["message"] = f"save_extraction: unsupported type for '{data_var}': {type(data).__name__}"
            items = []

        if not items:
            result["saved_count"] = 0
            result["duplicate_count"] = 0
            result["error_count"] = 0
            if result.get("ok", True):
                result["message"] = "save_extraction: no items to save"
            return

        start_idx = 0
        if isinstance(data, list):
            offsets = sc.ctx.setdefault("__save_extraction_offsets__", {})
            start_idx = int(offsets.get(data_var, 0) or 0)
            if start_idx > 0:
                items = items[start_idx:]

        if not items:
            result["saved_count"] = 0
            result["duplicate_count"] = 0
            result["error_count"] = 0
            result["message"] = "save_extraction: no new items to save"
            return

        coll = step.get("collection", "default")
        plat = step.get("platform")
        ctype = step.get("content_type", "post")
        dedup_f = step.get("dedupe_field")
        tags = step.get("tags", "")
        dserial = sc.device.serial
        items_snap = list(items)
        parent_id_var = step.get("parent_id_var")
        parent_id = sc.ctx.get(parent_id_var) if parent_id_var else None
        item_level = int(step.get("item_level") or 0)
        user_id = (sc.scenario.get("_campaign_vars") or {}).get("__USER_ID__")
        execution_id = sc.scenario.get("_execution_id")   # real DB FK — set by Temporal
        run_hash_scope = sc.scenario.get("_run_hash_scope") or execution_id
        campaign_id = sc.scenario.get("_campaign_id")

        async def _resolve_user_id() -> str | None:
            """Fallback to device owner when caller context is absent."""
            if user_id:
                return user_id
            # Allow direct scenario payload overrides for non-campaign callers.
            direct_uid = sc.scenario.get("user_id") or sc.scenario.get("__USER_ID__")
            if direct_uid:
                s = str(direct_uid).strip()
                if s:
                    return s
            try:
                from db.database import activity_session
                from db.crud.device import get_device_by_serial
                async with activity_session() as db:
                    dev = await get_device_by_serial(db, dserial)
                    return dev.user_id if dev else None
            except Exception:
                return None

        async def _save_all_items():
            resolved_uid = await _resolve_user_id()
            sv = dp = er = pc = 0
            last: dict = {}
            for it in items_snap:
                try:
                    r = await save_content_item(
                        data=it, collection=coll, platform=plat, content_type=ctype,
                        dedupe_field=dedup_f, tags=tags, device_serial=dserial,
                        parent_id=parent_id, item_level=item_level, user_id=resolved_uid,
                        campaign_id=campaign_id, execution_id=execution_id,
                        hash_scope=run_hash_scope,
                    )
                    last = r
                    if r.get("saved"):
                        sv += 1
                    else:
                        dp += 1
                    pc += 1
                except Exception as exc:
                    er += 1
                    log.warning("[%s] save_extraction item failed (%s): %s", dserial, data_var, exc)
                    break
            return sv, dp, er, pc, last

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(asyncio.run, _save_all_items())
            saved_count, duplicate_count, error_count, processed_count, last_result = fut.result(timeout=120)

        if isinstance(data, list):
            offsets = sc.ctx.setdefault("__save_extraction_offsets__", {})
            offsets[data_var] = start_idx + processed_count

        result["saved"] = saved_count > 0
        result["saved_count"] = saved_count
        result["duplicate_count"] = duplicate_count
        result["error_count"] = error_count
        result["last_result"] = last_result
        if error_count > 0 and saved_count == 0 and duplicate_count == 0:
            result["ok"] = False
            result["message"] = "save_extraction: all items failed"
        else:
            result["message"] = f"save_extraction: saved={saved_count}, duplicate={duplicate_count}, errors={error_count}"
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"save_extraction failed: {exc}"
