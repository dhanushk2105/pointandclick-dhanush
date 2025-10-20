"""Action and task verification logic."""

import asyncio
import logging
from typing import Dict
from openai import OpenAI

from .prompt_manager import prompt_manager, PromptType
from .config import OPENAI_MODEL, DOM_CONTENT_LIMIT
from .utils import format_action, format_page_state, log_detail
from .websocket_manager import manager

logger = logging.getLogger(__name__)


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
        
        # Render prompt using prompt manager
        prompt_config = prompt_manager.render(
            PromptType.ACTION_VERIFICATION,
            action=action_description,
            expected=expected_outcome,
            page_state=state_context
        )
        
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            **prompt_config
        )
        
        import json
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
    Uses both DOM content and optionally screenshot for verification.
    """
    try:
        client = OpenAI(api_key=api_key)
        
        # Truncate DOM if too long
        if len(dom_content) > DOM_CONTENT_LIMIT:
            dom_content = dom_content[:DOM_CONTENT_LIMIT] + "... (truncated)"
        
        # Render prompt using prompt manager
        prompt_config = prompt_manager.render(
            PromptType.FINAL_VERIFICATION,
            task=task_description,
            url=page_url,
            title=page_title,
            dom=dom_content
        )
        
        messages = prompt_config["messages"]
        
        # Add screenshot if available (GPT-4o supports vision)
        if screenshot_base64 and OPENAI_MODEL.startswith("gpt-4"):
            messages[1] = {
                "role": "user",
                "content": [
                    {"type": "text", "text": messages[1]["content"]},
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
            temperature=prompt_config["temperature"],
            max_tokens=prompt_config.get("max_tokens"),
            response_format=prompt_config["response_format"],
            messages=messages
        )
        
        import json
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


async def get_page_state_for_verification(task_id: str) -> Dict:
    """Get current page state for verification purposes."""
    import uuid
    
    if not manager.has_connections():
        return {
            "url": "",
            "title": "",
            "elements": [],
            "diagnostics": {"error": "No browser connection"}
        }

    ws = manager.get_first_connection()

    try:
        # Get page info
        info_id = f"{task_id}_info_{uuid.uuid4().hex[:8]}"
        info_future = manager.create_response_future(info_id)
        await manager.send_action(ws, info_id, "getPageInfo", {})
        info_resp = await asyncio.wait_for(info_future, timeout=5)

        page_info = {}
        info_err = None
        if info_resp.get("status") == "success":
            page_info = info_resp.get("data", {}) or {}
        else:
            info_err = info_resp.get("error", "getPageInfo failed")

        # Get elements
        elements_id = f"{task_id}_elements_{uuid.uuid4().hex[:8]}"
        elements_future = manager.create_response_future(elements_id)
        await manager.send_action(ws, elements_id, "getInteractiveElements", {})
        elements_resp = await asyncio.wait_for(elements_future, timeout=5)

        elements = []
        elements_err = None
        if elements_resp.get("status") == "success":
            elements = elements_resp.get("data", []) or []
        else:
            elements_err = elements_resp.get("error", "getInteractiveElements failed")

        state = {
            "url": page_info.get("url", ""),
            "title": page_info.get("title", ""),
            "elements": elements[:20],
        }
        
        diags = {}
        if info_err:
            diags["getPageInfo"] = info_err
        if elements_err:
            diags["getInteractiveElements"] = elements_err
        if diags:
            state["diagnostics"] = diags

        return state

    except Exception as e:
        return {
            "url": "",
            "title": "",
            "elements": [],
            "diagnostics": {"exception": str(e)}
        }