"""Validation for chat attachments.

Only images are used by the advisor (they are passed to the model as vision input), so only
inline image data URLs are accepted. Everything else is rejected instead of being stored and
silently ignored, and sizes are bounded because attachments are persisted with the message.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

MAX_ATTACHMENTS = 4
MAX_IMAGE_BYTES = 4 * 1024 * 1024
ALLOWED_IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")

_DATA_URL = re.compile(r"^data:(image/[a-z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+)$")


class AttachmentError(ValueError):
    """Raised with a user-facing message when an attachment is not acceptable."""


def validate_attachments(raw: Optional[List[Any]]) -> List[Dict[str, Any]]:
    """Return a cleaned list of image attachments or raise AttachmentError."""
    if not raw:
        return []
    if not isinstance(raw, list):
        raise AttachmentError("Attachments must be a list.")
    if len(raw) > MAX_ATTACHMENTS:
        raise AttachmentError(f"You can attach at most {MAX_ATTACHMENTS} images per message.")

    cleaned: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise AttachmentError("Each attachment must be an object.")
        data = item.get("data")
        match = _DATA_URL.match(data) if isinstance(data, str) else None
        if not match:
            raise AttachmentError("Only image attachments (PNG, JPEG, WebP or GIF) are supported.")
        mime = match.group(1).lower()
        if mime not in ALLOWED_IMAGE_TYPES:
            raise AttachmentError("Only image attachments (PNG, JPEG, WebP or GIF) are supported.")
        approx_bytes = len(match.group(2)) * 3 // 4
        if approx_bytes > MAX_IMAGE_BYTES:
            raise AttachmentError(f"Each image must be {MAX_IMAGE_BYTES // (1024 * 1024)} MB or smaller.")
        name = str(item.get("name") or "image")[:120]
        cleaned.append({"type": "image", "name": name, "mime_type": mime, "size": approx_bytes, "data": data})
    return cleaned
