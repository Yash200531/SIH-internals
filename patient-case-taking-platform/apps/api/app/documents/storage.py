"""Private quarantine storage adapter for source documents."""

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from app.config import settings
from app.documents.normalization import NormalizedPage
from app.documents.registry import DocumentRegistryEntry, DocumentState

_READ_CHUNK_BYTES = 64 * 1024


class ObjectVerificationError(ValueError):
    """Raised when a quarantined object does not match its registration."""


@dataclass(frozen=True)
class UploadGrant:
    url: str
    object_key: str
    expires_in_seconds: int
    required_headers: dict[str, str]


@dataclass(frozen=True)
class PreviewGrant:
    url: str
    expires_in_seconds: int


@dataclass(frozen=True)
class VerifiedUpload:
    object_key: str
    size_bytes: int
    checksum_sha256: str
    detected_mime: str


@dataclass(frozen=True)
class StoredPage:
    page_number: int
    object_key: str
    checksum_sha256: str
    mime: str
    width: int
    height: int
    preprocessing_version: str
    operations: tuple[str, ...]


@dataclass(frozen=True)
class PageArtifact:
    id: UUID
    page_number: int
    object_key: str
    checksum_sha256: str
    mime: str
    width: int
    height: int
    preprocessing_version: str


class DocumentStore(Protocol):
    async def create_upload_grant(self, document: DocumentRegistryEntry) -> UploadGrant: ...

    async def verify_upload(
        self, document: DocumentRegistryEntry, object_key: str
    ) -> VerifiedUpload: ...

    async def read_for_scan(self, document: DocumentRegistryEntry) -> bytes: ...

    async def promote_after_clean_scan(
        self, document: DocumentRegistryEntry, processing_run_id: str
    ) -> str: ...

    async def read_processing_source(self, document: DocumentRegistryEntry) -> bytes: ...

    async def store_normalized_pages(
        self,
        document: DocumentRegistryEntry,
        normalization_run_id: str,
        pages: list[NormalizedPage],
    ) -> list[StoredPage]: ...

    async def read_normalized_page(
        self,
        document: DocumentRegistryEntry,
        page: PageArtifact,
        *,
        max_bytes: int,
    ) -> bytes: ...

    async def create_page_preview_grant(
        self, document: DocumentRegistryEntry, page: PageArtifact
    ) -> PreviewGrant: ...


def quarantine_object_key(document: DocumentRegistryEntry) -> str:
    return f"quarantine/{document.tenant_id}/{document.id}/source"


def detect_supported_mime(data: bytes) -> str:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise ObjectVerificationError("Uploaded object type is unsupported or unreadable")


class S3DocumentStore:
    def __init__(
        self,
        *,
        client: Any | None = None,
        presign_client: Any | None = None,
        bucket: str | None = None,
        grant_ttl_seconds: int | None = None,
        server_side_encryption: str | None = None,
    ) -> None:
        self._provided_client = client
        self._provided_presign_client = presign_client
        self._bucket = bucket or settings.S3_BUCKET
        self._grant_ttl_seconds = (
            grant_ttl_seconds or settings.DOCUMENT_UPLOAD_GRANT_TTL_SECONDS
        )
        self._server_side_encryption = (
            settings.S3_SERVER_SIDE_ENCRYPTION
            if server_side_encryption is None
            else server_side_encryption
        )

    def _client(self) -> Any:
        if self._provided_client is not None:
            return self._provided_client
        import boto3

        return boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
        )

    def _presign_client(self) -> Any:
        if self._provided_presign_client is not None:
            return self._provided_presign_client
        if not settings.S3_PUBLIC_ENDPOINT:
            return self._client()
        import boto3

        return boto3.client(
            "s3",
            endpoint_url=settings.S3_PUBLIC_ENDPOINT,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
        )

    @staticmethod
    def object_key(document: DocumentRegistryEntry) -> str:
        return quarantine_object_key(document)

    async def create_upload_grant(self, document: DocumentRegistryEntry) -> UploadGrant:
        if document.state is not DocumentState.INITIATED:
            raise ObjectVerificationError("Only initiated documents can receive an upload grant")
        if document.upload_expires_at <= datetime.now(UTC):
            raise ObjectVerificationError("Upload session has expired")
        if settings.APP_ENV != "development" and not self._server_side_encryption:
            raise ObjectVerificationError(
                "Server-side encryption must be configured outside development"
            )
        object_key = self.object_key(document)
        required_headers = {
            "Content-Type": document.declared_mime,
            "Content-Length": str(document.declared_size_bytes),
            "x-amz-meta-document-id": str(document.id),
        }
        params = {
            "Bucket": self._bucket,
            "Key": object_key,
            "ContentType": document.declared_mime,
            "ContentLength": document.declared_size_bytes,
            "Metadata": {"document-id": str(document.id)},
        }
        if self._server_side_encryption:
            required_headers["x-amz-server-side-encryption"] = self._server_side_encryption
            params["ServerSideEncryption"] = self._server_side_encryption
        url = await asyncio.to_thread(
            self._presign_client().generate_presigned_url,
            "put_object",
            Params=params,
            ExpiresIn=self._grant_ttl_seconds,
            HttpMethod="PUT",
        )
        return UploadGrant(url, object_key, self._grant_ttl_seconds, required_headers)

    async def verify_upload(
        self, document: DocumentRegistryEntry, object_key: str
    ) -> VerifiedUpload:
        expected_key = self.object_key(document)
        if object_key != expected_key:
            raise ObjectVerificationError("Object is outside the registered quarantine scope")

        client = self._client()
        head = await asyncio.to_thread(
            client.head_object,
            Bucket=self._bucket,
            Key=object_key,
        )
        if head.get("ContentLength") != document.declared_size_bytes:
            raise ObjectVerificationError("Uploaded object size does not match registration")
        if head.get("ContentType") != document.declared_mime:
            raise ObjectVerificationError("Uploaded content type does not match registration")

        response = await asyncio.to_thread(
            client.get_object,
            Bucket=self._bucket,
            Key=object_key,
        )
        body = response["Body"]
        digest = hashlib.sha256()
        prefix = bytearray()
        total = 0
        try:
            for chunk in body.iter_chunks(chunk_size=_READ_CHUNK_BYTES):
                total += len(chunk)
                if total > document.declared_size_bytes:
                    raise ObjectVerificationError("Uploaded object exceeds registered size")
                if len(prefix) < 16:
                    prefix.extend(chunk[: 16 - len(prefix)])
                digest.update(chunk)
        finally:
            body.close()

        if total != document.declared_size_bytes:
            raise ObjectVerificationError("Uploaded object size changed during verification")
        detected_mime = detect_supported_mime(bytes(prefix))
        if detected_mime != document.declared_mime:
            raise ObjectVerificationError("Detected object type does not match registration")
        return VerifiedUpload(object_key, total, digest.hexdigest(), detected_mime)

    async def read_for_scan(self, document: DocumentRegistryEntry) -> bytes:
        if document.state is not DocumentState.SCANNING or not document.object_key:
            raise ObjectVerificationError("Document is not ready for malware scanning")
        if document.object_key != self.object_key(document):
            raise ObjectVerificationError("Source object is outside quarantine scope")
        response = await asyncio.to_thread(
            self._client().get_object,
            Bucket=self._bucket,
            Key=document.object_key,
        )
        body = response["Body"]
        payload = bytearray()
        digest = hashlib.sha256()
        try:
            for chunk in body.iter_chunks(chunk_size=_READ_CHUNK_BYTES):
                if len(payload) + len(chunk) > document.declared_size_bytes:
                    raise ObjectVerificationError("Source object exceeds registered size")
                payload.extend(chunk)
                digest.update(chunk)
        finally:
            body.close()
        if len(payload) != document.declared_size_bytes:
            raise ObjectVerificationError("Source object size changed before scanning")
        if digest.hexdigest() != document.source_checksum_sha256:
            raise ObjectVerificationError("Source object checksum changed before scanning")
        return bytes(payload)

    async def promote_after_clean_scan(
        self, document: DocumentRegistryEntry, processing_run_id: str
    ) -> str:
        if document.state is not DocumentState.SCANNING or not document.object_key:
            raise ObjectVerificationError("Document is not ready for scan promotion")
        if not processing_run_id:
            raise ObjectVerificationError("Processing run identity is required")
        destination = (
            f"clinical-processing/{document.tenant_id}/{document.id}/"
            f"{processing_run_id}/source"
        )
        params: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": destination,
            "CopySource": {"Bucket": self._bucket, "Key": document.object_key},
            "MetadataDirective": "COPY",
        }
        if self._server_side_encryption:
            params["ServerSideEncryption"] = self._server_side_encryption
        await asyncio.to_thread(self._client().copy_object, **params)
        return destination

    async def read_processing_source(self, document: DocumentRegistryEntry) -> bytes:
        if document.state is not DocumentState.PROCESSING or not document.processing_object_key:
            raise ObjectVerificationError("Document is not ready for page normalization")
        expected_prefix = f"clinical-processing/{document.tenant_id}/{document.id}/"
        if not document.processing_object_key.startswith(expected_prefix):
            raise ObjectVerificationError("Processing source is outside document scope")
        response = await asyncio.to_thread(
            self._client().get_object,
            Bucket=self._bucket,
            Key=document.processing_object_key,
        )
        body = response["Body"]
        payload = bytearray()
        digest = hashlib.sha256()
        try:
            for chunk in body.iter_chunks(chunk_size=_READ_CHUNK_BYTES):
                if len(payload) + len(chunk) > document.declared_size_bytes:
                    raise ObjectVerificationError("Processing source exceeds registered size")
                payload.extend(chunk)
                digest.update(chunk)
        finally:
            body.close()
        if len(payload) != document.declared_size_bytes:
            raise ObjectVerificationError("Processing source size changed")
        if digest.hexdigest() != document.source_checksum_sha256:
            raise ObjectVerificationError("Processing source checksum changed")
        return bytes(payload)

    async def store_normalized_pages(
        self,
        document: DocumentRegistryEntry,
        normalization_run_id: str,
        pages: list[NormalizedPage],
    ) -> list[StoredPage]:
        if document.state is not DocumentState.PROCESSING:
            raise ObjectVerificationError("Document is not in processing state")
        if not pages or not normalization_run_id:
            raise ObjectVerificationError("Normalized pages and run identity are required")
        stored: list[StoredPage] = []
        client = self._client()
        for page in pages:
            object_key = (
                f"derived/{document.tenant_id}/{document.id}/{normalization_run_id}/"
                f"pages/{page.page_number:04d}.png"
            )
            params: dict[str, Any] = {
                "Bucket": self._bucket,
                "Key": object_key,
                "Body": page.data,
                "ContentType": page.mime,
                "Metadata": {
                    "document-id": str(document.id),
                    "source-checksum": document.source_checksum_sha256 or "",
                    "normalization-run-id": normalization_run_id,
                    "preprocessing-version": page.preprocessing_version,
                },
            }
            if self._server_side_encryption:
                params["ServerSideEncryption"] = self._server_side_encryption
            await asyncio.to_thread(client.put_object, **params)
            stored.append(
                StoredPage(
                    page_number=page.page_number,
                    object_key=object_key,
                    checksum_sha256=page.checksum_sha256,
                    mime=page.mime,
                    width=page.width,
                    height=page.height,
                    preprocessing_version=page.preprocessing_version,
                    operations=page.operations,
                )
            )
        return stored

    async def read_normalized_page(
        self,
        document: DocumentRegistryEntry,
        page: PageArtifact,
        *,
        max_bytes: int,
    ) -> bytes:
        if document.state is not DocumentState.PROCESSING:
            raise ObjectVerificationError("Document is not ready for OCR")
        if max_bytes <= 0:
            raise ObjectVerificationError("OCR page byte limit must be positive")
        expected_prefix = f"derived/{document.tenant_id}/{document.id}/"
        if not page.object_key.startswith(expected_prefix):
            raise ObjectVerificationError("Normalized page is outside document scope")
        if page.mime != "image/png":
            raise ObjectVerificationError("Normalized page type is not supported")
        response = await asyncio.to_thread(
            self._client().get_object,
            Bucket=self._bucket,
            Key=page.object_key,
        )
        body = response["Body"]
        payload = bytearray()
        digest = hashlib.sha256()
        try:
            for chunk in body.iter_chunks(chunk_size=_READ_CHUNK_BYTES):
                if len(payload) + len(chunk) > max_bytes:
                    raise ObjectVerificationError("Normalized page exceeds OCR byte limit")
                payload.extend(chunk)
                digest.update(chunk)
        finally:
            body.close()
        if digest.hexdigest() != page.checksum_sha256:
            raise ObjectVerificationError("Normalized page checksum changed before OCR")
        return bytes(payload)

    async def create_page_preview_grant(
        self, document: DocumentRegistryEntry, page: PageArtifact
    ) -> PreviewGrant:
        if document.state not in {
            DocumentState.REVIEW_REQUIRED,
            DocumentState.REVIEWED,
        }:
            raise ObjectVerificationError("Document is not available for review preview")
        expected_prefix = f"derived/{document.tenant_id}/{document.id}/"
        if not page.object_key.startswith(expected_prefix):
            raise ObjectVerificationError("Preview page is outside document scope")
        url = await asyncio.to_thread(
            self._presign_client().generate_presigned_url,
            "get_object",
            Params={"Bucket": self._bucket, "Key": page.object_key},
            ExpiresIn=settings.DOCUMENT_PREVIEW_GRANT_TTL_SECONDS,
            HttpMethod="GET",
        )
        return PreviewGrant(url, settings.DOCUMENT_PREVIEW_GRANT_TTL_SECONDS)
