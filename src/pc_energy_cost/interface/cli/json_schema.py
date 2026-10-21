"""Saída JSON v1 da CLI: serialização, schema e validador mínimo (stdlib)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from ...application.refresh_catalog import RefreshResult
from ...domain.energy_estimation.estimate import CostEstimate
from ...domain.location_supplier.model import SupplierLink
from ...domain.shared.errors import DomainError

SCHEMA_VERSION = "1"

_STR = {"type": "string"}
_STR_LIST = {"type": "array", "items": _STR}
_NULLABLE_STR = {"type": ["string", "null"]}

_CATALOG = {
    "type": "object",
    "required": ["refreshed", "stale", "age_seconds", "vigencia", "label"],
    "properties": {
        "refreshed": {"type": "boolean"},
        "stale": {"type": "boolean"},
        "age_seconds": _STR,
        "vigencia": {
            "type": ["object", "null"],
            "required": ["inicio", "fim"],
            "properties": {"inicio": _STR, "fim": _STR},
        },
        "label": _STR,
        "tariffs_loaded": {"type": ["integer", "null"]},
    },
}

_ESTIMATE = {
    "type": "object",
    "required": [
        "label", "energy_kwh", "cost_brl", "cost_unrounded_brl", "taxa_total", "tarifa_base",
        "adicional", "adicional_tipo", "inclusoes_declaradas", "warnings", "scope",
        "requested_duration", "coverage_duration", "excluded_duration", "excluded_intervals",
        "partial_data", "slices", "provenance", "supplier", "catalog",
    ],
    "properties": {
        "label": _STR,
        "energy_kwh": _STR,
        "cost_brl": _STR,
        "cost_unrounded_brl": _STR,
        "taxa_total": _STR,
        "tarifa_base": _STR,
        "adicional": _STR,
        "adicional_tipo": _NULLABLE_STR,
        "inclusoes_declaradas": _STR_LIST,
        "warnings": _STR_LIST,
        "scope": _STR,
        "requested_duration": _STR,
        "coverage_duration": _STR,
        "excluded_duration": _STR,
        "excluded_intervals": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["start", "end", "reason"],
                "properties": {"start": _STR, "end": _STR, "reason": _STR},
            },
        },
        "partial_data": {"type": "boolean"},
        "slices": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["start", "end", "rate", "energy_kwh", "projected"],
                "properties": {
                    "start": _STR, "end": _STR, "rate": _STR, "energy_kwh": _STR,
                    "projected": {"type": "boolean"},
                },
            },
        },
        "provenance": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "url", "resource_id", "sha256", "fetched_at", "reh", "data_geracao",
                    "inicio", "fim", "units", "warning",
                ],
            },
        },
        "supplier": {
            "type": ["object", "null"],
            "required": ["cnpj", "sig_agente"],
        },
        "catalog": {"anyOf": [_CATALOG, {"type": "null"}]},
    },
}

_NULLABLE_STR_T = {"type": ["string", "null"]}

_SESSION_ROW = {
    "type": "object",
    "required": [
        "id", "started_at", "ended_at", "end_reason", "scope", "energy_basis", "measured_kwh",
        "assumed_kwh", "covered_s", "excluded_s", "partial_data",
    ],
    "properties": {
        "id": {"type": "integer"},
        "started_at": _STR,
        "ended_at": _NULLABLE_STR_T,
        "end_reason": _NULLABLE_STR_T,
        "scope": _STR,
        "energy_basis": _STR,
        "measured_kwh": _STR,
        "assumed_kwh": _STR,
        "covered_s": _STR,
        "excluded_s": _STR,
        "partial_data": {"type": "boolean"},
    },
}

_SESSION_TICK = {
    "type": "object",
    "required": [
        "label", "session_id", "at", "measured_kwh", "assumed_kwh", "energy_kwh", "cost_brl",
        "stale", "stale_for_s", "covered_s", "excluded_s", "partial_data", "final",
        "end_reason", "warnings",
    ],
    "properties": {
        "label": _STR,
        "session_id": {"type": "integer"},
        "at": _STR,
        "measured_kwh": _STR,
        "assumed_kwh": _STR,
        "energy_kwh": _STR,
        "cost_brl": _NULLABLE_STR_T,
        "stale": {"type": "boolean"},
        "stale_for_s": _NULLABLE_STR_T,
        "covered_s": _STR,
        "excluded_s": _STR,
        "partial_data": {"type": "boolean"},
        "final": {"type": "boolean"},
        "end_reason": _NULLABLE_STR_T,
        "warnings": _STR_LIST,
    },
}

_SESSION_LIST = {
    "type": "object",
    "required": ["label", "sessions"],
    "properties": {"label": _STR, "sessions": {"type": "array", "items": _SESSION_ROW}},
}

_SESSION_SUMMARY = {
    "type": "object",
    "required": [
        "label", "since", "until", "sessions", "measured_kwh", "assumed_kwh",
        "measured_cost_brl", "assumed_cost_brl", "cost_brl", "covered_s", "excluded_s",
        "partial_data", "slices",
    ],
    "properties": {
        "label": _STR,
        "since": _STR,
        "until": _STR,
        "sessions": {"type": "integer"},
        "measured_kwh": _STR,
        "assumed_kwh": _STR,
        "measured_cost_brl": _STR,
        "assumed_cost_brl": _STR,
        "cost_brl": _STR,
        "covered_s": _STR,
        "excluded_s": _STR,
        "partial_data": {"type": "boolean"},
        "slices": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["start", "end", "measured_kwh", "assumed_kwh", "rate"],
                "properties": {
                    "start": _STR, "end": _STR, "measured_kwh": _STR, "assumed_kwh": _STR,
                    "rate": _NULLABLE_STR_T,
                },
            },
        },
    },
}

_EXPORT = {
    "type": "object",
    "required": ["label", "session_id", "truncated", "delivered", "text"],
    "properties": {
        "label": _STR,
        "session_id": {"type": "integer"},
        "truncated": {"type": "boolean"},
        "delivered": {"type": "boolean"},
        "text": _STR,
    },
}

COMMANDS = (
    "estimar", "atualizar-catalogo", "sessao acompanhar", "sessao listar", "sessao custo",
    "sessao exportar",
)

_ERROR = {
    "type": "object",
    "required": ["code", "message"],
    "properties": {
        "code": _STR,
        "message": _STR,
        "candidates": {
            "type": "array",
            "items": {"type": "object", "required": ["cnpj", "sig_agente"]},
        },
    },
}

SCHEMA: dict[str, Any] = {
    "anyOf": [
        {
            "type": "object",
            "required": ["schema_version", "ok", "command", "result"],
            "properties": {
                "schema_version": {"const": SCHEMA_VERSION},
                "ok": {"const": True},
                "command": {"enum": list(COMMANDS)},
                "result": {
                    "anyOf": [
                        _ESTIMATE, _CATALOG, _SESSION_TICK, _SESSION_LIST, _SESSION_SUMMARY,
                        _EXPORT,
                    ]
                },
            },
        },
        {
            "type": "object",
            "required": ["schema_version", "ok", "error"],
            "properties": {
                "schema_version": {"const": SCHEMA_VERSION},
                "ok": {"const": False},
                "error": _ERROR,
            },
        },
    ]
}

_TYPES: dict[str, Any] = {
    "object": Mapping, "array": (list, tuple), "string": str, "null": type(None),
    "boolean": bool,
}


def _is_type(value: Any, name: str) -> bool:
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name in ("string", "object", "array", "null") and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES[name])


def _errors(value: Any, schema: Mapping[str, Any], path: str) -> list[str]:
    if "anyOf" in schema:
        branches = [_errors(value, s, path) for s in schema["anyOf"]]
        if any(not b for b in branches):
            return []
        return [f"{path}: nenhuma alternativa válida ({'; '.join(b[0] for b in branches if b)})"]
    if "const" in schema and (value != schema["const"] or type(value) is not type(schema["const"])):
        return [f"{path}: esperado {schema['const']!r}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path}: fora de {schema['enum']!r}"]
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(value, n) for n in names):
            return [f"{path}: tipo inválido ({type(value).__name__}), esperado {names}"]
    found: list[str] = []
    if isinstance(value, Mapping):
        for key in schema.get("required", ()):
            if key not in value:
                found.append(f"{path}: campo obrigatório ausente {key!r}")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                found.extend(_errors(value[key], sub, f"{path}.{key}"))
    elif isinstance(value, (list, tuple)) and "items" in schema:
        for i, item in enumerate(value):
            found.extend(_errors(item, schema["items"], f"{path}[{i}]"))
    return found


def validate(document: Any, schema: Mapping[str, Any] = SCHEMA) -> None:
    """Valida o documento (subconjunto do JSON Schema); falha com ValueError."""
    problems = _errors(document, schema, "$")
    if problems:
        raise ValueError("; ".join(problems))


def _dec(value: Decimal) -> str:
    return f"{value:f}"


def _seconds(delta: timedelta) -> str:
    micros = delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds
    return _dec((Decimal(micros) / Decimal(1_000_000)).normalize()) if micros % 1_000_000 else str(
        micros // 1_000_000
    )


def _day(value: date) -> str:
    return value.isoformat()


def _when(value: datetime) -> str:
    return value.isoformat()


def supplier_to_json(link: SupplierLink | None) -> dict[str, Any] | None:
    if link is None:
        return None
    return {
        "cnpj": link.distributor.cnpj,
        "sig_agente": link.distributor.sig_agente,
        "ibge_code": link.municipality.ibge_code,
        "municipality": link.municipality.name,
        "uf": link.municipality.uf,
        "user_confirmed": link.user_confirmed,
    }


def catalog_to_json(result: RefreshResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    vigencia = (
        None
        if result.vigencia is None
        else {"inicio": _day(result.vigencia[0]), "fim": _day(result.vigencia[1])}
    )
    return {
        "refreshed": result.refreshed,
        "stale": result.stale,
        "age_seconds": _seconds(result.age),
        "vigencia": vigencia,
        "label": result.label,
        "tariffs_loaded": result.tariffs_loaded,
    }


def estimate_to_json(
    estimate: CostEstimate,
    label: str,
    supplier: SupplierLink | None = None,
    catalog: RefreshResult | None = None,
) -> dict[str, Any]:
    return {
        "label": label,
        "energy_kwh": _dec(estimate.energy.value),
        "cost_brl": estimate.cost.to_json(),
        "cost_unrounded_brl": _dec(estimate.cost_unrounded),
        "taxa_total": _dec(estimate.taxa_total),
        "tarifa_base": _dec(estimate.tarifa_base),
        "adicional": _dec(estimate.adicional),
        "adicional_tipo": estimate.adicional_tipo,
        "inclusoes_declaradas": list(estimate.inclusoes_declaradas),
        "warnings": list(estimate.warnings),
        "scope": estimate.scope.value,
        "requested_duration": _seconds(estimate.requested_duration),
        "coverage_duration": _seconds(estimate.coverage_duration),
        "excluded_duration": _seconds(estimate.excluded_duration),
        "excluded_intervals": [
            {"start": _when(i.start), "end": _when(i.end), "reason": i.reason}
            for i in estimate.excluded_intervals
        ],
        "partial_data": estimate.partial_data,
        "slices": [
            {
                "start": _when(s.slice.start),
                "end": _when(s.slice.end),
                "rate": _dec(s.rate),
                "energy_kwh": _dec(s.energy.value),
                "projected": s.slice.window.projected,
            }
            for s in estimate.slices
        ],
        "provenance": [
            {
                "url": p.source.url,
                "resource_id": p.source.resource_id,
                "sha256": p.source.sha256,
                "fetched_at": _when(p.source.fetched_at),
                "metadata_modified": p.source.metadata_modified,
                "last_modified": p.source.last_modified,
                "reh": p.reh,
                "data_geracao": _day(p.data_geracao),
                "inicio": _day(p.inicio),
                "fim": _day(p.fim),
                "units": p.units,
                "warning": p.warning,
            }
            for p in estimate.provenance
        ],
        "supplier": supplier_to_json(supplier),
        "catalog": catalog_to_json(catalog),
    }


def session_row_to_json(row: Any) -> dict[str, Any]:
    """`row`: `SessionRow` (sessão + acumulador)."""
    s, a = row.session, row.acc
    return {
        "id": s.id,
        "started_at": _when(s.started_at),
        "ended_at": _when(s.ended_at) if s.ended_at else None,
        "end_reason": s.end_reason.value if s.end_reason else None,
        "scope": s.scope.value,
        "energy_basis": s.energy_basis.value,
        "measured_kwh": _dec(a.measured_wh / 1000),
        "assumed_kwh": _dec(a.assumed_wh / 1000),
        "covered_s": _dec(a.covered_s),
        "excluded_s": _dec(a.excluded_s),
        "partial_data": a.partial_data,
    }


def session_list_to_json(rows: Any, label: str) -> dict[str, Any]:
    return {"label": label, "sessions": [session_row_to_json(r) for r in rows]}


def session_tick_to_json(
    view: Any, label: str, *, final: bool = False, end_reason: str | None = None,
    warnings: tuple[str, ...] = (),
) -> dict[str, Any]:
    """`view`: `TrackView`."""
    return {
        "label": label,
        "session_id": view.session_id,
        "at": _when(view.at),
        "measured_kwh": _dec(view.measured_kwh),
        "assumed_kwh": _dec(view.assumed_kwh),
        "energy_kwh": _dec(view.measured_kwh + view.assumed_kwh),
        "cost_brl": view.cost.to_json() if view.cost is not None else None,
        "stale": view.acc.stale,
        "stale_for_s": _dec(view.stale_for_s) if view.stale_for_s is not None else None,
        "covered_s": _dec(view.acc.covered_s),
        "excluded_s": _dec(view.acc.excluded_s),
        "partial_data": view.acc.partial_data,
        "final": final,
        "end_reason": end_reason,
        "warnings": list(warnings),
    }


def period_cost_to_json(cost: Any) -> dict[str, Any]:
    """`cost`: `PeriodCost`."""
    return {
        "label": cost.label,
        "since": _when(cost.since),
        "until": _when(cost.until),
        "sessions": cost.sessions,
        "measured_kwh": _dec(cost.measured_kwh),
        "assumed_kwh": _dec(cost.assumed_kwh),
        "measured_cost_brl": cost.measured_cost.to_json(),
        "assumed_cost_brl": cost.assumed_cost.to_json(),
        "cost_brl": cost.total_cost.to_json(),
        "covered_s": _dec(cost.covered_s),
        "excluded_s": _dec(cost.excluded_s),
        "partial_data": cost.partial_data,
        "slices": [
            {
                "start": _day(sl.start), "end": _day(sl.end),
                "measured_kwh": _dec(sl.measured_energy_kwh),
                "assumed_kwh": _dec(sl.assumed_energy_kwh),
                "rate": _dec(sl.rate_brl_per_kwh) if sl.rate_brl_per_kwh is not None else None,
            }
            for sl in cost.slices
        ],
    }


def export_to_json(session_id: int, outcome: Any, text: str, label: str) -> dict[str, Any]:
    """`outcome`: `ExportOutcome`; `text`: o texto exportado."""
    return {
        "label": label, "session_id": session_id, "truncated": outcome.truncated,
        "delivered": outcome.delivered, "text": text,
    }


def success_document(command: str, result: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "ok": True, "command": command, "result": result}


def error_document(
    code: str, message: str, candidates: tuple[SupplierLink, ...] = ()
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if candidates:
        error["candidates"] = [supplier_to_json(c) for c in candidates]
    return {"schema_version": SCHEMA_VERSION, "ok": False, "error": error}


def domain_error_document(exc: DomainError) -> dict[str, Any]:
    candidates = tuple(getattr(exc, "candidates", ()))
    return error_document(exc.code, exc.message, candidates)
