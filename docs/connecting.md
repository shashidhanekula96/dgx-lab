# Connecting dgx-lab to your environment

dgx-lab talks to any server that implements the OpenAI-compatible
`POST /v1/chat/completions` API. `GET /v1/models` is optional but powers
`dgxlab check-endpoint`.

The workflow is the same for every backend:

```bash
dgxlab init-config -o my-exp.yaml          # 1. starter config
# edit serve.base_url and serve.model_name   # 2. point it at your server
dgxlab check-endpoint --config my-exp.yaml  # 3. verify URL, auth, model id
dgxlab run my-exp.yaml --execute            # 4. run golden eval + KPI gates
```

The base URL works with or without a trailing `/v1`.

## Security rules (enforced, not advisory)

| Endpoint | Scheme | Token |
|----------|--------|-------|
| Loopback (`127.0.0.0/8`, `localhost`, `::1`) | `http://` or `https://` | Required, unless you pass `--no-auth` |
| Anything else (LAN, cluster, cloud) | `https://` only | Always required; `--no-auth` is rejected |

Tokens are read from `--token`, from the env var named in `serve.api_key_env`, or
from `DGX_LAB_API_TOKEN`. They're sent only as an `Authorization: Bearer` header.
They're never written to run records, and URLs or configs that contain
credentials are rejected.

---

## Recipes

### Ollama (local, no auth)

```bash
ollama pull llama3.2
ollama serve                     # listens on 127.0.0.1:11434
```

```yaml
serve:
  base_url: http://127.0.0.1:11434
  model_name: llama3.2
```

```bash
dgxlab check-endpoint --config my-exp.yaml --no-auth
dgxlab run my-exp.yaml --execute --no-auth
```

### LM Studio (local, no auth)

Start the local server from the Developer tab (default port 1234) and load a model.

```yaml
serve:
  base_url: http://127.0.0.1:1234
  model_name: <id shown by check-endpoint>
```

Run with `--no-auth`.

### llama.cpp `llama-server`

```bash
llama-server -m model.gguf --port 8080            # no auth → use --no-auth
llama-server -m model.gguf --port 8080 --api-key "$DGX_LAB_API_TOKEN"   # with auth
```

```yaml
serve:
  base_url: http://127.0.0.1:8080
  model_name: model            # llama-server accepts any name for its single model
```

### vLLM / SGLang on this machine

```bash
export DGX_LAB_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
vllm serve Qwen/Qwen3-8B --host 127.0.0.1 --port 8000 --api-key "$DGX_LAB_API_TOKEN"
```

```yaml
serve:
  base_url: http://127.0.0.1:8000
  model_name: Qwen/Qwen3-8B
```

For the digest-pinned Docker workflow (admit → serve → smoke → lock), see
`./scripts/phase1 --help` and [spark-lab-plan.md](spark-lab-plan.md).

### A GPU box elsewhere (DGX, workstation, cloud VM): use an SSH tunnel

Keep the server bound to loopback on the remote box and tunnel to it. You never
expose an unauthenticated port to the network.

```bash
# on your laptop
ssh -N -L 8000:127.0.0.1:8000 user@gpu-box
```

Then use `base_url: http://127.0.0.1:8000` locally. To dgx-lab, the tunnel
counts as loopback.

### Cluster gateway / hosted OpenAI-compatible API (HTTPS + token)

```yaml
serve:
  base_url: https://llm-gateway.your-company.example/v1
  model_name: <id shown by check-endpoint>
  api_key_env: GATEWAY_API_KEY     # the NAME of the env var, never the key
```

```bash
export GATEWAY_API_KEY='...'                 # PowerShell: $env:GATEWAY_API_KEY = '...'
dgxlab check-endpoint --config my-exp.yaml
dgxlab run my-exp.yaml --execute
```

Gateways that require extra query parameters, such as Azure's `?api-version=...`,
are supported. Query parameters that look like credentials (`?api_key=`,
`?token=`, ...) are rejected.

The same pattern works for hosted providers that expose an OpenAI-compatible
API. Check your provider's terms and pricing before running large eval suites.

---

## Reasoning models

Models such as Qwen3, DeepSeek-R1 and QwQ "think" before answering, either inline as
`<think>...</think>` or in a separate `reasoning_content` / `reasoning` field (vLLM and
SGLang with `--reasoning-parser`, Ollama). dgx-lab scores **only the final answer**:
inline reasoning blocks are stripped before the substring, regex and JSON checks run.

- The reasoning is kept on each case in `metrics.json` (`reasoning`, capped at 4,000
  characters) and the run reports how many cases had it (`reasoning_cases`).
- Thinking uses up completion tokens. The bundled smoke cases allow 16-64 tokens, which
  is often not enough. If a reply runs out inside the reasoning block, the case fails with
  a hint telling you to raise `max_tokens` or disable thinking.
- To score the raw output instead, set `eval.strip_reasoning: false` in the experiment.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `API token required ... pass --no-auth` | Local server without auth: add `--no-auth`. Otherwise set `DGX_LAB_API_TOKEN`. |
| `Non-loopback endpoints must use https://` | Use HTTPS for remote hosts, or an SSH tunnel to keep it on loopback. |
| `could not connect to the endpoint` | Server not running, wrong port, or firewall. Try `curl <base_url>/v1/models`. |
| `HTTP 401` / `403` | Wrong token, or the token is in the wrong env var. |
| `HTTP 404` on every case | Wrong base URL path (gateway prefix?) or wrong `serve.model_name`. Run `check-endpoint`. |
| `server does not implement GET /v1/models` | Fine for some servers. Skip `check-endpoint` and run directly. |
| Every case fails, `tokens_per_second` = 0 | The server didn't return `usage`. Loosen the `tokens_per_second` gate in your KPI file. |
| `reply ended inside the reasoning block` | A reasoning model (Qwen3, DeepSeek-R1) spent all of `max_tokens` thinking. Raise `serve.max_tokens` / the case's `max_tokens`, or turn thinking off (`/no_think` for Qwen3). See [Reasoning models](#reasoning-models). |
| Need a full traceback | Re-run with `DGX_LAB_DEBUG=1`. |
