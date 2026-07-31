"""Tests for Sub-System G (intelligence + embeddings + multimodal + eval)."""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from app.intelligence.embeddings import (
    EMBEDDING_DIM,
    HashEmbeddingProvider,
    InMemoryVectorStore,
    SentenceTransformerProvider,
    _cosine,
    get_default_provider,
    get_vector_store,
    index_text,
    reset_for_tests,
    semantic_search,
)
from app.intelligence.eval import (
    EvalCase,
    EvalHarness,
    contains_match,
    cosine_match,
    exact_match,
    load_jsonl,
)
from app.intelligence.finetune import (
    to_anthropic_format,
    to_openai_format,
    write_jsonl,
)
from app.intelligence.multimodal import ImageInput, VisionClient


@pytest.fixture(autouse=True)
def _reset_store():
    reset_for_tests()
    yield
    reset_for_tests()


# -------------------- Embeddings --------------------


def test_embedding_dim_is_384():
    assert EMBEDDING_DIM == 384


def test_hash_provider_is_deterministic():
    p = HashEmbeddingProvider()
    a = p.embed("hello world")
    b = p.embed("hello world")
    assert a == b


def test_hash_provider_different_texts_yield_different_vectors():
    p = HashEmbeddingProvider()
    a = p.embed("hello world")
    b = p.embed("goodbye world")
    # Vectors should not be identical
    assert a != b


def test_hash_provider_returns_unit_vectors():
    """Each vector should be roughly unit-length (normalized)."""
    p = HashEmbeddingProvider()
    vec = p.embed("test text here")
    norm = sum(x * x for x in vec) ** 0.5
    assert abs(norm - 1.0) < 1e-6


def test_hash_provider_short_text_returns_nonzero_vector():
    """Even very short text produces a non-zero vector."""
    p = HashEmbeddingProvider()
    vec = p.embed("a")
    assert any(x != 0 for x in vec)


def test_get_default_provider_returns_hash_by_default():
    p = get_default_provider()
    assert isinstance(p, HashEmbeddingProvider)


def test_sentence_transformer_provider_falls_back_on_missing_model():
    """If sentence-transformers isn't installed, fall back to hash."""
    p = SentenceTransformerProvider(model_name="nonexistent-model-xyz")
    # Should not raise — falls back to HashEmbeddingProvider
    vec = p.embed("test")
    assert len(vec) == EMBEDDING_DIM


# -------------------- Vector store --------------------


def test_in_memory_store_add_and_search():
    store = InMemoryVectorStore()
    p = HashEmbeddingProvider()
    store.add("1", "hello", p.embed("hello"), {"src": "test"})
    store.add("2", "goodbye", p.embed("goodbye"), {"src": "test"})
    results = store.search(p.embed("hello"), limit=5)
    assert len(results) == 2
    assert results[0].id == "1"  # most similar to itself


def test_in_memory_store_replace_existing():
    store = InMemoryVectorStore()
    p = HashEmbeddingProvider()
    store.add("1", "old", p.embed("old"))
    store.add("1", "new", p.embed("new"))
    assert len(store) == 1
    assert store._items[0].text == "new"


def test_in_memory_store_threshold_filters_low_scores():
    store = InMemoryVectorStore()
    p = HashEmbeddingProvider()
    store.add("1", "a", p.embed("a"))
    store.add("2", "completely unrelated", p.embed("z"))
    # Threshold 0.999 → only near-identical matches
    results = store.search(p.embed("a"), limit=5, threshold=0.999)
    assert len(results) == 1
    assert results[0].id == "1"


# -------------------- semantic_search high-level --------------------


def test_semantic_search_finds_self_match():
    index_text(id="doc-1", text="authentication middleware")
    index_text(id="doc-2", text="database migrations")
    results = semantic_search("authentication middleware", limit=2)
    assert len(results) == 2
    assert results[0]["id"] == "doc-1"


def test_semantic_search_returns_metadata():
    index_text(id="d", text="x", metadata={"path": "/foo.py", "line": 42})
    results = semantic_search("x", limit=1)
    assert results[0]["metadata"] == {"path": "/foo.py", "line": 42}


def test_semantic_search_with_limit():
    for i in range(10):
        index_text(id=f"d{i}", text=f"doc {i}")
    results = semantic_search("doc", limit=3)
    assert len(results) == 3


def test_cosine_function_basic():
    a = [1.0, 0.0, 0.0]
    b = [1.0, 0.0, 0.0]
    assert _cosine(a, b) == 1.0

    c = [0.0, 1.0, 0.0]
    assert abs(_cosine(a, c)) < 1e-6


# -------------------- Multimodal --------------------


@pytest.mark.asyncio
async def test_vision_client_stub_when_unknown_provider():
    """An unknown provider returns a deterministic stub result."""
    client = VisionClient(provider="unknown")
    result = await client.describe_image(
        ImageInput(data=b"\x89PNG\r\n\x1a\n", mime_type="image/png"),
        prompt="What's in this image?",
    )
    assert "stub-vision" in result.content
    assert "image" in result.content
    assert result.model == "<stub>"


@pytest.mark.asyncio
async def test_vision_client_describe_images_with_empty_list():
    client = VisionClient(provider="unknown")
    result = await client.describe_images([], prompt="test")
    assert "stub-vision" in result.content


@pytest.mark.asyncio
async def test_vision_client_multi_image_falls_back_to_first():
    """Unknown provider with multi-image falls back to describing the first."""
    client = VisionClient(provider="unknown")
    images = [
        ImageInput(data=b"a", mime_type="image/png"),
        ImageInput(data=b"b", mime_type="image/png"),
    ]
    result = await client.describe_images(images, prompt="p")
    assert "1 bytes" in result.content  # size of first image


def test_image_input_defaults():
    img = ImageInput(data=b"x")
    assert img.mime_type == "image/png"
    assert img.alt_text == ""


# -------------------- Fine-tuning data export --------------------


@pytest.mark.asyncio
async def test_export_dataset_returns_records():
    from sqlalchemy import delete
    from datetime import datetime

    from app.db import async_session_maker
    from app.models.agent_run import AgentRun
    from app.models.conversation import Conversation

    async with async_session_maker() as session:
        # Clean any prior data with this org
        await session.execute(delete(AgentRun).where(AgentRun.role == "ANL_FT"))

        conv = Conversation(
            role="ANL_FT",
            status="finished",
            summary="How do I center a div?",
        )
        session.add(conv)
        await session.flush()
        run = AgentRun(
            conversation_id=conv.id,
            role="ANL_FT",
            model="gpt-4o-mini",
            status="finished",
            steps=2,
            input_tokens=10,
            output_tokens=20,
        )
        session.add(run)
        await session.commit()

        from app.intelligence.finetune import export_dataset
        records = await export_dataset(session, role="ANL_FT")
        assert len(records) >= 1
        rec = records[0]
        assert rec["prompt"] == "How do I center a div?"
        assert rec["metadata"]["role"] == "ANL_FT"
        assert rec["metadata"]["steps"] == 2


@pytest.mark.asyncio
async def test_export_dataset_min_steps_filter():
    from sqlalchemy import delete
    from app.db import async_session_maker
    from app.models.agent_run import AgentRun
    from app.models.conversation import Conversation

    from app.intelligence.finetune import export_dataset

    async with async_session_maker() as session:
        await session.execute(delete(AgentRun).where(AgentRun.role == "FILTER_TEST"))

        for steps in [1, 2, 3, 5]:
            conv = Conversation(
                role="FILTER_TEST",
                status="finished",
                summary=f"prompt-{steps}",
            )
            session.add(conv)
            await session.flush()
            run = AgentRun(
                conversation_id=conv.id,
                role="FILTER_TEST",
                model="gpt-4o-mini",
                status="finished",
                steps=steps,
            )
            session.add(run)
        await session.commit()

        records = await export_dataset(session, role="FILTER_TEST", min_steps=3)
        assert all(r["metadata"]["steps"] >= 3 for r in records)
        # steps=1, 2 are filtered out
        step_set = {r["metadata"]["steps"] for r in records}
        assert step_set == {3, 5}


def test_write_jsonl_and_reload():
    records = [
        {"prompt": "a", "completion": "b", "metadata": {"role": "DEV"}},
        {"prompt": "c", "completion": "d", "metadata": {"role": "QA"}},
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        path = f.name
    n = write_jsonl(records, path)
    assert n == 2

    with open(path) as f:
        lines = [json.loads(l) for l in f if l.strip()]
    assert lines == records
    Path(path).unlink()


def test_to_openai_format():
    records = [{"prompt": "p1", "completion": "c1"}]
    out = to_openai_format(records)
    assert len(out) == 1
    assert out[0]["messages"][0]["role"] == "user"
    assert out[0]["messages"][0]["content"] == "p1"
    assert out[0]["messages"][1]["role"] == "assistant"
    assert out[0]["messages"][1]["content"] == "c1"


def test_to_anthropic_format():
    records = [{"prompt": "p1", "completion": "c1"}]
    out = to_anthropic_format(records)
    assert "Human: p1" in out[0]["prompt"]
    assert "Assistant:" in out[0]["prompt"]
    assert "c1" in out[0]["completion"]


# -------------------- Eval harness --------------------


def test_exact_match_passes_on_identical():
    passed, score = exact_match("hello", "hello")
    assert passed is True
    assert score == 1.0


def test_exact_match_case_insensitive():
    passed, score = exact_match("Hello World", "hello world")
    assert passed is True


def test_exact_match_fails_on_different():
    passed, score = exact_match("hello", "world")
    assert passed is False
    assert score == 0.0


def test_contains_match_passes():
    passed, score = contains_match("the quick brown fox", "brown")
    assert passed is True


def test_contains_match_case_insensitive():
    passed, _ = contains_match("The Quick BROWN Fox", "brown")
    assert passed is True


def test_contains_match_fails():
    passed, _ = contains_match("hello", "xyz")
    assert passed is False


def test_contains_empty_expected_always_passes():
    passed, score = contains_match("anything", "")
    assert passed is True
    assert score == 1.0


def test_cosine_match_with_hash_provider():
    p = HashEmbeddingProvider()
    passed, score = cosine_match("hello world", "hello world", p, 0.9)
    assert passed is True
    assert score > 0.99


def test_eval_case_dataclass():
    case = EvalCase(id="t1", prompt="q", expected="a")
    assert case.scoring == "contains"
    assert case.threshold == 0.7


def test_eval_harness_run_with_no_actuals():
    """No actuals → auto-pass (case.expected as actual)."""
    harness = EvalHarness()
    cases = [
        EvalCase(id="a", prompt="q1", expected="a1"),
        EvalCase(id="b", prompt="q2", expected="a2"),
    ]
    results = asyncio.run(harness.run(cases))
    assert len(results) == 2
    assert all(r.passed for r in results)


def test_eval_harness_run_with_actuals():
    harness = EvalHarness()
    cases = [EvalCase(id="a", prompt="q1", expected="a1", scoring="exact_match")]
    actuals = {"a": "a1"}
    results = asyncio.run(harness.run(cases, actuals))
    assert results[0].passed


def test_eval_harness_report_aggregate():
    harness = EvalHarness()
    cases = [
        EvalCase(id="p", prompt="q", expected="a", scoring="exact_match"),
        EvalCase(id="f", prompt="q", expected="a", scoring="exact_match"),
    ]
    actuals = {"p": "a", "f": "wrong"}
    results = asyncio.run(harness.run(cases, actuals))
    report = harness.report(results)
    assert report["total"] == 2
    assert report["passed"] == 1
    assert report["failed"] == 1
    assert report["pass_rate"] == 0.5


def test_eval_harness_unknown_scoring_fails():
    harness = EvalHarness()
    case = EvalCase(id="x", prompt="q", expected="a", scoring="unknown_metric")
    result = harness.score(case, "a")
    assert result.passed is False
    assert "Unknown" in result.reason


def test_eval_harness_report_empty():
    harness = EvalHarness()
    report = harness.report([])
    assert report["total"] == 0
    assert report["pass_rate"] == 0.0


def test_load_jsonl():
    data = [
        {"id": "a", "prompt": "q1", "expected": "a1"},
        {"id": "b", "prompt": "q2", "expected": "a2", "scoring": "exact_match"},
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        for r in data:
            f.write(json.dumps(r) + "\n")
        path = f.name
    cases = load_jsonl(path)
    assert len(cases) == 2
    assert cases[0].id == "a"
    assert cases[1].scoring == "exact_match"
    Path(path).unlink()


def test_load_jsonl_skips_blank_lines():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write('{"id":"a","prompt":"q","expected":"e"}\n')
        f.write("\n")
        f.write('{"id":"b","prompt":"q","expected":"e"}\n')
        f.write("\n")
        path = f.name
    cases = load_jsonl(path)
    assert len(cases) == 2
    Path(path).unlink()