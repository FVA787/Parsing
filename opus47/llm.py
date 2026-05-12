"""Small wrapper around the local llama.cpp OpenAI-compatible endpoint."""

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = "http://95.84.168.248:1234/v1/chat/completions"
MODEL = "Qwen3.6-35B-A3B-Q8_0.gguf"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(name):
    """Load a prompt template by stem (e.g. '01_address')."""
    p = PROMPTS_DIR / f"{name}.md"
    return p.read_text(encoding="utf-8")


def chat(messages, *, temperature=0.0, max_tokens=512, timeout=120, retries=2):
    """Send a chat completion request and return the assistant message text."""
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    data = json.dumps(payload).encode("utf-8")
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                ENDPOINT,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"]
        except (urllib.error.URLError, TimeoutError, KeyError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise


def call_prompt(prompt_name, slot_values, *, system=None, **kwargs):
    """Render a prompt template (replacing `{KEY}` placeholders) and call the LLM."""
    template = load_prompt(prompt_name)
    rendered = template
    for k, v in slot_values.items():
        rendered = rendered.replace(f"{{{k}}}", v)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": rendered})
    return chat(messages, **kwargs)


def call_prompt_json(prompt_name, slot_values, **kwargs):
    """Same as call_prompt, but parse the response as JSON.

    Tolerates leading/trailing whitespace and an accidental ```json fence.
    Raises ValueError on unparsable output.
    """
    raw = call_prompt(prompt_name, slot_values, **kwargs)
    s = raw.strip()
    if s.startswith("```"):
        # Strip code fence
        s = s.strip("`")
        # Drop optional language tag on first line
        if "\n" in s:
            first, rest = s.split("\n", 1)
            if first.lower().startswith("json") or not first.strip():
                s = rest
        s = s.strip("`").strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        raise ValueError(f"Bad JSON from LLM (prompt={prompt_name}): {raw!r}") from e
