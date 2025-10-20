"""Main execution engine"""

import asyncio
import json
import logging

from .config import (
    MAX_RETRIES,
    MAX_STEPS,
    ACTION_TIMEOUT_SECONDS,
    VERIFICATION_DELAY_SECONDS,
    PAGE_SETTLE_DELAY,
    RETRY_DELAY_SECONDS
)
from .task_manager import task_manager
from .websocket_manager import manager
from .verification import (
    verify_action_success,
    verify_final_completion,
    get_page_state_for_verification
)
from .planner import plan_next_action
from .utils import log_section, log_detail, get_step_description

logger = logging.getLogger(__name__)


async def execute_task_with_retry(task_id: str):
    """Main execution loop with exponential backoff retry."""
    task = task_manager.get_task(task_id)
    if not task:
        logger.error(f"Task {task_id} not found")
        return
    
    log_section("🔄 STARTING REACTIVE LOOP")
    
    for attempt in range(MAX_RETRIES):
        task.retry_count = attempt
        
        if attempt > 0:
            delay = RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
            log_detail("🔄", f"RETRY ATTEMPT {attempt + 1}", f"Waiting {delay}s before retry...")
            task.add_log("warning", f"Retry {attempt + 1}/{MAX_RETRIES}", 
                        f"Previous attempt failed: {task.verification_result}")
            await asyncio.sleep(delay)
            
            # Clear plan for fresh retry (let planner try different approach)
            log_detail("🧹", "Clearing failed plan for fresh retry")
            task.plan = []  # IMPORTANT: Clear so planner can try different strategy
        
        try:
            success = await execute_reactive_loop(task_id)
            
            if success:
                log_section("✅ TASK COMPLETED SUCCESSFULLY")
                task.status = "completed"
                return
                
        except Exception as e:
            log_detail("❌", f"ERROR on attempt {attempt + 1}", str(e))
            logger.exception("Full exception:")
            task.add_log("error", f"Attempt {attempt + 1} failed", str(e))
            task.verification_result = str(e)
    
    # All retries exhausted
    task.status = "failed"
    task.add_log("error", "All attempts exhausted", f"Failed after {MAX_RETRIES} attempts")
    log_section("❌ TASK FAILED - ALL ATTEMPTS EXHAUSTED")


async def execute_reactive_loop(task_id: str) -> bool:
    """Core reactive loop: observe → plan → act → verify.
    CRITICAL: No retry loops inside - only outer retry."""
    task = task_manager.get_task(task_id)
    if not task:
        return False
    
    step_count = 0
    
    while step_count < MAX_STEPS:
        step_count += 1
        log_section(f"🔍 REACTIVE STEP {step_count}")
        
        # STEP 1: OBSERVE
        log_detail("👀", "OBSERVING current page state...")
        page_state = await get_page_state_for_verification(task_id)
        
        if "error" in page_state.get("diagnostics", {}):
            log_detail("❌", "Failed to observe page", str(page_state.get("diagnostics")))
            task.verification_result = f"Cannot observe page: {page_state.get('diagnostics')}"
            return False
        
        log_detail("📊", "Page State", 
                  f"URL: {page_state.get('url', 'unknown')}\n"
                  f"Title: {page_state.get('title', 'unknown')}\n"
                  f"Elements: {len(page_state.get('elements', []))}")
        
        # STEP 2: PLAN
        task.status = "planning"
        log_detail("🧠", "PLANNING next action...")
        
        try:
            action_plan = await plan_next_action(
                task_description=task.description,
                page_state=page_state,
                steps_taken=task.plan,
                api_key=task.api_key
            )
        except Exception as e:
            log_detail("❌", "Planning failed", str(e))
            task.verification_result = f"Planning error: {str(e)}"
            return False
        
        log_detail("📝", "Next Action Planned", 
                  f"Action: {action_plan.get('action', 'N/A')}\n"
                  f"Reasoning: {action_plan.get('reasoning', 'N/A')}\n"
                  f"Complete: {action_plan.get('task_complete', False)}")
        
        # Check if task is complete
        if action_plan.get("task_complete", False):
            log_detail("🎯", "Agent says task is COMPLETE", action_plan.get("reasoning", ""))
            final_success = await verify_final_task(task_id)
            return final_success
        
        # Validate action exists
        if "action" not in action_plan:
            log_detail("❌", "Invalid action plan", "No 'action' field found")
            task.verification_result = "Invalid action plan: missing 'action' field"
            return False
        
        # STEP 3: ACT
        task.status = "processing"
        action_step = {
            "action": action_plan["action"],
            "payload": action_plan.get("payload", {})
        }
        
        log_detail("⚡", f"EXECUTING action: {action_step['action']}")
        
        success = await execute_single_action(task_id, action_step, step_count)
        
        if not success:
            log_detail("❌", "Action execution failed")
            # IMPORTANT: Return False to trigger outer retry, don't loop here
            return False
        
        task.plan.append(action_step)
        task.steps_executed += 1
        
        # STEP 4: VERIFY
        log_detail("🔍", "VERIFYING action success...")
        await asyncio.sleep(VERIFICATION_DELAY_SECONDS)
        
        verification = await verify_action_completed(
            task_id=task_id,
            action_taken=action_step,
            expected_outcome=action_plan.get("expected_outcome", "")
        )
        
        log_detail("📋", "Action Verification", 
                  f"Success: {verification['success']}\n"
                  f"Confidence: {verification.get('confidence', 'N/A')}\n"
                  f"Message: {verification['message']}")
        
        if not verification["success"]:
            log_detail("⚠️", "Action verification FAILED", verification["message"])
            task.verification_result = f"Step {step_count} verification failed: {verification['message']}"
            # IMPORTANT: Return False to trigger outer retry, DON'T continue loop
            return False
        
        log_detail("✅", f"Step {step_count} verified successfully")
        task.add_log("success", f"Step {step_count} completed", verification["message"])
        
        await asyncio.sleep(0.5)
    
    # Max steps reached
    log_detail("⚠️", "Maximum steps reached", f"Stopped at {MAX_STEPS} steps")
    task.verification_result = f"Maximum steps ({MAX_STEPS}) reached without completion"
    return False


async def execute_single_action(task_id: str, action_step: dict, step_num: int) -> bool:
    """Execute a single action with proper timeout handling."""
    task = task_manager.get_task(task_id)
    if not task:
        return False
    
    if not manager.has_connections():
        log_detail("❌", "No browser connection")
        task.verification_result = "No browser extension connected"
        return False
    
    websocket = manager.get_first_connection()
    
    try:
        action_id = f"{task_id}_step_{step_num}_{task.retry_count}"
        
        task.current_step = {
            "index": step_num,
            "total": "dynamic",
            "action": action_step["action"],
            "payload": action_step.get("payload", {}),
            "description": get_step_description(action_step)
        }
        
        log_detail("▶️", f"Executing", 
                  f"Action: {action_step['action']}\n"
                  f"Payload: {json.dumps(action_step.get('payload', {}), indent=2)}")
        
        task.add_log("step", f"Step {step_num}: {action_step['action']}", 
                    get_step_description(action_step))
        
        response_future = manager.create_response_future(action_id)
        
        await manager.send_action(
            websocket, 
            action_id, 
            action_step["action"], 
            action_step.get("payload", {})
        )
        
        response = await asyncio.wait_for(response_future, timeout=ACTION_TIMEOUT_SECONDS)
        
        log_detail("📨", "Response received", json.dumps(response, indent=2))
        
        if response.get("status") != "success":
            error_msg = response.get("error", "Unknown error")
            log_detail("❌", f"Action FAILED", error_msg)
            task.add_log("error", f"Step {step_num} failed", error_msg)
            task.verification_result = f"Step {step_num} failed: {error_msg}"
            return False
        
        log_detail("✅", "Action executed successfully")
        
        # Smart delays based on action type - LONGER for typing to let page settle
        if action_step["action"] in ["navigate", "click", "smartClick"]:
            await asyncio.sleep(PAGE_SETTLE_DELAY)
        elif action_step["action"] in ["smartType", "type"]:
            await asyncio.sleep(PAGE_SETTLE_DELAY * 1.5)  # Extra time for typing to register
        else:
            await asyncio.sleep(0.5)
        
        return True
        
    except asyncio.TimeoutError:
        log_detail("⏱️", "Action TIMEOUT", f"No response after {ACTION_TIMEOUT_SECONDS} seconds")
        task.add_log("error", f"Step {step_num} timeout", f"Action: {action_step['action']}")
        task.verification_result = f"Timeout on step {step_num}"
        return False
    except Exception as e:
        log_detail("❌", "Execution error", str(e))
        logger.exception("Exception:")
        task.verification_result = f"Execution error: {str(e)}"
        return False


async def verify_action_completed(task_id: str, action_taken: dict, expected_outcome: str) -> dict:
    """Verify that a single action succeeded using structured output."""
    task = task_manager.get_task(task_id)
    if not task:
        return {
            "success": False,
            "confidence": 0.0,
            "message": "Task not found"
        }
    
    try:
        page_state = await get_page_state_for_verification(task_id)
        
        verification = await verify_action_success(
            action_taken=action_taken,
            expected_outcome=expected_outcome,
            page_state=page_state,
            api_key=task.api_key
        )
        
        return verification
        
    except Exception as e:
        log_detail("❌", "Verification error", str(e))
        logger.exception("Exception:")
        return {
            "success": False,
            "confidence": 0.0,
            "message": f"Verification error: {str(e)}"
        }


async def verify_final_task(task_id: str) -> bool:
    """Final verification that entire task is complete."""
    task = task_manager.get_task(task_id)
    if not task:
        return False
    
    task.status = "verifying"
    task.add_log("info", "Final verification", "Checking if goal achieved")
    
    log_section("🔎 FINAL VERIFICATION")
    
    try:
        page_state = await get_page_state_for_verification(task_id)
        
        websocket = manager.get_first_connection()
        
        # Get DOM content
        verify_id = f"{task_id}_final_verify"
        verify_future = manager.create_response_future(verify_id)
        
        from .config import DOM_CONTENT_LIMIT
        await manager.send_action(websocket, verify_id, "query", 
                                 {"selector": "body", "limit": DOM_CONTENT_LIMIT})
        
        verify_response = await asyncio.wait_for(verify_future, timeout=10)
        dom_content = verify_response.get("data", "")
        
        log_detail("📄", "Final DOM retrieved", f"Length: {len(dom_content)} chars")
        
        # Get screenshot for visual verification
        screenshot_id = f"{task_id}_screenshot"
        screenshot_future = manager.create_response_future(screenshot_id)
        
        await manager.send_action(websocket, screenshot_id, "captureScreenshot", {})
        screenshot_response = await asyncio.wait_for(screenshot_future, timeout=5)
        screenshot_data = screenshot_response.get("data", "")
        
        verification = await verify_final_completion(
            task_description=task.description,
            dom_content=dom_content,
            page_url=page_state.get("url", ""),
            page_title=page_state.get("title", ""),
            screenshot_base64=screenshot_data,
            api_key=task.api_key
        )
        
        task.verification_result = verification["message"]
        
        log_detail("📊", "Final Verification", 
                  f"Success: {verification['success']}\n"
                  f"Confidence: {verification.get('confidence', 'N/A')}\n"
                  f"Message: {verification['message']}")
        
        if verification["success"]:
            task.add_log("success", "Task completed successfully", verification["message"])
            log_detail("✅", "FINAL VERIFICATION PASSED")
            return True
        else:
            task.add_log("warning", "Final verification failed", verification["message"])
            log_detail("⚠️", "FINAL VERIFICATION FAILED")
            return False
        
    except Exception as e:
        log_detail("❌", "Final verification error", str(e))
        logger.exception("Exception:")
        task.verification_result = f"Final verification error: {str(e)}"
        return False