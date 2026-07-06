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
LLM_GATEWAY_MODEL=openai/gpt-4o-mini
```

Self-hosted gateway:

```bash
AI_PROVIDER=llmgateway
LLM_GATEWAY_API_KEY=your_self_hosted_gateway_key
LLM_GATEWAY_BASE_URL=http://your-gateway-server:4001/v1
LLM_GATEWAY_MODEL=your_gateway_model_name
```

## Where Provider Choice Goes

Choose providers and models inside LLM Gateway. The document splitter should only know the gateway model name.

For example, after adding provider keys/models in LLM Gateway, only change:

```bash
LLM_GATEWAY_MODEL=provider/model-name
```

## Recommended Workflow

1. Start with `AI_PROVIDER=rules` and test obvious single-category documents.
2. Add LLM Gateway when you want AI help for mixed-category PDFs.
3. Use hosted LLM Gateway for quick testing.
4. Move to self-hosted LLM Gateway when the project becomes a shared workflow or needs tighter control.

The splitter still stays cost-conscious: local rules run first, and AI is only allowed for mixed-category source PDFs.
