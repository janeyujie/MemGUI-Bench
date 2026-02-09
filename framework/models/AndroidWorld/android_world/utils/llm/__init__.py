# encoding: utf-8
"""
LLM utilities for AndroidWorld agent
"""

from .llm_api import (
    inference_chat_gemini_2_image,
    inference_chat_gemini_1_image,
    inference_chat_gemini_wo_image,
    inference_chat_gemini_multi_images,
    inference_chat_gemini_multiturn,
    extract_token_usage,
    calculate_api_cost,
)

from .llm_config import (
    DEFAULT_MODEL,
    DEFAULT_BASE_URL,
    DEFAULT_API_KEY,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    MODEL_PRICING,
    MODEL_CONFIGS,
    get_model_config,
)

from .auth_util import gen_sign_headers

__all__ = [
    # API functions
    "inference_chat_gemini_2_image",
    "inference_chat_gemini_1_image",
    "inference_chat_gemini_wo_image",
    "inference_chat_gemini_multi_images",
    "inference_chat_gemini_multiturn",
    "extract_token_usage",
    "calculate_api_cost",
    # Config
    "DEFAULT_MODEL",
    "DEFAULT_BASE_URL",
    "DEFAULT_API_KEY",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_RETRY_DELAY",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_TEMPERATURE",
    "MODEL_PRICING",
    "MODEL_CONFIGS",
    "get_model_config",
    # Auth
    "gen_sign_headers",
]

