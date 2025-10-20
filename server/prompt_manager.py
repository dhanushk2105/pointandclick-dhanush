"""
Centralized prompt management with templating and validation.
"""

from typing import Any, Dict, Optional
from dataclasses import dataclass
from enum import Enum


class PromptType(Enum):
    """Types of prompts available."""
    NEXT_ACTION = "next_action"
    ACTION_VERIFICATION = "action_verification"
    FINAL_VERIFICATION = "final_verification"


@dataclass
class PromptTemplate:
    """Structured prompt template with metadata."""
    name: str
    system_message: str
    user_template: str
    required_vars: set
    response_format: Dict[str, Any]
    temperature: float = 0.1
    max_tokens: Optional[int] = None


class PromptManager:
    """Manages prompt templates with validation and rendering."""
    
    def __init__(self):
        self.templates: Dict[PromptType, PromptTemplate] = {
            PromptType.NEXT_ACTION: self._create_next_action_template(),
            PromptType.ACTION_VERIFICATION: self._create_verification_template(),
            PromptType.FINAL_VERIFICATION: self._create_final_verification_template(),
        }
    
    def render(self, prompt_type: PromptType, **kwargs) -> Dict[str, Any]:
        """
        Render a prompt with variables, returning full LLM request config.
        
        Args:
            prompt_type: Type of prompt to render
            **kwargs: Variables to substitute in template
            
        Returns:
            Dict with 'messages', 'temperature', 'response_format', etc.
        """
        template = self.templates[prompt_type]
        
        # Validate required variables
        missing = template.required_vars - set(kwargs.keys())
        if missing:
            raise ValueError(f"Missing required variables for {prompt_type}: {missing}")
        
        # Sanitize inputs
        safe_kwargs = {k: self._sanitize(v) for k, v in kwargs.items()}
        
        # Render template
        user_content = template.user_template.format(**safe_kwargs)
        
        config = {
            "messages": [
                {"role": "system", "content": template.system_message},
                {"role": "user", "content": user_content}
            ],
            "temperature": template.temperature,
            "response_format": template.response_format,
        }
        
        if template.max_tokens:
            config["max_tokens"] = template.max_tokens
        
        return config
    
    def _sanitize(self, value: Any) -> str:
        """Sanitize input values to prevent injection and handle None."""
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            import json
            return json.dumps(value, ensure_ascii=False, indent=2)
        
        text = str(value)
        # Truncate very long inputs
        if len(text) > 10000:
            text = text[:10000] + "\n... (truncated)"
        return text
    
    def _create_next_action_template(self) -> PromptTemplate:
        """Create next action planning template."""
        return PromptTemplate(
            name="next_action",
            system_message=(
                "You are a pragmatic browser agent. Plan ONE next step like a thoughtful human would. "
                "Always respond with valid JSON."
            ),
            user_template="""You are a pragmatic browser agent. Plan ONE next step like a thoughtful human would.

GOAL: {task}

PAGE (ground truth only—do not assume beyond this):
{page_state}

HISTORY (recent actions & outcomes):
{history}

First, ask: "Is the job already done?"
- If YES → Return exactly: {{"task_complete": true, "reasoning": "<why, citing concrete on-page cues>"}}

If NO, choose the BEST single next step. Behave like a cautious human:
- Prefer stable selectors: id > name > role/aria-label > explicit CSS selector. Use visible text only if nothing else is reliable.
- If a form has a submit button, click it (do NOT press Enter unless no obvious submit control).
- Handle real-web hiccups before the main action:
  • Cookie/consent banners → dismiss if they block interaction.
  • Spinners/"loading…" → wait briefly, then re-check the target.
  • Modals/popovers covering the target → close first.
  • Infinite lists → scroll just enough to reveal the target, then act.
  • Bad nav (404, hard redirect to login) → do NOT continue blindly; pick a safer step or stop next turn.
  • Rate-limits/captchas → STOP and report (do not attempt to bypass).
- When searching: type into the site's search field, then click the site's search/submit button (avoid Enter unless no button).
- For downloads/uploads: use dedicated actions, not clicks, when you already have a direct URL or file input selector.
- Never enter secrets/credentials unless they explicitly appear in PAGE or HISTORY as provided inputs.
- Avoid destructive actions (delete/purchase/submit forms with irreversible effects) unless the GOAL explicitly requests it.

AVAILABLE ACTIONS (return ONE):
1) {{"action":"navigate","payload":{{"url":"https://example.com"}}}}
2) {{"action":"smartClick","payload":{{"selector":"#id"}}}}  or  {{"action":"smartClick","payload":{{"text":"Submit"}}}}
3) {{"action":"smartType","payload":{{"selector":"input[name='q']","text":"search query"}}}}
4) {{"action":"press","payload":{{"key":"Enter"}}}}  (only if no submit control exists)
5) {{"action":"download","payload":{{"url":"https://example.com/file.pdf"}}}}
6) {{"action":"uploadFile","payload":{{"selector":"input[type='file']","filepath":"/path/to/file"}}}}

Decision procedure (think, then act):
1) Extract the immediate intent from GOAL (what should be visible/changed after the next step?).
2) From PAGE, locate the most reliable target element (favor id/name/role/aria; fall back to text only if necessary).
3) If a blocker is present (cookie banner/modal/spinner), handle that FIRST as the one action.
4) Choose the least-surprising, low-risk step that clearly progresses toward the goal.
5) State what you expect to see right after this step (URL/Title/DOM changes).

Return JSON with ONE of:
- {{"task_complete": true, "reasoning": "<why>"}}
- {{"action": "...", "payload": {{}}, "reasoning": "<plain, human explanation>", "expected_outcome": "<what should appear/change>", "task_complete": false}}

If the page is blank or unsupported (empty URL/title), start by navigating to a sensible entry point for the GOAL.

Respond with VALID JSON ONLY.
""",
            required_vars={"task", "page_state", "history"},
            response_format={"type": "json_object"},
            max_tokens=500,
        )
    
    def _create_verification_template(self) -> PromptTemplate:
        """Create action verification template."""
        return PromptTemplate(
            name="action_verification",
            system_message=(
                "You verify if browser actions succeeded. Always respond with valid JSON containing "
                "'success' (boolean), 'confidence' (0.0-1.0), and 'message' (string)."
            ),
            user_template="""You are a careful human QA validating the LAST ACTION against the EXPECTED outcome.

ACTION: {action}
EXPECTED: {expected}

PAGE STATE (evidence only—do not assume beyond this):
{page_state}

How to verify like a human:
1) Identify what SUCCESS would look like on-screen for this ACTION (navigation, click, type, press, etc.).
2) Look for concrete cues in PAGE STATE (URL, Title, DOM text/attributes) that confirm or contradict EXPECTED.
   - Navigation: URL/Title change, relevant path/query, main heading consistent with target page.
   - Click: target element missing/hidden after click; dialog/banner closed; section expanded.
   - Type: input/textarea value reflects EXPECTED; field is focused.
   - Press/Submit: presence of results, toasts/alerts, form validation messages, or route change.
3) Tolerate small variations (punctuation/case), SPA delays, but do NOT infer success without explicit cues.
4) If outcome is partial, mark success=false and explain briefly what worked.
5) Confidence rubric (be conservative):
   - 0.95–1.00: Multiple independent cues strongly confirm EXPECTED.
   - 0.75–0.90: One strong cue + one weak cue.
   - 0.40–0.70: Ambiguous/partial evidence.
   - 0.00–0.30: Clear failure or contradicting evidence.

Return STRICT JSON only:
{{
   "success": true|false,
   "confidence": <float 0.0–1.0>,
   "message": "<≤240 chars; cite 2–3 specific cues from PAGE STATE>"
}}

Write the message like a human note, referencing short evidence snippets.
""",
            required_vars={"action", "expected", "page_state"},
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=300,
        )
    
    def _create_final_verification_template(self) -> PromptTemplate:
        """Create final task verification template."""
        return PromptTemplate(
            name="final_verification",
            system_message=(
                "You verify if browser tasks are complete. Always respond with valid JSON containing "
                "'success' (boolean), 'confidence' (0.0-1.0), and 'message' (string)."
            ),
            user_template="""You are a meticulous human double-checking whether the GOAL was actually accomplished.
Use ONLY the evidence provided (URL, Title, DOM). Do not invent or assume anything beyond it.

GOAL: {task}

FINAL STATE:
- URL: {url}
- Title: {title}
- DOM: {dom}

How to judge like a careful human:
1) Extract the essential intent from the GOAL (what outcome would a person expect on-screen?).
2) Look for AT LEAST ONE CLEAR on-screen confirmation of success in the DOM. Prefer multiple independent signals.
3) Cross-check the URL and Title for alignment (keywords, query params, page type).
4) Actively scan for negative states: empty/zero results, "no results", "not found", "access denied", errors, spinners with no content.
5) If the GOAL mentions recency or dates, look for timestamps/dates in DOM.
6) If the GOAL is about finding a specific entity, check keyword overlap in DOM text.
7) If evidence is mixed, it can still be success with LOWER confidence—explain why.

Confidence mapping (be conservative):
- 0.95–1.00: Multiple independent signals agree.
- 0.75–0.90: One strong signal + one weak signal.
- 0.40–0.70: Partial/ambiguous signals.
- 0.00–0.30: Clear failure or contradicting evidence.

Return STRICT JSON:
{{
  "success": true|false,
  "confidence": <float 0.0–1.0>,
  "message": "<single concise rationale citing concrete cues from URL/Title/DOM>"
}}

Keep message under 240 characters, referencing 2-3 specific evidence snippets.
""",
            required_vars={"task", "url", "title", "dom"},
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=500,
        )


# Singleton instance
prompt_manager = PromptManager()