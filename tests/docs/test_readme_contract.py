"""R1: o README cumpre a regra e seus exemplos, números e caminhos são conferidos por máquina.

Desenho dos números de testes: o teste roda `pytest --collect-only -q` em subprocesso. Coletar
não executa funções de teste (só importa módulos), então este teste não recursa; comparar com a
coleta real é mais robusto do que manter uma contagem calculada à mão.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from pc_energy_cost.domain.shared.errors import EXIT_CODES

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"

REQUIRED_SECTIONS = [
    "Propósito e público",
    "Demonstração",
    "Papel e escopo",
    "Decisões técnicas",
    "Tratamento de dados incompletos",
    "Instalação",
    "Uso",
    "Sessões e custo em tempo real",
    "Exportação Proxmox-compatível (texto)",
    "Limites e avisos",
    "Códigos de saída",
    "Verificação e testes",
    "Limitações",
    "Documentação",
    "Licença",
]

# (comando como escrito no README, código de saída, campos estáveis citados no README)
EXAMPLES = [
    (
        "pc-energy-cost estimar --potencia 100 --inicio 2026-10-19T08:00 --fim 2026-10-19T18:00"
        " --tarifa-manual-total 0,80 --inclui tributos",
        0,
        ["Custo estimado: R$ 0,80", "Energia: 1,000 kWh", "Duração solicitada: 10 h 00 min 00 s"],
    ),
    (
        "pc-energy-cost estimar --potencia 100 --horas 10 --tarifa-manual-total 0,78938",
        0,
        ["Custo estimado: R$ 0,79", "Energia: 1,000 kWh"],
    ),
    (
        "pc-energy-cost estimar --serie-csv tests/fixtures/metering/serie_gap.csv"
        " --tarifa-manual-total 0,78938",
        0,
        ["Custo estimado: R$ 0,01", "Energia: 0,017 kWh", "Duração coberta: 0 h 10 min 00 s",
         "Dados parciais"],
    ),
    (
        "pc-energy-cost sessao exportar 99",
        2,
        ["Erro [session_not_found]: sessão 99 não encontrada"],
    ),
    (
        "pc-energy-cost sessao listar",
        0,
        ["Nenhuma sessão registrada."],
    ),
]


@pytest.fixture(scope="module")
def text() -> str:
    return README.read_text(encoding="utf-8")


def _outside_fences(text: str) -> list[str]:
    lines, fenced = [], False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            lines.append(line)
    return lines


def _headings(text: str) -> list[str]:
    return [m.group(2).strip() for line in _outside_fences(text)
            if (m := re.match(r"^(#{1,6})\s+(.*)$", line))]


def _run(command: str, db: Path) -> subprocess.CompletedProcess[str]:
    argv = command.split()
    assert argv[0] == "pc-energy-cost"
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PC_ENERGY_COST_DB=str(db),
               PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "pc_energy_cost", *argv[1:]], cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=60)


def test_r1_readme_has_required_sections_in_order(text):
    headings = _headings(text)
    positions = []
    for title in REQUIRED_SECTIONS:
        assert title in headings, f"seção obrigatória ausente: {title}"
        positions.append(headings.index(title))
    assert positions == sorted(positions), "seções obrigatórias fora da ordem esperada"


def test_r1_readme_paragraphs_are_single_line(text):
    previous_plain = False
    for number, line in enumerate(_outside_fences(text), 1):
        plain = bool(line.strip()) and not re.match(r"^(#|\||- |\d+\. |!\[|<)", line)
        assert not (plain and line.startswith(" ")), f"linha de continuação: {line!r}"
        assert not (plain and previous_plain), f"parágrafo quebrado em várias linhas: {line!r}"
        previous_plain = plain


@pytest.mark.parametrize("command,code,fields", EXAMPLES, ids=[e[0][:60] for e in EXAMPLES])
def test_r1_readme_examples_reproduce_the_quoted_fields(text, tmp_path, command, code, fields):
    assert f"\n{command}\n" in text, "comando do exemplo não aparece em bloco do README"
    result = _run(command, tmp_path / "store.sqlite")
    assert result.returncode == code, result.stderr
    out = result.stdout + result.stderr
    for field in fields:
        assert field in out, f"saída real não contém {field!r}"
        assert field in text, f"README não cita o campo estável {field!r}"


def test_r1_readme_examples_do_not_touch_a_real_database(tmp_path):
    _run(EXAMPLES[0][0], tmp_path / "store.sqlite")
    assert not (tmp_path / "store.sqlite").exists()  # tarifa manual: nada é criado


def test_r1_readme_test_numbers_match_pytest_collection(text):
    done = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q",
                           "-p", "no:cacheprovider"], cwd=ROOT, capture_output=True,
                          text=True, timeout=300)
    tail = [ln for ln in done.stdout.splitlines() if ln.strip()][-1]
    real = re.search(r"(\d+)/(\d+) tests collected \((\d+) deselected\)", tail)
    assert real, f"saída inesperada da coleta: {tail!r}"
    quoted = re.search(r"^(\d+)/(\d+) tests collected \((\d+) deselected\)", text, re.M)
    assert quoted, "README não traz a linha da coleta"
    assert quoted.groups() == real.groups()
    passed = re.search(r"^(\d+) passed, (\d+) deselected", text, re.M)
    assert passed, "README não traz a linha de aprovados"
    # aprovados na última execução = testes selecionados; 'deselected' igual nas duas linhas
    assert passed.group(1) == real.group(1) and passed.group(2) == real.group(3)


def test_r1_readme_cites_only_existing_paths(text):
    generated = ("dist/",)
    cited = set(re.findall(r"`([^`\s]+\.(?:md|py|svg|csv|yml|toml))`", text))
    cited |= set(re.findall(r"\]\(([^)#\s]+)\)", text))
    cited |= set(re.findall(r"`((?:src|tests|docs|plans)/[^`\s]*)`", text))
    cited |= {"LICENSE"}
    missing = sorted(p for p in cited if not p.startswith(generated)
                     and not p.startswith("http") and not (ROOT / p).exists())
    assert not missing, f"caminhos citados que não existem: {missing}"


def test_r1_readme_exit_code_table_lists_new_session_codes(text):
    assert EXIT_CODES["session_already_open"] == EXIT_CODES["session_not_found"] == 2
    row = next(ln for ln in text.splitlines() if ln.startswith("| 2 |"))
    assert "session_already_open" in row and "session_not_found" in row


def test_r1_readme_never_claims_official_proxmox_integration(text):
    lowered = text.lower()
    assert "proxmox-compatível (texto)" in lowered
    for line in text.splitlines():
        for sentence in re.split(r"(?<=[.;])\s", line.lower()):
            if "integração oficial" in sentence:
                # a negação precisa vir ANTES da expressão, na mesma frase
                head = sentence.split("integração oficial")[0]
                assert re.search(r"\b(não|nunca|sem)\b", head), sentence
