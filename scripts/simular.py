"""Simula fallas del sistema distribuido (útil para la demostración en video).

Uso:
  python scripts/simular.py cortar-internet     # la tienda se queda sin internet (el VPS sigue vivo)
  python scripts/simular.py restaurar-internet
  python scripts/simular.py caer-vps            # se apaga la base de datos de la nube
  python scripts/simular.py levantar-vps
  python scripts/simular.py estado
"""
import json
import subprocess
import sys
import urllib.request


def docker(*a):
    r = subprocess.run(["docker", *a], capture_output=True, text=True)
    print(("  ✔ " if r.returncode == 0 else "  ✖ ") + "docker " + " ".join(a) + (f"  ({r.stderr.strip()})" if r.returncode else ""))


ACCIONES = {
    "cortar-internet": lambda: [docker("network", "disconnect", "vet_internet", c) for c in ("vet-pos", "vet-sync")],
    "restaurar-internet": lambda: [docker("network", "connect", "vet_internet", c) for c in ("vet-pos", "vet-sync")],
    "caer-vps": lambda: docker("stop", "vet-nube"),
    "levantar-vps": lambda: docker("start", "vet-nube"),
    "estado": lambda: print(json.dumps(json.load(urllib.request.urlopen("http://localhost:8000/api/estado")),
                                       indent=2, ensure_ascii=False)),
}

if len(sys.argv) != 2 or sys.argv[1] not in ACCIONES:
    print(__doc__)
    sys.exit(1)
ACCIONES[sys.argv[1]]()
