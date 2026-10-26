from __future__ import annotations

import asyncio
import time

try:
    from google import genai
    from google.genai import types
except Exception:  # pragma: no cover - sólo para entorno sin dependencia
    genai = None
    types = None


class GeminiScene:
    def __init__(self, api_key: str, model: str, timeout: float = 20.0):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.client = None
        self.last_error: str | None = None
        self.last_success_at: float | None = None
        if genai is not None and api_key:
            self.client = genai.Client(api_key=api_key)

    async def describe(self, jpeg: bytes, prompt: str, retries: int = 0) -> str:
        """Un solo intento por defecto: el reintento lo decide el planificador
        (circuit breaker) para no sumar latencia a quien espera en voz alta."""
        if not self.client or not self.api_key:
            raise RuntimeError('Gemini no está configurado')
        if types is None:
            raise RuntimeError('La librería google-genai no está disponible')

        config = types.GenerateContentConfig(temperature=0.2, candidate_count=1)

        async def _call() -> str:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=[types.Part.from_bytes(data=jpeg, mime_type='image/jpeg'), prompt],
                config=config,
            )
            text = getattr(response, 'text', None)
            if not text:
                raise RuntimeError('Gemini devolvió una respuesta sin texto')
            return text.strip()

        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                result = await asyncio.wait_for(_call(), timeout=self.timeout)
                self.last_error = None
                self.last_success_at = time.time()
                return result
            except Exception as exc:
                last_error = exc
                self.last_error = f'{type(exc).__name__}: {exc}'.strip()
                if attempt < retries:
                    await asyncio.sleep(0.5)
        raise last_error or RuntimeError('Gemini no devolvió una respuesta')
