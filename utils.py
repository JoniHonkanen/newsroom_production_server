# utils.py
import json
import re
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from schema import (
    NewsArticle,
    Location,
    LocationTags,
    Source,
    BodyBlock,
    NewsOrderBy,
    SortOrder,
    NewsOrderField,
)

logger = logging.getLogger(__name__)


def remove_markdown_syntax(text: str) -> str:
    """Remove markdown syntax from text - Python equivalent of JavaScript function"""
    if not text or not isinstance(text, str):
        return text

    # Remove headers
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Remove bold/italic
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"_(.*?)_", r"\1", text)
    # Remove links
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Remove code blocks
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Remove quotes
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)
    # Remove lists
    text = re.sub(r"^[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)
    # Clean whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_json_field(field_value: Any, default=None) -> Any:
    """Safely parse JSON field"""
    if field_value is None:
        return default

    if isinstance(field_value, str):
        try:
            return json.loads(field_value)
        except json.JSONDecodeError:
            logger.error(f"Error parsing JSON field: {field_value}")
            return default

    return field_value


def parse_location_tags(location_tags_data: Any) -> Optional[LocationTags]:
    """Parse location tags from database"""
    if not location_tags_data:
        return None

    parsed_data = parse_json_field(location_tags_data)
    if not parsed_data or not isinstance(parsed_data, dict):
        return None

    locations = parsed_data.get("locations", [])
    if not isinstance(locations, list):
        return None

    location_objects = []
    for loc in locations:
        if isinstance(loc, dict):
            location_objects.append(
                Location(
                    city=loc.get("city"),
                    region=loc.get("region"),
                    country=loc.get("country"),
                    continent=loc.get("continent"),
                )
            )

    return LocationTags(locations=location_objects)


def parse_sources(sources_data: Any) -> Optional[List[Source]]:
    """Parse sources from database"""
    if not sources_data:
        return []

    parsed_sources = parse_json_field(sources_data, [])
    if not isinstance(parsed_sources, list):
        return []

    source_objects = []
    for source in parsed_sources:
        if isinstance(source, dict):
            source_objects.append(
                Source(
                    url=source.get("url"),
                    title=source.get("title"),
                    source=source.get("source"),
                )
            )
        elif isinstance(source, str):
            # Handle simple string URLs
            source_objects.append(Source(url=source))

    return source_objects


def parse_body_blocks(body_blocks_data: Any) -> Optional[List[BodyBlock]]:
    """Parse body blocks from database"""
    if not body_blocks_data:
        return []

    parsed_blocks = parse_json_field(body_blocks_data, [])
    if not isinstance(parsed_blocks, list):
        return []

    block_objects = []
    for block in parsed_blocks:
        if isinstance(block, dict):
            block_objects.append(
                BodyBlock(
                    html=block.get("html"),
                    type=block.get("type", "text"),
                    order=block.get("order", 0),
                    content=block.get("content"),
                )
            )

    return block_objects


def parse_interviews(interviews_data: Any) -> Optional[List[str]]:
    """Parse interviews from database"""
    if not interviews_data:
        return []

    parsed_interviews = parse_json_field(interviews_data, [])
    if isinstance(parsed_interviews, list):
        return [str(item) for item in parsed_interviews]

    return []


def build_order_clause(order_by: Optional[NewsOrderBy]) -> str:
    """Build SQL ORDER BY clause"""
    if not order_by:
        return "ORDER BY published_at DESC"

    sort_order = "ASC" if order_by.order == SortOrder.ASC else "DESC"

    field_mapping = {
        NewsOrderField.ID: "id",
        NewsOrderField.PUBLISHED_AT: "published_at",
        NewsOrderField.UPDATED_AT: "updated_at",
        NewsOrderField.CANONICAL_NEWS_ID: "canonical_news_id",
    }

    field_name = field_mapping.get(order_by.field, "published_at")
    return f"ORDER BY {field_name} {sort_order}"


def format_datetime(dt: Optional[datetime]) -> Optional[str]:
    """Format datetime to ISO string"""
    return dt.isoformat() if dt else None


def map_db_row_to_news_article(row: Dict[str, Any]) -> NewsArticle:
    """Map database row to NewsArticle object"""
    return NewsArticle(
        id=str(row["id"]),
        canonical_news_id=row.get("canonical_news_id", 0),
        language=row["language"],
        version=row.get("version"),
        lead=remove_markdown_syntax(row.get("lead")) if row.get("lead") else None,
        summary=row.get("summary"),
        status=row.get("status"),
        location_tags=parse_location_tags(row.get("location_tags")),
        sources=parse_sources(row.get("sources")),
        interviews=parse_interviews(row.get("interviews")),
        review_status=row.get("review_status"),
        author=row.get("author"),
        body_blocks=parse_body_blocks(row.get("body_blocks")),
        enrichment_status=row.get("enrichment_status"),
        markdown_content=row.get("markdown_content"),
        published_at=format_datetime(row.get("published_at")),
        updated_at=format_datetime(row.get("updated_at")),
        original_article_type=row.get("original_article_type"),
        featured=row.get("featured"),
    )
