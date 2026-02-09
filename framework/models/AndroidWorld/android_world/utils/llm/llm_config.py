# encoding: utf-8
"""
LLM API调用的配置文件
从config.yaml中读取模型配置，支持模式预设系统
"""

import os
import sys

# Add project root to path for config_loader import
# AndroidWorld is at framework/models/AndroidWorld, so we need to go up 5 levels
_project_root = os.path.join(os.path.dirname(__file__), "../../../../../..")
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

try:
    from config_loader import get_config
    
    # Use get_config() to get cached config with mode presets applied
    _config = get_config(verbose=False)
    
    # Agent API configuration from config.yaml
    AGENT_API_KEY = _config.get("QWEN_API_KEY")
    AGENT_BASE_URL = _config.get("BASE_URL")
    AGENT_MODEL = _config.get("QWEN_MODEL")
    
except Exception as e:
    # Fallback to environment variables if config loading fails
    print(f"Warning: Failed to load config.yaml, falling back to environment variables: {e}")
    AGENT_API_KEY = os.environ.get("QWEN_API_KEY")
    AGENT_BASE_URL = os.environ.get("BASE_URL", "https://openrouter.fans/v1")
    AGENT_MODEL = os.environ.get("QWEN_MODEL", "qwen/qwen3-vl-8b-instruct")

# Validate required configuration
if not AGENT_API_KEY:
    raise ValueError(
        "QWEN_API_KEY not found in config.yaml or environment variables. "
        "Please set it in config.yaml or as an environment variable."
    )

# Default values for backward compatibility
DEFAULT_MODEL = AGENT_MODEL or "qwen/qwen3-vl-8b-instruct"
DEFAULT_BASE_URL = AGENT_BASE_URL or "https://openrouter.fans/v1"
DEFAULT_API_KEY = AGENT_API_KEY
DEFAULT_MAX_RETRIES = 200
DEFAULT_RETRY_DELAY = 2
DEFAULT_MAX_TOKENS = 6500
DEFAULT_TEMPERATURE = 0.01

# Model pricing (USD per million tokens)
MODEL_PRICING = {
    "gemini-2.5-pro": {
        "input_price_per_million": 1.25,
        "output_price_per_million": 10.0,
    },
    "gemini-2.5-flash": {
        "input_price_per_million": 0.3,
        "output_price_per_million": 2.5,
    },
    "gemini-1.5-pro-001": {
        "input_price_per_million": 1.25,
        "output_price_per_million": 5.0,
    },
    "gemini-1.5-pro-002": {
        "input_price_per_million": 1.25,
        "output_price_per_million": 5.0,
    },
    "qwen-vl-max-2025-01-25": {
        "input_price_per_million": 2.0,
        "output_price_per_million": 6.0,
    },
    "qwen-vl-max-2024-12-30": {
        "input_price_per_million": 2.0,
        "output_price_per_million": 6.0,
    },
    "qwen/qwen3-vl-8b-instruct": {
        "input_price_per_million": 0.2,
        "output_price_per_million": 0.2,
    },
}

# Model configuration dictionary
MODEL_CONFIGS = {
    "default": {
        "model": DEFAULT_MODEL,
        "base_url": DEFAULT_BASE_URL,
        "api_key": DEFAULT_API_KEY,
        "max_tokens": DEFAULT_MAX_TOKENS,
        "temperature": DEFAULT_TEMPERATURE,
        "max_retries": DEFAULT_MAX_RETRIES,
        "retry_delay": DEFAULT_RETRY_DELAY,
    },
    "high_precision": {
        "model": DEFAULT_MODEL,
        "base_url": DEFAULT_BASE_URL,
        "api_key": DEFAULT_API_KEY,
        "max_tokens": DEFAULT_MAX_TOKENS,
        "temperature": 0.01,
        "max_retries": DEFAULT_MAX_RETRIES,
        "retry_delay": DEFAULT_RETRY_DELAY,
    },
    "high_creativity": {
        "model": DEFAULT_MODEL,
        "base_url": DEFAULT_BASE_URL,
        "api_key": DEFAULT_API_KEY,
        "max_tokens": DEFAULT_MAX_TOKENS,
        "temperature": 1.0,
        "max_retries": DEFAULT_MAX_RETRIES,
        "retry_delay": DEFAULT_RETRY_DELAY,
    },
}


def get_model_config(config_name="default"):
    """
    获取指定名称的模型配置

    Args:
        config_name: 配置名称，默认为"default"

    Returns:
        配置字典
    """
    return MODEL_CONFIGS.get(config_name, MODEL_CONFIGS["default"])

