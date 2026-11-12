import hashlib
import uuid
from pathlib import Path

from app.core.config import settings


ALLOWED_EVIDENCE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf", ".csv", ".json", ".xml"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def save_evidence_file(filename: str, content: bytes, category: str = "general") -> dict:
    """Store uploaded evidence outside public paths using UUID keys to block path traversal."""
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("File exceeds maximum allowed size of 10 MB")
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EVIDENCE_EXTENSIONS:
        raise ValueError(f"Unsupported file extension: {ext}")
    safe_category = "".join(c for c in category.lower() if c.isalnum() or c in ("_", "-")) or "general"
    target_dir = (settings.storage_path / safe_category).resolve()
    if settings.storage_path.resolve() not in target_dir.parents and target_dir != settings.storage_path.resolve():
        raise ValueError("Invalid storage category path")
    target_dir.mkdir(parents=True, exist_ok=True)
    file_id = f"{uuid.uuid4().hex}{ext}"
    dest = target_dir / file_id
    dest.write_bytes(content)
    sha256 = hashlib.sha256(content).hexdigest()
    return {
        "storage_key": f"{safe_category}/{file_id}",
        "sha256": sha256,
        "size_bytes": len(content),
    }


def read_evidence_file(storage_key: str) -> bytes:
    base = settings.storage_path.resolve()
    target = (base / storage_key).resolve()
    if base not in target.parents:
        raise PermissionError("Invalid storage key")
    if not target.exists():
        raise FileNotFoundError("Evidence file not found")
    return target.read_bytes()

