"""Planning logic using prompt manager for cleaner prompt handling."""

import json
import logging
from typing import Dict, List, Any
from openai import OpenAI

from .prompt_manager import prompt_manager, PromptType
from .config import OPENAI_MODEL
from .utils import format_page_state, format_action_history

logger = logging.getLogger(__name__)


def _extract_json_object(raw: str) -> Any:
    """Be tolerant: strip code fences, unwrap lists, and parse first JSON object."""
    s = raw.strip()

    # strip triple backticks if present
    if s.startswith("```"):
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()

    # try direct parse
    try:
        parsed = json.loads(s)
    except Exception:
        first_brace = s.find("{")
        last_brace = s.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            try:
                parsed = json.loads(s[first_brace:last_brace + 1])
            except Exception as e2:
                raise json.JSONDecodeError(f"Could not parse JSON object from content: {e2}", s, 0)
        else:
            raise

    # unwrap single-item list
    if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
        return parsed[0]
    return parsed


def _normalize_plan(plan: Any) -> Dict[str, Any]:
    """Ensure expected keys exist; never KeyError on 'task_complete'."""
    if not isinstance(plan, dict):
        raise ValueError(f"Unexpected JSON type: {type(plan).__name__}")

    normalized: Dict[str, Any] = dict(plan)

    # task_complete default
    if "task_complete" not in normalized:
        normalized["task_complete"] = False
    else:
        if isinstance(normalized["task_complete"], str):
            normalized["task_complete"] = normalized["task_complete"].strip().lower() == "true"
        else:
            normalized["task_complete"] = bool(normalized["task_complete"])

    # payload default
    if "payload" not in normalized or not isinstance(normalized.get("payload"), dict):
        normalized["payload"] = {}

    # reasoning / expected_outcome defaults
    normalized["reasoning"] = str(normalized.get("reasoning", "") or "")
    normalized["expected_outcome"] = str(normalized.get("expected_outcome", "") or "")

    # optional aliasing: map low-level names to smart*
    action = normalized.get("action")
    if isinstance(action, str):
        action = action.strip()
        if action == "click":
            action = "smartClick"
        elif action == "type":
            action = "smartType"
        normalized["action"] = action

    return normalized


async def plan_next_action(
    task_description: str,
    page_state: Dict,
    steps_taken: List[dict],
    api_key: str
) -> Dict:
    """
    Plan ONLY the next single action with structured JSON output.
    Uses prompt_manager for cleaner prompt handling.
    """
    client = OpenAI(api_key=api_key)

    # Format context
    state_context = format_page_state(page_state)
    history_context = format_action_history(steps_taken)

    # Render prompt using prompt manager
    prompt_config = prompt_manager.render(
        PromptType.NEXT_ACTION,
        task=task_description,
        page_state=state_context,
        history=history_context
    )

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            **prompt_config
        )

        raw = (response.choices[0].message.content or "").strip()
        plan_obj = _extract_json_object(raw)
        plan = _normalize_plan(plan_obj)

        # If the agent says the task is complete, accept and return
        if plan["task_complete"] is True:
            if not plan.get("reasoning"):
                plan["reasoning"] = "Agent reports goal already satisfied based on page evidence."
            logger.info("✓ Agent determined task is complete")
            return plan

        # Otherwise validate action + payload
        if "action" not in plan or not isinstance(plan["action"], str) or not plan["action"]:
            raise ValueError(f"Plan missing 'action' field. Raw: {raw}")

        action = plan["action"]
        payload = plan.get("payload", {}) or {}

        # Validate required payload fields for each action
        if action == "navigate":
            if not payload.get("url"):
                raise ValueError("navigate action requires 'url' in payload")

        elif action == "smartType":
            if not payload.get("text"):
                raise ValueError("smartType action requires 'text' in payload")

        elif action == "press":
            if not payload.get("key"):
                payload["key"] = "Enter"

        elif action == "smartClick":
            allowed = ["selector", "text", "description", "name", "id", "ariaLabel", "role"]
            if not any(k in payload for k in allowed):
                raise ValueError("smartClick requires selector, text, description, name, id, ariaLabel, or role")

            # Normalize to selector if possible
            if "selector" not in payload:
                if "id" in payload:
                    payload["selector"] = f"#{payload['id']}"
                elif "name" in payload:
                    payload["selector"] = f"[name='{payload['name']}']"
                elif "ariaLabel" in payload:
                    payload["selector"] = f"[aria-label='{payload['ariaLabel']}'], button[aria-label='{payload['ariaLabel']}'], a[aria-label='{payload['ariaLabel']}']"
                elif "role" in payload:
                    payload["selector"] = f"[role='{payload['role']}']"

            plan["payload"] = payload

        logger.info(f"✓ Planned next action: {action}")
        return plan

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {e}")
        logger.error(f"Raw content: {locals().get('raw', '')}")
        raise Exception(f"Invalid JSON response from LLM: {str(e)}") from e
    except Exception as e:
        raw = locals().get('raw', '')
        logger.error(f"Next action planning failed: {e}")
        if raw:
            logger.error(f"Raw content: {raw}")
        raise Exception(f"Failed to plan next action: {e}")