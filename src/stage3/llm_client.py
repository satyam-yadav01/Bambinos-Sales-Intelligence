"""OpenAI structured-output client with bounded retries and injectable testing."""
from __future__ import annotations
import os, time
from typing import Optional, Callable, Any
from pydantic import ValidationError
from .schemas import CallIntelligenceOutput

try:
    from openai import OpenAI
except ImportError:  # Import remains possible for offline unit tests.
    OpenAI = None


class LLMClientError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None,
                 timeout: float = 60.0, max_retries: int = 2,
                 client: Any = None, sleep: Callable[[float], None] = time.sleep):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-2024-08-06")
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self._sleep = sleep
        self.client = client
        if self.client is None and self.api_key:
            if OpenAI is None:
                raise LLMClientError("The openai package is not installed. Install requirements.txt.")
            self.client = OpenAI(api_key=self.api_key, timeout=self.timeout, max_retries=0)

    def extract_intelligence(self, system_prompt: str, user_prompt: str,
                             mock_response: Optional[CallIntelligenceOutput] = None) -> CallIntelligenceOutput:
        if mock_response is not None:
            return mock_response
        if self.client is None:
            raise LLMClientError("No provider client configured. Set OPENAI_API_KEY in the environment.")
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.beta.chat.completions.parse(
                    model=self.model,
                    messages=[{"role": "system", "content": system_prompt},
                              {"role": "user", "content": user_prompt}],
                    response_format=CallIntelligenceOutput,
                    temperature=0,
                    timeout=self.timeout,
                )
                message = response.choices[0].message
                if getattr(message, "refusal", None):
                    raise LLMClientError(f"Provider refusal: {message.refusal}")
                parsed = getattr(message, "parsed", None)
                if parsed is None:
                    raise LLMClientError("Provider returned no parsed structured output (possibly refusal or incomplete response).")
                return parsed if isinstance(parsed, CallIntelligenceOutput) else CallIntelligenceOutput.model_validate(parsed)
            except (ValidationError, LLMClientError):
                raise
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries or not self._is_retryable(exc):
                    break
                self._sleep(min(2 ** attempt, 4))
        raise LLMClientError(f"OpenAI extraction failed after {attempt + 1} attempt(s): {type(last_error).__name__}: {last_error}") from last_error

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        name = type(exc).__name__.lower()
        status = getattr(exc, "status_code", None)
        return (status in (408, 409, 429) or (isinstance(status, int) and status >= 500)
                or any(x in name for x in ("timeout", "connection", "ratelimit", "internalserver")))
