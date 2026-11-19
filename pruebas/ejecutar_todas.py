"""Ejecuta toda la batería de pruebas y guarda las evidencias en /evidencias."""
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
PRUEBAS = [
    [sys.executable, "-m", "pytest", "-v", "test_circuit_breaker.py"],
    [sys.executable, "prueba_funcional.py"],
    [sys.executable, "prueba_concurrencia_rendimiento.py"],
    [sys.executable, "prueba_tolerancia_fallos.py"],
]
resultados = []
for cmd in PRUEBAS:
    print(f"\n>>> {' '.join(cmd[1:])}")
    r = subprocess.run(cmd, cwd=AQUI, capture_output=True, text=True, encoding="utf-8",
                       env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    print(r.stdout[-4000:], r.stderr[-2000:])
    if "pytest" in cmd:
        (AQUI.parent / "evidencias" / "00_pruebas_unitarias.txt").write_text(r.stdout, encoding="utf-8")
    resultados.append((cmd[-1], r.returncode == 0))
print("\nRESUMEN")
for nombre, ok in resultados:
    print(f"  {'OK   ' if ok else 'FALLA'} {nombre}")
sys.exit(0 if all(ok for _, ok in resultados) else 1)
