"""General E2E agent adapted for AndroidWorld and MemGUI-Bench via shared core."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from openai import OpenAI
from PIL import Image

_PATH_CANDIDATES = (
    Path(__file__).resolve().parents[5],
    Path(__file__).resolve().parents[6],
)
for _candidate in _PATH_CANDIDATES:
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from android_world.agents import base_agent
from android_world.env import interface
from android_world.env import json_action
from general_e2e_agent.adapters import memgui as memgui_adapter
from general_e2e_agent.core.context_agent import ContextAgent
from general_e2e_agent.core.context_agent import ExecutionContext
from general_e2e_agent.core.engine import GeneralE2ECore
from general_e2e_agent.core.model_client import ResponseObjectChatBackend
from general_e2e_agent.core.parser import parse_json_markdown
from general_e2e_agent.core.parser import parse_response_to_unified_action
from general_e2e_agent.core.parser import parse_thought_action
from general_e2e_agent.core.types import GeneralE2EConfig
from general_e2e_agent.core.types import UnifiedObservation

CLAUDE_IMAGE_SIZE = (1280, 720)


def parse_action(plan_output: str) -> tuple[str, str]:
    return parse_thought_action(plan_output)


def parse_response_to_action(
    action_str: str,
    image_width: int,
    image_height: int,
    scale_factor: int | tuple[int, int] = 1000,
) -> dict[str, Any]:
    action = parse_response_to_unified_action(
        action_str,
        image_width,
        image_height,
        scale_factor,
    )
    return memgui_adapter.unified_action_to_memgui_actor_dict(action)


def convert_action_to_env_action(
    action_payload: dict[str, Any],
    actor_action: dict[str, Any],
) -> json_action.JSONAction:
    del action_payload
    return json_action.JSONAction(**memgui_adapter.actor_action_to_memgui_env_dict(actor_action))


class GeneralE2E(base_agent.EnvironmentInteractingAgent):
    """MemGUI-compatible port backed by the shared general_e2e core."""

    def __init__(
        self,
        env: interface.AsyncEnv,
        config: dict[str, Any],
        name: str = "GeneralE2E",
    ):
        super().__init__(env, name)

        base_url = config.get("GENERAL_E2E_BASE_URL") or config.get("BASE_URL")
        api_key = config.get("GENERAL_E2E_API_KEY") or config.get("OPENAI_API_KEY")
        model_name = config.get("GENERAL_E2E_MODEL")

        if not base_url:
            raise ValueError("GENERAL_E2E_BASE_URL or BASE_URL is required in config")
        if not api_key:
            raise ValueError(
                "GENERAL_E2E_API_KEY or OPENAI_API_KEY is required in config"
            )
        if not model_name:
            raise ValueError("GENERAL_E2E_MODEL is required in config")

        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model_name = model_name
        self.base_url = base_url
        self.api_key = api_key
        self.enable_monitor = str(
            config.get("GENERAL_E2E_ENABLE_MONITOR", False)
        ).lower() in {"1", "true", "yes", "on"}
        self.context_mode = str(config.get("GENERAL_E2E_CONTEXT_MODE", "full"))
        self.detailed_model_logs: list[dict[str, Any]] = []
        self.history: list[dict[str, Any]] = []

        scale_factor: int | tuple[int, int] = 1000
        if "claude" in self.model_name.lower():
            scale_factor = CLAUDE_IMAGE_SIZE
        elif "k2.5" in self.model_name.lower():
            scale_factor = 1

        self.context_agent = None
        if self.enable_monitor:
            lm_config = {
                "api_key": self.api_key,
                "base_url": self.base_url,
                "model": self.model_name,
            }
            self.context_agent = ContextAgent(lm_config)

        cfg = GeneralE2EConfig(
            model_name=self.model_name,
            temperature=float(config.get("GENERAL_E2E_TEMPERATURE", 0.0)),
            max_tokens=int(config.get("GENERAL_E2E_MAX_TOKENS", 2048)),
            history_n_images=int(config.get("GENERAL_E2E_HISTORY_N", 3)),
            scale_factor=scale_factor,
            enable_context=self.enable_monitor,
            context_mode=self.context_mode,
        )
        self._core = GeneralE2ECore(
            ResponseObjectChatBackend(
                self.client.chat.completions.create,
                model_name=self.model_name,
            ),
            cfg,
            memgui_adapter.CAPABILITIES,
            context_agent=self.context_agent,
            context_cls=ExecutionContext,
            context_observation_builder=lambda observation: {
                "screenshot": observation.screenshot,
                "screenshot_raw": observation.screenshot,
            },
        )

    @property
    def history_images(self):
        return self._core.history_images

    @property
    def history_responses(self):
        return self._core.history_responses

    @property
    def actions(self):
        return self._core.actions

    @property
    def execution_context(self):
        return self._core.execution_context

    @property
    def monitor_feedback(self):
        return self._core.monitor_feedback

    @property
    def total_prompt_tokens(self):
        return self._core.total_prompt_tokens

    @property
    def total_completion_tokens(self):
        return self._core.total_completion_tokens

    def reset(self, go_home_on_reset: bool = False):
        super().reset(go_home=go_home_on_reset)
        self._core.reset()
        self.detailed_model_logs = []
        self.history = []

    def get_enhanced_log_data(self):
        metrics = self._core.get_metrics()
        return {
            "detailed_model_logs": self.detailed_model_logs,
            "total_prompt_tokens": metrics["prompt_tokens"],
            "total_completion_tokens": metrics["completion_tokens"],
            "total_model_calls": metrics["total_model_calls"],
        }

    def _action_to_dict(self, action: json_action.JSONAction) -> dict[str, Any]:
        parsed_action = {"action_type": action.action_type}
        if action.x is not None:
            parsed_action["x"] = action.x
        if action.y is not None:
            parsed_action["y"] = action.y
        if action.text is not None:
            parsed_action["text"] = action.text
        if action.direction is not None:
            parsed_action["direction"] = action.direction
        if action.goal_status is not None:
            parsed_action["goal_status"] = action.goal_status
        if action.app_name is not None:
            parsed_action["app_name"] = action.app_name
        if action.coordinate1 is not None:
            parsed_action["coordinate1"] = action.coordinate1
        if action.coordinate2 is not None:
            parsed_action["coordinate2"] = action.coordinate2
        return parsed_action

    def step(self, goal: str) -> base_agent.AgentInteractionResult:
        step_data = {
            "before_screenshot": None,
            "action_output": None,
            "raw_response": None,
            "thought": None,
            "raw_action": None,
            "actor_action": None,
        }

        state = self.get_post_transition_state()
        before_screenshot = state.pixels.copy()
        step_data["before_screenshot"] = before_screenshot
        screenshot = Image.fromarray(before_screenshot)

        try:
            prediction = self._core.predict(
                UnifiedObservation(
                    goal=goal,
                    screenshot=screenshot,
                    step_index=len(self.history),
                    env_name="memgui",
                )
            )
        except Exception as exc:
            step_data["raw_response"] = str(exc)
            step_data["parsed_action"] = {"action_type": "error", "error": str(exc)}
            step_data["action_summary"] = f"Model call failed: {str(exc)[:100]}"
            self.history.append(step_data)
            return base_agent.AgentInteractionResult(False, step_data)

        step_data["system_prompt"] = prediction.messages[0]["content"]
        step_data["messages"] = prediction.messages
        if self.enable_monitor:
            step_data["execution_context"] = self.execution_context.to_dict()
            step_data["monitor_feedback"] = self.monitor_feedback

        if prediction.prompt_tokens or prediction.completion_tokens:
            step_data["usage_raw"] = {
                "prompt_tokens": prediction.prompt_tokens,
                "completion_tokens": prediction.completion_tokens,
                "total_tokens": prediction.total_tokens,
            }

        step_data["action_output"] = prediction.raw_response
        step_data["raw_response"] = prediction.raw_response
        step_data["thought"] = prediction.thought
        step_data["raw_action"] = prediction.raw_action

        actor_action = memgui_adapter.unified_action_to_memgui_actor_dict(
            prediction.action
        )
        env_action = convert_action_to_env_action(
            prediction.action.as_dict(),
            actor_action,
        )
        parsed_action = self._action_to_dict(env_action)
        step_data["actor_action"] = actor_action
        step_data["parsed_action"] = parsed_action
        step_data["action_summary"] = env_action.action_type

        self.detailed_model_logs.append(
            {
                "step": len(self.history) + 1,
                "input_messages": prediction.messages,
                "model": self.model_name,
                "raw_response": prediction.raw_response,
                "parsed_action": parsed_action,
                "actor_action": actor_action,
                "success": True,
                "error": None,
                "prompt_tokens": prediction.prompt_tokens,
                "completion_tokens": prediction.completion_tokens,
                "total_tokens": prediction.total_tokens,
            }
        )

        if env_action.action_type == "status":
            self.history.append(step_data)
            return base_agent.AgentInteractionResult(True, step_data)

        try:
            actual_action_coordinates = self.env.execute_action(env_action)
            step_data["actual_action_coordinates"] = actual_action_coordinates
        except Exception as exc:
            step_data["action_summary"] = f"Failed to execute action: {exc}"
            self.history.append(step_data)
            return base_agent.AgentInteractionResult(False, step_data)

        self.history.append(step_data)
        return base_agent.AgentInteractionResult(False, step_data)
