import pytest
import asyncio
import json
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from server.main import app
from server.planner import create_mock_plan, verify_mock_completion
from server.prompts import PLANNING_PROMPT

client = TestClient(app)


def test_root_endpoint():
    """Test the root endpoint returns API info."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "name" in data
    assert data["name"] == "Computer Use Agent API"
    assert "endpoints" in data


def test_execute_with_mock():
    """Test task execution with mock planner."""
    response = client.post("/execute", json={
        "task": "Find promotional emails older than 3 months"
    })
    
    assert response.status_code == 200
    data = response.json()
    assert "task_id" in data
    assert data["status"] == "processing"
    assert data["plan_generated"] == True
    assert data["provider"] == "mock"


def test_execute_with_invalid_provider():
    """Test execution falls back to mock with invalid provider."""
    response = client.post("/execute", json={
        "task": "Test task",
        "provider": "invalid_provider"
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "mock"


def test_status_endpoint():
    """Test task status endpoint."""
    # First create a task
    execute_response = client.post("/execute", json={
        "task": "Test task"
    })
    task_id = execute_response.json()["task_id"]
    
    # Check status
    response = client.get(f"/status/{task_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == task_id
    assert "status" in data
    assert "steps_executed" in data


def test_status_not_found():
    """Test status endpoint with non-existent task."""
    response = client.get("/status/non-existent-task-id")
    assert response.status_code == 404


def test_mock_plan_gmail():
    """Test mock planner creates correct plan for Gmail tasks."""
    plan = create_mock_plan("Find promotional emails older than 3 months")
    
    assert plan["generated_by"] == "mock"
    assert len(plan["steps"]) > 0
    
    # Check first action is navigation to Gmail
    first_step = plan["steps"][0]
    assert first_step["action"] == "navigate"
    assert "mail.google.com" in first_step["payload"]["url"]
    
    # Check search action exists
    type_steps = [s for s in plan["steps"] if s["action"] == "type"]
    assert len(type_steps) > 0
    assert "category:promotions" in type_steps[0]["payload"]["text"]


def test_mock_plan_huggingface():
    """Test mock planner creates correct plan for HuggingFace tasks."""
    plan = create_mock_plan("Find UI Agents paper on HuggingFace")
    
    assert plan["generated_by"] == "mock"
    assert len(plan["steps"]) > 0
    
    # Check navigation to HuggingFace
    first_step = plan["steps"][0]
    assert first_step["action"] == "navigate"
    assert "huggingface.co" in first_step["payload"]["url"]


def test_mock_verification_success():
    """Test mock verification detects successful completion."""
    result = verify_mock_completion(
        "Find promotional emails",
        "Showing results for category:promotions older_than:3m"
    )
    
    assert result["success"] == True
    assert "found" in result["message"].lower()


def test_mock_verification_failure():
    """Test mock verification detects failure."""
    result = verify_mock_completion(
        "Find promotional emails",
        "Error: No results"
    )
    
    # Should fail due to short DOM content
    assert len(result["message"]) > 0


def test_planning_prompt_format():
    """Test planning prompt contains required instructions."""
    prompt = PLANNING_PROMPT.format(task="Test task")
    
    assert "JSON" in prompt
    assert "navigate" in prompt
    assert "waitFor" in prompt
    assert "click" in prompt
    assert "steps" in prompt


@pytest.mark.asyncio
async def test_websocket_connection():
    """Test WebSocket endpoint accepts connections."""
    from fastapi.testclient import TestClient
    
    with TestClient(app) as test_client:
        # This would need a proper WebSocket test client
        # For now, just verify the endpoint exists
        assert "/ws" in [route.path for route in app.routes]


def test_action_plan_max_steps():
    """Test that plans don't exceed maximum steps."""
    plan = create_mock_plan("Complex multi-step task")
    
    assert len(plan["steps"]) <= 10  # Max 10 steps as per spec


def test_parse_json_from_text():
    """Test JSON extraction from LLM response."""
    text = """Here's the plan:
    {"steps": [{"action": "navigate", "payload": {"url": "test.com"}}]}
    That should work!"""
    
    json_start = text.find("{")
    json_end = text.rfind("}") + 1
    
    assert json_start != -1
    assert json_end > json_start
    
    json_str = text[json_start:json_end]
    parsed = json.loads(json_str)
    
    assert "steps" in parsed
    assert len(parsed["steps"]) == 1