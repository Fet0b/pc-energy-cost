"""Erros de domínio com códigos estáveis e códigos de saída (D13)."""

from __future__ import annotations

_EXIT_2 = (
    "invalid_input", "ambiguous_decimal", "invalid_interval",
    "overlapping_intervals", "timezone_data_missing", "double_inclusion",
    "inclusion_undeclared", "csv_conflicting_duplicate", "csv_unknown_columns",
    "csv_invalid_header", "csv_invalid_row", "csv_too_many_rows",
)
_EXIT_3 = ("supplier_ambiguous", "unsupported", "tariff_ambiguous")
_EXIT_4 = (
    "tariff_not_found", "tariff_not_in_effect", "schema_mismatch",
    "unexpected_html", "download_incomplete", "cache_corrupted",
)

EXIT_CODES: dict[str, int] = {
    **{c: 2 for c in _EXIT_2},
    **{c: 3 for c in _EXIT_3},
    **{c: 4 for c in _EXIT_4},
    "network_unavailable": 5,
    "unavailable": 6,
}

COVERAGE_SOURCES = ("csv", "counter")


def exit_code_for(code: str) -> int:
    """Código de saída da CLI para um código estável (não vale para insufficient_coverage)."""
    try:
        return EXIT_CODES[code]
    except KeyError:
        raise ValueError(f"código de erro desconhecido: {code!r}") from None


class DomainError(Exception):
    def __init__(self, code: str, message: str) -> None:
        if code != "insufficient_coverage":
            exit_code_for(code)  # valida o código
        super().__init__(message)
        self.code = code
        self.message = message

    @property
    def exit_code(self) -> int:
        return exit_code_for(self.code)


class InvalidInput(DomainError):
    def __init__(self, message: str, code: str = "invalid_input") -> None:
        super().__init__(code, message)


class UnavailableError(DomainError):
    def __init__(self, message: str) -> None:
        super().__init__("unavailable", message)


class InsufficientCoverage(DomainError):
    def __init__(self, message: str, source: str) -> None:
        if source not in COVERAGE_SOURCES:
            raise ValueError(f"source inválido: {source!r}")
        super().__init__("insufficient_coverage", message)
        self.source = source

    @property
    def exit_code(self) -> int:
        return 2 if self.source == "csv" else 6
