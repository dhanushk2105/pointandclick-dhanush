import json
import logging
from typing import Dict, List, Optional
import anthropic
import openai
from .prompts import PLANNING_PROMPT, VERIFICATION_PROMPT

logger = logging.getLogger(__name__)


async def create_plan(
    task_description: str,
    api_key: Optional[str] = None,
    provider: str = "mock"
) -> Dict:
    """Create an action plan for the given task using LLM or mock planner."""
    
    if not api_key or provider == "mock":
        return create_mock_plan(task_description)
    
    if provider == "anthropic":
        return await create_anthropic_plan(task_description, api_key)
    elif provider == "openai":
        return await create_openai_plan(task_description, api_key)
    else:
        return create_mock_plan(task_description)


def create_mock_plan(task_description: str) -> Dict:
    """Create a hardcoded plan for demo purposes."""
    
    task_lower = task_description.lower()
    
    if "gmail" in task_lower or "email" in task_lower or "promotional" in task_lower:
        return {
            "generated_by": "mock",
            "steps": [
                {"action": "navigate", "payload": {"url": "https://mail.google.com"}},
                {"action": "waitFor", "payload": {"selector": "[aria-label='Search mail']"}},
                {"action": "click", "payload": {"selector": "[aria-label='Search mail']"}},
                {"action": "type", "payload": {
                    "selector": "[aria-label='Search mail']",
                    "text": "category:promotions older_than:3m"
                }},
                {"action": "press", "payload": {"key": "Enter"}},
                {"action": "waitFor", "payload": {"selector": ".ae4", "timeout": 3000}}
            ]
        }
    
    elif "hugging" in task_lower or "paper" in task_lower:
        return {
            "generated_by": "mock",
            "steps": [
                {"action": "navigate", "payload": {"url": "https://huggingface.co/papers"}},
                {"action": "waitFor", "payload": {"selector": "input[type='search']"}},
                {"action": "click", "payload": {"selector": "input[type='search']"}},
                {"action": "type", "payload": {
                    "selector": "input[type='search']",
                    "text": "UI Agents"
                }},
                {"action": "press", "payload": {"key": "Enter"}},
                {"action": "waitFor", "payload": {"selector": "article", "timeout": 3000}}
            ]
        }
    
    # Default generic plan
    return {
        "generated_by": "mock",
        "steps": [
            {"action": "navigate", "payload": {"url": "https://google.com"}},
            {"action": "waitFor", "payload": {"selector": "input[name='q']"}},
            {"action": "type", "payload": {
                "selector": "input[name='q']",
                "text": task_description
            }},
            {"action": "press", "payload": {"key": "Enter"}}
        ]
    }


async def create_anthropic_plan(task_description: str, api_key: str) -> Dict:
    """Create a plan using Claude API."""
    
    try:
        client = anthropic.Anthropic(api_key=api_key)
        
        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1000,
            temperature=0,
            system="You are a browser automation expert. Create precise action plans.",
            messages=[
                {
                    "role": "user",
                    "content": PLANNING_PROMPT.format(task=task_description)
                }
            ]
        )
        
        # Parse JSON from response
        content = response.content[0].text
        
        # Extract JSON from response
        json_start = content.find("{")
        json_end = content.rfind("}") + 1
        
        if json_start != -1 and json_end > json_start:
            json_str = content[json_start:json_end]
            plan = json.loads(json_str)
            plan["generated_by"] = "anthropic"
            return plan
        else:
            raise ValueError("No valid JSON found in response")
            
    except Exception as e:
        logger.error(f"Anthropic plan creation failed: {e}")
        return create_mock_plan(task_description)


async def create_openai_plan(task_description: str, api_key: str) -> Dict:
    """Create a plan using OpenAI API."""
    
    try:
        client = openai.OpenAI(api_key=api_key)
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": "You are a browser automation expert. Create precise action plans."
                },
                {
                    "role": "user",
                    "content": PLANNING_PROMPT.format(task=task_description)
                }
            ]
        )
        
        # Parse JSON from response
        content = response.choices[0].message.content
        
        # Extract JSON from response
        json_start = content.find("{")
        json_end = content.rfind("}") + 1
        
        if json_start != -1 and json_end > json_start:
            json_str = content[json_start:json_end]
            plan = json.loads(json_str)
            plan["generated_by"] = "openai"
            return plan
        else:
            raise ValueError("No valid JSON found in response")
            
    except Exception as e:
        logger.error(f"OpenAI plan creation failed: {e}")
        return create_mock_plan(task_description)


async def verify_completion(
    task_description: str,
    dom_content: str,
    api_key: Optional[str] = None,
    provider: str = "mock"
) -> Dict:
    """Verify if the task was completed successfully."""
    
    if not api_key or provider == "mock":
        return verify_mock_completion(task_description, dom_content)
    
    if provider == "anthropic":
        return await verify_anthropic_completion(task_description, dom_content, api_key)
    elif provider == "openai":
        return await verify_openai_completion(task_description, dom_content, api_key)
    else:
        return verify_mock_completion(task_description, dom_content)


def verify_mock_completion(task_description: str, dom_content: str) -> Dict:
    """Mock verification based on keywords in DOM."""
    
    task_lower = task_description.lower()
    dom_lower = dom_content.lower()
    
    if "gmail" in task_lower or "email" in task_lower:
        if "promotions" in dom_lower or "category:promotions" in dom_lower:
            return {
                "success": True,
                "message": "Successfully found and filtered promotional emails"
            }
    
    if "hugging" in task_lower or "paper" in task_lower:
        if "ui agent" in dom_lower or "papers" in dom_lower:
            return {
                "success": True,
                "message": "Successfully found UI Agents papers on HuggingFace"
            }
    
    # Default response
    return {
        "success": len(dom_content) > 100,
        "message": "Task execution completed" if len(dom_content) > 100 else "Unable to verify task completion"
    }


async def verify_anthropic_completion(
    task_description: str,
    dom_content: str,
    api_key: str
) -> Dict:
    """Verify completion using Claude."""
    
    try:
        client = anthropic.Anthropic(api_key=api_key)
        
        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=200,
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": VERIFICATION_PROMPT.format(
                        task=task_description,
                        dom=dom_content[:1000]  # Limit DOM content
                    )
                }
            ]
        )
        
        content = response.content[0].text
        
        # Simple parsing
        success = "success" in content.lower() or "completed" in content.lower()
        
        return {
            "success": success,
            "message": content[:200]
        }
        
    except Exception as e:
        logger.error(f"Anthropic verification failed: {e}")
        return verify_mock_completion(task_description, dom_content)


async def verify_openai_completion(
    task_description: str,
    dom_content: str,
    api_key: str
) -> Dict:
    """Verify completion using OpenAI."""
    
    try:
        client = openai.OpenAI(api_key=api_key)
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": VERIFICATION_PROMPT.format(
                        task=task_description,
                        dom=dom_content[:1000]  # Limit DOM content
                    )
                }
            ]
        )
        
        content = response.choices[0].message.content
        
        # Simple parsing
        success = "success" in content.lower() or "completed" in content.lower()
        
        return {
            "success": success,
            "message": content[:200]
        }
        
    except Exception as e:
        logger.error(f"OpenAI verification failed: {e}")
        return verify_mock_completion(task_description, dom_content)