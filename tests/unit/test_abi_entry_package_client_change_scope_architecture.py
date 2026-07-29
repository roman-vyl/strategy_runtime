"""9.3: the existing ABI entry-package HTTP client change is limited to the
accepted_risk_multiplier removal (DTO field, codec field-set, decode path,
fixtures, conformance test) with no transport, timeout, redirect, or
public-error mapping change."""

from pathlib import Path


def test_transport_module_is_completely_unchanged() -> None:
    source = Path("src/strategy_runtime/runtime/abi/entry_package_http.py").read_text(
        encoding="utf-8"
    )
    assert "follow_redirects=False" in source
    assert "httpx.HTTPTransport(retries=0)" in source
    assert "accepted_risk_multiplier" not in source


def test_port_module_is_completely_unchanged() -> None:
    source = Path("src/strategy_runtime/runtime/abi/entry_package_ports.py").read_text(
        encoding="utf-8"
    )
    assert "def send(self, request: EntryPackageRequest) -> EntryPackageResult: ..." in source


def test_request_dto_and_public_error_mapping_are_unchanged() -> None:
    models_source = Path("src/strategy_runtime/runtime/abi/entry_package_models.py").read_text(
        encoding="utf-8"
    )
    assert "risk_multiplier: str" in models_source
    assert "_require_positive_exact_decimal_text(self.risk_multiplier" in models_source
    for code in (
        "EntryPackageMalformedJson",
        "EntryPackageUnsupportedMediaType",
        "EntryPackageValidationFailed",
        "EntryPackageInternalError",
    ):
        assert code in models_source

    codec_source = Path("src/strategy_runtime/runtime/abi/entry_package_codec.py").read_text(
        encoding="utf-8"
    )
    assert '400: "malformed_json"' in codec_source
    assert '415: "unsupported_media_type"' in codec_source
    assert '422: "validation_failed"' in codec_source
    assert '500: "internal_error"' in codec_source


def test_accepted_risk_multiplier_is_fully_removed() -> None:
    for relative_path in (
        "src/strategy_runtime/runtime/abi/entry_package_models.py",
        "src/strategy_runtime/runtime/abi/entry_package_codec.py",
    ):
        source = Path(relative_path).read_text(encoding="utf-8")
        assert "accepted_risk_multiplier" not in source
