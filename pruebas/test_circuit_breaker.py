"""Pruebas unitarias del circuit breaker (no requieren Docker)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pos"))
from app.circuit import CircuitBreaker  # noqa: E402


class Reloj:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_inicia_cerrado_y_permite():
    cb = CircuitBreaker()
    assert cb.estado == "CERRADO" and cb.permitir()


def test_se_abre_tras_umbral_de_fallos():
    cb = CircuitBreaker(umbral_fallos=2, reloj=Reloj())
    cb.fallo()
    assert cb.estado == "CERRADO"
    cb.fallo()
    assert cb.estado == "ABIERTO" and not cb.permitir()


def test_semiabierto_permite_una_sola_prueba():
    r = Reloj()
    cb = CircuitBreaker(umbral_fallos=1, tiempo_reset=5, reloj=r)
    cb.fallo()
    r.t = 5
    assert cb.estado == "SEMIABIERTO"
    assert cb.permitir() is True
    assert cb.permitir() is False


def test_prueba_exitosa_cierra_el_circuito():
    r = Reloj()
    cb = CircuitBreaker(umbral_fallos=1, tiempo_reset=5, reloj=r)
    cb.fallo(); r.t = 6; cb.permitir(); cb.exito()
    assert cb.estado == "CERRADO"


def test_prueba_fallida_reabre_el_circuito():
    r = Reloj()
    cb = CircuitBreaker(umbral_fallos=3, tiempo_reset=5, reloj=r)
    for _ in range(3):
        cb.fallo()
    r.t = 6; cb.permitir(); cb.fallo()
    assert cb.estado == "ABIERTO"
    r.t = 10
    assert cb.estado == "ABIERTO"
    r.t = 11
    assert cb.estado == "SEMIABIERTO"


def test_exito_reinicia_contador():
    cb = CircuitBreaker(umbral_fallos=2, reloj=Reloj())
    cb.fallo(); cb.exito(); cb.fallo()
    assert cb.estado == "CERRADO"
