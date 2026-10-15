"""Flask API demonstrating Langfuse latency and token/cost analysis.

Workflow:
- Research Agent: generates a research summary.
- Analysis Agent: uses the research summary to answer the user's question.
- SLOW_REQUEST=true injects a controlled 3-second delay before the Research
  Agent's model call.
- RESEARCH_DEPTH=standard (default) keeps the research summary concise.
- RESEARCH_DEPTH=detailed raises the Research Agent's output-token budget so
  usage differences are easier to inspect. Actual usage is not guaranteed.
- REDACT_PII=true (default) masks emails and phone numbers before the message
  reaches the model or Langfuse. Set it to false to see unredacted PII in a trace.
"""

import logging
import os
import re
import time

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from google import genai
from langfuse import get_client
from waitress import serve

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
langfuse = get_client()

DEFAULT_MODEL = "gemini-3.5-flash-lite"
DELAY_SECONDS = 3
RESEARCH_DEPTHS = {"standard": 256, "detailed": 1024}
ANALYSIS_TOKEN_LIMIT = 256

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_PATTERN = re.compile(r"(?<!\w)\+?\d[\d\s().-]{8,}\d(?!\w)")


def env_flag(name: str, default: bool = False) -> bool:
    """Read a boolean environment variable."""
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> dict:
    """Read and check the demo settings for one request."""
    depth = os.getenv("RESEARCH_DEPTH", "standard").strip().lower() or "standard"
    if depth not in RESEARCH_DEPTHS:
        raise ValueError("RESEARCH_DEPTH must be 'standard' or 'detailed'.")
    return {
        "model": os.getenv("GEMINI_MODEL", DEFAULT_MODEL),
        "slow_request": env_flag("SLOW_REQUEST"),
        "research_depth": depth,
        "redact_pii": env_flag("REDACT_PII", default=True),
    }


def get_gemini_client():
    """Create a Gemini client using the configured API key."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")
    return genai.Client(api_key=api_key)


def redact_pii(text: str) -> str:
    """Basic demo-only redaction of email addresses and phone numbers.

    Names and addresses are not detected. A production system needs a proper
    PII-detection step.
    """

    def mask_phone(match):
        digits = sum(character.isdigit() for character in match.group())
        return "[REDACTED_PHONE]" if 10 <= digits <= 15 else match.group()

    text = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", text)
    return PHONE_PATTERN.sub(mask_phone, text)


def validate_message(body):
    """Return (message, error) for a request body."""
    message = body.get("message") if isinstance(body, dict) else None
    if not isinstance(message, str) or not message.strip():
        return None, "Provide a non-empty message string."
    message = message.strip()
    if len(message) > 1000:
        return None, "Message must be at most 1000 characters."
    return message, None


def get_token_usage(response) -> dict:
    """Extract token counts when Gemini returns usage metadata.

    Reasoning ("thinking") tokens are reported separately from the visible
    answer but are billed as output, so they are added to the output count.
    """
    metadata = getattr(response, "usage_metadata", None)
    if metadata is None:
        return {}
    answer_tokens = getattr(metadata, "candidates_token_count", None)
    reasoning_tokens = getattr(metadata, "thoughts_token_count", None)
    output_tokens = None
    if answer_tokens is not None or reasoning_tokens is not None:
        output_tokens = (answer_tokens or 0) + (reasoning_tokens or 0)
    fields = {
        "input": getattr(metadata, "prompt_token_count", None),
        "output": output_tokens,
        "total": getattr(metadata, "total_token_count", None),
    }
    return {key: value for key, value in fields.items() if value is not None}


def call_gemini(client, settings, prompt, observation_name, max_output_tokens) -> str:
    """Call Gemini and record input, output, duration and token usage.

    Langfuse works out cost from the model name and these usage counts.
    """
    with langfuse.start_as_current_observation(
        as_type="generation",
        name=observation_name,
        model=settings["model"],
        model_parameters={"max_output_tokens": max_output_tokens},
        input=prompt,
    ) as generation:
        response = client.models.generate_content(
            model=settings["model"],
            contents=prompt,
            config={"max_output_tokens": max_output_tokens},
        )
        reply = response.text or "The model returned no text."
        usage = get_token_usage(response)
        generation.update(output=reply)
        if usage:
            generation.update(usage_details=usage)
        return reply


def research_prompt(question: str, context: str, detailed: bool) -> str:
    """Build the Research Agent prompt."""
    if detailed:
        instruction = (
            "You are the Research Agent. Produce a comprehensive research "
            "brief with these sections: overview, key concepts, detailed "
            "explanation, practical example, benefits, limitations, common "
            "mistakes, and conclusion. Explain each section in several "
            "sentences where relevant. Do not invent citations."
        )
    else:
        instruction = (
            "You are the Research Agent. Provide a concise summary with "
            "the main findings and key facts. Do not invent citations."
        )
    return f"{instruction}\n\nContext: {context}\nQuestion: {question}"


def analysis_prompt(question: str, research_notes: str) -> str:
    """Build the Analysis Agent prompt."""
    return (
        "You are the Analysis Agent. Use the research notes to answer "
        "the user's question directly. Summarize the key points and avoid "
        "unnecessary repetition or unsupported claims.\n\n"
        f"User question: {question}\n\n"
        f"Research notes:\n{research_notes}"
    )


def run_chat(trace, body, settings):
    """Run the workflow inside the chat-request trace. Returns (payload, status)."""
    with langfuse.start_as_current_observation(
        as_type="span", name="validate-input"
    ) as span:
        message, error = validate_message(body)
        if error:
            span.update(level="WARNING", status_message=error)
            return {"error": error}, 400
        safe_message = redact_pii(message) if settings["redact_pii"] else message
        span.update(output="Input validated")
    trace.update(input={"message": safe_message})

    with langfuse.start_as_current_observation(
        as_type="span", name="retrieve-context"
    ) as span:
        context = "No external documents were retrieved (demo placeholder)."
        span.update(output=context)

    client = get_gemini_client()
    detailed = settings["research_depth"] == "detailed"

    with langfuse.start_as_current_observation(
        as_type="agent",
        name="research-agent",
        metadata={"research_depth": settings["research_depth"]},
    ):
        if settings["slow_request"]:
            with langfuse.start_as_current_observation(
                as_type="span",
                name="injected-delay",
                input={"seconds": DELAY_SECONDS},
            ) as delay_span:
                time.sleep(DELAY_SECONDS)
                delay_span.update(
                    output=f"Completed controlled {DELAY_SECONDS}-second delay"
                )
        research_result = call_gemini(
            client,
            settings,
            research_prompt(safe_message, context, detailed),
            "research-generation",
            RESEARCH_DEPTHS[settings["research_depth"]],
        )

    with langfuse.start_as_current_observation(as_type="agent", name="analysis-agent"):
        final_reply = call_gemini(
            client,
            settings,
            analysis_prompt(safe_message, research_result),
            "analysis-generation",
            ANALYSIS_TOKEN_LIMIT,
        )

    with langfuse.start_as_current_observation(
        as_type="span", name="format-response"
    ) as span:
        result = {"reply": final_reply}
        span.update(output="Response formatted")

    return result, 200


@app.get("/health")
def health():
    """Return application health and version."""
    return jsonify(status="ok", version=os.getenv("APP_VERSION", "local"))


@app.post("/chat")
def chat():
    """Run a two-agent workflow and record it in Langfuse."""
    try:
        settings = load_settings()
    except ValueError as error:
        app.logger.error("Invalid configuration: %s", error)
        return jsonify(error=str(error)), 500

    body = request.get_json(silent=True)

    try:
        with langfuse.start_as_current_observation(
            as_type="span", name="chat-request"
        ) as trace:
            payload, status = run_chat(trace, body, settings)
            trace.update(output=payload)
        langfuse.flush()
        return jsonify(payload), status
    except Exception:
        app.logger.exception("Chat request failed")
        langfuse.flush()
        return jsonify(error="The request could not be completed."), 502


if __name__ == "__main__":
    load_settings()  # Stop at startup if the configuration is invalid.
    app.logger.info("Application starting on port 8080")
    serve(app, host="127.0.0.1", port=8080)