"""Arquitetura: grafo de imports por `ast` (A47) e ausência de float em dinheiro (A8)."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PKG = "pc_energy_cost"
SRC = Path(__file__).resolve().parents[2] / "src" / PKG
FORBIDDEN_IN_DOMAIN = {"sqlite3", "urllib", "os", "subprocess", "csv", "http", "socket", "shutil"}
LAYERS = ("domain", "application", "infrastructure", "interface")
# camadas internas permitidas por camada (além da própria)
ALLOWED = {
    "domain": set(),
    "application": {"domain"},
    "infrastructure": {"domain", "application"},
    "interface": {"domain", "application"},
}


def _modules() -> list[tuple[str, Path]]:
    out = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC.parent).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts.pop()
        out.append((".".join(parts), path))
    return out


def _imports(module: str, path: Path) -> set[str]:
    """Nomes absolutos importados por um módulo (relativos resolvidos)."""
    is_pkg = path.name == "__init__.py"
    base = module.split(".") if is_pkg else module.split(".")[:-1]
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                root = base[: len(base) - (node.level - 1)]
                name = ".".join([*root, *([node.module] if node.module else [])])
            else:
                name = node.module or ""
            found.add(name)
            found.update(f"{name}.{alias.name}" for alias in node.names)
    return found


def _layer(module: str) -> str | None:
    parts = module.split(".")
    if parts[0] != PKG or len(parts) < 2:
        return None
    return parts[1] if parts[1] in LAYERS else parts[1]  # composition, __main__ etc.


def _is_stdlib(name: str) -> bool:
    return name.split(".")[0] in sys.stdlib_module_names


def test_a47_import_graph_respects_layers():
    violations: list[str] = []
    for module, path in _modules():
        layer = _layer(module)
        if layer not in LAYERS:
            continue
        for imported in _imports(module, path):
            top = imported.split(".")[0]
            if top == PKG:
                target = _layer(imported)
                if target is not None and target != layer and target not in ALLOWED[layer]:
                    violations.append(f"{module} -> {imported}")
            elif layer == "domain" and top in FORBIDDEN_IN_DOMAIN:
                violations.append(f"{module} -> {imported} (proibido no domain)")
            elif not _is_stdlib(imported) and imported:
                violations.append(f"{module} -> {imported} (dependência de terceiros)")
    assert violations == []


def test_layering_check_is_not_vacuous_every_layer_has_modules_and_cross_imports_are_seen(tmp_path):
    names = [m for m, _ in _modules()]
    for layer in LAYERS:
        assert any(m.startswith(f"{PKG}.{layer}.") for m in names), layer
    composition_imports = _imports(f"{PKG}.composition", SRC / "composition.py")
    assert any(i.startswith(f"{PKG}.infrastructure") for i in composition_imports)
    assert any(i.startswith(f"{PKG}.interface") for i in composition_imports)
    fake = tmp_path / "bad.py"
    fake.write_text("from ..infrastructure import x\nimport sqlite3\n", encoding="utf-8")
    found = _imports(f"{PKG}.domain.shared.bad", fake)
    assert f"{PKG}.domain.infrastructure" in found or any("infrastructure" in i for i in found)
    assert "sqlite3" in found and "sqlite3" in FORBIDDEN_IN_DOMAIN


def test_only_composition_and_main_import_everything():
    importers: dict[str, set[str]] = {}
    for module, path in _modules():
        for imported in _imports(module, path):
            if imported == f"{PKG}.composition" or imported.startswith(f"{PKG}.composition."):
                importers.setdefault(module, set()).add(imported)
    assert set(importers) <= {f"{PKG}.__main__"}
    reaching = {}
    for module, path in _modules():
        layers = {
            _layer(i) for i in _imports(module, path) if i.split(".")[0] == PKG
        } & set(LAYERS)
        reaching[module] = layers
    wide = {m for m, ls in reaching.items() if {"infrastructure", "interface"} <= ls}
    assert wide <= {f"{PKG}.composition"}


def test_a08_no_float_calls_or_annotations_in_domain_and_value_objects_use_decimal():
    offenders: list[str] = []
    for module, path in _modules():
        if _layer(module) != "domain":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "float":
                offenders.append(f"{module}:{node.lineno} float()")
            if isinstance(node, ast.AnnAssign) and any(
                isinstance(n, ast.Name) and n.id == "float" for n in ast.walk(node.annotation)
            ):
                offenders.append(f"{module}:{node.lineno} annotation float")
    assert offenders == []

    from decimal import Decimal

    from pc_energy_cost.domain.shared import money, units

    for cls in (money.MoneyBRL, units.Watts, units.Wh, units.KWh, units.UnitRateBRLPerKWh):
        value = cls.__dataclass_fields__["value"]
        assert value.type in (Decimal, "Decimal"), cls
    assert units.Duration.__dataclass_fields__["hours"].type in (Decimal, "Decimal")
