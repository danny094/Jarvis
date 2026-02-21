"""
BlueprintSemanticRouter — Embedding-basierter Blueprint-Gate

Deterministisches, LLM-freies Routing für Container-Anfragen:

  score >= MATCH_THRESHOLD_STRICT (0.85)  → use_blueprint    (auto-route, kein User-Input nötig)
  score >= MATCH_THRESHOLD_SUGGEST (0.68) → suggest_blueprint (TRION fragt nach, nennt Top-2 Kandidaten)
  score <  MATCH_THRESHOLD_SUGGEST        → no_blueprint      (kein Match, kein Freestyle-Fallback!)

Warum zwei Schwellwerte:
  Container-Aktionen sind keine read-only Aktionen — Fehlstarts sind teuer.
  0.68 ist für python/node/db/shell-sandbox empirisch korrekt (mxbai-embed-large-v1),
  aber nicht konservativ genug für blindes Auto-Routing.
  Unter 0.85: TRION nennt Top-2 Kandidaten und fragt den User.

Trust-Guard: nur Blueprints mit trust_level="verified" werden berücksichtigt.
Kaputter metadata → treat as untrusted → skip.

Phase 5 — Graph Hygiene:
  Alle Graph-Kandidaten laufen durch apply_graph_hygiene() (core/graph_hygiene.py):
    parse → trust_level-Filter → dedupe_latest_by_blueprint_id → sqlite_crosscheck (fail-closed)
  Kein Fail-Open bei SQLite-Fehler (war vorher: _active_ids = None → skip filter).
"""

from typing import List, Optional
from utils.logger import log_info, log_warn
from core.graph_hygiene import apply_graph_hygiene, GraphCandidate

# ═══════════════════════════════════════════════════════
# SCHWELLWERTE
# ═══════════════════════════════════════════════════════

MATCH_THRESHOLD_STRICT  = 0.85  # Auto-route: hohe Konfidenz, kein User-Input nötig
MATCH_THRESHOLD_SUGGEST = 0.68  # Suggest-Zone: TRION fragt nach (kein blindes Starten!)
PARTIAL_THRESHOLD       = 0.52  # Unter diesem Wert: kein Blueprint erkennbar

MAX_QUERY_LEN = 200


class BlueprintRouterDecision:
    """Ergebnis einer Blueprint-Router-Entscheidung."""

    __slots__ = ("decision", "blueprint_id", "score", "reason", "candidates")

    def __init__(
        self,
        decision: str,                      # "use_blueprint" | "suggest_blueprint" | "no_blueprint"
        blueprint_id: Optional[str] = None,
        score: float = 0.0,
        reason: str = "",
        candidates: Optional[List[dict]] = None,  # [{"id": ..., "score": ...}] für suggest
    ):
        self.decision = decision
        self.blueprint_id = blueprint_id
        self.score = score
        self.reason = reason
        self.candidates = candidates or []

    def __repr__(self):
        return (
            f"BlueprintRouterDecision(decision={self.decision!r}, "
            f"blueprint={self.blueprint_id!r}, score={self.score:.3f})"
        )


class BlueprintSemanticRouter:
    """
    Embedding-basierter Blueprint-Router mit zwei Schwellwerten.

    Workflow (Phase 5):
    1. Baue Query aus user_text + intent
    2. Suche in _blueprints graph via cosine similarity (kein extra LLM)
    3. Hygiene-Pipeline (core/graph_hygiene.apply_graph_hygiene):
         parse → trust_level-Filter → dedupe(latest) → sqlite-crosscheck (fail-closed)
    4. Entscheide basierend auf bestem Score:
       - >= STRICT   → use_blueprint    (auto-route)
       - >= SUGGEST  → suggest_blueprint (Rückfrage mit Top-2)
       - sonst       → no_blueprint     (kein Freestyle-Fallback!)
    """

    def route(
        self,
        user_text: str,
        intent: str = "",
        top_k: int = 5,
    ) -> BlueprintRouterDecision:
        """
        Haupt-Routing-Methode.

        Args:
            user_text: Originale User-Anfrage
            intent:    Intent aus ThinkingLayer-Plan
            top_k:     Wie viele Treffer abrufen (mehr = bessere Suggest-Liste)

        Returns:
            BlueprintRouterDecision
        """
        try:
            from mcp.client import blueprint_semantic_search

            query = self._build_query(user_text, intent)
            results = blueprint_semantic_search(
                query=query,
                limit=top_k,
                min_similarity=0.0,
            )

            if not results:
                log_info("[BlueprintRouter] Kein Blueprint im Graph gefunden")
                return BlueprintRouterDecision(
                    decision="no_blueprint",
                    reason="Kein Blueprint im Graph",
                )

            # Trust-Level-Filter: nur "verified" Blueprints zulassen.
            # Als extra_filter an apply_graph_hygiene() übergeben — läuft VOR dem Dedupe.
            def _trust_filter(c: GraphCandidate) -> bool:
                if c.meta.get("trust_level") != "verified":
                    log_info(
                        f"[BlueprintRouter] Blueprint übersprungen — "
                        f"trust_level={c.meta.get('trust_level')!r}"
                    )
                    return False
                if not c.blueprint_id:
                    log_info("[BlueprintRouter] Blueprint übersprungen — keine blueprint_id")
                    return False
                return True

            # Hygiene-Pipeline (Phase 5): fail-closed (kein Fail-Open bei SQLite-Fehler)
            candidates, log_meta = apply_graph_hygiene(
                results,
                fail_closed=True,
                crosscheck_mode="strict",
                extra_filter=_trust_filter,
            )
            log_info(
                f"[BlueprintRouter] Hygiene: "
                f"raw={log_meta['graph_candidates_raw']} "
                f"→ trust_filtered={log_meta['graph_candidates_after_extra']} "
                f"→ deduped={log_meta['graph_candidates_deduped']} "
                f"→ final={log_meta['graph_candidates_after_sqlite_filter']} "
                f"(mode={log_meta['graph_crosscheck_mode']})"
            )

            if not candidates:
                return BlueprintRouterDecision(
                    decision="no_blueprint",
                    reason="Keine verifizierten, aktiven Blueprints nach Hygiene-Filter",
                )

            # Bester Treffer entscheidet (candidates sind score-sorted descending)
            best = candidates[0]
            best_score = best.score
            best_id = best.blueprint_id

            log_info(
                f"[BlueprintRouter] Bester Kandidat: '{best_id}' score={best_score:.3f} "
                f"(strict={MATCH_THRESHOLD_STRICT}, suggest={MATCH_THRESHOLD_SUGGEST})"
            )

            if best_score >= MATCH_THRESHOLD_STRICT:
                log_info(f"[BlueprintRouter] AUTO-ROUTE → '{best_id}' (score={best_score:.3f} >= {MATCH_THRESHOLD_STRICT})")
                return BlueprintRouterDecision(
                    decision="use_blueprint",
                    blueprint_id=best_id,
                    score=best_score,
                    reason=f"Hohe Konfidenz ({best_score:.2f}) → auto-route '{best_id}'",
                )

            elif best_score >= MATCH_THRESHOLD_SUGGEST:
                top2 = [{"id": c.blueprint_id, "score": c.score} for c in candidates[:2]]
                log_info(
                    f"[BlueprintRouter] SUGGEST → score={best_score:.3f} in "
                    f"[{MATCH_THRESHOLD_SUGGEST}, {MATCH_THRESHOLD_STRICT}) "
                    f"— Kandidaten: {[c['id'] for c in top2]}"
                )
                return BlueprintRouterDecision(
                    decision="suggest_blueprint",
                    blueprint_id=best_id,
                    score=best_score,
                    reason=f"Nicht sicher genug für auto-route ({best_score:.2f}) — Rückfrage nötig",
                    candidates=top2,
                )

            elif best_score >= PARTIAL_THRESHOLD:
                log_info(f"[BlueprintRouter] Partieller Treffer ({best_score:.2f}) — unter Suggest-Threshold")
                return BlueprintRouterDecision(
                    decision="no_blueprint",
                    score=best_score,
                    reason=f"Partieller Treffer ({best_score:.2f}) — unter Suggest-Threshold {MATCH_THRESHOLD_SUGGEST}",
                )

            else:
                return BlueprintRouterDecision(
                    decision="no_blueprint",
                    score=best_score,
                    reason=f"Kein passender Blueprint (bester Score: {best_score:.2f})",
                )

        except Exception as e:
            log_warn(f"[BlueprintRouter] Fehler bei Routing: {e} — no_blueprint")
            return BlueprintRouterDecision(
                decision="no_blueprint",
                reason=f"Router-Fehler: {e}",
            )

    def _build_query(self, user_text: str, intent: str) -> str:
        """Baut eine kompakte Query für die Embedding-Suche."""
        parts = []
        if intent and intent != "unknown":
            parts.append(intent.strip())
        if user_text:
            parts.append(user_text.strip())
        query = " ".join(parts)
        return query[:MAX_QUERY_LEN]


# Singleton
_router: Optional[BlueprintSemanticRouter] = None


def get_blueprint_router() -> BlueprintSemanticRouter:
    global _router
    if _router is None:
        _router = BlueprintSemanticRouter()
    return _router
