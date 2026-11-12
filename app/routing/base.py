from __future__ import annotations

from typing import Protocol

from app.routing.models import LatLng, Ruta


class ProviderError(Exception):
    """El proveedor de rutas falló (red, cuota, clave). El mensaje no debe contener claves ni coordenadas."""


class NotConfigured(ProviderError):
    """No hay clave de API configurada."""


class RouteNotFound(ProviderError):
    """El proveedor respondió, pero no hay camino a pie hasta ese destino."""


class PlaceNotFound(ProviderError):
    """El texto del destino no corresponde a ningún lugar."""


class RouteProvider(Protocol):
    async def walk_route(self, origen: LatLng, destino: LatLng) -> Ruta:
        """Ruta a pie. No existe parámetro de modo: un ciego no conduce."""

    async def geocode(self, texto: str, cerca: LatLng) -> tuple[LatLng, str]:
        """Devuelve (coordenadas, dirección legible) del lugar que mejor coincide."""

    async def reverse(self, punto: LatLng) -> str | None:
        """Nombre de la calle (o del cruce) donde está la persona, o None si no se sabe."""
