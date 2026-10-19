"""A50: sdist -> wheel -> venv limpo (marcador `install`; exige rede para o build isolado e o pip)."""

import json
import os
import subprocess
import sys
import venv
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REQUIRES_TZDATA = 'Requires-Dist: tzdata; sys_platform == "win32"'

pytestmark = pytest.mark.install


def _clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")}
    env.update(extra or {})
    return env


def _run(cmd: list[str], cwd: Path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=cwd, env=_clean_env(extra_env), capture_output=True, text=True, timeout=600
    )


def _bin(env_dir: Path, name: str) -> Path:
    return env_dir / ("Scripts" if sys.platform == "win32" else "bin") / (
        name + (".exe" if sys.platform == "win32" else "")
    )


def _install_and_check(env_dir: Path, artifact: Path, workdir: Path) -> None:
    venv.EnvBuilder(with_pip=True, clear=True).create(env_dir)
    pip = _run([str(_bin(env_dir, "python")), "-m", "pip", "install", str(artifact)], workdir)
    assert pip.returncode == 0, pip.stdout + pip.stderr
    script = _run([str(_bin(env_dir, "pc-energy-cost")), "--help"], workdir)
    assert script.returncode == 0, script.stdout + script.stderr
    module = _run([str(_bin(env_dir, "python")), "-m", "pc_energy_cost", "--help"], workdir)
    assert module.returncode == 0, module.stdout + module.stderr
    assert "estimar" in script.stdout and "estimar" in module.stdout
    # pacote realmente instalado (não o código-fonte via PYTHONPATH/cwd): fora de src/
    where = _run(
        [str(_bin(env_dir, "python")), "-I", "-c", "import pc_energy_cost;print(pc_energy_cost.__file__)"],
        workdir,
    )
    assert where.returncode == 0 and "site-packages" in where.stdout, where.stdout + where.stderr
    # exemplo offline real, com banco isolado
    out = _run(
        [str(_bin(env_dir, "pc-energy-cost")), "estimar", "--potencia", "100", "--horas", "10",
         "--tarifa-manual-total", "0,78938", "--json"],
        workdir,
        {"PC_ENERGY_COST_DB": str(workdir / "isolado" / "store.sqlite")},
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert json.loads(out.stdout)["schema_version"] == "1"


def test_a50_install_sdist_wheel_clean_venv(tmp_path):
    dist = tmp_path / "dist"
    work = tmp_path / "work"
    work.mkdir()
    build = _run([sys.executable, "-m", "build", "--outdir", str(dist), str(ROOT)], work)
    assert build.returncode == 0, build.stdout + build.stderr
    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))
    assert len(wheels) == 1 and len(sdists) == 1, list(dist.iterdir())

    with zipfile.ZipFile(wheels[0]) as zf:
        metadata = next(n for n in zf.namelist() if n.endswith(".dist-info/METADATA"))
        lines = zf.read(metadata).decode("utf-8").splitlines()
    assert REQUIRES_TZDATA in lines, [ln for ln in lines if ln.startswith("Requires-Dist")]

    _install_and_check(tmp_path / "v1", wheels[0], work)
    _install_and_check(tmp_path / "v2", sdists[0], work)
