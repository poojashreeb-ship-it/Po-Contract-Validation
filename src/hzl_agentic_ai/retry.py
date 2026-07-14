"""Retry policy for transient LLM/provider failures.

Upstream providers occasionally fail transiently under load or rate limiting.
This has also surfaced as a `TypeError: 'NoneType' object is not iterable`
from the OpenAI SDK's response parser when a provider (e.g. an OpenRouter
free-tier model) returns a malformed/empty completion instead of a proper
error. All of these are worth a short retry with backoff rather than failing
the whole extraction/validation step outright.
"""
from openai import APIConnectionError, APITimeoutError, RateLimitError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

llm_retry = retry(
    retry=retry_if_exception_type(
        (RateLimitError, APIConnectionError, APITimeoutError, TypeError)
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=20),
    reraise=True,
)
