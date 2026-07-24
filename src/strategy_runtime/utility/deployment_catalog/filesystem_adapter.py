"""Filesystem-backed deployment catalog."""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from strategy_runtime.utility.deployment_catalog import (
    DeploymentCatalogSnapshot,
    DeploymentCatalogUnavailableError,
    DeploymentSpecification,
    DuplicateDeploymentIdentity,
    InvalidDeploymentFile,
)
from strategy_runtime.utility.deployment_catalog.identity import (
    derive_strategy_instance_id,
)

_FORBIDDEN_OBSOLETE_FIELDS = (
    "strategy_instance_id",
    "strategy_version",
    "compatibility_profile",
)

_REQUIRED_STRINGS = (
    "ticker",
    "base_timeframe",
    "strategy_id",
)


class FilesystemDeploymentCatalog:
    """Discover immutable deployment specifications from one flat directory."""

    def __init__(self, catalog_path: Path) -> None:
        self._catalog_path = catalog_path

    def load_snapshot(self) -> DeploymentCatalogSnapshot:
        candidates = self._enumerate_candidates()
        accepted_candidates: list[DeploymentSpecification] = []
        invalid_files: list[InvalidDeploymentFile] = []

        for path in candidates:
            try:
                document = self._read_document(path)
                accepted_candidates.append(self._parse_deployment(path.name, document))
            except _InvalidDeployment as exc:
                invalid_files.append(
                    InvalidDeploymentFile(
                        source_path=path.name,
                        error_code=exc.code,
                        error_message=exc.message,
                    )
                )

        grouped: dict[str, list[DeploymentSpecification]] = defaultdict(list)
        for deployment in accepted_candidates:
            grouped[deployment.strategy_instance_id].append(deployment)

        duplicate_identities = tuple(
            DuplicateDeploymentIdentity(
                strategy_instance_id=strategy_instance_id,
                source_paths=tuple(sorted(item.source_path for item in deployments)),
            )
            for strategy_instance_id, deployments in sorted(grouped.items())
            if len(deployments) > 1
        )
        duplicate_ids = {duplicate.strategy_instance_id for duplicate in duplicate_identities}
        accepted_deployments = tuple(
            deployment
            for deployment in accepted_candidates
            if deployment.strategy_instance_id not in duplicate_ids
        )

        return DeploymentCatalogSnapshot(
            scanned_file_count=len(candidates),
            accepted_deployments=accepted_deployments,
            invalid_files=tuple(invalid_files),
            duplicate_identities=duplicate_identities,
        )

    def _enumerate_candidates(self) -> tuple[Path, ...]:
        try:
            return tuple(
                sorted(
                    (
                        path
                        for path in self._catalog_path.iterdir()
                        if path.is_file()
                        and not path.name.startswith(".")
                        and path.suffix == ".json"
                    ),
                    key=lambda path: path.name,
                )
            )
        except OSError as exc:
            raise DeploymentCatalogUnavailableError(
                "deployment catalog directory scan failed"
            ) from exc

    @staticmethod
    def _read_document(path: Path) -> Any:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise _InvalidDeployment("file_read_failed", str(exc)) from exc
        try:
            return json.loads(
                text,
                parse_constant=_reject_non_finite_number,
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise _InvalidDeployment("invalid_json", str(exc)) from exc

    @staticmethod
    def _parse_deployment(filename: str, document: Any) -> DeploymentSpecification:
        if not isinstance(document, dict):
            raise _InvalidDeployment("invalid_root")
        for field_name in _FORBIDDEN_OBSOLETE_FIELDS:
            if field_name in document:
                raise _InvalidDeployment("forbidden_obsolete_field", field_name)
        if "enabled" not in document:
            raise _InvalidDeployment("missing_required_field", "enabled")
        if not isinstance(document["enabled"], bool):
            raise _InvalidDeployment("invalid_field_type", "enabled")
        for field_name in _REQUIRED_STRINGS:
            if field_name not in document:
                raise _InvalidDeployment("missing_required_field", field_name)
            value = document[field_name]
            if not isinstance(value, str):
                raise _InvalidDeployment("invalid_field_type", field_name)
            if not value.strip():
                raise _InvalidDeployment("empty_required_field", field_name)
        if "raw_spec" not in document:
            raise _InvalidDeployment("missing_required_field", "raw_spec")
        raw_spec = document["raw_spec"]
        if not isinstance(raw_spec, dict):
            raise _InvalidDeployment("invalid_raw_spec")

        strategy_instance_id = derive_strategy_instance_id(
            strategy_id=document["strategy_id"],
            ticker=document["ticker"],
            base_timeframe=document["base_timeframe"],
            raw_spec=raw_spec,
        )

        return DeploymentSpecification(
            strategy_instance_id=strategy_instance_id,
            enabled=document["enabled"],
            instrument=document["ticker"],
            base_timeframe=document["base_timeframe"],
            strategy_id=document["strategy_id"],
            raw_spec=raw_spec,
            source_path=filename,
        )


class _InvalidDeployment(Exception):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


def _reject_non_finite_number(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")
