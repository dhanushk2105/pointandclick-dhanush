import asyncio
import json
import uuid
from typing import Dict, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import logging

from .models import Task, ExecuteRequest
from .planner import create_plan, verify_completion

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Computer Use Agent API")

# Store active tasks and WebSocket connections
tasks: Dict[str, Task] = {}
active_connections: list[WebSocket] = []


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")
    
    async def send_action(self, websocket: WebSocket, action_id: str, action: str, payload: dict):
        message = {
            "id": action_id,
            "action": action,
            "payload": payload
        }
        await websocket.send_json(message)
        logger.info(f"Sent action: {action} with id: {action_id}")
    
    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)


manager = ConnectionManager()


@app.get("/")
async def root():
    return {
        "name": "Computer Use Agent API",
        "version": "1.0.0",
        "endpoints": {
            "POST /execute": "Execute a natural language task",
            "GET /status/{task_id}": "Check task status",
            "WS /ws": "WebSocket for browser communication"
        }
    }


@app.post("/execute")
async def execute_task(request: ExecuteRequest):
    """Execute a natural language task using LLM planning and browser automation."""
    
    # Create new task
    task_id = str(uuid.uuid4())
    task = Task(
        task_id=task_id,
        description=request.task,
        status="planning"
    )
    tasks[task_id] = task
    
    # Generate plan using LLM or mock
    try:
        logger.info(f"Creating plan for task: {request.task}")
        plan = await create_plan(
            task_description=request.task,
            api_key=request.api_key,
            provider=request.provider
        )
        
        task.plan = plan["steps"]
        task.status = "processing"
        
        # Start task execution in background
        asyncio.create_task(execute_plan(task_id))
        
        return JSONResponse(content={
            "task_id": task_id,
            "status": "processing",
            "plan_generated": True,
            "provider": plan.get("generated_by", "mock"),
            "steps_count": len(plan["steps"])
        })
        
    except Exception as e:
        logger.error(f"Failed to create plan: {str(e)}")
        task.status = "failed"
        task.verification_result = f"Planning failed: {str(e)}"
        
        return JSONResponse(
            status_code=500,
            content={
                "task_id": task_id,
                "status": "failed",
                "error": str(e)
            }
        )


@app.get("/status/{task_id}")
async def get_task_status(task_id: str):
    """Get the status of a running or completed task."""
    
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task = tasks[task_id]
    
    return {
        "task_id": task_id,
        "status": task.status,
        "steps_executed": task.steps_executed,
        "total_steps": len(task.plan),
        "verification": task.verification_result,
        "success": task.status == "completed",
        "description": task.description
    }


async def execute_plan(task_id: str):
    """Execute a task plan step by step through the browser."""
    
    task = tasks[task_id]
    
    if not manager.active_connections:
        task.status = "failed"
        task.verification_result = "No browser extension connected"
        logger.error("No WebSocket connections available")
        return
    
    websocket = manager.active_connections[0]  # Use first available connection
    
    try:
        # Execute each step in the plan
        for i, step in enumerate(task.plan):
            action_id = f"{task_id}_{i}"
            
            logger.info(f"Executing step {i+1}/{len(task.plan)}: {step['action']}")
            
            # Send action to browser
            await manager.send_action(
                websocket,
                action_id,
                step["action"],
                step.get("payload", {})
            )
            
            # Wait for response (with timeout)
            response = await wait_for_response(websocket, action_id, timeout=10)
            
            if response.get("status") != "success":
                raise Exception(f"Action failed: {response.get('error', 'Unknown error')}")
            
            task.steps_executed += 1
            
            # Small delay between actions
            await asyncio.sleep(0.5)
        
        # Verify task completion
        task.status = "verifying"
        
        # Query DOM for verification
        verify_id = f"{task_id}_verify"
        await manager.send_action(
            websocket,
            verify_id,
            "query",
            {"selector": "body", "limit": 1000}
        )
        
        verify_response = await wait_for_response(websocket, verify_id, timeout=5)
        dom_content = verify_response.get("data", "")
        
        # Use LLM to verify completion
        verification = await verify_completion(
            task_description=task.description,
            dom_content=dom_content,
            api_key=tasks[task_id].api_key if hasattr(tasks[task_id], 'api_key') else None,
            provider=tasks[task_id].provider if hasattr(tasks[task_id], 'provider') else "mock"
        )
        
        task.verification_result = verification["message"]
        task.status = "completed" if verification["success"] else "failed"
        
        logger.info(f"Task {task_id} completed with result: {task.verification_result}")
        
    except Exception as e:
        logger.error(f"Task execution failed: {str(e)}")
        task.status = "failed"
        task.verification_result = f"Execution failed: {str(e)}"


async def wait_for_response(websocket: WebSocket, action_id: str, timeout: int = 10):
    """Wait for a response from the browser for a specific action."""
    
    start_time = asyncio.get_event_loop().time()
    
    while asyncio.get_event_loop().time() - start_time < timeout:
        try:
            # Set a short timeout for receiving messages
            message = await asyncio.wait_for(websocket.receive_json(), timeout=0.1)
            
            if message.get("id") == action_id:
                return message
                
        except asyncio.TimeoutError:
            continue
        except Exception as e:
            logger.error(f"Error receiving message: {e}")
            break
    
    raise TimeoutError(f"No response received for action {action_id} within {timeout} seconds")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for browser extension communication."""
    
    await manager.connect(websocket)
    
    try:
        while True:
            # Keep connection alive with ping/pong
            await websocket.send_json({"type": "ping"})
            
            # Wait for messages
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                message = json.loads(data)
                
                logger.info(f"Received WebSocket message: {message.get('type', 'unknown')}")
                
                # Handle pong responses
                if message.get("type") == "pong":
                    continue
                    
            except asyncio.TimeoutError:
                continue
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)