# SPrint5: LLM Observability With Langfuse

## Demo 2: Identify Performance Bottlenecks with Langfuse

## Objective

Use Langfuse traces to investigate a multi-agent request and identify which steps contribute most to latency and token usage.

By completing this demo, you will be able to:

- Distinguish a trace from its child spans and observations.
- Follow a request through a two-agent workflow.
- Compare a baseline trace with a deliberately delayed trace.
- Inspect token usage and any cost information available in Langfuse.
- Use trace evidence to explain a performance bottleneck.

## Workflow

The Flask application exposes a `/chat` endpoint and runs two sequential agents:

1. **Research Agent** — generates research/context for the request.
2. **Analysis Agent** — uses the research result to produce the final response.

Langfuse records the request as a trace with child observations for input validation, context retrieval, each agent's generation, and response formatting. When delay injection is enabled, an additional delay span is recorded inside the Research Agent's generation path.

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

- Python installed.
- A Gemini API key.
- A Langfuse project and API credentials.
- Access to the demo project directory.

## Setup

Run these commands from the `demo-2-identify-performance-bottlenecks-with-langfuse` directory.

### 1. Activate the virtual environment

If the project already has a `.venv` directory:

```bash
source .venv/bin/activate
```

If it does not, create one and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment variables

Create or update `.env` using the project's expected variable names:

```dotenv
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=your_supported_gemini_model

LANGFUSE_SECRET_KEY=your_langfuse_secret_key
LANGFUSE_PUBLIC_KEY=your_langfuse_public_key
LANGFUSE_BASE_URL=https://cloud.langfuse.com

SLOW_REQUEST=false
RESEARCH_DEPTH=standard
```

`RESEARCH_DEPTH` controls the Research Agent behavior:

- `standard` keeps the concise summary mode and a 256-token output budget.
- `detailed` increases the Research Agent output budget to 1024 tokens and asks for a more comprehensive brief.

Use the Langfuse host URL appropriate to your project. Do not commit `.env` or share API keys. Keep the variable names consistent with the application code.

### 3. Start the application

```bash
python app.py
```

The app listens on port `8080`.

## Run the demo

### 1. Check application health

```bash
curl http://localhost:8080/health
```

Confirm that the service reports a healthy status and the expected application version.

### 2. Send a baseline request

Set `SLOW_REQUEST=false` and `RESEARCH_DEPTH=standard` in `.env`, restart the application if needed, and send a request:

```bash
curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Explain why application latency matters."}'
```

Record the response and open the corresponding trace in Langfuse. Inspect the total trace duration and the durations of the Research Agent and Analysis Agent observations. This baseline run reflects the default concise research path.

### 3. Send a detailed-research request

Set:

```dotenv
SLOW_REQUEST=false
RESEARCH_DEPTH=detailed
```

Restart the application if required, then send the same request again. This variation increases the Research Agent output budget and asks for a more comprehensive brief, which will usually change the output token count and cost profile while keeping the analysis step unchanged.

### 4. Send a deliberately delayed request

Set:

```dotenv
SLOW_REQUEST=true
RESEARCH_DEPTH=standard
```

Restart the application if required, then send the same request again. Find the new trace in Langfuse and inspect the `injected-delay` span and the surrounding Research Agent observation.

The configured delay is approximately three seconds. Actual end-to-end duration can vary because of network, model, and service latency.

### 5. Compare the traces

For the standard, detailed, and delayed traces, inspect:

- Total trace duration.
- Duration of each agent and generation observation.
- Input, output, and total token usage, when reported.
- Cost information, if Langfuse has the necessary model pricing/configuration and usage data.
- Any errors or missing usage details.
- Whether the deeper research mode changes the Research Agent output length and token footprint.

Use the trace and span hierarchy to identify _where_ time was spent. Do not assume that the longest span is always caused by model inference: inspect nested observations, the injected-delay span, and the effect of the research depth setting.

## Tests

Run the automated tests from the project directory:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The chat test should account for **two Gemini generation calls**: one for the Research Agent and one for the Analysis Agent. Tests should mock both calls and verify the returned response and relevant error cases.

## Troubleshooting

- **Missing environment variables:** Check `.env` names against the variables read by `app.py`.
- **Gemini request fails:** Verify the API key, model name, network access, and current API availability.
- **No Langfuse trace appears:** Check Langfuse credentials and host URL, then inspect application logs for SDK errors.
- **No token usage appears:** Check whether the model response includes usage metadata and whether the app records it. Usage reporting can vary by model/API.
- **No cost appears:** Token usage and cost are different. Cost may be unavailable until model pricing is configured or recognized by Langfuse.
- **No extra delay is visible:** Confirm `SLOW_REQUEST=true`, restart the app if environment values are loaded only at startup, and inspect the child observations under the Research Agent.
- **Research output is unexpectedly long or short:** Check `RESEARCH_DEPTH` in `.env` and restart the app. `standard` uses the concise summary mode, while `detailed` requests a longer, higher-token research brief.

## Completion checklist

- [ ] `/health` returns a healthy status.
- [ ] A baseline request succeeds and creates a Langfuse trace.
- [ ] A delayed request succeeds and creates a separate trace.
- [ ] The trace hierarchy shows the Research Agent and Analysis Agent.
- [ ] The delayed trace contains the injected-delay span.
- [ ] Durations and available token/cost information are inspected.
- [ ] The Observations section below is completed using actual trace data.

## Observations

Complete this section after inspecting the actual Langfuse traces. Record measured values from your own run; do not use expected or estimated values as if they were observed.

### Trace comparison

| Observation                  | Baseline trace (`SLOW_REQUEST=false`) | Delayed trace (`SLOW_REQUEST=true`) |
| ---------------------------- | ------------------------------------- | ----------------------------------- |
| Trace ID or link             |                                       |                                     |
| Total trace duration         |                                       |                                     |
| Research Agent duration      |                                       |                                     |
| Injected-delay span duration | Not present                           |                                     |
| Analysis Agent duration      |                                       |                                     |
| Input tokens                 |                                       |                                     |
| Output tokens                |                                       |                                     |
| Total tokens                 |                                       |                                     |
| Cost shown by Langfuse       |                                       |                                     |
| Errors or missing usage data |                                       |                                     |

### Conclusions

- **Main latency bottleneck:** Identify the observation that contributed most to the request duration and cite the trace evidence.
- **Effect of injected delay:** Compare the baseline and delayed durations. Explain whether the increase is consistent with the configured delay, allowing for normal service/network variation.
- **Token usage:** State whether the two runs report usage, and whether the delayed run changed token usage. A delay by itself should not require extra model tokens.
- **Cost:** Record the cost shown by Langfuse, or state that cost was unavailable. Do not infer a monetary cost from token counts unless the pricing basis is known.
- **Next improvement:** Suggest one specific change that could reduce latency or cost, based on the observations.

### Key takeaway

A trace shows the end-to-end request, while its observations help locate the work within that request. Comparing baseline and delayed traces helps distinguish time spent waiting from time spent in model calls. Token usage and cost should be assessed separately from latency.
