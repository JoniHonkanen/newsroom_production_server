# schema.py
import strawberry
from typing import List, Optional
from enum import Enum


# GraphQL Types
@strawberry.type
class Location:
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    continent: Optional[str] = None

# LOCATION TAGS
@strawberry.type
class LocationTags:
    locations: List[Location]

# BODY BLOCKS - with this we construct the body of the news article
@strawberry.type
class BodyBlock:
    html: Optional[str] = None
    type: str
    order: Optional[int] = None
    content: Optional[str] = None


@strawberry.type
class Source:
    url: Optional[str] = None
    title: Optional[str] = None
    source: Optional[str] = None
    
@strawberry.type
class CategoryStats:
    id: int
    slug: str
    count: int



# By default, Strawberry converts snake_case field names to camelCase in the GraphQL schema.
# Since the database and backend use snake_case, we explicitly define field names
# to maintain consistency and prevent errors (e.g., ApolloError: unknown field).
@strawberry.type
class NewsArticle:
    id: strawberry.ID
    canonical_news_id: int = strawberry.field(name="canonical_news_id")
    language: str
    version: Optional[int] = None
    lead: Optional[str] = None
    summary: Optional[str] = None
    status: Optional[str] = None
    location_tags: Optional[LocationTags] = strawberry.field(default=None, name="location_tags")
    sources: Optional[List[Source]] = strawberry.field(default=None, name="sources")
    interviews: Optional[List[str]] = strawberry.field(default=None, name="interviews")
    review_status: Optional[str] = strawberry.field(default=None, name="review_status")
    author: Optional[str] = None
    body_blocks: Optional[List[BodyBlock]] = strawberry.field(default=None, name="body_blocks")
    enrichment_status: Optional[str] = strawberry.field(default=None, name="enrichment_status")
    markdown_content: Optional[str] = strawberry.field(default=None, name="markdown_content")
    published_at: Optional[str] = strawberry.field(default=None, name="published_at")
    updated_at: Optional[str] = strawberry.field(default=None, name="updated_at")
    original_article_type: Optional[str] = strawberry.field(default=None, name="original_article_type")
    featured: Optional[bool] = None
    categories: List[str] = strawberry.field(default_factory=list)
    hero_image_url: Optional[str] = strawberry.field(default=None, name="hero_image_url")

# For similar news articles
@strawberry.type
class SimilarNewsArticle:
    id: strawberry.ID
    language: Optional[str] = None
    lead: Optional[str] = None
    summary: Optional[str] = None
    published_at: Optional[str] = strawberry.field(default=None, name="published_at")
    updated_at: Optional[str] = strawberry.field(default=None, name="updated_at")
    similarity_score: float = strawberry.field(name="similarity_score")


# Enums
@strawberry.enum
class SortOrder(Enum):
    ASC = "ASC"
    DESC = "DESC"


@strawberry.enum
class NewsOrderField(Enum):
    ID = "ID"
    PUBLISHED_AT = "PUBLISHED_AT"
    UPDATED_AT = "UPDATED_AT"
    CANONICAL_NEWS_ID = "CANONICAL_NEWS_ID"


@strawberry.input
class NewsOrderBy:
    field: NewsOrderField
    order: SortOrder
