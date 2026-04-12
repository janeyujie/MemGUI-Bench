"""General E2E agent adapted for AndroidWorld and MemGUI-Bench."""

import base64
import io
import json
import re
from string import Template
from typing import Any, Callable

from openai import OpenAI
from PIL import Image

from android_world.agents import base_agent
from android_world.agents.retry_utils import RetryableAPIClient
from android_world.env import interface
from android_world.env import json_action


ACTION_ALIASES = {
    "click": ["tap", "press", "touch"],
    "long_press": ["long tap", "long press", "hold"],
    "input_text": ["type", "enter_text", "write", "enter"],
    "scroll": ["fling"],
    "keyboard_enter": ["enter"],
}

NORMALIZED_ACTION_MAP: dict[str, str] = {}
for standard_action, aliases in ACTION_ALIASES.items():
    NORMALIZED_ACTION_MAP[standard_action] = standard_action
    for alias in aliases:
        NORMALIZED_ACTION_MAP[alias.replace(" ", "_")] = standard_action
        NORMALIZED_ACTION_MAP[alias] = standard_action

CLAUDE_IMAGE_SIZE = (1280, 720)

SYSTEM_PROMPT_TEMPLATE = Template(
    """# Role: Android Phone Operator AI
You are an AI that controls an Android phone to complete user requests. Your responsibilities:
- Answer questions by retrieving information from the phone.
- Perform tasks by executing precise actions.

# Action Framework
Respond with EXACT JSON format for one of these actions:
| Action          | Description                              | JSON Format Example                                                         |
|-----------------|----------------------------------------- |-----------------------------------------------------------------------------|
| `click`         | Tap visible element (describe clearly)   | `{"action_type": "click", "coordinate": [x, y]}`   |
| `double_tap`    | Double-tap visible element (describe clearly)   | `{"action_type": "double_tap", "coordinate": [x, y]}`   |
| `long_press`    | Long-press visible element (describe clearly) | `{"action_type": "long_press", "coordinate": [x, y]}`            |
| `drag`          | Drag from visible element to another visible element (describe both clearly) | `{"action_type": "drag", "start_coordinate": [x1, y1], "end_coordinate": [x2, y2]}`            |
| `input_text`    | Type into field (this action only provides the text; the target field still needs to be active) | `{"action_type":"input_text", "text":"Hello"}` |
| `answer`        | Respond to user                          | `{"action_type":"answer", "text":"It's 25 degrees today."}`               |
| `navigate_home` | Return to home screen                    | `{"action_type": "navigate_home"}`                                        |
| `navigate_back` | Navigate back                            | `{"action_type": "navigate_back"}`                                        |
| `open_app`      | Open an app by name                      | `{"action_type":"open_app", "app_name":"Calendar"}`                       |
| `scroll`        | Scroll direction (up/down/left/right)    | `{"action_type":"scroll", "direction":"down"}`                            |
| `swipe`         | Swipe the whole screen in a direction     | `{"action_type":"swipe", "direction":"up"}`                               |
| `status`        | Mark task as `complete` or `infeasible`  | `{"action_type":"status", "goal_status":"complete"}`                      |
| `wait`          | Wait for screen to update                | `{"action_type":"wait"}`                                                  |
| `keyboard_enter`| Press enter key                          | `{"action_type":"keyboard_enter"}`                                        |

Note:
- The coordinate is the center of the element to be clicked/long-pressed/dragged.
- x, y are coordinates in the screen, the origin is the top-left corner of the screen.
- x, y are numbers, the range is normalized to [0, $scale_factor].

# Execution Principles
1. Communication Rule:
   - ALWAYS use 'answer' action to reply to users - never assume on-screen text is sufficient.
   - Please follow the user instruction strictly to answer the question, e.g., only return a single number, only return True/False, only return items separated by comma.
   - NEVER use 'answer' action to indicate waiting or loading - use 'wait' action instead.
   - Note that `answer` will terminate the task immediately.

2. Efficiency First:
   - Choose simplest path to complete tasks.
   - If action fails twice, try alternatives (e.g., long_press instead of click).

3. Smart Navigation:
   - Gather information when needed (e.g., open Calendar to check schedule).
   - For scrolling:
     * Scroll direction is INVERSE to swipe (scroll down to see lower content).
     * If scroll fails, try opposite direction.

4. Text Operations:
   - You MUST first click the input box to activate it before typing the text.
   - For text manipulation:
     1. Long-press to select
     2. Use selection bar options (Copy/Paste/Select All)
     3. Delete by selecting then cutting

# Decision Process
1. Analyze goal, history, and current screen.
2. Determine if the task is already complete (use `status` if true).
3. If not, choose the most appropriate action to complete the task.
4. Output in exact format below, and ensure the Action is a valid JSON string.

# Expected Output Format (`Thought: ` and `Action: ` are required):
Thought: [Analysis including reference to key steps or observations when applicable]
Action: [Single JSON action]

# Output Format Example
Thought: I need to type the search query into the active text box.
Action: {"action_type": "input_text", "text": "What is weather like in San Francisco today?"}

# User Goal
$goal"""
)


def _replace_new_line(match: re.Match[str]) -> str:
    value = match.group(2)
    value = re.sub(r"\n", r"\\n", value)
    value = re.sub(r"\r", r"\\r", value)
    value = re.sub(r"\t", r"\\t", value)
    value = re.sub(r'(?<!\\)"', r"\"", value)
    return match.group(1) + value + match.group(3)


def _custom_parser(multiline_string: str | bytes | bytearray) -> str:
    if isinstance(multiline_string, (bytes, bytearray)):
        multiline_string = multiline_string.decode()

    return re.sub(
        r'("action_input"\:\s*")(.*?)(")',
        _replace_new_line,
        multiline_string,
        flags=re.DOTALL,
    )


def parse_partial_json(s: str, *, strict: bool = False) -> Any:
    try:
        return json.loads(s, strict=strict)
    except json.JSONDecodeError:
        pass

    new_chars = []
    stack = []
    is_inside_string = False
    escaped = False

    for char in s:
        new_char = char
        if is_inside_string:
            if char == '"' and not escaped:
                is_inside_string = False
            elif char == "\n" and not escaped:
                new_char = "\\n"
            elif char == "\\":
                escaped = not escaped
            else:
                escaped = False
        elif char == '"':
            is_inside_string = True
            escaped = False
        elif char == "{":
            stack.append("}")
        elif char == "[":
            stack.append("]")
        elif char in {"}", "]"}:
            if stack and stack[-1] == char:
                stack.pop()
            else:
                return None

        new_chars.append(new_char)

    if is_inside_string:
        if escaped:
            new_chars.pop()
        new_chars.append('"')

    stack.reverse()
    while new_chars:
        try:
            return json.loads("".join(new_chars + stack), strict=strict)
        except json.JSONDecodeError:
            new_chars.pop()

    return json.loads(s, strict=strict)


_JSON_MARKDOWN_RE = re.compile(r"```(json)?(.*)", re.DOTALL)
_JSON_STRIP_CHARS = " \n\r\t`"


def _parse_json(json_str: str, *, parser: Callable[[str], Any] = parse_partial_json):
    json_str = json_str.strip(_JSON_STRIP_CHARS)
    json_str = _custom_parser(json_str)
    return parser(json_str)


def parse_json_markdown(
    json_string: str, *, parser: Callable[[str], Any] = parse_partial_json
) -> dict:
    try:
        return _parse_json(json_string, parser=parser)
    except json.JSONDecodeError:
        match = _JSON_MARKDOWN_RE.search(json_string)
        json_str = json_string if match is None else match.group(2)
    return _parse_json(json_str, parser=parser)


def normalize_action_type(action_type: str | None) -> str | None:
    if not action_type:
        return None
    processed_type = action_type.lower().strip().replace(" ", "_")
    return NORMALIZED_ACTION_MAP.get(processed_type, action_type)


def parse_action(plan_output: str) -> tuple[str, str]:
    match = re.search(
        r"Thought:\s*(.*?)\s*Action:\s*(.*)$",
        plan_output.strip(),
        re.DOTALL | re.IGNORECASE,
    )
    if not match:
        raise ValueError("Output must contain 'Thought:' followed by 'Action:'.")
    return match.group(1).strip(), match.group(2).strip()


def _pil_to_base64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _scale_to_absolute(
    value: int | float,
    image_size: int,
    scale_factor: int | tuple[int, int],
    index: int,
) -> int:
    if isinstance(scale_factor, int):
        base = scale_factor
    else:
        base = scale_factor[index]
    return int(float(value) * image_size / base)


def parse_response_to_action(
    action_str: str,
    image_width: int,
    image_height: int,
    scale_factor: int | tuple[int, int] = 1000,
) -> json_action.JSONAction:
    action_data = parse_json_markdown(action_str)
    if not isinstance(action_data, dict):
        raise ValueError("Action payload is not a JSON object.")

    original_action_type = action_data.get("action_type")
    action_type = normalize_action_type(original_action_type)
    if not action_type:
        raise ValueError("Action type is missing or empty.")

    if action_type in ["click", "double_tap", "long_press"]:
        coord = action_data.get("coordinate")
        if not isinstance(coord, list) or len(coord) != 2:
            raise ValueError(f"Missing or invalid coordinate for {action_type}")
        x = _scale_to_absolute(coord[0], image_width, scale_factor, 0)
        y = _scale_to_absolute(coord[1], image_height, scale_factor, 1)
        return json_action.JSONAction(action_type=action_type, x=x, y=y)

    if action_type == "drag":
        start_coord = action_data.get("start_coordinate")
        end_coord = action_data.get("end_coordinate")
        if not isinstance(start_coord, list) or len(start_coord) != 2:
            raise ValueError("Missing or invalid start_coordinate for drag")
        if not isinstance(end_coord, list) or len(end_coord) != 2:
            raise ValueError("Missing or invalid end_coordinate for drag")
        start_x = _scale_to_absolute(start_coord[0], image_width, scale_factor, 0)
        start_y = _scale_to_absolute(start_coord[1], image_height, scale_factor, 1)
        end_x = _scale_to_absolute(end_coord[0], image_width, scale_factor, 0)
        end_y = _scale_to_absolute(end_coord[1], image_height, scale_factor, 1)
        return json_action.JSONAction(
            action_type="drag",
            coordinate1=(start_x, start_y),
            coordinate2=(end_x, end_y),
        )

    if action_type == "input_text":
        return json_action.JSONAction(
            action_type="input_text",
            text=action_data.get("text", ""),
        )

    if action_type == "answer":
        return json_action.JSONAction(
            action_type="answer",
            text=action_data.get("text", ""),
        )

    if action_type == "open_app":
        return json_action.JSONAction(
            action_type="open_app",
            app_name=action_data.get("app_name") or action_data.get("text"),
        )

    if action_type == "navigate_home":
        return json_action.JSONAction(action_type="navigate_home")

    if action_type == "navigate_back":
        return json_action.JSONAction(action_type="navigate_back")

    if action_type == "keyboard_enter":
        return json_action.JSONAction(action_type="keyboard_enter")

    if action_type == "scroll":
        return json_action.JSONAction(
            action_type="scroll",
            direction=action_data.get("direction"),
        )

    if action_type == "swipe":
        swipe_kwargs: dict[str, Any] = {
            "action_type": "swipe",
            "direction": action_data.get("direction"),
        }
        if "coordinate" in action_data:
            coord = action_data.get("coordinate")
            if isinstance(coord, list) and len(coord) == 2:
                swipe_kwargs["x"] = _scale_to_absolute(
                    coord[0], image_width, scale_factor, 0
                )
                swipe_kwargs["y"] = _scale_to_absolute(
                    coord[1], image_height, scale_factor, 1
                )
        return json_action.JSONAction(**swipe_kwargs)

    if action_type == "wait":
        return json_action.JSONAction(action_type="wait")

    if action_type == "status":
        goal_status = action_data.get("goal_status", "")
        if goal_status == "failure":
            goal_status = "infeasible"
        if goal_status not in ["complete", "infeasible"]:
            goal_status = "complete"
        return json_action.JSONAction(
            action_type="status",
            goal_status=goal_status,
        )

    return json_action.JSONAction(action_type=action_type)


class GeneralE2E(base_agent.EnvironmentInteractingAgent):
    """AndroidWorld-compatible port of MobileWorld GeneralE2EAgentMCP."""

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

        raw_client = OpenAI(base_url=base_url, api_key=api_key)
        self.client = RetryableAPIClient(
            raw_client,
            max_retries=None,
            base_delay=2.0,
            max_delay=120.0,
            verbose=True,
        )

        self.model_name = model_name
        self.base_url = base_url
        self.api_key = api_key
        self.history_n_images = int(config.get("GENERAL_E2E_HISTORY_N", 3))
        self.temperature = float(config.get("GENERAL_E2E_TEMPERATURE", 0.0))
        self.max_tokens = int(config.get("GENERAL_E2E_MAX_TOKENS", 2048))

        self.scale_factor: int | tuple[int, int] = 1000
        if "claude" in self.model_name.lower():
            self.scale_factor = CLAUDE_IMAGE_SIZE
        if "k2.5" in self.model_name.lower():
            self.scale_factor = 1

        self.history = []
        self.history_images: list[Image.Image] = []
        self.history_responses: list[str] = []
        self.detailed_model_logs = []
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    def reset(self, go_home_on_reset: bool = False):
        super().reset(go_home=go_home_on_reset)
        self.history = []
        self.history_images = []
        self.history_responses = []
        self.detailed_model_logs = []
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    def get_enhanced_log_data(self):
        return {
            "detailed_model_logs": self.detailed_model_logs,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_model_calls": len(self.detailed_model_logs),
        }

    def _render_system_prompt(self, goal: str) -> str:
        scale = (
            self.scale_factor
            if isinstance(self.scale_factor, int)
            else self.scale_factor[0]
        )
        return SYSTEM_PROMPT_TEMPLATE.substitute(goal=goal, scale_factor=scale)

    def _build_messages(self, goal: str) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._render_system_prompt(goal)}
        ]

        hidden_cutoff = max(len(self.history_images) - self.history_n_images, 0)
        for idx, image in enumerate(self.history_images):
            if idx > 0:
                messages.append(
                    {"role": "assistant", "content": self.history_responses[idx - 1]}
                )

            if idx < hidden_cutoff:
                content = [
                    {"type": "text", "text": "(Previous turn, screen not shown)"}
                ]
            else:
                content = [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{_pil_to_base64(image)}"},
                    }
                ]
            messages.append({"role": "user", "content": content})

        return messages

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
        }

        state = self.get_post_transition_state()
        step_data["before_screenshot"] = state.pixels.copy()
        screenshot = Image.fromarray(state.pixels)
        if "claude" in self.model_name.lower():
            screenshot = screenshot.resize(CLAUDE_IMAGE_SIZE)
        self.history_images.append(screenshot)

        messages = self._build_messages(goal)
        step_data["system_prompt"] = messages[0]["content"]
        step_data["messages"] = messages

        model_log_entry = {
            "step": len(self.history) + 1,
            "timestamp": None,
            "input_messages": messages,
            "model": self.model_name,
            "raw_response": None,
            "parsed_action": None,
            "success": False,
            "error": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        try:
            response = self.client.create_chat_completion(
                model=self.model_name,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            response_str = response.choices[0].message.content or ""
            model_log_entry["raw_response"] = response_str

            if hasattr(response, "usage") and response.usage:
                usage = response.usage
                model_log_entry["prompt_tokens"] = getattr(usage, "prompt_tokens", 0)
                model_log_entry["completion_tokens"] = getattr(
                    usage, "completion_tokens", 0
                )
                model_log_entry["total_tokens"] = getattr(usage, "total_tokens", 0)
                try:
                    if hasattr(usage, "model_dump"):
                        step_data["usage_raw"] = usage.model_dump()
                    elif hasattr(usage, "dict"):
                        step_data["usage_raw"] = usage.dict()
                    elif hasattr(usage, "__dict__"):
                        step_data["usage_raw"] = dict(usage.__dict__)
                except Exception:
                    step_data["usage_raw"] = str(usage)

                self.total_prompt_tokens += model_log_entry["prompt_tokens"]
                self.total_completion_tokens += model_log_entry["completion_tokens"]
        except Exception as e:
            model_log_entry["error"] = str(e)
            self.detailed_model_logs.append(model_log_entry)
            step_data["raw_response"] = str(e)
            step_data["parsed_action"] = {"action_type": "error", "error": str(e)}
            step_data["action_summary"] = f"Model call failed: {str(e)[:100]}"
            self.history.append(step_data)
            self.history_images.pop()
            return base_agent.AgentInteractionResult(False, step_data)

        step_data["action_output"] = response_str
        step_data["raw_response"] = response_str

        try:
            thought, action_str = parse_action(response_str)
            step_data["thought"] = thought
            step_data["raw_action"] = action_str
            action = parse_response_to_action(
                action_str,
                state.pixels.shape[1],
                state.pixels.shape[0],
                self.scale_factor,
            )
        except Exception as e:
            model_log_entry["error"] = str(e)
            self.detailed_model_logs.append(model_log_entry)
            step_data["parsed_action"] = {}
            step_data["action_summary"] = f"Failed to parse action: {str(e)}"
            self.history.append(step_data)
            self.history_images.pop()
            return base_agent.AgentInteractionResult(False, step_data)

        parsed_action = self._action_to_dict(action)
        step_data["parsed_action"] = parsed_action
        step_data["action_summary"] = action.action_type
        model_log_entry["parsed_action"] = parsed_action
        model_log_entry["success"] = True
        self.detailed_model_logs.append(model_log_entry)
        self.history_responses.append(response_str)

        if action.action_type == "status":
            self.history.append(step_data)
            return base_agent.AgentInteractionResult(True, step_data)

        try:
            actual_action_coordinates = self.env.execute_action(action)
            step_data["actual_action_coordinates"] = actual_action_coordinates
        except Exception as e:
            step_data["action_summary"] = (
                f"Error executing {action.action_type}: {str(e)}"
            )
            self.history.append(step_data)
            return base_agent.AgentInteractionResult(False, step_data)

        self.history.append(step_data)
        return base_agent.AgentInteractionResult(False, step_data)
