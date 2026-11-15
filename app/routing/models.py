from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LatLng(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class RutaRequest(BaseModel):
    """Origen y destino. Deliberadamente sin campo de modo: la ruta siempre es a pie."""

    model_config = ConfigDict(extra='forbid')

    origen: LatLng | None = None
    # Si el GPS no da la ubicación, la persona dice dónde está ("calle 72 con séptima") y se busca como el destino.
    origen_texto: str | None = Field(default=None, min_length=3, max_length=200)
    destino: LatLng | None = None
    destino_texto: str | None = Field(default=None, min_length=3, max_length=200)

    @model_validator(mode='after')
    def _uno_solo(self) -> 'RutaRequest':
        if (self.destino is None) == (self.destino_texto is None):
            raise ValueError('envíe destino (lat/lng) o destino_texto, no ambos ni ninguno')
        if (self.origen is None) == (self.origen_texto is None):
            raise ValueError('envíe origen (lat/lng) u origen_texto, no ambos ni ninguno')
        return self


class Paso(BaseModel):
    indice: int
    maniobra: str  # clave normalizada del proveedor, p. ej. TURN_RIGHT
    accion: str  # "gire a la derecha"
    distancia_m: int  # largo de este tramo, hasta la siguiente maniobra
    frase: str  # "Gire a la derecha y siga unos 50 metros"
    detalle: str | None = None  # texto del proveedor (con nombre de calle), si lo hay
    inicio: LatLng
    fin: LatLng


class Cruce(BaseModel):
    lat: float
    lng: float
    tipo: str  # 'semaforo' | 'cebra' | 'cruce'


class Ruta(BaseModel):
    distancia_m: int
    duracion_s: int
    resumen: str
    advertencias: list[str]
    pasos: list[Paso]
    polilinea: str  # codificada (Google); el cliente la usa para detectar desvíos
    destino: LatLng
    destino_confirmado: str | None = None  # dirección que se encontró, para leerla en voz alta
    origen_confirmado: str | None = None  # si la persona dijo dónde está: lo que se entendió, para que pueda corregirlo
    cruces: list[Cruce] = []  # puntos de cruce de calle cerca de la ruta (OpenStreetMap)
    cruces_consultados: bool = False  # False: no se pudo consultar; el cliente no debe asumir "no hay cruces"
