"""
SkillSemanticRouter — Embedding-basierter Skill-Gate

Deterministisches, LLM-freies Routing:
- Wenn ein passender Skill gefunden (Score > MATCH_THRESHOLD) → use_existing
- Wenn Score unter Schwellwert → create_new (MiniControlLayer übernimmt)

Kein Prompt-Update nötig wenn neue Skills hinzukommen.
Kein Layer wird übergangen — sitzt als Schritt 1.7 im Orchestrator.
"""

import re
from typing import Optional, Dict, Any
from utils.logger import log_info, log_warn

# ═══════════════════════════════════════════════════════
# SCHWELLWERTE
# ═══════════════════════════════════════════════════════

MATCH_THRESHOLD = 0.75   # Score > 0.75 → existierender Skill ist gut genug
PARTIAL_THRESHOLD = 0.50  # Score 0.50-0.75 → Skill existiert, aber unsicher

# Maximale Länge der Embedding-Query (Performance)
MAX_QUERY_LEN = 200


class SkillRouterDecision:
    """Ergebnis einer Skill-Router-Entscheidung."""

    __slots__ = ("decision", "skill_name", "score", "reason")

    def __init__(
        self,
        decision: str,       # "use_existing" | "create_new" | "pass_through"
        skill_name: Optional[str] = None,
        score: float = 0.0,
        reason: str = "",
    ):
        self.decision = decision
        self.skill_name = skill_name
        self.score = score
        self.reason = reason

    def __repr__(self):
        return (
            f"SkillRouterDecision(decision={self.decision!r}, "
            f"skill={self.skill_name!r}, score={self.score:.3f})"
        )


class SkillSemanticRouter:
    """
    Embedding-basierter Skill-Router.

    Workflow:
    1. Baue Query aus user_text + intent
    2. Suche in _skills graph via cosine similarity (kein extra LLM)
    3. Entscheide basierend auf Score:
       - > MATCH_THRESHOLD  → use_existing (run_skill)
       - > PARTIAL_THRESHOLD → create_new (aber warnen)
       - sonst              → create_new (definitive Lücke)
    """

    def route(
        self,
        user_text: str,
        intent: str = "",
        top_k: int = 3,
    ) -> SkillRouterDecision:
        """
        Haupt-Routing-Methode.

        Args:
            user_text: Originale User-Anfrage
            intent:    Intent aus ThinkingLayer-Plan
            top_k:     Wie viele Treffer prüfen

        Returns:
            SkillRouterDecision
        """
        try:
            from mcp.client import skill_semantic_search

            query = self._build_query(user_text, intent)
            results = skill_semantic_search(
                query=query,
                limit=top_k,
                min_similarity=0.0,  # Alle Scores liefern, wir filtern selbst
            )

            if not results:
                log_info("[SkillRouter] Kein Skill im Graph gefunden")
                return SkillRouterDecision(
                    decision="create_new",
                    reason="Kein Skill im Graph",
                )

            # Bester Treffer
            best = results[0]
            score = float(best.get("similarity", 0.0))
            content = best.get("content", "")

            # Skill-Name aus Content extrahieren
            skill_name = self._extract_skill_name(content, best.get("metadata", {}))

            log_info(
                f"[SkillRouter] Bester Treffer: '{skill_name}' score={score:.3f} "
                f"(threshold={MATCH_THRESHOLD})"
            )

            if score >= MATCH_THRESHOLD:
                return SkillRouterDecision(
                    decision="use_existing",
                    skill_name=skill_name,
                    score=score,
                    reason=f"Hohe Ähnlichkeit ({score:.2f}) mit '{skill_name}'",
                )
            elif score >= PARTIAL_THRESHOLD:
                log_info(
                    f"[SkillRouter] Partieller Treffer ({score:.2f}) — "
                    f"Skill '{skill_name}' könnte passen, Score zu niedrig"
                )
                return SkillRouterDecision(
                    decision="create_new",
                    skill_name=skill_name,
                    score=score,
                    reason=f"Partieller Treffer ({score:.2f}) — neuer Skill wird erstellt",
                )
            else:
                return SkillRouterDecision(
                    decision="create_new",
                    score=score,
                    reason=f"Kein passender Skill (bester Score: {score:.2f})",
                )

        except Exception as e:
            log_warn(f"[SkillRouter] Fehler bei Routing: {e} — pass_through")
            return SkillRouterDecision(
                decision="pass_through",
                reason=f"Router-Fehler: {e}",
            )

    # ─────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────

    def _build_query(self, user_text: str, intent: str) -> str:
        """Baut eine kompakte Query für die Embedding-Suche."""
        parts = []
        if intent and intent != "unknown":
            parts.append(intent.strip())
        if user_text:
            parts.append(user_text.strip())
        query = " ".join(parts)
        return query[:MAX_QUERY_LEN]

    def _extract_skill_name(self, content: str, metadata: dict) -> Optional[str]:
        """
        Extrahiert den Skill-Namen aus einem Embedding-Ergebnis.
        Format in graph_add_node: "skill:NAME description..." oder "NAME: description"
        """
        # Metadata-Prio (gesetzt von _register_skill_in_graph)
        if metadata.get("skill_name"):
            return metadata["skill_name"]
        if metadata.get("name"):
            return metadata["name"]

        # Content-Parsing: "skill:NAME ..." Format
        m = re.match(r"^skill:(\S+)", content, re.IGNORECASE)
        if m:
            return m.group(1)

        # "crypto_price: Zeigt..." Format
        m = re.match(r"^([a-z0-9_]+)\s*:", content)
        if m:
            return m.group(1)

        # Fallback: erstes Wort
        first_word = content.split()[0] if content.split() else None
        return first_word


# ═══════════════════════════════════════════════════════
# KEYWORD EXTRAKTION (für Skill-Registrierung)
# ═══════════════════════════════════════════════════════

# Deutsche + englische Stop-Words (minimal)
_STOP_WORDS = frozenset({
    "der", "die", "das", "ein", "eine", "und", "oder", "ist", "sind",
    "wird", "werden", "für", "von", "mit", "auf", "bei", "nach",
    "the", "a", "an", "is", "are", "for", "of", "with", "on", "in",
    "to", "this", "that", "and", "or", "it", "its", "skill", "erstellt",
    "zeigt", "gibt", "macht", "holt", "liefert", "shows", "gets", "returns",
})


def extract_skill_keywords(name: str, description: str = "") -> list:
    """
    Extrahiert Keywords aus Skill-Name + Description.
    KEIN LLM — rein regelbasiert.

    Verarbeitet:
    - snake_case → einzelne Wörter: "crypto_price" → ["crypto", "price"]
    - camelCase → einzelne Wörter: "cryptoPrice" → ["crypto", "price"]
    - Description → Wörter ohne Stop-Words

    Returns:
        List[str] unique keywords, max 20
    """
    keywords = set()

    # 1. Skill-Name: snake_case + camelCase aufsplitten
    name_parts = re.split(r"[_\-\s]+", name.lower())
    for part in name_parts:
        # camelCase innerhalb der Parts
        sub = re.sub(r"([a-z])([A-Z])", r"\1 \2", part).lower()
        for word in sub.split():
            if len(word) >= 3 and word not in _STOP_WORDS:
                keywords.add(word)

    # 2. Description: Wörter ohne Stop-Words
    if description:
        desc_words = re.findall(r"[a-zA-ZäöüÄÖÜß]{3,}", description.lower())
        for word in desc_words:
            if word not in _STOP_WORDS and len(word) >= 3:
                keywords.add(word)

    return sorted(keywords)[:20]


# Singleton
_router: Optional[SkillSemanticRouter] = None


def get_skill_router() -> SkillSemanticRouter:
    global _router
    if _router is None:
        _router = SkillSemanticRouter()
    return _router
