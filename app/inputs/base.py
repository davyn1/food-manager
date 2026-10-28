"""Item input sources (Phase 3 seam).

Manual entry, photo recognition and receipt scanning all produce `ItemDraft`s. Drafts go
through one confirm/edit screen, become `ItemCreate`s, and only then reach
`PantryService.add_items`. A new source only needs to implement `InputSource`.
"""

from typing import Any, Protocol

from app.core.schemas import ItemDraft


class InputSource(Protocol):
    name: str

    def drafts(self, payload: Any) -> list[ItemDraft]:
        """Turn source-specific input (form fields, an image, a receipt) into drafts."""
        ...
