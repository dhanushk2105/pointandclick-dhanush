"""
FastAPI application - routes and WebSocket endpoint only.
"""

import asyncio
import json
import uuid
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import logging

from .models import ExecuteRequest
from .task_manager import task_manager
from .websocket_manager import manager
from .execution_engine import execute_task_with_retry
from .utils import log_section, log_detail

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(title="Computer Use Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["chrome-extension://*", "http://localhost:*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """API information endpoint."""
    return {
        "name": "Computer Use Agent API",
        "version": "4.1.0",
        "status": "running",
        "active_tasks": task_manager.count_active_tasks(),
        "total_tasks": len(task_manager.get_all_tasks()),
        "architecture": "observe-plan-act-verify loop with structured outputs"
    }


@app.post("/execute")
async def execute_task(request: ExecuteRequest):
    """
    Start executing a new task.
    Creates a task and begins async execution.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return JSONResponse(
            status_code=400,
            content={"error": "OPENAI_API_KEY not found in environment"}
        )
    
    # Create task
    task_id = str(uuid.uuid4())
    task = task_manager.create_task(
        task_id=task_id,
        description=request.task,
        api_key=api_key
    )
    
    log_section(f"🆕 NEW TASK RECEIVED")
    log_detail("📋", "Task Description", request.task)
    log_detail("🆔", "Task ID", task_id)
    
    # Start execution asynchronously
    asyncio.create_task(execute_task_with_retry(task_id))
    
    return JSONResponse(content={
        "task_id": task_id,
        "status": "processing",
        "architecture": "reactive step-by-step with structured outputs"
    })


@app.get("/status/{task_id}")
async def get_task_status(task_id: str):
    """
    Get the current status of a task.
    """
    if not task_manager.task_exists(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    
    task = task_manager.get_task(task_id)
    
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


@app.delete("/task/{task_id}")
async def delete_task(task_id: str):
    """
    Delete a task.
    """
    if task_manager.delete_task(task_id):
        return {"message": "Task deleted", "task_id": task_id}
    else:
        raise HTTPException(status_code=404, detail="Task not found")


@app.post("/cleanup")
async def cleanup_tasks(keep_last_n: int = 100):
    """
    Clean up old completed/failed tasks.
    """
    removed = task_manager.cleanup_completed_tasks(keep_last_n)
    return {
        "message": f"Cleaned up {removed} old tasks",
        "remaining_tasks": len(task_manager.get_all_tasks())
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for browser extension communication.
    """
    await manager.connect(websocket)
    
    try:
        # Send initial ping
        await websocket.send_json({"type": "ping"})
        last_ping = asyncio.get_event_loop().time()
        
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=1)
                message = json.loads(data)
                
                # Handle pong
                if message.get("type") == "pong":
                    continue
                
                # Handle connection confirmation
                if message.get("type") == "connected":
                    log_detail("✅", "Extension ready and connected")
                    continue
                
                # Handle action responses
                if "id" in message and "status" in message:
                    manager.resolve_response(message["id"], message)
                
            except asyncio.TimeoutError:
                # Send periodic pings
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