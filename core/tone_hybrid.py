"""
Hybrid tone/dialogue-act classification for TRION.

Design:
- Fast lexical heuristics first (always available)
- Optional embedding similarity refinement (when lexical confidence is low)
- Deterministic fallback when embeddings are unavailable
"""

from __future__ import annotations

import asyncio
import math
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from config import OLLAMA_BASE, get_embedding_model
from utils.logger import log_debug, log_warning
from utils.role_endpoint_resolver import resolve_role_endpoint


class ToneHybridClassifier:
    _TONE_LABELS = ("warm", "neutral", "formal")
    _ACT_LABELS = ("ack", "feedback", "question", "request", "analysis", "smalltalk")

    _TONE_PROTOTYPES = {
        "warm": "Danke dir, passt. Sehr gern, wir machen das zusammen.",
        "neutral": "Verstanden. Ich prüfe die Anfrage und liefere ein Ergebnis.",
        "formal": "Vielen Dank für Ihre Anfrage. Ich werde dies strukturiert prüfen.",
    }
    _ACT_PROTOTYPES = {
        "ack": "ok passt danke",
        "feedback": "das war gut aber bitte lockerer antworten",
        "question": "kannst du mir sagen warum das passiert ist?",
        "request": "prüfe das bitte und erstelle einen plan",
        "analysis": "analysiere das problem und erkläre die ursache",
        "smalltalk": "wie geht es dir heute und wie fühlst du dich",
    }

    _WARM_TOKENS = {
        "danke",
        "dankeschön",
        "dankeschoen",
        "gern",
        "gerne",
        "perfekt",
        "super",
        "top",
        "cool",
        "nice",
        "klasse",
        "passt",
        "lieben",
        "freu",
    }
    _FORMAL_TOKENS = {
        "bitte",
        "könnten",
        "koennten",
        "würden",
        "wuerden",
        "hiermit",
        "vielen",
        "dank",
        "analyse",
        "strukturiert",
        "formal",
    }
    _ACK_TOKENS = {"ok", "okay", "okey", "passt", "verstanden", "alles", "klar", "jo"}
    _FEEDBACK_TOKENS = {"hart", "locker", "ton", "emotion", "mismatch", "stil"}
    _REQUEST_TOKENS = {
        "kannst",
        "bitte",
        "prüf",
        "pruef",
        "check",
        "analysier",
        "analysiere",
        "mach",
        "mache",
        "baue",
        "implementiere",
        "starte",
        "teste",
        "erstelle",
        "plan",
        "leg",
    }
    _ANALYSIS_TOKENS = {
        "analyse",
        "analysiere",
        "ursache",
        "warum",
        "problem",
        "plan",
        "strategie",
        "vergleich",
    }
    _SMALLTALK_TOKENS = {"wie", "fühlst", "fuehlst", "geht", "laune", "mood"}
    _QUESTION_WORDS = {
        "was",
        "wie",
        "warum",
        "wieso",
        "weshalb",
        "wann",
        "wer",
        "wo",
        "welche",
        "welcher",
        "kannst",
    }

    def __init__(self):
        self._prototype_cache: Dict[str, List[float]] = {}
        self._prototype_cache_ts = 0.0
        self._prototype_lock = asyncio.Lock()
        self._prototype_cache_ttl_s = 6 * 60 * 60
        self._embed_timeout_s = 2.8

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return re.findall(r"[a-zA-ZäöüÄÖÜß]+", (text or "").lower())

    @staticmethod
    def _contains_emoji(text: str) -> bool:
        return bool(re.search(r"[\U0001F300-\U0001FAFF]", text or ""))

    @staticmethod
    def _contains_formal_phrase(text: str) -> bool:
        lower = (text or "").lower()
        return any(
            phrase in lower
            for phrase in ("vielen dank", "ich bitte um", "würden sie", "koennten sie", "könnten sie")
        )

    @staticmethod
    def _normalize_scores(scores: Dict[str, float]) -> Dict[str, float]:
        if not scores:
            return {}
        max_v = max(scores.values()) if scores else 0.0
        if max_v <= 0:
            return {k: 0.0 for k in scores}
        return {k: max(0.0, float(v) / max_v) for k, v in scores.items()}

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = 0.0
        norm_a = 0.0
        norm_b = 0.0
        for x, y in zip(a, b):
            dot += x * y
            norm_a += x * x
            norm_b += y * y
        if norm_a <= 0.0 or norm_b <= 0.0:
            return 0.0
        return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))

    async def _embed_text(self, text: str) -> Optional[List[float]]:
        route = resolve_role_endpoint("embedding", default_endpoint=OLLAMA_BASE)
        if route.get("hard_error"):
            return None
        endpoint = route.get("endpoint") or OLLAMA_BASE
        payload = {
            "model": get_embedding_model(),
            "prompt": text,
        }
        try:
            async with httpx.AsyncClient(timeout=self._embed_timeout_s) as client:
                resp = await client.post(f"{endpoint}/api/embeddings", json=payload)
                resp.raise_for_status()
                data = resp.json()
            vec = data.get("embedding")
            if isinstance(vec, list) and vec:
                return [float(v) for v in vec]
        except Exception as e:
            log_debug(f"[ToneHybrid] Embedding unavailable: {type(e).__name__}: {e}")
        return None

    async def _ensure_prototype_vectors(self) -> bool:
        now = time.time()
        if self._prototype_cache and (now - self._prototype_cache_ts) < self._prototype_cache_ttl_s:
            return True
        async with self._prototype_lock:
            now = time.time()
            if self._prototype_cache and (now - self._prototype_cache_ts) < self._prototype_cache_ttl_s:
                return True
            cache: Dict[str, List[float]] = {}
            all_prototypes = {}
            for key, text in self._TONE_PROTOTYPES.items():
                all_prototypes[f"tone::{key}"] = text
            for key, text in self._ACT_PROTOTYPES.items():
                all_prototypes[f"act::{key}"] = text
            for key, text in all_prototypes.items():
                vec = await self._embed_text(text)
                if vec:
                    cache[key] = vec
            if not cache:
                return False
            self._prototype_cache = cache
            self._prototype_cache_ts = now
            return True

    def _lexical_classify(self, user_text: str) -> Dict[str, Any]:
        text = (user_text or "").strip()
        lower = text.lower()
        tokens = self._tokenize(text)
        token_set = set(tokens)
        token_count = len(tokens)
        is_question = "?" in text or (tokens and tokens[0] in self._QUESTION_WORDS)
        has_emoji = self._contains_emoji(text)
        formal_phrase = self._contains_formal_phrase(text)

        warm_hits = len(token_set.intersection(self._WARM_TOKENS)) + (1 if has_emoji else 0)
        formal_hits = len(token_set.intersection(self._FORMAL_TOKENS)) + (1 if formal_phrase else 0)
        ack_hits = len(token_set.intersection(self._ACK_TOKENS))
        feedback_hits = len(token_set.intersection(self._FEEDBACK_TOKENS))
        request_hits = len(token_set.intersection(self._REQUEST_TOKENS))
        analysis_hits = len(token_set.intersection(self._ANALYSIS_TOKENS))
        smalltalk_hits = len(token_set.intersection(self._SMALLTALK_TOKENS))

        tone_scores = {
            "warm": 0.4 + (0.55 * warm_hits) + (0.2 if has_emoji else 0.0),
            "neutral": 0.6 + (0.12 * max(0, token_count - 8)),
            "formal": 0.4 + (0.65 * formal_hits),
        }
        if warm_hits > 0 and formal_hits == 0:
            tone_scores["neutral"] -= 0.15
        if formal_hits > 0:
            tone_scores["warm"] -= 0.1

        act_scores = {
            "ack": 0.2 + (0.8 * ack_hits) + (0.2 if token_count <= 8 else 0.0),
            "feedback": 0.1 + (0.7 * feedback_hits),
            "question": 0.2 + (0.9 if is_question else 0.0),
            "request": 0.2 + (0.7 * request_hits),
            "analysis": 0.15 + (0.55 * analysis_hits),
            "smalltalk": 0.1 + (0.65 * smalltalk_hits),
        }

        if is_question:
            act_scores["ack"] -= 0.2
        if request_hits > 0:
            act_scores["ack"] -= 0.25
        if analysis_hits > 0 and request_hits > 0:
            act_scores["analysis"] += 0.2
        if "zu hart" in lower or "zu streng" in lower:
            act_scores["feedback"] += 0.7
        if "leg los" in lower or "los geht" in lower:
            act_scores["request"] += 0.7
        if "danke" in token_set and request_hits == 0 and not is_question:
            act_scores["ack"] += 0.25

        normalized_tone = self._normalize_scores(tone_scores)
        normalized_act = self._normalize_scores(act_scores)
        return {
            "tone_scores": normalized_tone,
            "act_scores": normalized_act,
            "token_count": token_count,
            "is_question": is_question,
        }

    async def _embedding_classify(self, user_text: str) -> Optional[Dict[str, Dict[str, float]]]:
        if not await self._ensure_prototype_vectors():
            return None
        query_vec = await self._embed_text(user_text)
        if not query_vec:
            return None

        tone_scores: Dict[str, float] = {}
        for label in self._TONE_LABELS:
            vec = self._prototype_cache.get(f"tone::{label}")
            if not vec:
                continue
            tone_scores[label] = (self._cosine_similarity(query_vec, vec) + 1.0) / 2.0

        act_scores: Dict[str, float] = {}
        for label in self._ACT_LABELS:
            vec = self._prototype_cache.get(f"act::{label}")
            if not vec:
                continue
            act_scores[label] = (self._cosine_similarity(query_vec, vec) + 1.0) / 2.0

        return {
            "tone_scores": self._normalize_scores(tone_scores),
            "act_scores": self._normalize_scores(act_scores),
        }

    @staticmethod
    def _top_label(scores: Dict[str, float], default: str) -> Tuple[str, float]:
        if not scores:
            return default, 0.0
        best = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        return best[0][0], float(best[0][1])

    @staticmethod
    def _margin(scores: Dict[str, float]) -> float:
        if not scores:
            return 0.0
        vals = sorted([float(v) for v in scores.values()], reverse=True)
        if len(vals) < 2:
            return vals[0] if vals else 0.0
        return max(0.0, vals[0] - vals[1])

    @staticmethod
    def _length_hint(dialogue_act: str, user_text: str) -> str:
        lower = (user_text or "").lower()
        if any(tok in lower for tok in ("ausführlich", "ausfuehrlich", "detailliert", "im detail")):
            return "long"
        if dialogue_act in {"ack", "feedback", "smalltalk"}:
            return "short"
        if dialogue_act == "analysis":
            return "long"
        if dialogue_act in {"question", "request"}:
            return "medium"
        return "medium"

    async def classify(self, user_text: str, messages: Optional[List[Any]] = None) -> Dict[str, Any]:
        _ = messages  # reserved for future history-aware scoring

        text = (user_text or "").strip()
        if not text:
            return {
                "dialogue_act": "request",
                "response_tone": "neutral",
                "response_length_hint": "medium",
                "tone_confidence": 0.5,
                "classifier_mode": "fallback_empty",
            }

        lexical = self._lexical_classify(text)
        lex_tone_scores = dict(lexical.get("tone_scores", {}))
        lex_act_scores = dict(lexical.get("act_scores", {}))

        lex_tone_label, _ = self._top_label(lex_tone_scores, "neutral")
        lex_act_label, _ = self._top_label(lex_act_scores, "request")
        lexical_margin = min(self._margin(lex_tone_scores), self._margin(lex_act_scores))

        use_embedding = lexical_margin < 0.28 or len(text) > 140
        emb = await self._embedding_classify(text) if use_embedding else None

        if emb:
            tone_scores = {}
            for label in self._TONE_LABELS:
                tone_scores[label] = (0.62 * lex_tone_scores.get(label, 0.0)) + (
                    0.38 * emb["tone_scores"].get(label, 0.0)
                )
            act_scores = {}
            for label in self._ACT_LABELS:
                act_scores[label] = (0.62 * lex_act_scores.get(label, 0.0)) + (
                    0.38 * emb["act_scores"].get(label, 0.0)
                )
            mode = "hybrid"
        else:
            tone_scores = lex_tone_scores
            act_scores = lex_act_scores
            mode = "lexical"
            if use_embedding:
                log_warning("[ToneHybrid] Embedding refinement skipped; using lexical fallback")

        tone_label, _ = self._top_label(tone_scores, lex_tone_label)
        act_label, _ = self._top_label(act_scores, lex_act_label)
        margin = min(self._margin(tone_scores), self._margin(act_scores))
        confidence = max(0.45, min(0.98, 0.56 + (1.25 * margin)))

        if tone_label == "warm":
            response_tone = "mirror_user"
        elif tone_label == "formal":
            response_tone = "formal"
        else:
            response_tone = "neutral"

        result = {
            "dialogue_act": act_label,
            "response_tone": response_tone,
            "response_length_hint": self._length_hint(act_label, text),
            "tone_confidence": round(confidence, 3),
            "classifier_mode": mode,
        }
        log_debug(
            f"[ToneHybrid] mode={mode} act={result['dialogue_act']} tone={result['response_tone']} "
            f"len={result['response_length_hint']} conf={result['tone_confidence']}"
        )
        return result
