# Sprint 5: Instrument LLM Observability With Langfuse

## Demo 2: Identify Performance Bottlenecks with Langfuse

## Objective

Use Langfuse traces to investigate a multi-agent request and identify which steps contribute most to latency and token usage.

By completing this demo, you will be able to:

- Distinguish a trace from its child spans and observations.
- Follow a request through a two-agent workflow.
- Compare a baseline trace with a detailed-research trace and a deliberately delayed trace.
- Inspect token usage and the cost Langfuse calculates for each model call.
- See personal data appear in a trace, then mask it before it is captured.
- Use trace evidence to explain a performance bottleneck.

## Workflow

The Flask application exposes a `/chat` endpoint and runs two sequential agents:

1. **Research Agent** - generates research/context for the request.
2. **Analysis Agent** - uses the research result to produce the final response.

Langfuse records the request as a trace with child observations for input validation, context retrieval, each agent and its model call, and response formatting. When delay injection is enabled, an additional `injected-delay` span is recorded inside the Research Agent, just before its model call.

```text
POST /chat
  └── chat-request (trace)
      ├── validate-input
      ├── retrieve-context
      ├── research-agent
      │   ├── injected-delay (only when enabled)
      │   └── research-generation
      ├── analysis-agent
      │   └── analysis-generation
      └── format-response
```

The context-retrieval step is a placeholder in this demo; it does not represent a production retrieval system.

## Prerequisites

- Ubuntu with Python 3.10 or later, `python3-venv` and `curl` installed.
- A Gemini API key.
- A Langfuse Cloud project with its API keys.
- Access to the demo project directory.

## Setup

Run these commands from the `demo-2-identify-performance-bottlenecks-with-langfuse` directory.

### 1. Create the virtual environment and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If the `.venv` directory already exists, run only the `source` line.

### 2. Configure environment variables

Create a `.env` file with these variables:

```dotenv
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-3.5-flash-lite

LANGFUSE_PUBLIC_KEY=your_langfuse_public_key
LANGFUSE_SECRET_KEY=your_langfuse_secret_key
LANGFUSE_BASE_URL=https://cloud.langfuse.com

SLOW_REQUEST=false
RESEARCH_DEPTH=standard
REDACT_PII=true
```

- `LANGFUSE_BASE_URL` must match the region of your Langfuse project: `https://cloud.langfuse.com` for the EU region or `https://us.cloud.langfuse.com` for the US region. A key pair from one region does not work against the other.
- `SLOW_REQUEST=true` adds a controlled three-second delay before the Research Agent's model call.
- `RESEARCH_DEPTH` controls the Research Agent. `standard` asks for a concise summary with a 256-token output budget. `detailed` asks for a more comprehensive brief with a 1024-token output budget. Any other value is rejected.
- `REDACT_PII=true` masks email addresses and phone numbers before the message reaches the model or Langfuse. Set it to `false` only for the PII step below.

Do not commit `.env` or share API keys. Values set on the command line override `.env`, so the steps below change settings that way and you do not need to edit the file between runs.

### 3. Start the application

```bash
python app.py
```

The app listens on `127.0.0.1:8080`, so it is reachable only from your own machine. Leave it running and open a **second terminal** in the same directory for the `curl` commands.

To stop the app, press `Ctrl+C` in its terminal. To change a setting, stop the app and start it again, because settings are read when the app starts.

## Run the demo

### 1. Check application health

```bash
curl http://localhost:8080/health
```

Expected output: `{"status":"ok","version":"local"}`.

### 2. Send a baseline request

Start the app with the default settings (no `.env` changes needed), then send a request:

```bash
curl -sS -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Explain why application latency matters."}'
```

In Langfuse, open **Tracing > Traces**. Traces appear within a few seconds. Open the newest `chat-request` trace and inspect:

- the tree of observations, in the order they ran;
- the duration of the trace, the Research Agent and the Analysis Agent;
- the input, output and total tokens, and the cost, on each generation.

The observation table lists the newest rows first, so it reads upward in time. Use the trace tree to read the order of execution.

### 3. Send a detailed-research request

Stop the app and start it with:

```bash
RESEARCH_DEPTH=detailed python app.py
```

Send the same request again from the second terminal. The Research Agent now has a larger output budget and a request for a more comprehensive brief. Compare the `research-generation` output tokens and cost with the baseline. Also compare the `analysis-generation` input tokens, because the Analysis Agent receives the longer research notes.

Latency varies from run to run, so do not assume that the detailed run is always slower. Token counts and cost are the reliable difference.

### 4. Send a deliberately delayed request

Stop the app and start it with:

```bash
SLOW_REQUEST=true python app.py
```

Send the same request again. Open the new trace and inspect the `injected-delay` span and the `research-agent` observation around it.

The configured delay is approximately three seconds. Actual end-to-end duration can vary because of network, model and service latency.

### 5. See personal data in a trace, then mask it

Stop the app and start it with masking turned off:

```bash
REDACT_PII=false python app.py
```

Send a message that contains personal data:

```bash
curl -sS -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"My email is priya@example.com and my phone is +91 98765 43210. Suggest three job-search tips."}'
```

Open the trace and find the email address and phone number in the `chat-request` input and in the generation prompts. Anyone with access to the Langfuse project can read them.

Now stop the app, start it normally with `python app.py`, and send the same request. The trace now shows `[REDACTED_EMAIL]` and `[REDACTED_PHONE]` in place of the original values.

The masking in this demo handles only email addresses and phone numbers. Names and addresses are not detected, so a real system needs a proper PII-detection step.

### 6. Send an invalid request

```bash
curl -sS -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{"message":""}'
```

The app returns a 400 error. In Langfuse, the trace shows `validate-input` at `WARNING` level with the reason, and no research or analysis steps.

### 7. Compare the traces

For the baseline, detailed and delayed traces, inspect:

- Total trace duration.
- Duration of each agent and generation observation.
- Input, output and total token usage on each generation.
- The cost Langfuse shows for each generation.
- Any errors or missing usage details.

Use the trace and span hierarchy to identify _where_ time was spent. Do not assume that the longest span is caused by model inference: inspect the nested observations, the `injected-delay` span and the effect of the research depth setting.

Cost is calculated by Langfuse from the model name and the token counts the app reports. Output tokens include the model's reasoning tokens, because Gemini bills them as output. If you use a free-tier Gemini key you are not charged, even though Langfuse still shows a calculated cost.

## Tests

Run the automated tests from the project directory:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The tests mock both Gemini calls (one for the Research Agent, one for the Analysis Agent) and the Langfuse flush, so they need no API keys and make no network calls. They also set their own values for the app settings, so your `.env` does not affect them.

One test deliberately simulates a Gemini failure. You will see a logged traceback for `Simulated Gemini failure` in the output, and that test still reports `ok`.

## Troubleshooting

- **Missing environment variables:** Check the `.env` names against the variables read by `app.py`.
- **`/chat` returns a 500 error about `RESEARCH_DEPTH`:** The value must be exactly `standard` or `detailed`. The app also refuses to start with any other value.
- **Gemini request fails (502 response):** Verify the API key, model name, network access and current API availability. The app log shows the cause.
- **No Langfuse trace appears:** Check that the key pair and `LANGFUSE_BASE_URL` belong to the same Langfuse region, then look for SDK errors in the app log.
- **No token usage appears:** Check whether the model response includes usage metadata. Usage reporting can vary by model and API.
- **No cost appears:** Cost is calculated only when Langfuse recognizes the model name and receives token usage. Confirm that `GEMINI_MODEL` matches the model name shown on the generation.
- **No extra delay is visible:** Confirm the app was started with `SLOW_REQUEST=true`, and inspect the child observations under the Research Agent.
- **Research output is unexpectedly long, short or cut off:** Check `RESEARCH_DEPTH`. The output budgets are 256 tokens for `standard` and 1024 for `detailed`, and an answer that reaches its budget is cut off.
- **Settings do not change:** Settings are read at startup. Stop the app with `Ctrl+C` and start it again.

## Completion checklist

- [ ] `/health` returns a healthy status.
- [ ] A baseline request succeeds and creates a Langfuse trace.
- [ ] A detailed-research request creates a separate trace with higher output tokens and cost.
- [ ] A delayed request creates a separate trace containing the `injected-delay` span.
- [ ] The trace hierarchy shows the Research Agent and the Analysis Agent.
- [ ] Personal data is visible with `REDACT_PII=false` and masked with `REDACT_PII=true`.
- [ ] An invalid request shows a `WARNING` on `validate-input`.
- [ ] Durations, token usage and cost are inspected.
- [ ] The Observations section below is completed using actual trace data.

## Observations

Complete this section after inspecting the actual Langfuse traces. Record measured values from your own run; do not use expected or estimated values as if they were observed.

### Trace comparison

| Observation                              | Baseline | Detailed research | Delayed (`SLOW_REQUEST=true`) |
| ---------------------------------------- | -------- | ----------------- | ----------------------------- |
| Time of the trace                        |          |                   |                               |
| Total trace duration                     |          |                   |                               |
| Research Agent duration                  |          |                   |                               |
| Injected-delay span duration             | Not present | Not present    |                               |
| `research-generation` duration           |          |                   |                               |
| Analysis Agent duration                  |          |                   |                               |
| `research-generation` input / output tokens |       |                   |                               |
| `analysis-generation` input / output tokens |       |                   |                               |
| Cost shown by Langfuse (both generations) |         |                   |                               |
| Errors or missing usage data             |          |                   |                               |

### Conclusions

- **Main latency bottleneck:** Identify the observation that contributed most to the request duration and cite the trace evidence.
- **Effect of injected delay:** Compare the baseline and delayed durations. Explain whether the increase is consistent with the configured delay, allowing for normal service and network variation. State which observation shows the delay.
- **Effect of research depth:** Compare the baseline and detailed traces. State what changed in the `research-generation` and `analysis-generation` tokens and cost, and whether duration changed.
- **Token usage:** State whether the delayed run changed token usage. A delay by itself should not require extra model tokens.
- **Cost:** Record the cost shown by Langfuse, or state that cost was unavailable.
- **Next improvement:** Suggest one specific change that could reduce latency or cost, based on the observations.

### Key takeaway

A trace shows the end-to-end request, while its observations help locate the work within that request. Comparing baseline, detailed and delayed traces helps distinguish time spent waiting from time spent in model calls, and shows that latency, token usage and cost are separate measurements. Traces also capture whatever you send to the model, so personal data must be masked before it is recorded.