import json
import logging
from typing import Dict, List, Any
from openai import OpenAI
from .prompts import (
    render_next_action_prompt,
    render_action_verification_prompt,
    render_final_verification_prompt
)
from .config import OPENAI_MODEL, OPENAI_TEMPERATURE

logger = logging.getLogger(__name__)


def _extract_json_object(raw: str) -> Any:
    """Be tolerant: strip code fences, unwrap lists, and parse first JSON object."""
    s = raw.strip()

    # strip triple backticks if present
    if s.startswith("```"):
        # keep content inside first fenced block
        lines = s.splitlines()
        # remove first line (``` or ```json)
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        # drop trailing ``` if present
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()

    # try direct parse
    try:
        parsed = json.loads(s)
    except Exception:
        # some models wrap json in text like: Response: {...}
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

    # coerce types + defaults
    normalized: Dict[str, Any] = dict(plan)  # shallow copy

    # task_complete default
    if "task_complete" not in normalized:
        normalized["task_complete"] = False
    else:
        # sometimes it's "true"/"false" as string
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

    Returns dict with either:
      {"task_complete": true, "reasoning": "..."}
    or
      {"action": "...", "payload": {...}, "reasoning": "...", "expected_outcome": "...", "task_complete": false}
    """
    client = OpenAI(api_key=api_key)

    # Helpful nudge if page is empty → ask model to navigate first
    is_page_empty = not (page_state.get("url") or page_state.get("title") or page_state.get("elements"))
    state_context = format_page_state(page_state)
    history_context = format_action_history(steps_taken)

    preface = ""
    if is_page_empty:
        preface = (
            "NOTE: Page appears empty (no URL/title/elements). "
            "Start by navigating to a sensible entry point for the GOAL.\n\n"
        )

    prompt = preface +  render_next_action_prompt(task=task_description, page_state=state_context, history=history_context)

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=OPENAI_TEMPERATURE,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": "You are a browser automation agent. Always respond with valid JSON. Plan ONE action at a time based on current page state."
                },
                {"role": "user", "content": prompt}
            ]
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
            # allow name/id/ariaLabel/role as well
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
                    # try aria-label, then button/link roles as common clickables
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
        # show raw content to help diagnose, but avoid crashing caller with cryptic KeyError
        raw = locals().get('raw', '')
        logger.error(f"Next action planning failed: {e}")
        if raw:
            logger.error(f"Raw content: {raw}")
        # Re-raise a clean error
        raise Exception(f"Failed to plan next action: {e}")



async def verify_action_success(
    action_taken: dict,
    expected_outcome: str,
    page_state: Dict,
    api_key: str
) -> Dict:
    """
    Verify that a single action succeeded using structured JSON output.
    
    Returns: {
        "success": true/false,
        "confidence": 0.0-1.0,
        "message": "explanation"
    }
    """
    
    try:
        client = OpenAI(api_key=api_key)
        
        action_description = format_action(action_taken)
        state_context = format_page_state(page_state)
        
        prompt = render_action_verification_prompt(
            action=action_description,
            expected=expected_outcome,
            page_state=state_context
        )
        
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0,
            max_tokens=300,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": "You verify if browser actions succeeded. Always respond with valid JSON containing 'success' (boolean), 'confidence' (0.0-1.0), and 'message' (string)."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        
        content = response.choices[0].message.content.strip()
        result = json.loads(content)
        
        # Validate structure
        if "success" not in result:
            raise ValueError("Verification response missing 'success' field")
        
        # Ensure proper types
        result["success"] = bool(result["success"])
        result["confidence"] = float(result.get("confidence", 0.5))
        result["message"] = str(result.get("message", "No message provided"))
        
        logger.info(f"Action verification: {'SUCCESS' if result['success'] else 'FAILED'} (confidence: {result['confidence']:.2f})")
        
        return result
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse verification JSON: {e}")
        return {
            "success": False,
            "confidence": 0.0,
            "message": f"JSON parse error: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Action verification failed: {e}")
        return {
            "success": False,
            "confidence": 0.0,
            "message": f"Verification error: {str(e)}"
        }


async def verify_final_completion(
    task_description: str,
    dom_content: str,
    page_url: str,
    page_title: str,
    screenshot_base64: str,
    api_key: str
) -> Dict:
    """
    Final verification that the entire task is complete.
    Uses both DOM content and screenshot for verification.
    """
    
    try:
        client = OpenAI(api_key=api_key)
        
        # Truncate DOM if too long
        if len(dom_content) > 3000:
            dom_content = dom_content[:3000] + "... (truncated)"
        
        prompt = render_final_verification_prompt(
            task=task_description,
            url=page_url,
            title=page_title,
            dom=dom_content
        )
        
        messages = [
            {
                "role": "system",
                "content": "You verify if browser tasks are complete. Always respond with valid JSON containing 'success' (boolean), 'confidence' (0.0-1.0), and 'message' (string)."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
        
        # Add screenshot if available (GPT-4o supports vision)
        if screenshot_base64 and OPENAI_MODEL.startswith("gpt-4"):
            messages[1] = {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{screenshot_base64}",
                            "detail": "high"
                        }
                    }
                ]
            }
        
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0,
            max_tokens=500,
            response_format={"type": "json_object"},
            messages=messages
        )
        
        content = response.choices[0].message.content.strip()
        result = json.loads(content)
        
        # Validate and normalize
        if "success" not in result:
            raise ValueError("Final verification missing 'success' field")
        
        result["success"] = bool(result["success"])
        result["confidence"] = float(result.get("confidence", 0.5))
        result["message"] = str(result.get("message", "No message provided"))
        
        logger.info(f"Final verification: {'SUCCESS' if result['success'] else 'FAILED'} (confidence: {result['confidence']:.2f})")
        
        return result
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse final verification JSON: {e}")
        return {
            "success": False,
            "confidence": 0.0,
            "message": f"JSON parse error: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Final verification failed: {e}")
        return {
            "success": False,
            "confidence": 0.0,
            "message": f"Verification error: {str(e)}"
        }


def format_action(action: dict) -> str:
    """Format action for human-readable display."""
    
    action_type = action.get("action", "unknown")
    payload = action.get("payload", {})
    
    if action_type == "navigate":
        return f"Navigate to {payload.get('url', 'URL')}"
    elif action_type == "smartClick":
        if payload.get("text"):
            return f"Click element with text '{payload['text']}'"
        elif payload.get("selector"):
            return f"Click element matching '{payload['selector']}'"
        else:
            return "Click element"
    elif action_type == "smartType":
        return f"Type '{payload.get('text', '')}' into input field"
    elif action_type == "press":
        return f"Press {payload.get('key', 'key')}"
    elif action_type == "download":
        return f"Download file from {payload.get('url', 'URL')}"
    elif action_type == "uploadFile":
        return f"Upload file: {payload.get('filename', 'unknown')}"
    else:
        return f"{action_type}: {json.dumps(payload)}"


def format_action_history(steps: List[dict]) -> str:
    """Format action history for context."""
    
    if not steps:
        return "No actions taken yet."
    
    history = f"Actions taken so far ({len(steps)} steps):\n"
    for i, step in enumerate(steps, 1):
        action_desc = format_action(step)
        history += f"{i}. {action_desc}\n"
    
    return history


def format_page_state(page_state: Dict) -> str:
    """Format page state into readable context."""
    
    if "error" in page_state:
        return f"Error: {page_state['error']}"

    context = f"Current URL: {page_state.get('url', 'unknown')}\n"
    context += f"Page Title: {page_state.get('title', 'unknown')}\n\n"

    diags = page_state.get("diagnostics")
    if diags:
        context += f"Diagnostics: {json.dumps(diags)[:240]}\n\n"

    elements = page_state.get('elements', [])

    if elements:
        context += "Interactive Elements (up to 15 shown):\n"
        for i, elem in enumerate(elements[:15], 1):
            elem_type = elem.get('type', 'unknown')
            elem_text = elem.get('text', '')
            elem_id = elem.get('id', '')
            elem_name = elem.get('name', '')
            elem_placeholder = elem.get('placeholder', '')
            
            context += f"  {i}. <{elem_type}>"
            if elem_text:
                context += f" text='{elem_text[:50]}'"
            if elem_id:
                context += f" id='{elem_id}'"
            if elem_name:
                context += f" name='{elem_name}'"
            if elem_placeholder:
                context += f" placeholder='{elem_placeholder}'"
            
            # Add special flags
            if elem.get('isSubmitButton'):
                context += " [SUBMIT]"
            if elem.get('isPdfLink'):
                context += " [PDF]"
            
            context += "\n"
    else:
        context += "No interactive elements found yet.\n"
    
    return context