"""
shared/schemas.py
-----------------
Contrato JSON entre todos los módulos de ArcFast.
Todos importan desde aquí — nadie define estructuras propias.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FieldMapping:
    campo_origen: str        # Campo en el portal del cliente
    campo_destino: str       # Campo en sistema Arca
    confianza: float         # 0.0 - 1.0 (Bayesian confidence)
    flag: bool = False       # True si confianza < umbral

    def to_dict(self):
        return self.__dict__


@dataclass
class WorkflowConfirmado:
    url_portal: str
    pasos: list[str]
    mapeos: list[FieldMapping]

    def to_dict(self):
        return {
            "url_portal": self.url_portal,
            "pasos": self.pasos,
            "mapeos": [m.to_dict() for m in self.mapeos],
        }


@dataclass
class MissingProduct:
    sku_arca: str
    nombre: str
    cantidad: int
    precio_unitario: float
    campo_origen_raw: str    # Valor original del portal del cliente

    def to_dict(self):
        return self.__dict__


@dataclass
class AgentResult:
    workflow: WorkflowConfirmado
    missing_products: list[MissingProduct]
    errores: list[str]
    challenges: list[str]    # Problemas que el agente encontró navegando

    def to_dict(self):
        return {
            "workflow": self.workflow.to_dict(),
            "missing_products": [p.to_dict() for p in self.missing_products],
            "errores": self.errores,
            "challenges": self.challenges,
        }
