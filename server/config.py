"""Configuration constants for the Computer Use Agent."""

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2  # Base delay, will use exponential backoff

# Execution limits
MAX_STEPS = 20

# Timeout configuration
ACTION_TIMEOUT_SECONDS = 20
VERIFICATION_DELAY_SECONDS = 1
PAGE_SETTLE_DELAY = 2  # Delay after navigation/clicks

# Content limits
DOM_CONTENT_LIMIT = 3000  # Max characters of DOM to send to LLM

# Logging
VERBOSE = True

# OpenAI model configuration
OPENAI_MODEL = "gpt-4o"  # Use gpt-4o for best results
OPENAI_TEMPERATURE = 0.1

# Screenshot configuration
ENABLE_SCREENSHOTS = True
MAX_SCREENSHOT_SIZE = 1024  # Max dimension for screenshots