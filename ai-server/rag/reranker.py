"""
Reranker
========
Result reranking, deduplication, and diversity filtering for RAG search results.

Strategies:
- score: Pure relevance score reranking
- keyword: Keyword matching boost
- diversity: MMR (Maximal Marginal Relevance) for diverse results
- combined: Fusion of all signals (default)
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any, Optional

from .vector_store import SearchResult

logger = logging.getLogger(__name__)


class RerankStrategy:
    """Enum-like constants for reranking strategies."""

    SCORE = "score"
    KEYWORD = "keyword"
    DIVERSITY = "diversity"
    COMBINED = "combined"


class Reranker:
    """Reranks search results using multiple signals.

    Supports several strategies for combining relevance scores,
    keyword matching, deduplication, and diversity filtering.

    Usage::

        reranker = Reranker(strategy="combined")
        reranked = reranker.rerank("python web scraping", raw_results, top_k=5)
    """

    def __init__(
        self,
        strategy: str = "combined",
        keyword_weight: float = 0.3,
        diversity_weight: float = 0.2,
        dedup_threshold: float = 0.95,
        min_score: float = 0.0,
    ) -> None:
        """Initialize the reranker.

        Args:
            strategy: Reranking strategy ('score', 'keyword', 'diversity', 'combined').
            keyword_weight: Weight for keyword signal in combined mode.
            diversity_weight: Weight for diversity signal in combined mode.
            dedup_threshold: Similarity threshold for deduplication (0.0-1.0).
            min_score: Minimum score to keep a result.
        """
        self.strategy = strategy
        self._keyword_weight = keyword_weight
        self._diversity_weight = diversity_weight
        self._dedup_threshold = dedup_threshold
        self._min_score = min_score

    def rerank(
        self,
        query: str,
        results: list[SearchResult],
        top_k: int = 5,
    ) -> list[SearchResult]:
        """Rerank search results.

        Args:
            query: The original query (used for keyword matching).
            results: Raw search results to rerank.
            top_k: Number of results to return.

        Returns:
            Reranked list of SearchResult objects.
        """
        if not results:
            return []

        # Step 1: Filter by minimum score
        filtered = [r for r in results if r.score >= self._min_score]
        if not filtered:
            filtered = results[:top_k]  # Keep top results even below threshold

        # Step 2: Apply strategy-specific scoring
        if self.strategy == RerankStrategy.SCORE:
            scored = self._score_rerank(query, filtered)
        elif self.strategy == RerankStrategy.KEYWORD:
            scored = self._keyword_rerank(query, filtered)
        elif self.strategy == RerankStrategy.DIVERSITY:
            scored = self._diversity_rerank(query, filtered)
        elif self.strategy == RerankStrategy.COMBINED:
            scored = self._combined_rerank(query, filtered)
        else:
            scored = filtered

        # Step 3: Deduplicate
        deduped = self._deduplicate(scored)

        # Step 4: Diversity filter
        diverse = self._diversify(deduped, top_k)

        return diverse[:top_k]

    def _score_rerank(
        self,
        query: str,
        results: list[SearchResult],
    ) -> list[SearchResult]:
        """Pure score-based reranking (sort by original score)."""
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def _keyword_rerank(
        self,
        query: str,
        results: list[SearchResult],
    ) -> list[SearchResult]:
        """Boost results that match query keywords."""
        query_tokens = set(self._tokenize(query))

        for r in results:
            text_tokens = set(self._tokenize(r.text))
            meta_tokens = set()
            for v in r.metadata.values():
                if isinstance(v, str):
                    meta_tokens.update(self._tokenize(v))
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, str):
                            meta_tokens.update(self._tokenize(item))

            all_tokens = text_tokens | meta_tokens

            # Calculate keyword overlap
            if query_tokens:
                overlap = len(query_tokens & all_tokens) / len(query_tokens)
                r.score = min(1.0, r.score + overlap * self._keyword_weight)

        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def _diversity_rerank(
        self,
        query: str,
        results: list[SearchResult],
    ) -> list[SearchResult]:
        """MMR (Maximal Marginal Relevance) for diversity."""
        if len(results) <= 1:
            return results

        selected: list[SearchResult] = []
        candidates = list(results)

        while candidates and len(selected) < len(results):
            best_idx = 0
            best_mmr = -float("inf")

            for i, candidate in enumerate(candidates):
                # Relevance component
                relevance = candidate.score

                # Diversity component: max similarity to already selected
                max_sim = 0.0
                if selected:
                    cand_tokens = set(self._tokenize(candidate.text))
                    for s in selected:
                        sel_tokens = set(self._tokenize(s.text))
                        if cand_tokens and sel_tokens:
                            sim = len(cand_tokens & sel_tokens) / len(cand_tokens | sel_tokens)
                            max_sim = max(max_sim, sim)

                # MMR = lambda * relevance - (1 - lambda) * max_similarity
                lam = 0.7  # Balance relevance vs diversity
                mmr = lam * relevance - (1 - lam) * max_sim

                if mmr > best_mmr:
                    best_mmr = mmr
                    best_idx = i

            selected.append(candidates.pop(best_idx))

        return selected

    def _combined_rerank(
        self,
        query: str,
        results: list[SearchResult],
    ) -> list[SearchResult]:
        """Combine multiple signals: score + keyword + source diversity."""
        # First pass: keyword boost
        self._keyword_rerank(query, results)

        # Second pass: source diversity boost
        source_counts: dict[str, int] = {}
        for r in results:
            source = r.metadata.get("source", "unknown")
            count = source_counts.get(source, 0)
            if count > 0:
                # Penalize multiple results from same source
                r.score = max(0.0, r.score - 0.1 * count)
            source_counts[source] = count + 1

        # Third pass: type diversity
        type_counts: dict[str, int] = {}
        for r in results:
            doc_type = r.metadata.get("type", "unknown")
            count = type_counts.get(doc_type, 0)
            if count > 1:
                r.score = max(0.0, r.score - 0.05 * (count - 1))
            type_counts[doc_type] = count + 1

        # Sort by final score
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def _deduplicate(self, results: list[SearchResult]) -> list[SearchResult]:
        """Remove near-duplicate results.

        Uses text similarity to detect duplicates while keeping the
        highest-scored version.
        """
        if not results or self._dedup_threshold >= 1.0:
            return results

        unique: list[SearchResult] = []
        seen_hashes: set[str] = set()

        for r in results:
            # Quick dedup by exact text
            text_hash = hash(r.text.strip().lower())
            if text_hash in seen_hashes:
                continue

            # Check for near-duplicates
            is_dup = False
            r_tokens = set(self._tokenize(r.text))
            if r_tokens:
                for existing in unique:
                    e_tokens = set(self._tokenize(existing.text))
                    if e_tokens and r_tokens:
                        similarity = len(r_tokens & e_tokens) / len(r_tokens | e_tokens)
                        if similarity >= self._dedup_threshold:
                            is_dup = True
                            break

            if not is_dup:
                unique.append(r)
                seen_hashes.add(text_hash)

        return unique

    def _diversify(self, results: list[SearchResult], top_k: int) -> list[SearchResult]:
        """Ensure diversity in the top results.

        Makes sure we don't return all results from the same source/type.
        """
        if len(results) <= top_k:
            return results

        # Group by source
        by_source: dict[str, list[SearchResult]] = {}
        for r in results:
            source = r.metadata.get("source", "unknown")
            by_source.setdefault(source, []).append(r)

        # Interleave from different sources
        diversified: list[SearchResult] = []
        source_iters = {k: iter(v) for k, v in by_source.items()}
        max_per_source = max(1, top_k // max(1, len(by_source)))

        while len(diversified) < top_k and source_iters:
            exhausted: list[str] = []
            for source, it in source_iters.items():
                if len(diversified) >= top_k:
                    break
                count = sum(
                    1 for r in diversified
                    if r.metadata.get("source") == source
                )
                if count < max_per_source:
                    try:
                        diversified.append(next(it))
                    except StopIteration:
                        exhausted.append(source)
                else:
                    exhausted.append(source)

            for s in exhausted:
                source_iters.pop(s, None)

            # Fill remaining from any source
            if not source_iters and len(diversified) < top_k:
                for r in results:
                    if r not in diversified:
                        diversified.append(r)
                        if len(diversified) >= top_k:
                            break
                break

        return diversified

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Simple tokenization for keyword matching."""
        text_lower = text.lower()
        # Extract words and 2-char+ tokens
        tokens = re.findall(r"\w+", text_lower)
        # Remove stop words
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "can", "shall",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "as", "into", "through", "during", "before", "after", "and",
            "but", "or", "nor", "not", "so", "yet", "both", "either",
            "neither", "each", "every", "all", "any", "few", "more",
            "most", "other", "some", "such", "no", "only", "own", "same",
            "than", "too", "very", "just", "about", "above", "below",
            "between", "this", "that", "these", "those", "i", "you",
            "he", "she", "it", "we", "they", "what", "which", "who",
            "how", "when", "where", "why",
        }
        return [t for t in tokens if t not in stop_words and len(t) > 1]


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


def rerank_results(
    query: str,
    results: list[SearchResult],
    top_k: int = 5,
    strategy: str = "combined",
) -> list[SearchResult]:
    """Convenience function to rerank results.

    Args:
        query: The original query.
        results: Raw search results.
        top_k: Number of results to return.
        strategy: Reranking strategy.

    Returns:
        Reranked results.
    """
    reranker = Reranker(strategy=strategy)
    return reranker.rerank(query, results, top_k)
