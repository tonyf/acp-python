# Agent Communication Protocol (ACP)

## Minimal Testing

Start a local NATS server and a openai compatible completions server with ollama. The ollama server will be used in the example ChatAgent `src/acp_python/agents/chat.py`.

```bash
nats server run --jetstream --clean --port 4222 --no-tlsfirst --verbose
```

```bash
ollama serve
```

Run a minimal chat agent. This will run both the `ChatAgent` and a `ConsoleUserAgent` to create a user-promptable conversation.

```bash
python -m acp_python.agents.user chat --nats_url=local:<NATS_TOKEN>@0.0.0.0:4222
```
