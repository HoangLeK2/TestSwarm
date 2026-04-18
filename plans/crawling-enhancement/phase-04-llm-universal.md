# Phase 4: LLM Universal Extractor

## Objective

Build schema-defined extraction via LLM (GPT-4V / Gemini Vision) that works on ANY app without hardcoded selectors. Used as: primary for unknown apps, fallback when XML parser returns 0 items.

## Architecture

```
Screenshot + XML Hierarchy
        ↓
[Confidence Cascade]
   1. XML hierarchy parse (fast, free)   → if items > 0: use result
   2. OCR + regex (medium, cheap)        → if items > 0: use result  
   3. LLM Vision (slow, costs money)     → always has result
        ↓
[Cache Layer] — skip LLM if same screen hash seen recently
        ↓
[Schema Validator] — validate output matches ExtractionSchema
        ↓
[ContentItem]
```

## Extraction Schema (YAML Templates)

**File**: `config/extraction_templates/` (new directory)

```yaml
# config/extraction_templates/social_post.yaml
name: social_post
description: "Extract social media posts from any platform"
fields:
  - name: author
    type: string
    required: true
    hint: "Username or display name of the post author"
  - name: body
    type: string
    required: true
    hint: "Main text content of the post"
  - name: likes_count
    type: integer
    required: false
    hint: "Number of likes, reactions, or hearts"
  - name: comments_count
    type: integer
    required: false
    hint: "Number of comments or replies"
  - name: shares_count
    type: integer
    required: false
    hint: "Number of shares, reposts, or retweets"
  - name: media_type
    type: enum
    values: [photo, video, text, story, reel]
    required: false
  - name: timestamp
    type: string
    required: false
    hint: "Post time, e.g. '2 hours ago' or '2026-04-16'"
multiple: true
container_hint: "Each separate post card in a social media feed"
```

```yaml
# config/extraction_templates/comment_thread.yaml
name: comment_thread
description: "Extract comments from a post comment section"
fields:
  - name: author
    type: string
    required: true
  - name: body
    type: string
    required: true
  - name: likes_count
    type: integer
    required: false
  - name: level
    type: integer
    required: false
    hint: "0=top-level comment, 1=reply to comment"
multiple: true
```

## LLM Extractor Implementation

**File**: `runtime/extraction/llm_extractor.py` (new)

```python
import base64, json, hashlib
from pathlib import Path
from openai import AsyncOpenAI
import google.generativeai as genai
from lxml import etree

class LLMExtractor:
    def __init__(self, config):
        self.config = config
        self.openai = AsyncOpenAI(api_key=config.openai_api_key) if config.openai_api_key else None
        if config.gemini_api_key:
            genai.configure(api_key=config.gemini_api_key)
        self._cache: dict[str, list] = {}  # screen_hash → items

    async def extract(
        self,
        screenshot_path: str,
        xml_root: etree._Element,
        template_name: str = "social_post",
        model: str = "gpt-4o",
    ) -> list[dict]:
        # Cache check
        screen_hash = self._hash_screen(screenshot_path)
        if screen_hash in self._cache:
            return self._cache[screen_hash]
        
        template = self._load_template(template_name)
        prompt = self._build_prompt(template, xml_root)
        
        if model.startswith("gpt") and self.openai:
            items = await self._extract_openai(screenshot_path, prompt, model)
        else:
            items = await self._extract_gemini(screenshot_path, prompt)
        
        validated = self._validate(items, template)
        self._cache[screen_hash] = validated
        return validated

    def _build_prompt(self, template: dict, xml_root) -> str:
        # Include simplified hierarchy as context (reduce tokens)
        hierarchy_summary = self._summarize_hierarchy(xml_root, max_nodes=50)
        
        fields_desc = "\n".join(
            f"- {f['name']} ({f['type']}): {f.get('hint','')}"
            for f in template["fields"]
        )
        
        return f"""Extract structured data from this mobile app screenshot.

Template: {template['description']}
Fields to extract:
{fields_desc}

{"Extract multiple items (one per " + template.get('container_hint', 'item') + ")." if template.get('multiple') else "Extract one item."}

UI Hierarchy context (simplified):
{hierarchy_summary}

Return ONLY a JSON array. Example:
[{{"author": "username", "body": "post text", "likes_count": 123}}]

If no items found, return empty array: []"""

    async def _extract_openai(self, screenshot_path: str, prompt: str, model: str) -> list[dict]:
        with open(screenshot_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        
        response = await self.openai.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                    {"type": "text", "text": prompt}
                ]
            }],
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        data = json.loads(raw)
        return data if isinstance(data, list) else data.get("items", [])

    async def _extract_gemini(self, screenshot_path: str, prompt: str) -> list[dict]:
        model = genai.GenerativeModel("gemini-1.5-pro-vision")
        img = genai.upload_file(screenshot_path, mime_type="image/jpeg")
        response = await model.generate_content_async(
            [prompt, img],
            generation_config={"response_mime_type": "application/json"}
        )
        data = json.loads(response.text)
        return data if isinstance(data, list) else data.get("items", [])

    def _summarize_hierarchy(self, xml_root, max_nodes: int = 50) -> str:
        """Extract text-bearing nodes from XML for context (reduces tokens 10x)"""
        nodes = []
        for node in xml_root.iter():
            text = node.get("text","") or node.get("content-desc","")
            if text and len(text) > 3:
                cls = node.get("class","").split(".")[-1]
                nodes.append(f"[{cls}] {text[:100]}")
            if len(nodes) >= max_nodes:
                break
        return "\n".join(nodes)

    def _validate(self, items: list[dict], template: dict) -> list[dict]:
        validated = []
        required_fields = [f["name"] for f in template["fields"] if f.get("required")]
        for item in items:
            if all(item.get(f) for f in required_fields):
                validated.append(item)
        return validated

    def _hash_screen(self, screenshot_path: str) -> str:
        with open(screenshot_path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()

    def _load_template(self, name: str) -> dict:
        import yaml
        template_path = Path(f"config/extraction_templates/{name}.yaml")
        with open(template_path) as f:
            return yaml.safe_load(f)
```

## Integrate into Extraction Step

**File**: `tasks/scenario/steps/extraction.py` (modify)

```python
from runtime.extraction.llm_extractor import LLMExtractor

async def handle_llm_extract(ctx: ScenarioContext, step, idx, result):
    """Universal LLM-based extraction fallback"""
    template = step.config.get("llm_template", "social_post")
    model = step.config.get("llm_model", "gpt-4o")
    
    screenshot_path = await ctx.take_screenshot(f"llm_extract_{idx}")
    xml_root = await ctx.get_hierarchy_xml()
    
    extractor = LLMExtractor(ctx.config)
    items = await extractor.extract(screenshot_path, xml_root, template, model)
    
    if step.config.get("collection") and items:
        for item_dict in items:
            await content_store.save_raw(
                item_dict,
                platform=ctx.current_platform,
                collection=step.config["collection"],
                content_type=step.config.get("content_type", "post"),
            )
    
    result.data = items
    result.item_count = len(items)
```

New step type in scenario:
```json
{
  "type": "llm_extract",
  "llm_template": "social_post",
  "llm_model": "gpt-4o",
  "collection": "universal_posts",
  "content_type": "post"
}
```

## Cost Control

```python
# In LLMExtractor: track cost per session
COST_PER_IMAGE = {
    "gpt-4o": 0.005,           # $0.005 per image
    "gemini-1.5-pro-vision": 0.001,
}

async def extract_with_budget(self, ..., max_cost_usd: float = 1.0):
    if self._session_cost >= max_cost_usd:
        raise BudgetExceededError(f"LLM budget ${max_cost_usd} reached")
    items = await self.extract(...)
    self._session_cost += COST_PER_IMAGE.get(model, 0.005)
    return items
```

## Files Summary

| File | Action |
|------|--------|
| `runtime/extraction/llm_extractor.py` | New — LLM extractor with cache + validation |
| `config/extraction_templates/social_post.yaml` | New — default post schema |
| `config/extraction_templates/comment_thread.yaml` | New — comment schema |
| `config/extraction_templates/video_feed.yaml` | New — video (TikTok/YT) schema |
| `tasks/scenario/steps/extraction.py` | Modify — add `llm_extract` step type |
| `services/content_store.py` | Modify — add `save_raw(dict, ...)` method |
| `core/config.py` | Modify — add `llm_extractor` config section |

## Config

```yaml
llm_extractor:
  default_model: "gemini-1.5-pro-vision"  # cheaper than gpt-4o
  fallback_model: "gpt-4o"
  cache_ttl_seconds: 300
  max_cost_per_session_usd: 5.0
  template_dir: "config/extraction_templates"
```

## Tradeoffs

| Approach | Speed | Cost | Maintenance |
|---|---|---|---|
| XML parser | Fast (~50ms) | Free | High (breaks on app update) |
| OCR | Medium (~500ms) | Free | Medium |
| LLM Vision | Slow (~3-10s) | $0.001-0.005/call | Low (no selectors) |

**Recommendation**: Use XML parser primary, LLM as fallback only. Log when LLM fallback triggers — indicates XML parser needs update.
