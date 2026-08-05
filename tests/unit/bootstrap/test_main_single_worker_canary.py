"""Documentation/canary test (11.1): `bootstrap/main.py`'s `uvicorn.run(...)`
call carries no `workers=` argument. This is not a runtime enforcement
mechanism -- multi-process/multi-worker deployment remains unsupported and
undetected at runtime, exactly as already documented for
`StrategyInstanceKeyedMutexRegistry`'s "no cross-process guarantee". This
canary only guards against silently regressing into a multi-worker uvicorn
invocation, which would break this change's single-worker
`CommittedBarIntakeWorker` concurrency guarantee (each process would get its
own independent intake boundary and worker, uncoordinated with any other)."""

import ast
from pathlib import Path


def test_uvicorn_run_is_invoked_with_no_workers_argument() -> None:
    source_path = Path("src/strategy_runtime/bootstrap/main.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))

    run_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "uvicorn"
    ]

    assert len(run_calls) == 1, "expected exactly one uvicorn.run(...) call in bootstrap/main.py"
    keyword_names = {keyword.arg for keyword in run_calls[0].keywords}
    assert "workers" not in keyword_names
