"""Flask multi-agent demo with Gemini and Langfuse observability."""

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

EMAIL_PATTERN = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)
PHONE_PATTERN = re.compile(r"(?<!\w)\+?\d[\d ().-]{7,}\d(?!\w)")


def redact_pii(text):
    """Mask common email addresses and phone numbers in text."""
    if not isinstance(text, str):
        return text
    text = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", text)
    text = PHONE_PATTERN.sub("[REDACTED_PHONE]", text)
    return text


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(message)s",
)

langfuse = get_client()


def get_gemini_client():
    """Create a Gemini client using the configured API key."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")
    return genai.Client(api_key=api_key)


def get_model_name():
    """Return the configured Gemini model name."""
    return os.getenv("GEMINI_MODEL", "gemini-flash-latest")


def record_generation_result(generation, response):
    """Record redacted output and usage returned by Gemini, when available."""
    reply = response.text or "The model returned no text."
    usage = getattr(response, "usage_metadata", None)

    if usage:
        # Langfuse v4 usage_details keys: input, output, total.
        generation.update(
            output=redact_pii(reply),
            usage_details={
                "input": getattr(usage, "prompt_token_count", None) or 0,
                "output": getattr(usage, "candidates_token_count", None) or 0,
                "total": getattr(usage, "total_token_count", None) or 0,
            },
        )
    else:
        generation.update(output=redact_pii(reply))

    return reply


def call_gemini(client, prompt, generation_name, *, inject_delay=False):
    """Run one Gemini generation inside a named Langfuse generation."""
    model_name = get_model_name()

    with langfuse.start_as_current_observation(
        as_type="generation",
        name=generation_name,
        model=model_name,
        input=redact_pii(prompt),
    ) as generation:
        if inject_delay and os.getenv("SLOW_REQUEST", "false").lower() == "true":
            with langfuse.start_as_current_observation(
                name="injected-delay",
                as_type="span",
                input={"seconds": 3},
            ) as delay_span:
                logging.info("Simulating a three-second delay in %s", generation_name)
                time.sleep(3)
                delay_span.update(output={"delay_seconds": 3, "status": "completed"})

        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
        )
        return record_generation_result(generation, response)


@app.get("/health")
def health():
    """Return application health and version."""
    return jsonify(
        status="ok",
        version=os.getenv("APP_VERSION", "demo-2"),
    )


@app.post("/chat")
def chat():
    """Validate input, run two specialist agents, and capture a Langfuse trace."""
    body = request.get_json(silent=True)
    message = body.get("message") if isinstance(body, dict) else None

    if not isinstance(message, str) or not message.strip():
        return jsonify(error="Provide a non-empty message string."), 400

    message = message.strip()
    if len(message) > 1000:
        return jsonify(error="Message must be at most 1000 characters."), 400

    # Redact before sending user input to Gemini or recording it in Langfuse.
    message = redact_pii(message)

    try:
        with langfuse.start_as_current_observation(
            as_type="span",
            name="chat-request",
            input={"message": message},
        ) as trace:
            with langfuse.start_as_current_observation(
                as_type="span",
                name="validate-input",
            ) as span:
                valid_message = message
                span.update(output="Input validated")

            with langfuse.start_as_current_observation(
                as_type="span",
                name="retrieve-context",
            ) as span:
                # Placeholder context: this demo does not retrieve external documents.
                context = "No external documents were retrieved."
                span.update(output=context)

            client = get_gemini_client()

            # Agent 1: produce candidate job-search recommendations.
            with langfuse.start_as_current_observation(
                as_type="span",
                name="research-agent",
                input={"task": valid_message},
            ) as research_span:
                research_prompt = (
                    "You are the Research Agent in a simple two-agent workflow. "
                    "Generate three concise, practical ideas that answer the user's request. "
                    "Do not claim to have searched the web or external sources.\n"
                    f"Context: {context}\n"
                    f"User request: {valid_message}"
                )
                research_result = call_gemini(
                    client,
                    research_prompt,
                    "research-generation",
                    inject_delay=True,
                )
                research_span.update(output=redact_pii(research_result))

            # Agent 2: assess and prioritise Agent 1's recommendations.
            with langfuse.start_as_current_observation(
                as_type="span",
                name="analysis-agent",
                input={"research_result": redact_pii(research_result)},
            ) as analysis_span:
                analysis_prompt = (
                    "You are the Analysis Agent. Review the recommendations from the "
                    "Research Agent, remove repetition, and produce a clear final answer "
                    "with three prioritised, actionable tips. Do not invent facts.\n"
                    f"Original request: {valid_message}\n"
                    f"Research Agent output:\n{redact_pii(research_result)}"
                )
                final_reply = call_gemini(
                    client,
                    analysis_prompt,
                    "analysis-generation",
                )
                analysis_span.update(output=redact_pii(final_reply))

            with langfuse.start_as_current_observation(
                as_type="span",
                name="format-response",
            ) as span:
                result = {"reply": redact_pii(final_reply)}
                span.update(output="Response formatted")

            trace.update(output={"reply": redact_pii(result["reply"])})

        langfuse.flush()
        return jsonify(result)

    except Exception:
        app.logger.exception("Chat request failed")
        langfuse.flush()
        return jsonify(error="The request could not be completed."), 502


if __name__ == "__main__":
    app.logger.info("Application starting on port 8080")
    serve(app, host="0.0.0.0", port=8080)
