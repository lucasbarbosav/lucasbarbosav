"""Roda todos os testes de unidade do projeto."""
import subprocess, sys
from pathlib import Path

TESTES = sorted(Path(__file__).parent.glob("test_*.py"))
falhas = [t.name for t in TESTES if subprocess.run([sys.executable, str(t)]).returncode]
print(f"\n=== {len(TESTES) - len(falhas)}/{len(TESTES)} arquivos de teste OK ===")
if falhas:
    print("falharam:", ", ".join(falhas))
sys.exit(1 if falhas else 0)
