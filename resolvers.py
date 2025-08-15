# resolvers.py
import strawberry
from strawberry import ID
import logging
from typing import List, Optional

from schema import CategoryStats, NewsArticle, NewsOrderBy, SimilarNewsArticle
from database import get_db_pool
from utils import build_order_clause, map_db_row_to_news_article

logger = logging.getLogger(__name__)


@strawberry.type
class Query:

    # All the news (without featured)
    @strawberry.field
    async def news(
        self,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
        total_limit: Optional[int] = None,
        order_by: Optional[NewsOrderBy] = None,
    ) -> List[NewsArticle]:
        """Fetch all news articles"""
        try:
            effective_limit = limit or 17
            effective_offset = offset or 0
            max_limit = total_limit or 100

            remaining_count = max(0, max_limit - effective_offset)
            final_limit = min(effective_limit, remaining_count)

            if final_limit <= 0:
                return []

            order_clause = build_order_clause(order_by)

            pool = await get_db_pool()
            async with pool.acquire() as conn:
                query = f"""
                    SELECT 
                        id, language, lead, summary,
                        published_at, updated_at, categories, hero_image_url
                    FROM news_article 
                    WHERE COALESCE(featured, false) = false
                    {order_clause}
                    LIMIT $1 OFFSET $2
                """

                rows = await conn.fetch(query, final_limit, effective_offset)

                return [map_db_row_to_news_article(dict(row)) for row in rows]

        except Exception as e:
            logger.error(f"Error fetching news: {e}")
            raise Exception("Failed to fetch news articles")

    # Featured news articles
    @strawberry.field
    async def featured_news(
        self,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        total_limit: Optional[int] = None,
        order_by: Optional[NewsOrderBy] = None,
    ) -> List[NewsArticle]:
        """Fetch featured news articles"""
        try:
            effective_limit = limit or 2
            effective_offset = offset or 0
            max_limit = total_limit or 100

            remaining_count = max(0, max_limit - effective_offset)
            final_limit = min(effective_limit, remaining_count)

            if final_limit <= 0:
                return []

            order_clause = build_order_clause(order_by)

            pool = await get_db_pool()
            async with pool.acquire() as conn:
                query = f"""
                    SELECT 
                        id, language, lead, summary,
                        location_tags, author,
                        published_at, updated_at, featured, categories, hero_image_url
                    FROM news_article 
                    WHERE featured = true
                    {order_clause}
                    LIMIT $1 OFFSET $2
                """

                rows = await conn.fetch(query, final_limit, effective_offset)

                return [map_db_row_to_news_article(dict(row)) for row in rows]

        except Exception as e:
            logger.error(f"Error fetching featured news: {e}")
            raise Exception("Failed to fetch featured news articles")

    # Most relevant categories based on category count (How many articles are in each category)
    @strawberry.field
    async def top_categories(self, limit: Optional[int] = 8) -> List[CategoryStats]:
        """Yksinkertainen versio ilman kielirajausta"""
        try:
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                query = """
                SELECT 
                    c.id,
                    c.slug,
                    COUNT(DISTINCT na.id) as article_count
                FROM category c
                LEFT JOIN news_article_category nac ON c.id = nac.category_id
                LEFT JOIN news_article na ON na.id = nac.article_id
                WHERE na.id IS NOT NULL
                GROUP BY c.id, c.slug
                HAVING COUNT(DISTINCT na.id) > 0
                ORDER BY article_count DESC
                LIMIT $1
                """
                rows = await conn.fetch(query, limit)

                return [
                    CategoryStats(
                        id=row["id"],
                        slug=row["slug"],
                        count=row["article_count"],
                    )
                    for row in rows
                ]

        except Exception as e:
            logger.error(f"Error fetching top categories: {e}")
            raise Exception("Failed to fetch top categories")

    # We use this is user want to search news by category
    @strawberry.field
    async def news_by_category(
        self,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
        total_limit: Optional[int] = None,
        order_by: Optional[NewsOrderBy] = None,
        category_slug: str = "",
    ) -> List[NewsArticle]:
        """Hae uutiset kategorian perusteella"""
        try:
            effective_limit = limit or 17
            effective_offset = offset or 0
            max_limit = total_limit or 100

            remaining_count = max(0, max_limit - effective_offset)
            final_limit = min(effective_limit, remaining_count)

            if final_limit <= 0:
                return []

            order_clause = build_order_clause(order_by)

            pool = await get_db_pool()
            async with pool.acquire() as conn:
                query = f"""
                    SELECT DISTINCT
                        na.id, na.language, na.lead, na.summary, 
                        na.published_at, na.updated_at, na.author, na.featured, na.categories, na.hero_image_url
                    FROM news_article na
                    JOIN news_article_category nac ON na.id = nac.article_id
                    JOIN category c ON c.id = nac.category_id
                    WHERE c.slug = $1 AND COALESCE(na.featured, false) = false
                    {order_clause}
                    LIMIT $2 OFFSET $3
                """
                rows = await conn.fetch(
                    query, category_slug, final_limit, effective_offset
                )
                return [map_db_row_to_news_article(dict(row)) for row in rows]

        except Exception as e:
            logger.error(f"Error fetching news by category: {e}")
            raise Exception("Failed to fetch news by category")

    # Featured news articles WITH CATEGORY
    @strawberry.field
    async def featured_news_by_category(
        self,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        total_limit: Optional[int] = None,
        order_by: Optional[NewsOrderBy] = None,
        category_slug: str = "",
    ) -> List[NewsArticle]:
        """Hae featured uutiset kategorian perusteella"""
        try:
            effective_limit = limit or 2
            effective_offset = offset or 0
            max_limit = total_limit or 100

            remaining_count = max(0, max_limit - effective_offset)
            final_limit = min(effective_limit, remaining_count)

            if final_limit <= 0:
                return []

            order_clause = build_order_clause(order_by)

            pool = await get_db_pool()
            async with pool.acquire() as conn:
                query = f"""
                    SELECT DISTINCT
                        na.id, na.language, na.lead, na.summary, 
                        na.published_at, na.updated_at, na.author, na.featured, na.categories, na.hero_image_url
                    FROM news_article na
                    JOIN news_article_category nac ON na.id = nac.article_id
                    JOIN category c ON c.id = nac.category_id
                    WHERE c.slug = $1 AND COALESCE(na.featured, false) = true
                    {order_clause}
                    LIMIT $2 OFFSET $3
                """
                rows = await conn.fetch(
                    query, category_slug, final_limit, effective_offset
                )
                return [map_db_row_to_news_article(dict(row)) for row in rows]

        except Exception as e:
            logger.error(f"Error fetching featured news by category: {e}")
            raise Exception("Failed to fetch featured news by category")

    # SINGLE ARTICLE -> FIND BY ID
    @strawberry.field
    async def news_article(self, id: ID) -> Optional[NewsArticle]:
        """Fetch single news article by ID"""
        try:
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                query = """
                    SELECT 
                        id, canonical_news_id, language, version, lead, summary, status,
                        location_tags, sources, interviews, review_status, author,
                        body_blocks, enrichment_status, markdown_content,
                        published_at, updated_at, original_article_type, featured, categories, hero_image_url
                    FROM news_article 
                    WHERE id = $1
                """

                row = await conn.fetchrow(query, int(id))

                if not row:
                    return None

                return map_db_row_to_news_article(dict(row))

        except Exception as e:
            logger.error(f"Error fetching news article: {e}")
            raise Exception("Failed to fetch news article")

    # Similar news articles based on lead and summary

    @strawberry.field
    async def similar_articles(
        self,
        article_id: int,
        limit: Optional[int] = 5,
        min_similarity: Optional[float] = 0.4,
        max_age_days: Optional[int] = None,
    ) -> List[NewsArticle]:  # Käytä NewsArticle tyyppiä, ei SimilarNewsArticle
        """Hae samankaltaisia artikkeleita embedding-vektorien perusteella"""

        try:
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                where_conditions = [
                    "na.id != $1",
                    "na.embedding IS NOT NULL",
                    "target.embedding IS NOT NULL",
                    f"(1 - (na.embedding <=> target.embedding)) > $2",  # Korjaa tämä
                ]

                params = [article_id, min_similarity]
                param_counter = 3

                if max_age_days is not None:
                    where_conditions.append(
                        f"na.published_at > NOW() - INTERVAL '{max_age_days} days'"
                    )

                where_clause = " AND ".join(where_conditions)

                query = f"""
                    SELECT 
                        na.id,
                        na.language,
                        na.lead,
                        na.summary,
                        na.published_at,
                        na.updated_at,
                        na.categories,
                        na.hero_image_url
                    FROM news_article na
                    CROSS JOIN (
                        SELECT embedding 
                        FROM news_article 
                        WHERE id = $1
                    ) AS target
                    WHERE {where_clause}
                    ORDER BY na.embedding <=> target.embedding
                    LIMIT $3
                """

                rows = await conn.fetch(query, *params + [limit])

                # Yksinkertainen mapping
                return [map_db_row_to_news_article(dict(row)) for row in rows]

        except Exception as e:
            logger.error(f"Error fetching similar articles: {e}")
            raise Exception("Failed to fetch similar articles")

    # NOT USED YET... WHEN WE HAVE MULTIPLE LANGUAGES, THEN MAYBE WE NEED THIS
    @strawberry.field
    async def news_by_language(self, language: str) -> List[NewsArticle]:
        """Fetch news articles by language"""
        try:
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                query = """
                    SELECT 
                        id, canonical_news_id, language, version, lead, summary, status,
                        location_tags, sources, interviews, review_status, author,
                        body_blocks, enrichment_status, markdown_content,
                        published_at, updated_at, original_article_type
                    FROM news_article 
                    WHERE language = $1
                    ORDER BY published_at DESC
                """

                rows = await conn.fetch(query, language)

                return [map_db_row_to_news_article(dict(row)) for row in rows]

        except Exception as e:
            logger.error(f"Error fetching news by language: {e}")
            raise Exception("Failed to fetch news articles by language")

    @strawberry.field
    async def news_by_status(self, status: str) -> List[NewsArticle]:
        """Fetch news articles by status"""
        try:
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                query = """
                    SELECT 
                        id, canonical_news_id, language, version, lead, summary, status,
                        location_tags, sources, interviews, review_status, author,
                        body_blocks, enrichment_status, markdown_content,
                        published_at, updated_at, original_article_type
                    FROM news_article 
                    WHERE status = $1
                    ORDER BY published_at DESC
                """

                rows = await conn.fetch(query, status)

                return [map_db_row_to_news_article(dict(row)) for row in rows]

        except Exception as e:
            logger.error(f"Error fetching news by status: {e}")
            raise Exception("Failed to fetch news articles by status")
