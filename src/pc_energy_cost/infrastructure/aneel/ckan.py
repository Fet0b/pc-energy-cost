"""Cliente CKAN da ANEEL: package_show e escolha de recurso (sem rede própria)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from ...domain.shared.errors import DomainError

CKAN_API = "https://dadosabertos.aneel.gov.br/api/3/action"

Fetch = Callable[[str], bytes]


@dataclass(frozen=True)
class ResourceRef:
    resource_id: str
    url: str
    metadata_modified: str  # do pacote (proveniência)
    resource_metadata_modified: str | None


def _mismatch(message: str) -> DomainError:
    return DomainError("schema_mismatch", message)


def package_show(fetch: Fetch, package_id: str) -> dict[str, Any]:
    """Consulta `package_show` via `fetch` injetado e devolve o JSON validado."""
    url = f"{CKAN_API}/package_show?id={quote(package_id, safe='-_.')}"
    try:
        data = json.loads(fetch(url))
    except (ValueError, UnicodeDecodeError) as exc:
        raise _mismatch(f"resposta do CKAN não é JSON válido ({package_id})") from exc
    _result(data)
    return data


def _result(package_json: Any) -> dict[str, Any]:
    result = package_json.get("result") if isinstance(package_json, dict) else None
    if not isinstance(result, dict) or not isinstance(result.get("resources"), list):
        raise _mismatch("resposta do CKAN sem 'result.resources'")
    return result


def _ref(result: dict[str, Any], resource: dict[str, Any]) -> ResourceRef:
    url = resource.get("url")
    modified = result.get("metadata_modified")
    if not isinstance(url, str) or not url or not isinstance(modified, str):
        raise _mismatch("recurso CKAN sem 'url' ou pacote sem 'metadata_modified'")
    res_modified = resource.get("metadata_modified")
    return ResourceRef(
        resource_id=str(resource.get("id")),
        url=url,
        metadata_modified=modified,
        resource_metadata_modified=res_modified if isinstance(res_modified, str) else None,
    )


def resolve_resource(
    package_json: Any,
    resource_id: str,
    fallback_name_contains: str | None = None,
) -> ResourceRef:
    """Escolhe o recurso por `id`; fallback só com exatamente um CSV cujo nome contém o texto."""
    result = _result(package_json)
    resources = [r for r in result["resources"] if isinstance(r, dict)]
    for resource in resources:
        if resource.get("id") == resource_id:
            return _ref(result, resource)
    if fallback_name_contains is None:
        raise _mismatch(f"recurso {resource_id} ausente no pacote")
    candidates = [
        r for r in resources
        if str(r.get("format", "")).upper() == "CSV"
        and fallback_name_contains in str(r.get("name", ""))
    ]
    if len(candidates) != 1:
        raise _mismatch(
            f"recurso {resource_id} ausente e fallback com {len(candidates)} candidatos "
            f"(esperado exatamente 1)"
        )
    return _ref(result, candidates[0])
