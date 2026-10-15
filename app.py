"""Flask API demonstrating Langfuse latency and token/cost analysis.

Workflow:
- Research Agent: generates a research summary.
- Analysis Agent: uses the research summary to answer the user's question.
- SLOW_REQUEST=true injects a controlled delay inside the Research Agent path.
- RESEARCH_DEPTH=standard keeps the default concise research summary.
- RESEARCH_DEPTH=detailed raises the output-token budget
  to make usage differences easier to inspect. Actual token usage/cost are not
  guaranteed.
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


def env_flag(name: str) -> bool:
    """Read a boolean environment variable."""
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}


def get_research_depth() -> str:
    """Resolve the research mode from the env var."""
    research_depth = os.getenv("RESEARCH_DEPTH")
    if research_depth is None:
        return "detailed" if env_flag("RESEARCH_DEPTH") else "standard"
    return research_depth.strip().lower() or "standard"


def get_gemini_client():
    """Create a Gemini client using the configured API key."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")
    return genai.Client(api_key=api_key)


def redact_pii(text: str) -> str:
    """Basic demo-only redaction for common email addresses and phone numbers."""
    text = re.sub(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "[REDACTED_EMAIL]",
        text,
    )
    return re.sub(r"\b(?:\+?\d[\d .()-]{7,}\d)\b", "[REDACTED_PHONE]", text)


def get_token_usage(response) -> dict:
    """Extract token counts when Gemini returns usage metadata."""
    metadata = getattr(response, "usage_metadata", None)
    if metadata is None:
        return {}
    fields = {
        "input": getattr(metadata, "prompt_token_count", None),
        "output": getattr(metadata, "candidates_token_count", None),
        "total": getattr(metadata, "total_token_count", None),
    }
    return {key: value for key, value in fields.items() if value is not None}


def call_gemini(
    client,
    model: str,
    prompt: str,
    observation_name: str,
    max_output_tokens: int,
    inject_delay: bool = False,
) -> str:
    """Call Gemini and record input, output, duration, and available usage."""
    with langfuse.start_as_current_observation(
        as_type="generation",
        name=observation_name,
        model=model,
        input=prompt,
    ) as generation:
        if inject_delay:
            with langfuse.start_as_current_observation(
                as_type="span",
                name="injected-delay",
                input={"seconds": 3},
            ) as delay_span:
                time.sleep(3)
                delay_span.update(output="Completed controlled 3-second delay")

        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config={"max_output_tokens": max_output_tokens},
        )
        reply = response.text or "The model returned no text."
        generation.update(output=reply)

        usage = get_token_usage(response)
        if usage:
            generation.update(usage_details=usage)

        return reply


@app.get("/health")
def health():
    """Return application health and version."""
    return jsonify(status="ok", version=os.getenv("APP_VERSION", "local"))


@app.post("/chat")
def chat():
    """Run a two-agent workflow and record it in Langfuse."""
    body = request.get_json(silent=True)
    message = body.get("message") if isinstance(body, dict) else None

    if not isinstance(message, str) or not message.strip():
        return jsonify(error="Provide a non-empty message string."), 400
    message = message.strip()
    if len(message) > 1000:
        return jsonify(error="Message must be at most 1000 characters."), 400

    safe_message = redact_pii(message)
    model = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
    slow_request = env_flag("SLOW_REQUEST")
    research_depth = get_research_depth()
    detailed_research = research_depth in {
        "deep",
        "detailed",
        "extended",
        "verbose",
        "high-budget"
    }

    # The larger budget permits, but does not guarantee, more output tokens.
    research_token_limit = 1024 if detailed_research else 256
    analysis_token_limit = 256

    try:
        with langfuse.start_as_current_observation(
            as_type="span",
            name="chat-request",
            input={"message": safe_message},
        ) as trace:
            with langfuse.start_as_current_observation(
                as_type="span", name="validate-input"
            ) as span:
                span.update(output="Input validated")

            with langfuse.start_as_current_observation(
                as_type="span", name="retrieve-context"
            ) as span:
                context = "No external documents were retrieved (demo placeholder)."
                span.update(output=context)

            client = get_gemini_client()

            if detailed_research:
                research_instruction = (
                    "You are the Research Agent. Produce a comprehensive research "
                    "brief with these sections: overview, key concepts, detailed "
                    "explanation, practical example, benefits, limitations, common "
                    "mistakes, and conclusion. Explain each section in several "
                    "sentences where relevant. Do not invent citations."
                )
            else:
                research_instruction = (
                    "You are the Research Agent. Provide a concise summary with "
                    "the main findings and key facts. Do not invent citations."
                )

            research_prompt = (
                f"{research_instruction}\n\n"
                f"Context: {context}\nQuestion: {safe_message}"
            )
            research_result = call_gemini(
                client=client,
                model=model,
                prompt=research_prompt,
                observation_name="research-generation",
                max_output_tokens=research_token_limit,
                inject_delay=slow_request,
            )

            analysis_prompt = (
                "You are the Analysis Agent. Use the research notes to answer "
                "the user's question directly. Summarize the key points and avoid "
                "unnecessary repetition or unsupported claims.\n\n"
                f"User question: {safe_message}\n\n"
                f"Research notes:\n{research_result}"
            )
            final_reply = call_gemini(
                client=client,
                model=model,
                prompt=analysis_prompt,
                observation_name="analysis-generation",
                max_output_tokens=analysis_token_limit,
            )

            with langfuse.start_as_current_observation(
                as_type="span", name="format-response"
            ) as span:
                result = {"reply": final_reply}
                span.update(output="Response formatted")

            trace.update(output=result)

        langfuse.flush()
        return jsonify(result)

    except Exception:
        app.logger.exception("Chat request failed")
        langfuse.flush()
        return jsonify(error="The request could not be completed."), 502


if __name__ == "__main__":
    app.logger.info("Application starting on port 8080")
    serve(app, host="0.0.0.0", port=8080)
