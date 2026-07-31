"""Sub-System G — Intelligence & Search.

Vector embeddings + semantic_search + multimodal support + fine-tuning
data collection + eval harness.

Components:
- ``embeddings.py``: EmbeddingProvider + in-memory + pgvector stores
- ``multimodal.py``: Vision model client (gpt-4o-vision, claude-3-vision)
- ``finetune.py``: Fine-tuning dataset collection from agent_runs
- ``eval.py``: Eval harness scoring agent outputs against expected answers

When pgvector is unavailable (e.g. local dev), falls back to a hash-based
embedding so semantic_search still works in tests + minimal setups.
"""