"""Immutable value objects shared across the scraper."""
from __future__ import annotations

from dataclasses import dataclass

SITE = "https://imgflip.com"
# imgflip ids grow with time but pages carry no absolute date. Calibrated on 2026-10-20 from the
# relative ages shown on user-image pages (~630M = Dec 2025, ~640M = Feb 2026), so this is an
# approximation good to a few weeks, not an exact boundary.
ID_2026_START = 633_000_000


@dataclass(frozen=True)
class Box:
    """One caption text box, in template-pixel coordinates."""

    box_index: int
    x: float
    y: float
    w: float
    h: float
    rotation: float
    font: str
    font_color: str
    outline_color: str
    force_caps: bool
    text_align: str
    vertical_align: str
    font_max_size: int | None = None


@dataclass(frozen=True)
class ListingEntry:
    """A template card from /memetemplates."""

    slug: str
    name: str
    image_url: str
    template_id: int | None


@dataclass(frozen=True)
class TemplateDetail:
    """Template metadata embedded in a /memegenerator/<slug> page."""

    asset_id: int
    creator_uid: int | None
    name: str
    width: int
    height: int
    file_type: str
    alt_names: tuple[str, ...]
    safe_for_work: bool
    boxes: tuple[Box, ...]
    box_count: int
    boxes_explicit: bool


@dataclass(frozen=True)
class ExampleCaption:
    """A community-made meme shown on a template page, with its caption text and author."""

    example_id: str
    url: str
    title: str
    caption_raw: str
    box_texts: tuple[str, ...]
    tags: tuple[str, ...]
    author: str | None
    author_url: str | None
    views: int
    upvotes: int
    comments: int


@dataclass(frozen=True)
class MemeRecord:
    """Everything stored for one meme template."""

    asset_id: int
    slug: str
    name: str
    image_url: str
    width: int
    height: int
    file_type: str
    safe_for_work: bool
    creator_uid: int | None
    alt_names: tuple[str, ...]
    listing_page: int
    boxes: tuple[Box, ...]
    boxes_explicit: bool = True
    default_box_count: int = 2

    @property
    def box_count(self) -> int:
        """Explicit box count, or imgflip's default when the template defines none."""
        return len(self.boxes) if self.boxes_explicit else self.default_box_count

    @property
    def source_url(self) -> str:
        return f"{SITE}/meme/{self.asset_id}/{self.slug}"

    @property
    def attribution(self) -> str:
        uploader = f"imgflip user id {self.creator_uid}" if self.creator_uid else "unknown uploader"
        return (
            f"Template via imgflip.com ({self.source_url}); uploaded by {uploader}. "
            "Underlying image rights belong to the original owner."
        )

    @classmethod
    def from_parts(cls, entry: ListingEntry, detail: TemplateDetail, listing_page: int) -> MemeRecord:
        return cls(
            asset_id=detail.asset_id,
            slug=entry.slug,
            name=detail.name or entry.name,
            image_url=entry.image_url,
            width=detail.width,
            height=detail.height,
            file_type=detail.file_type,
            safe_for_work=detail.safe_for_work,
            creator_uid=detail.creator_uid,
            alt_names=detail.alt_names,
            listing_page=listing_page,
            boxes=detail.boxes,
            boxes_explicit=detail.boxes_explicit,
            default_box_count=detail.box_count,
        )
