PLANNING_PROMPT = """Create a browser automation plan for this task: {task}

Generate a JSON object with a "steps" array containing actions to complete this task.
Each step should have an "action" and optional "payload".

Available actions:
- navigate: Go to a URL (payload: {{"url": "..."}})
- waitFor: Wait for element (payload: {{"selector": "CSS selector", "timeout": ms}})
- click: Click element (payload: {{"selector": "CSS selector"}})
- type: Type text (payload: {{"selector": "CSS selector", "text": "..."}})
- press: Press key (payload: {{"key": "Enter"}})
- query: Get DOM text (payload: {{"selector": "CSS selector", "limit": chars}})

Example response:
{{
  "steps": [
    {{"action": "navigate", "payload": {{"url": "https://example.com"}}}},
    {{"action": "waitFor", "payload": {{"selector": "input[name='search']"}}}},
    {{"action": "type", "payload": {{"selector": "input[name='search']", "text": "query"}}}},
    {{"action": "press", "payload": {{"key": "Enter"}}}}
  ]
}}

Generate a precise plan with proper selectors. Respond ONLY with valid JSON."""

VERIFICATION_PROMPT = """Task: {task}

Current page content (partial):
{dom}

Based on the DOM content above, has the task been completed successfully?
Respond with a brief assessment of whether the task succeeded.
Include words like "success" or "completed" if the task was achieved."""