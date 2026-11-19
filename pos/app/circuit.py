"""Circuit breaker para las llamadas del POS hacia la base de datos en la nube.

Estados:
  CERRADO      -> las peticiones van a la nube normalmente.
  ABIERTO      -> tras N fallos seguidos se deja de intentar (se usa el nodo LOCAL) durante `tiempo_reset` s.
  SEMIABIERTO  -> pasado ese tiempo se permite UNA petición de prueba; si funciona se cierra, si falla se reabre.
"""
import threading
import time


class CircuitBreaker:
    CERRADO, ABIERTO, SEMIABIERTO = "CERRADO", "ABIERTO", "SEMIABIERTO"

    def __init__(self, umbral_fallos: int = 2, tiempo_reset: float = 8.0, reloj=time.monotonic):
        self.umbral_fallos = umbral_fallos
        self.tiempo_reset = tiempo_reset
        self._reloj = reloj
        self._lock = threading.Lock()
        self._estado = self.CERRADO
        self._fallos = 0
        self._abierto_desde = 0.0
        self._prueba_en_curso = False

    @property
    def estado(self) -> str:
        with self._lock:
            self._actualizar()
            return self._estado

    def _actualizar(self):
        if self._estado == self.ABIERTO and self._reloj() - self._abierto_desde >= self.tiempo_reset:
            self._estado = self.SEMIABIERTO
            self._prueba_en_curso = False

    def permitir(self) -> bool:
        """¿Se puede intentar una llamada a la nube ahora?"""
        with self._lock:
            self._actualizar()
            if self._estado == self.CERRADO:
                return True
            if self._estado == self.SEMIABIERTO and not self._prueba_en_curso:
                self._prueba_en_curso = True
                return True
            return False

    def exito(self):
        with self._lock:
            self._estado = self.CERRADO
            self._fallos = 0
            self._prueba_en_curso = False

    def fallo(self):
        with self._lock:
            self._fallos += 1
            if self._estado == self.SEMIABIERTO or self._fallos >= self.umbral_fallos:
                self._estado = self.ABIERTO
                self._abierto_desde = self._reloj()
                self._prueba_en_curso = False
