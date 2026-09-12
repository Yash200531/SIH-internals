"""Fail-closed malware scanner contract and ClamAV INSTREAM adapter."""

import asyncio
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

_CHUNK_BYTES = 64 * 1024
_VERSION_PATTERN = re.compile(r"^ClamAV (?P<engine>[^/]+)/(?P<signature>[^/]+)/")
_FOUND_PATTERN = re.compile(r"^stream: (?P<threat>[A-Za-z0-9._():@+-]{1,255}) FOUND$")


class MalwareScanOutcome(StrEnum):
    CLEAN = "clean"
    INFECTED = "infected"


@dataclass(frozen=True)
class MalwareScanResult:
    outcome: MalwareScanOutcome
    engine: str
    engine_version: str
    signature_version: str
    threat_name: str | None = None


class MalwareScannerError(RuntimeError):
    """Raised with a non-sensitive class when the scanner cannot prove safety."""


class MalwareScanner(Protocol):
    async def scan(self, payload: bytes) -> MalwareScanResult: ...


def parse_clamav_response(response: bytes, *, engine_version: str) -> MalwareScanResult:
    version_match = _VERSION_PATTERN.match(engine_version)
    if version_match is None:
        raise MalwareScannerError("Scanner version unavailable")
    try:
        message = response.rstrip(b"\0").decode("ascii")
    except UnicodeDecodeError as exc:
        raise MalwareScannerError("Scanner response invalid") from exc
    common = {
        "engine": "clamav",
        "engine_version": version_match.group("engine"),
        "signature_version": version_match.group("signature"),
    }
    if message == "stream: OK":
        return MalwareScanResult(outcome=MalwareScanOutcome.CLEAN, **common)
    found = _FOUND_PATTERN.fullmatch(message)
    if found is not None:
        return MalwareScanResult(
            outcome=MalwareScanOutcome.INFECTED,
            threat_name=found.group("threat"),
            **common,
        )
    raise MalwareScannerError("Scanner did not return a conclusive result")


class ClamAVScanner:
    def __init__(
        self,
        *,
        host: str,
        port: int = 3310,
        timeout_seconds: float = 30,
        max_bytes: int = 10 * 1024 * 1024,
        engine_version: str | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes
        self._engine_version = engine_version

    async def _command(self, command: bytes, payload: bytes | None = None) -> bytes:
        reader, writer = await asyncio.open_connection(self._host, self._port)
        try:
            writer.write(command)
            if payload is not None:
                for offset in range(0, len(payload), _CHUNK_BYTES):
                    chunk = payload[offset : offset + _CHUNK_BYTES]
                    writer.write(len(chunk).to_bytes(4, "big"))
                    writer.write(chunk)
                writer.write((0).to_bytes(4, "big"))
            await writer.drain()
            return await reader.readuntil(b"\0")
        finally:
            writer.close()
            await writer.wait_closed()

    async def _scan(self, payload: bytes) -> MalwareScanResult:
        version = self._engine_version
        if version is None:
            version_response = await self._command(b"zVERSION\0")
            try:
                version = version_response.rstrip(b"\0").decode("ascii")
            except UnicodeDecodeError as exc:
                raise MalwareScannerError("Scanner version unavailable") from exc
        response = await self._command(b"zINSTREAM\0", payload)
        return parse_clamav_response(response, engine_version=version)

    async def scan(self, payload: bytes) -> MalwareScanResult:
        if not payload or len(payload) > self._max_bytes:
            raise MalwareScannerError("Payload failed scanner admission limits")
        try:
            return await asyncio.wait_for(self._scan(payload), self._timeout_seconds)
        except MalwareScannerError:
            raise
        except TimeoutError as exc:
            raise MalwareScannerError("Scanner deadline exceeded") from exc
        except (ConnectionError, OSError, asyncio.IncompleteReadError) as exc:
            raise MalwareScannerError("Scanner unavailable") from exc
