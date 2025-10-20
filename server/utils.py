"""Utility functions for logging and formatting."""

import logging
from typing import Dict, List, Any
from .config import VERBOSE

logger = logging.getLogger(__name__)


def log_section(title: str) -> None:
    """Log a section header."""
    if VERBOSE:
        logger.info(f"\n{'='*60}")
        logger.info(f"  {title}")
        logger.info(f"{'='*60}")


def log_detail(emoji: str, message: str, details: str = "") -> None:
    """Log a detailed message with optional details."""
    if VERBOSE:
        logger.info(f"{emoji} {message}")
        if details:
            for line in details.split('\n'):
                if line.strip():
                    logger.info(f"  → {line.strip()}")


def format_page_state(page_state: Dict) -> str:
    """Format page state into readable context."""
    if "error" in page_state:
        return f"Error: {page_state['error']}"

    context = f"Current URL: {page_state.get('url', 'unknown')}\n"
    context += f"Page Title: {page_state.get('title', 'unknown')}\n\n"

    diags = page_state.get("diagnostics")
    if diags:
        import json
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


def format_action_history(steps: List[dict]) -> str:
    """Format action history for context."""
    if not steps:
        return "No actions taken yet."
    
    history = f"Actions taken so far ({len(steps)} steps):\n"
    for i, step in enumerate(steps, 1):
        action_desc = format_action(step)
        history += f"{i}. {action_desc}\n"
    
    return history


def format_action(action: dict) -> str:
    """Format action for human-readable display."""
    import json
    
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


def get_step_description(step: dict) -> str:
    """Get human-readable step description."""
    action = step["action"]
    payload = step.get("payload", {})
    
    if action == "navigate":
        return f"Going to {payload.get('url', 'URL')}"
    elif action == "smartClick":
        text = payload.get('text', '')
        desc = payload.get('description', '')
        return f"Clicking {f'{text}' if text else desc or 'element'}"
    elif action == "smartType":
        return f"Typing '{payload.get('text', '')}'"
    elif action == "press":
        return f"Pressing {payload.get('key', 'key')}"
    elif action == "download":
        return f"Downloading {payload.get('url', 'file')}"
    elif action == "uploadFile":
        return f"Uploading file"
    else:
        return f"{action}"