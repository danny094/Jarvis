# utils/chunker.py
"""
Semantic Chunker für lange Texte.

Zerlegt Texte intelligent in Chunks basierend auf:
- Token-Limits (approximiert oder via tiktoken)
- Semantischen Grenzen (Paragraphen, Sätze, Überschriften)
- Konfigurierbarem Overlap für Kontexterhalt

Usage:
    from utils.chunker import Chunker, count_tokens
    
    chunker = Chunker(max_tokens=2000, overlap_tokens=200)
    chunks = chunker.chunk(long_text)
    
    for chunk in chunks:
        print(f"Chunk {chunk.index}: {chunk.tokens} tokens")
"""

import os
import re
from typing import List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from utils.logger import log_debug, log_info, log_warn


# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

# Token-Limit Defaults (konservativ für DeepSeek/Qwen)
DEFAULT_MAX_TOKENS = int(os.getenv("CHUNK_MAX_TOKENS", "4000"))
DEFAULT_OVERLAP_TOKENS = int(os.getenv("CHUNK_OVERLAP_TOKENS", "200"))
CHUNKING_THRESHOLD = int(os.getenv("CHUNKING_THRESHOLD", "6000"))

# Approximation: ~4 chars = 1 token (Englisch), ~3 chars für Deutsch
CHARS_PER_TOKEN = float(os.getenv("CHARS_PER_TOKEN", "3.5"))

# Try to import tiktoken for accurate counting
_tiktoken_available = False
_tiktoken_encoding = None

try:
    import tiktoken
    _tiktoken_encoding = tiktoken.get_encoding("cl100k_base")  # GPT-4/Claude style
    _tiktoken_available = True
    log_info("[Chunker] tiktoken available - using accurate token counting")
except ImportError:
    log_info("[Chunker] tiktoken not available - using approximation")


# ═══════════════════════════════════════════════════════════════
# TOKEN COUNTING
# ═══════════════════════════════════════════════════════════════

def count_tokens(text: str, use_tiktoken: bool = True) -> int:
    """
    Zählt Tokens in einem Text.
    
    Args:
        text: Der zu zählende Text
        use_tiktoken: Wenn True und verfügbar, nutze tiktoken
    
    Returns:
        int: Geschätzte/gezählte Token-Anzahl
    """
    if not text:
        return 0
    
    if use_tiktoken and _tiktoken_available and _tiktoken_encoding:
        return len(_tiktoken_encoding.encode(text))
    
    # Approximation basierend auf Zeichen
    return int(len(text) / CHARS_PER_TOKEN)


def estimate_tokens_fast(text: str) -> int:
    """
    Schnelle Token-Schätzung ohne tiktoken.
    Nützlich für Threshold-Checks.
    """
    if not text:
        return 0
    return int(len(text) / CHARS_PER_TOKEN)


def needs_chunking(text: str, threshold: int = CHUNKING_THRESHOLD) -> bool:
    """
    Prüft ob ein Text chunking braucht.
    
    Args:
        text: Der zu prüfende Text
        threshold: Token-Schwellwert
    
    Returns:
        bool: True wenn Text zu lang ist
    """
    return estimate_tokens_fast(text) > threshold


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

class ChunkType(str, Enum):
    """Art des Chunks basierend auf Inhalt."""
    TEXT = "text"
    CODE = "code"
    HEADING = "heading"
    LIST = "list"
    MIXED = "mixed"


@dataclass
class TextChunk:
    """Ein einzelner Text-Chunk."""
    index: int
    content: str
    tokens: int
    start_char: int
    end_char: int
    chunk_type: ChunkType = ChunkType.TEXT
    has_overlap_before: bool = False
    has_overlap_after: bool = False
    metadata: Optional[dict] = None
    
    def __repr__(self):
        preview = self.content[:50].replace("\n", " ")
        return f"TextChunk({self.index}, {self.tokens}t, '{preview}...')"


# ═══════════════════════════════════════════════════════════════
# SEMANTIC BOUNDARIES
# ═══════════════════════════════════════════════════════════════

class BoundaryDetector:
    """Erkennt semantische Grenzen im Text."""
    
    # Patterns für verschiedene Grenztypen
    PATTERNS = {
        "heading_md": re.compile(r'^#{1,6}\s+.+$', re.MULTILINE),
        "heading_underline": re.compile(r'^.+\n[=\-]{3,}$', re.MULTILINE),
        "paragraph": re.compile(r'\n\n+'),
        "sentence_end": re.compile(r'[.!?]\s+(?=[A-ZÄÖÜ])'),
        "code_block": re.compile(r''),
        "list_item": re.compile(r'^\s*[-*•]\s+', re.MULTILINE),
        "numbered_list": re.compile(r'^\s*\d+[.)]\s+', re.MULTILINE),
    }
    
    @classmethod
    def find_boundaries(cls, text: str) -> List[Tuple[int, str, int]]:
        """
        Findet alle semantischen Grenzen im Text.
        
        Returns:
            List[Tuple[position, type, priority]]: Grenzen sortiert nach Position
        """
        boundaries = []
        
        # Paragraphen (höchste Priorität)
        for match in cls.PATTERNS["paragraph"].finditer(text):
            boundaries.append((match.start(), "paragraph", 10))
        
        # Headings
        for match in cls.PATTERNS["heading_md"].finditer(text):
            boundaries.append((match.start(), "heading", 9))
        
        for match in cls.PATTERNS["heading_underline"].finditer(text):
            boundaries.append((match.start(), "heading", 9))
        
        # Satzenden (niedrigere Priorität)
        for match in cls.PATTERNS["sentence_end"].finditer(text):
            boundaries.append((match.end(), "sentence", 5))
        
        # Sortieren nach Position
        boundaries.sort(key=lambda x: x[0])
        
        return boundaries
    
    @classmethod
    def detect_chunk_type(cls, text: str) -> ChunkType:
        """Erkennt den Typ eines Text-Chunks."""
        code_matches = cls.PATTERNS["code_block"].findall(text)
        code_ratio = sum(len(m) for m in code_matches) / max(len(text), 1)
        
        if code_ratio > 0.5:
            return ChunkType.CODE
        
        list_matches = (
            len(cls.PATTERNS["list_item"].findall(text)) +
            len(cls.PATTERNS["numbered_list"].findall(text))
        )
        if list_matches > 3:
            return ChunkType.LIST
        
        if cls.PATTERNS["heading_md"].search(text):
            return ChunkType.HEADING
        
        if code_ratio > 0.1:
            return ChunkType.MIXED
        
        return ChunkType.TEXT


# ═══════════════════════════════════════════════════════════════
# CHUNKER
# ═══════════════════════════════════════════════════════════════

class Chunker:
    """
    Semantischer Text-Chunker.
    
    Zerlegt lange Texte in sinnvolle Chunks unter Beachtung von:
    - Token-Limits
    - Semantischen Grenzen
    - Overlap für Kontexterhalt
    """
    
    def __init__(
        self,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
        respect_code_blocks: bool = True,
        use_tiktoken: bool = True
    ):
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.respect_code_blocks = respect_code_blocks
        self.use_tiktoken = use_tiktoken and _tiktoken_available
        
        log_debug(f"[Chunker] Initialized: max={max_tokens}, overlap={overlap_tokens}")
    
    def count(self, text: str) -> int:
        """Zählt Tokens."""
        return count_tokens(text, self.use_tiktoken)
    
    def chunk(self, text: str) -> List[TextChunk]:
        """
        Zerlegt einen Text in Chunks.
        
        Args:
            text: Der zu zerlegende Text
        
        Returns:
            List[TextChunk]: Liste der Chunks
        """
        if not text:
            return []
        
        total_tokens = self.count(text)
        
        # Kein Chunking nötig?
        if total_tokens <= self.max_tokens:
            return [TextChunk(
                index=1,
                content=text,
                tokens=total_tokens,
                start_char=0,
                end_char=len(text),
                chunk_type=BoundaryDetector.detect_chunk_type(text),
            )]
        
        log_info(f"[Chunker] Chunking {total_tokens} tokens into ~{total_tokens // self.max_tokens + 1} chunks")
        
        # Code-Blöcke schützen wenn gewünscht
        if self.respect_code_blocks:
            return self._chunk_with_code_protection(text)
        else:
            return self._chunk_semantic(text)
    
    def _chunk_semantic(self, text: str) -> List[TextChunk]:
        """Semantisches Chunking ohne Code-Schutz."""
        boundaries = BoundaryDetector.find_boundaries(text)
        chunks = []
        
        current_start = 0
        chunk_index = 1
        
        while current_start < len(text):
            # Finde Ende dieses Chunks
            target_end = self._find_chunk_end(text, current_start, boundaries)
            
            # Extrahiere Chunk-Content
            chunk_content = text[current_start:target_end]
            chunk_tokens = self.count(chunk_content)
            
            # Chunk erstellen
            chunk = TextChunk(
                index=chunk_index,
                content=chunk_content,
                tokens=chunk_tokens,
                start_char=current_start,
                end_char=target_end,
                chunk_type=BoundaryDetector.detect_chunk_type(chunk_content),
                has_overlap_before=chunk_index > 1,
                has_overlap_after=target_end < len(text),
            )
            chunks.append(chunk)
            
            # Nächster Start mit Overlap
            overlap_start = self._find_overlap_start(text, target_end)
            current_start = overlap_start
            chunk_index += 1
            
            # Safety: Verhindere Endlosschleife
            if current_start >= len(text) - 10:
                break
        
        log_info(f"[Chunker] Created {len(chunks)} chunks")
        return chunks
    
    def _chunk_with_code_protection(self, text: str) -> List[TextChunk]:
        """
        Chunking das Code-Blöcke nicht zerschneidet.
        """
        # Finde alle Code-Blöcke
        code_blocks = []
        for match in BoundaryDetector.PATTERNS["code_block"].finditer(text):
            code_blocks.append((match.start(), match.end()))
        
        if not code_blocks:
            return self._chunk_semantic(text)
        
        # Teile Text in Segmente (normal vs code)
        segments = []
        last_end = 0
        
        for start, end in code_blocks:
            if start > last_end:
                segments.append(("text", text[last_end:start]))
            segments.append(("code", text[start:end]))
            last_end = end
        
        if last_end < len(text):
            segments.append(("text", text[last_end:]))
        
        # Chunke jedes Segment separat
        chunks = []
        chunk_index = 1
        char_offset = 0
        
        for seg_type, seg_content in segments:
            if seg_type == "code":
                # Code-Block als ganzes (oder aufteilen wenn zu groß)
                code_tokens = self.count(seg_content)
                if code_tokens <= self.max_tokens * 1.5:  # Etwas Toleranz für Code
                    chunks.append(TextChunk(
                        index=chunk_index,
                        content=seg_content,
                        tokens=code_tokens,
                        start_char=char_offset,
                        end_char=char_offset + len(seg_content),
                        chunk_type=ChunkType.CODE,
                    ))
                    chunk_index += 1
                else:
                    # Sehr langer Code-Block - muss geteilt werden
                    code_chunks = self._split_code_block(seg_content, char_offset, chunk_index)
                    chunks.extend(code_chunks)
                    chunk_index += len(code_chunks)
            else:
                # Normaler Text
                text_chunks = self._chunk_semantic(seg_content)
                for tc in text_chunks:
                    tc.index = chunk_index
                    tc.start_char += char_offset
                    tc.end_char += char_offset
                    chunks.append(tc)
                    chunk_index += 1
            
            char_offset += len(seg_content)
        
        # Index korrigieren
        for i, chunk in enumerate(chunks):
            chunk.index = i + 1
        
        return chunks
    
    def _find_chunk_end(
        self, 
        text: str, 
        start: int, 
        boundaries: List[Tuple[int, str, int]]
    ) -> int:
        """
        Findet das beste Ende für einen Chunk.
        
        Sucht nach der besten semantischen Grenze innerhalb des Token-Limits.
        """
        # Maximale Zeichenposition (grobe Schätzung)
        max_chars = int(self.max_tokens * CHARS_PER_TOKEN)
        hard_end = min(start + max_chars, len(text))
        
        # Finde Grenzen in diesem Bereich
        relevant_boundaries = [
            b for b in boundaries 
            if start < b[0] < hard_end
        ]
        
        if not relevant_boundaries:
            # Keine Grenze gefunden - schneide bei max_chars
            # Aber versuche bei Whitespace zu schneiden
            cut_point = hard_end
            while cut_point > start + max_chars // 2:
                if text[cut_point:cut_point+1].isspace():
                    break
                cut_point -= 1
            return cut_point if cut_point > start else hard_end
        
        # Sortiere nach Priorität (höchste zuerst)
        relevant_boundaries.sort(key=lambda x: (-x[2], -x[0]))
        
        # Nimm die beste Grenze die noch im Limit ist
        for pos, btype, priority in relevant_boundaries:
            chunk_text = text[start:pos]
            if self.count(chunk_text) <= self.max_tokens:
                return pos
        
        # Fallback: Nimm die letzte Grenze
        return relevant_boundaries[-1][0]
    
    def _find_overlap_start(self, text: str, end: int) -> int:
        """
        Findet den Start für den nächsten Chunk mit Overlap.
        """
        if self.overlap_tokens == 0 or end >= len(text):
            return end
        
        # Overlap in Zeichen (grobe Schätzung)
        overlap_chars = int(self.overlap_tokens * CHARS_PER_TOKEN)
        overlap_start = max(0, end - overlap_chars)
        
        # Versuche bei einer sauberen Grenze zu starten
        boundaries = BoundaryDetector.find_boundaries(text[overlap_start:end])
        
        if boundaries:
            # Nimm die erste Grenze nach overlap_start
            best_boundary = boundaries[0][0] + overlap_start
            return best_boundary
        
        # Fallback: Bei Whitespace starten
        while overlap_start < end:
            if text[overlap_start:overlap_start+1].isspace():
                return overlap_start + 1
            overlap_start += 1
        
        return end
    
    def _split_code_block(
        self, 
        code: str, 
        char_offset: int, 
        start_index: int
    ) -> List[TextChunk]:
        """Teilt einen sehr langen Code-Block."""
        chunks = []
        lines = code.split("\n")
        
        current_lines = []
        current_tokens = 0
        local_offset = 0
        
        for line in lines:
            line_tokens = self.count(line + "\n")
            
            if current_tokens + line_tokens > self.max_tokens and current_lines:
                # Chunk fertig
                chunk_content = "\n".join(current_lines)
                chunks.append(TextChunk(
                    index=start_index + len(chunks),
                    content=chunk_content,
                    tokens=current_tokens,
                    start_char=char_offset + local_offset,
                    end_char=char_offset + local_offset + len(chunk_content),
                    chunk_type=ChunkType.CODE,
                ))
                local_offset += len(chunk_content) + 1
                current_lines = [line]
                current_tokens = line_tokens
            else:
                current_lines.append(line)
                current_tokens += line_tokens
        
        # Letzter Chunk
        if current_lines:
            chunk_content = "\n".join(current_lines)
            chunks.append(TextChunk(
                index=start_index + len(chunks),
                content=chunk_content,
                tokens=current_tokens,
                start_char=char_offset + local_offset,
                end_char=char_offset + local_offset + len(chunk_content),
                chunk_type=ChunkType.CODE,
            ))
        
        return chunks


# ═══════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def quick_chunk(
    text: str, 
    max_tokens: int = DEFAULT_MAX_TOKENS
) -> List[TextChunk]:
    """
    Schnelles Chunking mit Default-Settings.
    
    Args:
        text: Zu chunkender Text
        max_tokens: Maximale Tokens pro Chunk
    
    Returns:
        List[TextChunk]: Die Chunks
    """
    chunker = Chunker(max_tokens=max_tokens)
    return chunker.chunk(text)


def chunk_for_processing(
    text: str,
    threshold: int = CHUNKING_THRESHOLD,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap: int = DEFAULT_OVERLAP_TOKENS
) -> Tuple[bool, List[TextChunk]]:
    """
    Prüft ob Chunking nötig ist und führt es ggf. durch.
    
    Args:
        text: Input-Text
        threshold: Ab wann chunken
        max_tokens: Token-Limit pro Chunk
        overlap: Overlap zwischen Chunks
    
    Returns:
        Tuple[was_chunked, chunks]: Bool ob gechunkt wurde + die Chunks
    """
    if not needs_chunking(text, threshold):
        # Kein Chunking nötig - gib ganzen Text als einzelnen Chunk zurück
        return False, [TextChunk(
            index=1,
            content=text,
            tokens=count_tokens(text),
            start_char=0,
            end_char=len(text),
            chunk_type=BoundaryDetector.detect_chunk_type(text),
        )]
    
    chunker = Chunker(
        max_tokens=max_tokens,
        overlap_tokens=overlap
    )
    chunks = chunker.chunk(text)
    return True, chunks


# ═══════════════════════════════════════════════════════════════
# STATS
# ═══════════════════════════════════════════════════════════════

def get_chunk_stats(chunks: List[TextChunk]) -> dict:
    """
    Generiert Statistiken über Chunks.
    
    Returns:
        dict mit total_tokens, avg_tokens, chunk_count, etc.
    """
    if not chunks:
        return {"chunk_count": 0, "total_tokens": 0}
    
    tokens = [c.tokens for c in chunks]
    types = [c.chunk_type.value for c in chunks]
    
    return {
        "chunk_count": len(chunks),
        "total_tokens": sum(tokens),
        "avg_tokens": sum(tokens) // len(tokens),
        "min_tokens": min(tokens),
        "max_tokens": max(tokens),
        "types": {t: types.count(t) for t in set(types)},
        "total_chars": sum(len(c.content) for c in chunks),
    }

# ═══════════════════════════════════════════════════════════════
# DOCUMENT STRUCTURE ANALYZER (Code-basiert, kein LLM)
# ═══════════════════════════════════════════════════════════════

@dataclass
class DocumentStructure:
    """Ergebnis der Code-basierten Dokumentanalyse."""
    total_chars: int = 0
    total_tokens: int = 0
    total_lines: int = 0
    
    # Struktur
    headings: List[str] = None
    heading_count: int = 0
    code_blocks: int = 0
    code_languages: List[str] = None
    
    # Content Hints
    intro: str = ""
    keywords: List[str] = None
    detected_topics: List[str] = None
    
    # Komplexität
    estimated_complexity: int = 0  # 1-10
    has_tables: bool = False
    has_lists: bool = False
    has_links: bool = False
    
    def __post_init__(self):
        if self.headings is None:
            self.headings = []
        if self.code_languages is None:
            self.code_languages = []
        if self.keywords is None:
            self.keywords = []
        if self.detected_topics is None:
            self.detected_topics = []
    
    def to_compact_summary(self) -> str:
        """Generiert eine kompakte Summary für den LLM."""
        parts = [
            f"Dokument: {self.total_chars} Zeichen, ~{self.total_tokens} Tokens, {self.total_lines} Zeilen",
        ]
        
        if self.headings:
            parts.append(f"Struktur: {self.heading_count} Überschriften")
            top_headings = self.headings[:5]
            parts.append(f"Hauptthemen: {', '.join(top_headings)}")
        
        if self.code_blocks > 0:
            langs = ', '.join(self.code_languages[:3]) if self.code_languages else 'diverse'
            parts.append(f"Code: {self.code_blocks} Blöcke ({langs})")
        
        if self.keywords:
            parts.append(f"Keywords: {', '.join(self.keywords[:10])}")
        
        if self.intro:
            parts.append(f"Intro: {self.intro[:300]}...")
        
        parts.append(f"Geschätzte Komplexität: {self.estimated_complexity}/10")
        
        return "\n".join(parts)


def analyze_document_structure(text: str) -> DocumentStructure:
    """
    Analysiert ein Dokument rein Code-basiert (kein LLM).
    """
    if not text:
        return DocumentStructure()
    
    result = DocumentStructure(
        total_chars=len(text),
        total_tokens=estimate_tokens_fast(text),
        total_lines=text.count('\n') + 1,
    )
    
    lines = text.split('\n')
    
    # === HEADINGS EXTRAHIEREN ===
    heading_pattern = re.compile(r'^(#{1,6})\s+(.+)$')
    headings = []
    for line in lines:
        match = heading_pattern.match(line.strip())
        if match:
            level = len(match.group(1))
            title = match.group(2).strip()
            if level <= 3:
                headings.append(title)
    
    result.headings = headings
    result.heading_count = len(headings)
    
    # === CODE-BLÖCKE ZÄHLEN ===
    code_pattern = re.compile(r'`{3}(\w*)\n[\s\S]*?`{3}')
    code_matches = code_pattern.findall(text)
    result.code_blocks = text.count('```') // 2
    
    languages = [m for m in code_matches if m]
    result.code_languages = list(set(languages))
    
    # === INTRO EXTRAHIEREN ===
    intro_lines = []
    found_content = False
    for line in lines[:50]:
        stripped = line.strip()
        if not stripped:
            if found_content and intro_lines:
                break
            continue
        if stripped.startswith('#'):
            continue
        if '```' in stripped:
            break
        found_content = True
        intro_lines.append(stripped)
        if len(' '.join(intro_lines)) > 500:
            break
    
    result.intro = ' '.join(intro_lines)[:500]
    
    # === KEYWORDS EXTRAHIEREN ===
    keyword_list = [
        'API', 'REST', 'HTTP', 'JSON', 'XML',
        'Docker', 'Container', 'Kubernetes',
        'Python', 'JavaScript', 'TypeScript',
        'LLM', 'AI', 'ML', 'GPT', 'Claude',
        'MCP', 'CIM', 'RAG', 'Sequential', 'Thinking',
        'Database', 'SQL', 'PostgreSQL', 'MongoDB',
        'Frontend', 'Backend', 'Server', 'Client',
        'Memory', 'Cache', 'Storage', 'Workspace',
        'Stream', 'Async', 'Layer', 'Bridge',
    ]
    
    keywords = set()
    text_lower = text.lower()
    for kw in keyword_list:
        if kw.lower() in text_lower:
            keywords.add(kw)
    
    result.keywords = sorted(list(keywords))[:15]
    
    # === FEATURES ERKENNEN ===
    result.has_tables = '|' in text and bool(re.search(r'\|.+\|.+\|', text))
    result.has_lists = bool(re.search(r'^\s*[-*]\s+', text, re.MULTILINE))
    result.has_links = bool(re.search(r'\[.+\]\(.+\)', text))
    
    # === KOMPLEXITÄT SCHÄTZEN ===
    complexity = 1
    
    if result.total_tokens > 2000: complexity += 1
    if result.total_tokens > 5000: complexity += 1
    if result.total_tokens > 10000: complexity += 2
    
    if result.heading_count > 5: complexity += 1
    if result.heading_count > 15: complexity += 1
    if result.code_blocks > 3: complexity += 1
    if result.code_blocks > 10: complexity += 1
    
    if result.has_tables: complexity += 1
    
    result.estimated_complexity = min(complexity, 10)
    
    return result


def quick_document_summary(text: str) -> str:
    """Schnelle Document-Summary für LLM-Kontext."""
    structure = analyze_document_structure(text)
    return structure.to_compact_summary()
