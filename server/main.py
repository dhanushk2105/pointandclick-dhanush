import asyncio
import json
import uuid
import os
from typing import Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import logging

from .models import Task, ExecuteRequest
from .planner import (
    plan_next_action, 
    verify_action_success, 
    verify_final_completion
)
from .config import (
    MAX_RETRIES,
    MAX_STEPS,
    VERBOSE,
    ACTION_TIMEOUT_SECONDS,
    VERIFICATION_DELAY_SECONDS,
    PAGE_SETTLE_DELAY,
    RETRY_DELAY_SECONDS,
    DOM_CONTENT_LIMIT
)

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Computer Use Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["chrome-extension://*", "http://localhost:*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

tasks: Dict[str, Task] = {}


def log_section(title: str):
    if VERBOSE:
        logger.info(f"\n{'='*60}")
        logger.info(f"  {title}")
        logger.info(f"{'='*60}")


def log_detail(emoji: str, message: str, details: str = ""):
    if VERBOSE:
        logger.info(f"{emoji} {message}")
        if details:
            for line in details.split('\n'):
                if line.strip():
                    logger.info(f"  → {line.strip()}")


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.pending_responses: Dict[str, asyncio.Future] = {}
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        log_detail("✅", f"WebSocket connected", f"Total: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        log_detail("❌", f"WebSocket disconnected", f"Remaining: {len(self.active_connections)}")
    
    async def send_action(self, websocket: WebSocket, action_id: str, action: str, payload: dict):
        message = {"id": action_id, "action": action, "payload": payload}
        await websocket.send_json(message)
        log_detail("📤", f"Sent action: {action}", f"ID: {action_id}\nPayload: {json.dumps(payload, indent=2)}")
    
    def create_response_future(self, action_id: str) -> asyncio.Future:
        future = asyncio.Future()
        self.pending_responses[action_id] = future
        log_detail("⏳", f"Waiting for response", f"Action ID: {action_id}")
        return future
    
    def resolve_response(self, action_id: str, response: dict):
        if action_id in self.pending_responses:
            if not self.pending_responses[action_id].done():
                self.pending_responses[action_id].set_result(response)
                log_detail("📥", f"Received response", f"ID: {action_id}\nStatus: {response.get('status')}")
            del self.pending_responses[action_id]


manager = ConnectionManager()


@app.get("/")
async def root():
    return {
        "name": "Computer Use Agent API",
        "version": "4.0.0",
        "status": "running",
        "active_tasks": len(tasks),
        "architecture": "observe-plan-act-verify loop with structured outputs"
    }


@app.post("/execute")
async def execute_task(request: ExecuteRequest):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return JSONResponse(
            status_code=400,
            content={"error": "OPENAI_API_KEY not found in environment"}
        )
    
    task_id = str(uuid.uuid4())
    task = Task(
        task_id=task_id,
        description=request.task,
        status="planning",
        api_key=api_key
    )
    tasks[task_id] = task
    
    log_section(f"🆕 NEW TASK RECEIVED")
    log_detail("📋", "Task Description", request.task)
    log_detail("🆔", "Task ID", task_id)
    
    asyncio.create_task(execute_reactive_loop(task_id))
    
    return JSONResponse(content={
        "task_id": task_id,
        "status": "processing",
        "architecture": "reactive step-by-step with structured outputs"
    })


@app.get("/status/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task = tasks[task_id]
    
    return {
        "task_id": task_id,
        "status": task.status,
        "steps_executed": task.steps_executed,
        "total_steps": len(task.plan),
        "retry_count": task.retry_count,
        "verification": task.verification_result,
        "success": task.status == "completed",
        "description": task.description,
        "current_step": task.current_step,
        "logs": task.logs
    }


async def execute_reactive_loop(task_id: str):
    """Main execution loop with exponential backoff retry."""
    
    task = tasks[task_id]
    log_section("🔄 STARTING REACTIVE LOOP")
    
    for attempt in range(MAX_RETRIES):
        task.retry_count = attempt
        
        if attempt > 0:
            delay = RETRY_DELAY_SECONDS * (2 ** (attempt - 1))  # Exponential backoff
            log_detail("🔄", f"RETRY ATTEMPT {attempt + 1}", f"Waiting {delay}s before retry...")
            task.add_log("warning", f"Retry {attempt + 1}/{MAX_RETRIES}", 
                        f"Reason: {task.verification_result}")
            await asyncio.sleep(delay)
        
        try:
            success = await reactive_execution_loop(task_id)
            
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


async def reactive_execution_loop(task_id: str) -> bool:
    """Core reactive loop: observe → plan → act → verify"""
    
    task = tasks[task_id]
    step_count = 0
    
    while step_count < MAX_STEPS:
        step_count += 1
        log_section(f"🔍 REACTIVE STEP {step_count}")
        
        # STEP 1: OBSERVE
        log_detail("👀", "OBSERVING current page state...")
        page_state = await get_page_state(task_id)
        
        if "error" in page_state:
            log_detail("❌", "Failed to observe page", page_state["error"])
            task.verification_result = f"Cannot observe page: {page_state['error']}"
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
    
    task = tasks[task_id]
    
    if not manager.active_connections:
        log_detail("❌", "No browser connection")
        task.verification_result = "No browser extension connected"
        return False
    
    websocket = manager.active_connections[0]
    
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
        
        # Smart delays based on action type
        if action_step["action"] in ["navigate", "click", "smartClick"]:
            await asyncio.sleep(PAGE_SETTLE_DELAY)
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
    
    task = tasks[task_id]
    
    try:
        page_state = await get_page_state(task_id)
        
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
    
    task = tasks[task_id]
    task.status = "verifying"
    task.add_log("info", "Final verification", "Checking if goal achieved")
    
    log_section("🔎 FINAL VERIFICATION")
    
    try:
        page_state = await get_page_state(task_id)
        
        websocket = manager.active_connections[0]
        verify_id = f"{task_id}_final_verify"
        verify_future = manager.create_response_future(verify_id)
        
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


async def get_page_state(task_id: str) -> Dict:
    """Get current page state; degrade gracefully on observe errors."""
    if not manager.active_connections:
        return {"url": "", "title": "", "elements": [], "diagnostics": {"error": "No browser connection"}}

    ws = manager.active_connections[0]

    try:
        # page info
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

        # elements
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
        if info_err: diags["getPageInfo"] = info_err
        if elements_err: diags["getInteractiveElements"] = elements_err
        if diags: state["diagnostics"] = diags

        return state

    except Exception as e:
        return {"url": "", "title": "", "elements": [], "diagnostics": {"exception": str(e)}}



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


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    
    try:
        await websocket.send_json({"type": "ping"})
        last_ping = asyncio.get_event_loop().time()
        
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=1)
                message = json.loads(data)
                
                if message.get("type") == "pong":
                    continue
                
                if message.get("type") == "connected":
                    log_detail("✅", "Extension ready and connected")
                    continue
                
                if "id" in message and "status" in message:
                    manager.resolve_response(message["id"], message)
                
            except asyncio.TimeoutError:
                current_time = asyncio.get_event_loop().time()
                if current_time - last_ping > 30:
                    await websocket.send_json({"type": "ping"})
                    last_ping = current_time
                continue
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        log_detail("❌", "WebSocket error", str(e))
        manager.disconnect(websocket)