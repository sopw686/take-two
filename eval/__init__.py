"""Evaluation harness: compare the app's measurements with human labels on recorded talks.

    uv run python -m eval.run                 every recording in eval/recordings/ -> eval/RESULTS.md
    uv run python -m eval.retest <take_id>... the spread of the same measurement across takes (noise floor)
    uv run python -m eval.make_synthetic      rebuild eval/recordings/synthetic-coral/ from the test fixture

See eval/README.md for how to record and label a talk.
"""
