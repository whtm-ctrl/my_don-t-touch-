"""
Filtering module for posts.
Handles blacklist/whitelist words, length checks, and duplicate detection.
"""

import re
import hashlib
from typing import List, Optional, Tuple
from datetime import datetime, timezone
import structlog
import numpy as np

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models import BlacklistWord, WhitelistWord, Post, DuplicateCache

logger = structlog.get_logger(__name__)


class ContentFilter:
    """
    Filter class for checking post content against various rules.
    """

    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self._blacklist_cache: List[Tuple[str, bool]] = []
        self._whitelist_cache: List[str] = []
        self._embedding_model = None

    async def load_filters(self) -> None:
        """Load blacklist and whitelist words from database into cache."""
        try:
            # Load blacklist
            blacklist_result = await self.db.execute(
                select(BlacklistWord.word, BlacklistWord.is_regex).where(
                    BlacklistWord.is_active == True
                )
            )
            self._blacklist_cache = blacklist_result.all()

            # Load whitelist
            whitelist_result = await self.db.execute(
                select(WhitelistWord.word).where(
                    WhitelistWord.is_active == True
                )
            )
            self._whitelist_cache = [row[0] for row in whitelist_result.all()]

            logger.info(
                "Filters loaded",
                blacklist_count=len(self._blacklist_cache),
                whitelist_count=len(self._whitelist_cache)
            )
        except Exception as e:
            logger.error("Failed to load filters", error=str(e))
            raise

    def check_blacklist(self, text: str) -> Tuple[bool, Optional[str]]:
        """
        Check if text contains any blacklisted words.
        Returns (is_blocked, matched_word).
        """
        if not text:
            return False, None

        text_lower = text.lower()

        for word, is_regex in self._blacklist_cache:
            if is_regex:
                try:
                    if re.search(word, text_lower, re.IGNORECASE):
                        logger.debug("Blacklist regex match", pattern=word)
                        return True, word
                except re.error as e:
                    logger.warning("Invalid regex pattern", pattern=word, error=str(e))
            else:
                if word.lower() in text_lower:
                    logger.debug("Blacklist word match", word=word)
                    return True, word

        return False, None

    def check_whitelist(self, text: str) -> bool:
        """
        Check if text contains any whitelisted words.
        If whitelist is empty, returns True (no restriction).
        """
        if not text:
            return False

        if not self._whitelist_cache:
            return True  # No whitelist means no restriction

        text_lower = text.lower()
        for word in self._whitelist_cache:
            if word.lower() in text_lower:
                return True

        return False

    def check_length(
        self,
        text: str,
        min_length: int = 10,
        max_length: int = 4096
    ) -> Tuple[bool, str]:
        """
        Check if text length is within acceptable range.
        Returns (is_valid, reason).
        """
        if not text:
            return False, "empty_text"

        if len(text) < min_length:
            return False, f"too_short ({len(text)} < {min_length})"

        if len(text) > max_length:
            return False, f"too_long ({len(text)} > {max_length})"

        return True, "ok"

    def _get_text_hash(self, text: str) -> str:
        """Generate SHA256 hash of normalized text."""
        normalized = " ".join(text.lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()

    def _load_embedding_model(self):
        """Lazy load sentence transformers model."""
        if self._embedding_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
                logger.info("Embedding model loaded successfully")
            except Exception as e:
                logger.error("Failed to load embedding model", error=str(e))
                raise
        return self._embedding_model

    def _compute_embedding(self, text: str) -> np.ndarray:
        """Compute sentence embedding for text."""
        model = self._load_embedding_model()
        embedding = model.encode([text], convert_to_numpy=True)[0]
        return embedding

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    async def check_duplicate(
        self,
        text: str,
        similarity_threshold: float = 0.85
    ) -> Tuple[bool, Optional[float]]:
        """
        Check if text is similar to existing posts using embeddings.
        Returns (is_duplicate, similarity_score).
        """
        if not text or len(text) < 20:
            return False, None

        text_hash = self._get_text_hash(text)

        try:
            # First check exact hash match
            existing = await self.db.execute(
                select(DuplicateCache).where(
                    DuplicateCache.text_hash == text_hash
                )
            )
            if existing.fetchone():
                logger.debug("Exact duplicate found", hash=text_hash)
                return True, 1.0

            # Check semantic similarity
            embedding = self._compute_embedding(text)
            embedding_str = ",".join(map(str, embedding.tolist()))

            # Get recent posts for comparison (last 1000)
            recent_posts = await self.db.execute(
                select(DuplicateCache)
                .where(DuplicateCache.created_at >= func.now() - func.interval('30 days'))
                .order_by(DuplicateCache.created_at.desc())
                .limit(1000)
            )
            cached_items = recent_posts.scalars().all()

            max_similarity = 0.0
            for cached in cached_items:
                if cached.embedding:
                    try:
                        cached_embedding = np.array([
                            float(x) for x in cached.embedding.split(",")
                        ])
                        similarity = self._cosine_similarity(embedding, cached_embedding)
                        max_similarity = max(max_similarity, similarity)

                        if similarity >= similarity_threshold:
                            logger.debug(
                                "Similar post found",
                                similarity=round(similarity, 3),
                                threshold=similarity_threshold
                            )
                            return True, similarity
                    except Exception as e:
                        logger.warning("Failed to compare embeddings", error=str(e))
                        continue

            # Cache the new embedding
            new_cache = DuplicateCache(
                text_hash=text_hash,
                embedding=embedding_str
            )
            self.db.add(new_cache)

            return False, max_similarity

        except Exception as e:
            logger.error("Duplicate check failed", error=str(e))
            return False, None

    def calculate_quality_score(self, text: str, has_media: bool = False) -> float:
        """
        Calculate quality score for a post (0.0 to 1.0).
        Based on various heuristics.
        """
        if not text:
            return 0.0

        score = 0.0

        # Length score (optimal: 100-500 chars)
        length = len(text)
        if 100 <= length <= 500:
            score += 0.3
        elif 50 <= length <= 1000:
            score += 0.2
        elif length > 20:
            score += 0.1

        # Has media bonus
        if has_media:
            score += 0.2

        # Has URLs penalty (might be spam)
        url_pattern = r'https?://\S+'
        url_count = len(re.findall(url_pattern, text))
        if url_count == 0:
            score += 0.2
        elif url_count <= 2:
            score += 0.1
        else:
            score -= 0.2

        # Has emojis bonus (engagement indicator)
        emoji_pattern = r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF]'
        if re.search(emoji_pattern, text):
            score += 0.1

        # Proper capitalization bonus
        sentences = [s.strip() for s in text.split('.') if s.strip()]
        if sentences:
            capitalized = sum(1 for s in sentences if s[0].isupper())
            if capitalized / len(sentences) > 0.7:
                score += 0.1

        # Normalize to 0-1 range
        return max(0.0, min(1.0, score))

    async def validate_post(
        self,
        text: str,
        has_media: bool = False,
        min_length: int = 10,
        max_length: int = 4096,
        similarity_threshold: float = 0.85
    ) -> Tuple[bool, str, float]:
        """
        Comprehensive post validation.
        Returns (is_valid, reason, quality_score).
        """
        # Check blacklist
        is_blocked, matched_word = self.check_blacklist(text)
        if is_blocked:
            return False, f"blacklisted: {matched_word}", 0.0

        # Check whitelist
        if not self.check_whitelist(text):
            return False, "not in whitelist", 0.0

        # Check length
        is_valid_length, length_reason = self.check_length(text, min_length, max_length)
        if not is_valid_length:
            return False, length_reason, 0.0

        # Check duplicates
        is_duplicate, similarity = await self.check_duplicate(text, similarity_threshold)
        if is_duplicate:
            return False, f"duplicate (similarity: {similarity:.2f})", 0.0

        # Calculate quality score
        quality_score = self.calculate_quality_score(text, has_media)

        return True, "passed", quality_score
