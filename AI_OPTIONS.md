# AI Provider Options

The app intentionally supports only two modes:

- `rules`: no AI calls at all.
- `llmgateway`: all AI calls go through LLM Gateway.

This keeps the app from accumulating provider-specific edge cases. Provider keys, model routing, analytics, and self-hosting belong in LLM Gateway, not inside the document splitter.

## LLM Gateway Setup

Hosted gateway:

```bash
AI_PROVIDER=llmgateway
LLM_GATEWAY_API_KEY=your_gateway_key
LLM_GATEWAY_BASE_URL=https://api.llmgateway.io/v1
LLM_GATEWAY_MODEL=gemini-2.5-flash-lite
LLM_GATEWAY_FALLBACK_MODELS=llama-3.1-8b-instant
```

Self-hosted gateway:

```bash
AI_PROVIDER=llmgateway
LLM_GATEWAY_API_KEY=your_self_hosted_gateway_key
LLM_GATEWAY_BASE_URL=http://your-gateway-server:4001/v1
LLM_GATEWAY_MODEL=your_gateway_model_name
LLM_GATEWAY_FALLBACK_MODELS=your_fallback_model_name
```

## Where Provider Choice Goes

Choose providers and models inside LLM Gateway. The document splitter should only know the gateway model name.

For example, after adding provider keys/models in LLM Gateway, only change:

```bash
LLM_GATEWAY_MODEL=exact-primary-model-id
LLM_GATEWAY_FALLBACK_MODELS=exact-fallback-model-id,another-fallback-id
```

`LLM_GATEWAY_MODEL` is tried first. If that model is rate-limited, unavailable, returns invalid split JSON, or fails for any other reason, the splitter tries each comma-separated model in `LLM_GATEWAY_FALLBACK_MODELS`. If all AI models fail, the local page-pattern splitter is used.

AI is used only for split detection in the normal processing path. Classification remains rules-based to avoid extra API calls after a document has already been split.

## Recommended Workflow

1. Start with `AI_PROVIDER=rules` and test obvious single-category documents.
2. Add LLM Gateway when you want AI help deciding split boundaries in multi-page PDFs.
3. Use hosted LLM Gateway for quick testing.
4. Move to self-hosted LLM Gateway when the project becomes a shared workflow or needs tighter control.

The splitter still stays cost-conscious: single-page PDFs never need split AI, and local page-pattern splitting remains the fallback whenever AI is unavailable.
