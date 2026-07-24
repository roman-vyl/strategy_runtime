from pathlib import Path


def test_processing_journal_has_no_forbidden_imports() -> None:
    root = Path("src/strategy_runtime")
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            root / "utility/processing_journal/models.py",
            root / "utility/processing_journal/jsonl_adapter.py",
        ]
    )
    forbidden = (
        "deployment_catalog",
        "domain.activation",
        "deployment_selection",
        "strategy_engine",
        "fastapi",
        "process_committed_bar",
        "adapters.journal",
        "domain.journal_event",
    )
    for token in forbidden:
        assert token not in text
