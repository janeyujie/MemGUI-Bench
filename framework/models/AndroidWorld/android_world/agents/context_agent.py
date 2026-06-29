"""Execution context agent for maintaining structured GUI task progress."""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from openai import OpenAI


logger = logging.getLogger(__name__)


def _pil_to_base64(image: Any) -> str:
    """Encodes a PIL image to a base64 PNG string."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _ensure_text(value: Any, default: str = "") -> str:
    """Normalize arbitrary values into concise strings."""
    if value is None:
        return default
    if isinstance(value, str):
        text = value.strip()
    else:
        text = str(value).strip()
    return text or default


def _ensure_list(value: Any) -> List[str]:
    """Normalize arbitrary values into a de-duplicated list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    else:
        items = [value]

    normalized: List[str] = []
    seen: set[str] = set()
    for item in items:
        text = _ensure_text(item)
        if text and text not in seen:
            normalized.append(text)
            seen.add(text)
    return normalized


def _merge_unique(primary: List[str], fallback: List[str]) -> List[str]:
    """Merge two string lists while preserving order."""
    merged: List[str] = []
    seen: set[str] = set()
    for collection in (primary, fallback):
        for item in collection:
            if item and item not in seen:
                merged.append(item)
                seen.add(item)
    return merged


@dataclass
class ExecutionContext:
    """Structured working memory injected into the actor prompt."""

    task_summary: str = ""
    task_decomposition: List[str] = field(default_factory=list)
    completed_progress: List[str] = field(default_factory=list)
    current_subgoal: str = ""
    remaining_requirements: List[str] = field(default_factory=list)
    last_step_result: str = ""
    next_action_focus: str = ""
    action_effective: Optional[bool] = None

    @classmethod
    def from_raw(cls, raw: Optional[Dict[str, Any] | str]) -> "ExecutionContext":
        """Parse an execution context from raw dict/JSON payload."""
        if raw is None:
            return cls()
        if isinstance(raw, str):
            raw = json.loads(raw)

        task_summary = _ensure_text(raw.get("task_summary") or raw.get("context_summary"))
        remaining_requirements = _ensure_list(raw.get("remaining_requirements"))
        current_subgoal = _ensure_text(raw.get("current_subgoal"))
        if not current_subgoal and remaining_requirements:
            current_subgoal = remaining_requirements[0]

        action_effective = raw.get("action_effective")
        if isinstance(action_effective, str):
            lowered = action_effective.strip().lower()
            if lowered in {"true", "yes"}:
                action_effective = True
            elif lowered in {"false", "no"}:
                action_effective = False
            else:
                action_effective = None
        elif action_effective is not None:
            action_effective = bool(action_effective)

        return cls(
            task_summary=task_summary,
            task_decomposition=_ensure_list(raw.get("task_decomposition")),
            completed_progress=_ensure_list(raw.get("completed_progress")),
            current_subgoal=current_subgoal,
            remaining_requirements=remaining_requirements,
            last_step_result=_ensure_text(raw.get("last_step_result")),
            next_action_focus=_ensure_text(raw.get("next_action_focus")),
            action_effective=action_effective,
        )

    @property
    def context_summary(self) -> str:
        """Compatibility alias for older monitor code paths."""
        return self.task_summary

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to plain dict."""
        return asdict(self)

    def to_prompt_injection(self, mode: str = "full") -> str:
        """Render the execution context into prompt text."""
        return format_execution_context(self, mode=mode)

    def to_prompt_injection_for_mode(self, mode: str = "full") -> str:
        """Render the execution context into prompt text for a context mode."""
        return self.to_prompt_injection(mode=mode)


def format_execution_context(
    execution_context: ExecutionContext | Dict[str, Any] | None,
    mode: str = "full",
) -> str:
    """Format execution context into a stable text block for actor injection."""
    context = (
        execution_context
        if isinstance(execution_context, ExecutionContext)
        else ExecutionContext.from_raw(execution_context)
    )
    normalized_mode = _normalize_context_mode(mode)

    sections: List[str] = []
    if normalized_mode in {"three_field", "four_field"}:
        completed_progress = context.completed_progress or ["[No confirmed progress yet]"]
        sections.append(
            "Completed Progress:\n" + "\n".join(f"- {item}" for item in completed_progress)
        )

        sections.append(f"Current Subgoal:\n{context.current_subgoal or '[Not set]'}")

        remaining = context.remaining_requirements or ["[No explicit remaining requirements]"]
        sections.append(
            "Remaining Requirements:\n" + "\n".join(f"- {item}" for item in remaining)
        )
        if normalized_mode == "four_field":
            sections.append(f"Next Action Focus:\n{context.next_action_focus or '[Not set]'}")
        return "\n\n".join(sections)

    if normalized_mode != "without_task_summary":
        sections.append(f"Task Summary:\n{context.task_summary or '[No summary yet]'}")

    task_decomposition = context.task_decomposition or ["[No decomposition yet]"]
    sections.append(
        "Task Decomposition:\n" + "\n".join(f"- {item}" for item in task_decomposition)
    )

    completed_progress = context.completed_progress or ["[No confirmed progress yet]"]
    sections.append(
        "Completed Progress:\n" + "\n".join(f"- {item}" for item in completed_progress)
    )

    sections.append(f"Current Subgoal:\n{context.current_subgoal or '[Not set]'}")

    remaining = context.remaining_requirements or ["[No explicit remaining requirements]"]
    sections.append("Remaining Requirements:\n" + "\n".join(f"- {item}" for item in remaining))

    if normalized_mode == "without_verifier":
        return "\n\n".join(sections)

    step_effect = (
        "effective"
        if context.action_effective is True
        else "ineffective"
        if context.action_effective is False
        else "uncertain"
    )
    sections.append(
        "Last Step Result:\n"
        f"- Effectiveness: {step_effect}\n"
        f"- Outcome: {context.last_step_result or '[No previous step result yet]'}"
    )

    sections.append(f"Next Action Focus:\n{context.next_action_focus or '[Not set]'}")
    return "\n\n".join(sections)


def _normalize_context_mode(mode: str | None) -> str:
    """Normalize supported context rendering modes."""
    normalized = _ensure_text(mode, "full").lower().replace("-", "_")
    if normalized in {"full", "complete"}:
        return "full"
    if normalized in {
        "three_field",
        "three_fields",
        "3field",
        "minimal",
        "ablation",
        "ablation_3field",
    }:
        return "three_field"
    if normalized in {
        "four_field",
        "four_fields",
        "4field",
        "ablation_4field",
        "three_field_plus_focus",
    }:
        return "four_field"
    if normalized in {
        "without_verifier",
        "no_verifier",
        "without_transition_assessment",
        "no_transition_assessment",
    }:
        return "without_verifier"
    if normalized in {
        "without_task_summary",
        "no_task_summary",
        "without_summary",
        "no_summary",
    }:
        return "without_task_summary"
    logger.warning("Unknown context_mode=%r; falling back to full context.", mode)
    return "full"


class ContextAgent:
    """LLM-based execution context manager for GUI actors."""

    def __init__(self, lm_config: Dict[str, Any], memory_config: Dict[str, Any] | None = None):
        """Initialize the context agent."""
        self.lm_config = lm_config
        self.memory_config = memory_config or {}

        self.client = OpenAI(
            api_key=lm_config.get("api_key"),
            base_url=lm_config.get("base_url"),
        )
        self.model = lm_config.get("model", "gpt-4")

        self.context = ExecutionContext()
        self.user_goal = ""

    def initialize(self, user_goal: str) -> Dict[str, Any]:
        """Initialize context for a new task."""
        self.user_goal = user_goal
        self.context = ExecutionContext(
            task_summary=f"Task started: {user_goal}",
            task_decomposition=[user_goal],
            completed_progress=[],
            current_subgoal=user_goal,
            remaining_requirements=[user_goal],
            last_step_result="No actions executed yet.",
            next_action_focus="Inspect the current screen and choose the first actionable step toward the goal.",
            action_effective=None,
        )
        logger.info("Execution context initialized for goal: %s", user_goal)
        return self.context.to_dict()

    def update_context(
        self,
        task: str,
        previous_thinking: str,
        previous_action: Dict[str, Any],
        observation_before: Dict[str, Any],
        observation_after: Dict[str, Any],
        previous_context: Optional[ExecutionContext | Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Update execution context using the latest transition."""
        current_context = (
            previous_context
            if isinstance(previous_context, ExecutionContext)
            else ExecutionContext.from_raw(previous_context)
        )
        if previous_context is None:
            current_context = self.context

        prompt = self._build_context_prompt(
            task=task,
            previous_thinking=previous_thinking,
            previous_action=previous_action,
            previous_context=current_context,
        )
        response = self._call_llm(prompt, observation_before, observation_after)
        updated_context = self._parse_response(
            response=response,
            fallback_context=current_context,
            task=task,
            previous_action=previous_action,
        )

        self.context = updated_context
        self.user_goal = task
        logger.debug("Execution context updated: %s...", updated_context.task_summary[:120])
        return updated_context.to_dict()

    def _build_context_prompt(
        self,
        task: str,
        previous_thinking: str,
        previous_action: Dict[str, Any],
        previous_context: ExecutionContext,
    ) -> str:
        """Build the structured update prompt."""
        action_desc = self._describe_action(previous_action)
        previous_context_json = json.dumps(
            previous_context.to_dict(), ensure_ascii=False, indent=2
        )

        return f"""You maintain structured execution context for a mobile GUI agent.

Task Goal:
{task}

Previous Execution Context (JSON):
{previous_context_json}

Last Step:
- Actor reasoning: {_ensure_text(previous_thinking, '[No reasoning provided]')[:400]}
- Action executed: {action_desc}
- Observation before action: screenshot provided separately if available
- Observation after action: screenshot provided separately if available

Your job:
1. Decide whether the last action made concrete progress toward the task.
2. Update the task decomposition when the task naturally breaks into smaller steps.
3. Preserve all valid completed progress from the previous context.
4. Update the current subgoal so the actor only needs to focus on the next stage.
5. Keep remaining requirements aligned with what still blocks completion.
6. Write a short next_action_focus that helps the actor choose only the next action.

Rules:
- Treat the previous execution context as persistent working memory.
- Do not invent hidden UI state. If the screenshots are insufficient, say the result is uncertain.
- Do not output stuck warnings, loop diagnostics, or hard override directives.
- Keep each list item concrete and task-relevant.
- Return JSON only.

Output JSON schema:
{{
  "action_effective": true,
  "task_summary": "high level cumulative summary",
  "task_decomposition": ["step 1", "step 2"],
  "completed_progress": ["confirmed progress item"],
  "current_subgoal": "single active subgoal",
  "remaining_requirements": ["what still needs to be done"],
  "last_step_result": "what changed after the action",
  "next_action_focus": "what the actor should pay attention to when deciding the next action"
}}"""

    def _call_llm(
        self,
        prompt: str,
        observation_before: Optional[Dict[str, Any]] = None,
        observation_after: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Call the LLM with prompt plus optional before/after screenshots."""
        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]

        before_image = self._build_image_payload(observation_before)
        if before_image is not None:
            content.extend(
                [
                    {"type": "text", "text": "Observation before action:"},
                    {"type": "image_url", "image_url": before_image},
                ]
            )

        after_image = self._build_image_payload(observation_after)
        if after_image is not None:
            content.extend(
                [
                    {"type": "text", "text": "Observation after action:"},
                    {"type": "image_url", "image_url": after_image},
                ]
            )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You maintain structured execution context for a mobile GUI actor. "
                            "Return strict JSON only."
                        ),
                    },
                    {"role": "user", "content": content},
                ],
                temperature=0.2,
                max_tokens=1024,
            )
            return response.choices[0].message.content or "{}"
        except Exception as exc:
            logger.error("Execution context LLM call failed: %s", exc)
            return "{}"

    def _parse_response(
        self,
        response: str,
        fallback_context: ExecutionContext,
        task: str,
        previous_action: Dict[str, Any],
    ) -> ExecutionContext:
        """Parse and normalize the LLM response."""
        raw_payload: Dict[str, Any] = {}
        json_match = re.search(r"\{.*\}", response, re.DOTALL)
        if json_match:
            try:
                raw_payload = json.loads(json_match.group())
            except json.JSONDecodeError as exc:
                logger.debug("Failed to decode execution context JSON: %s", exc)

        parsed = ExecutionContext.from_raw(raw_payload)

        parsed.task_decomposition = (
            _merge_unique(parsed.task_decomposition, fallback_context.task_decomposition)
            or [task]
        )
        parsed.completed_progress = _merge_unique(
            fallback_context.completed_progress,
            parsed.completed_progress,
        )

        if not parsed.task_summary:
            parsed.task_summary = fallback_context.task_summary or f"Working on task: {task}"
        if not parsed.current_subgoal:
            parsed.current_subgoal = (
                fallback_context.current_subgoal
                or (parsed.remaining_requirements[0] if parsed.remaining_requirements else task)
            )
        if not parsed.remaining_requirements:
            parsed.remaining_requirements = (
                fallback_context.remaining_requirements or [parsed.current_subgoal]
            )
        if not parsed.last_step_result:
            parsed.last_step_result = (
                f"Executed {self._describe_action(previous_action)}. Outcome could not be summarized reliably."
            )
        if not parsed.next_action_focus:
            parsed.next_action_focus = (
                "Use the latest screen to decide the next concrete action for the current subgoal."
            )
        if parsed.action_effective is None:
            parsed.action_effective = fallback_context.action_effective

        return parsed

    def _get_observation_screen(self, observation: Optional[Dict[str, Any]]) -> Any:
        """Prefer the raw screenshot for prompt attachments."""
        if not observation:
            return None
        return observation.get("screenshot_raw") or observation.get("screenshot")

    def _build_image_payload(
        self, observation: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, str]]:
        """Convert observation screenshot into OpenAI image payload."""
        screenshot = self._get_observation_screen(observation)
        if screenshot is None:
            return None
        if isinstance(screenshot, dict) and "url" in screenshot:
            return screenshot
        if isinstance(screenshot, str):
            return {"url": screenshot}
        if hasattr(screenshot, "save"):
            encoded_string = _pil_to_base64(screenshot)
            return {"url": f"data:image/png;base64,{encoded_string}"}
        return None

    def _describe_action(self, action: Dict[str, Any]) -> str:
        """Create a compact action description for prompt grounding."""
        action_type = action.get("action_type", "unknown")
        if action_type in ["click", "double_tap", "long_press"]:
            return f"{action_type}({action.get('x')}, {action.get('y')})"
        if action_type == "drag":
            return (
                f"drag(({action.get('start_x')}, {action.get('start_y')}) -> "
                f"({action.get('end_x')}, {action.get('end_y')}))"
            )
        if action_type == "scroll":
            return f"scroll(direction={action.get('direction')})"
        if action_type == "input_text":
            text = _ensure_text(action.get("text"))
            return f"input_text('{text[:60]}')"
        if action_type == "answer":
            text = _ensure_text(action.get("text"))
            return f"answer('{text[:60]}')"
        return action_type

    def reset(self) -> None:
        """Reset agent state."""
        self.context = ExecutionContext()
        self.user_goal = ""
