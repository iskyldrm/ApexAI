"""OpenTelemetry tracing for the agent runtime.

Sets up the OTel SDK once (idempotent — safe to call from FastAPI startup)
and exposes `tracer` for manual spans around LLM / tool / safety calls.

Spans follow the hierarchy:

    HTTP POST /agent/converse  (FastAPI auto-instrumentation)
      └─ agent.run               (role, agent_run_id, finish_reason)
          ├─ llm.completion      (model, input_tokens, output_tokens, cost_usd)
          ├─ tool.execute         (tool_name, ok)
          └─ safety.check         (guard_name, tripped)

If no OTLP endpoint is configured, we use the in-memory exporter for
tests; production should set OTEL_EXPORTER_OTLP_ENDPOINT to a collector
(Jaeger, Tempo, Honeycomb, etc.).
"""
from __future__ import annotations

import logging
import os
from threading import Lock

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

try:
    # OTel >=1.20 moved InMemorySpanExporter out of the SDK into the testing
    # util package. We import lazily so production code doesn't require it.
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )
except ImportError:  # pragma: no cover - older OTel fallback
    try:
        from opentelemetry.sdk.trace.export import (
            InMemorySpanExporter,  # type: ignore[attr-defined]
        )
    except ImportError:
        InMemorySpanExporter = None  # type: ignore[assignment,misc]  # noqa: N816


logger = logging.getLogger(__name__)


# Module-level singleton state
_init_lock = Lock()
_in_memory_exporter: InMemorySpanExporter | None = None


def init_tracing(service_name: str = "apexai-agent") -> None:
    """Initialize OTel tracing. Idempotent.

    Reads:
    - OTEL_EXPORTER_OTLP_ENDPOINT — if set, exports to that collector
    - OTEL_DISABLED=true — disables tracing entirely (faster tests)
    """
    global _in_memory_exporter
    with _init_lock:
        existing = trace.get_tracer_provider()
        if isinstance(existing, TracerProvider) and getattr(existing, "_apexai_init", False):
            return  # already initialized

        if os.environ.get("OTEL_DISABLED", "").lower() in ("1", "true", "yes"):
            # Use a no-op provider — no spans collected
            provider = TracerProvider()
            setattr(provider, "_apexai_init", True)
            trace.set_tracer_provider(provider)
            return

        resource = Resource.create({SERVICE_NAME: service_name})
        provider = TracerProvider(resource=resource)
        setattr(provider, "_apexai_init", True)

        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        if endpoint:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
            )
            logger.info("OTel: exporting to %s", endpoint)
        elif os.environ.get("OTEL_CONSOLE") == "1":
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
            logger.info("OTel: console exporter enabled")
        else:
            # In-memory exporter — spans collected for test assertions
            if InMemorySpanExporter is None:
                logger.warning(
                    "InMemorySpanExporter not available in this OTel version — "
                    "tracing will produce no output (set OTEL_EXPORTER_OTLP_ENDPOINT)"
                )
            else:
                _in_memory_exporter = InMemorySpanExporter()
                provider.add_span_processor(SimpleSpanProcessor(_in_memory_exporter))
                logger.info("OTel: in-memory exporter (set OTEL_EXPORTER_OTLP_ENDPOINT for prod)")

        trace.set_tracer_provider(provider)


def get_in_memory_exporter() -> "InMemorySpanExporter | None":  # type: ignore[name-defined]
    """Test helper: returns the in-memory exporter if initialized."""
    return _in_memory_exporter


def reset_in_memory_exporter() -> None:
    """Test helper: clear captured spans."""
    if _in_memory_exporter is not None:
        _in_memory_exporter.clear()


# Convenience tracer — used everywhere in the runtime
tracer = trace.get_tracer("apexai.agent")