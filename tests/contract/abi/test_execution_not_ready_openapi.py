import json
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "filename",
    [
        "abi-entry-package-api-v1.json",
        "abi-open-position-lookup-api-v1.json",
        "abi-entry-cycle-recovery-api-v1.json",
        "abi-position-management-api-v1.json",
    ],
)
def test_execution_not_ready_is_a_closed_pre_admission_error(filename: str) -> None:
    abi = Path(__file__).resolve().parents[4] / "abi_executor_bot"
    document = json.loads((abi / "docs" / "openapi" / filename).read_text())
    schema = document["components"]["schemas"]["ExecutionNotReady"]
    assert schema["additionalProperties"] is False
    error = schema["properties"]["error"]
    assert error["additionalProperties"] is False
    assert error["properties"]["code"]["const"] == "execution_not_ready"
    assert set(error["required"]) == {"code", "message"}
    for path in document["paths"].values():
        for operation in path.values():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            response = operation["responses"]["503"]["content"]["application/json"]
            assert response["schema"] == {"$ref": "#/components/schemas/ExecutionNotReady"}
            assert response["example"] == {
                "error": {"code": "execution_not_ready", "message": "execution is not ready"}
            }
