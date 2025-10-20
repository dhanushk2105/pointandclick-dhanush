"""Task storage and management."""

from typing import Dict, Optional
from .models import Task


class TaskManager:
    """Manages task storage and retrieval."""
    
    def __init__(self):
        self.tasks: Dict[str, Task] = {}
    
    def create_task(self, task_id: str, description: str, api_key: str) -> Task:
        """Create a new task."""
        task = Task(
            task_id=task_id,
            description=description,
            status="planning",
            api_key=api_key
        )
        self.tasks[task_id] = task
        return task
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        return self.tasks.get(task_id)
    
    def task_exists(self, task_id: str) -> bool:
        """Check if a task exists."""
        return task_id in self.tasks
    
    def delete_task(self, task_id: str) -> bool:
        """Delete a task."""
        if task_id in self.tasks:
            del self.tasks[task_id]
            return True
        return False
    
    def get_all_tasks(self) -> Dict[str, Task]:
        """Get all tasks."""
        return self.tasks
    
    def count_active_tasks(self) -> int:
        """Count tasks that are currently active."""
        return sum(
            1 for task in self.tasks.values()
            if task.status in ["planning", "replanning", "processing", "verifying"]
        )
    
    def cleanup_completed_tasks(self, keep_last_n: int = 100) -> int:
        """
        Clean up old completed/failed tasks, keeping only the last N.
        Returns number of tasks removed.
        """
        completed = [
            (task_id, task) for task_id, task in self.tasks.items()
            if task.status in ["completed", "failed"]
        ]
        
        if len(completed) <= keep_last_n:
            return 0
        
        # Sort by last update time (you'd need to add this to Task model)
        # For now, just remove oldest by insertion order
        to_remove = len(completed) - keep_last_n
        removed = 0
        
        for task_id, _ in completed[:to_remove]:
            del self.tasks[task_id]
            removed += 1
        
        return removed


# Global task manager instance
task_manager = TaskManager()