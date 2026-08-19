"""Serving-side package: loads and uses already-trained target buckets.

No training happens here (see CLAUDE.md §1/§13) — that lives in the
separate, out-of-scope model factory. Everything that knows about a
specific model format (AutoGluon, Chemprop) is isolated in
model_adapter.py so the rest of the app never imports them directly.
"""
