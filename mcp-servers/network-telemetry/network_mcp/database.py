# database.py - Network Telemetry Database

import os
import sqlite3
from datetime import datetime
from typing import Optional, Dict, List

from .config import Config


def init_db():
    """Initialize database with all required tables"""
    os.makedirs(os.path.dirname(Config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(Config.DB_PATH)
    
    try:
        # Raw network stats (short retention)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                container_name TEXT,
                interface TEXT,
                rx_bytes INTEGER DEFAULT 0,
                tx_bytes INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        
        # Aggregations (long-term storage)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS aggregations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period_type TEXT NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                download_bytes INTEGER DEFAULT 0,
                upload_bytes INTEGER DEFAULT 0,
                top_containers TEXT,
                data_completeness REAL DEFAULT 1.0,
                anomaly_score REAL DEFAULT 0.0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(period_type, period_start)
            )
            """
        )
        
        # Events (anomalies & important changes)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT UNIQUE NOT NULL,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                score REAL NOT NULL,
                container_name TEXT,
                details TEXT,
                acknowledged INTEGER DEFAULT 0,
                acknowledged_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        
        # Daily reports (mandatory!)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                download_gb REAL NOT NULL,
                upload_gb REAL NOT NULL,
                anomalies_count INTEGER DEFAULT 0,
                note TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        
        # Baselines (learned normal behavior)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS baselines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile TEXT NOT NULL,
                metric TEXT NOT NULL,
                median REAL NOT NULL,
                mad REAL NOT NULL,
                sample_count INTEGER NOT NULL,
                last_updated TEXT NOT NULL,
                UNIQUE(profile, metric)
            )
            """
        )
        
        conn.commit()
        print("✓ Database tables created")
        
    finally:
        conn.close()


def migrate_db():
    """Handle schema migrations"""
    conn = sqlite3.connect(Config.DB_PATH)
    cur = conn.cursor()
    
    # Check for new columns (example for future migrations)
    # cur.execute("PRAGMA table_info(aggregations)")
    # columns = [row[1] for row in cur.fetchall()]
    # if "new_column" not in columns:
    #     cur.execute("ALTER TABLE aggregations ADD COLUMN new_column TEXT")
    
    conn.commit()
    conn.close()
    print("✓ Database migrations checked")


def insert_raw_stat(timestamp: str, container_name: str, 
                    interface: str, rx_bytes: int, tx_bytes: int) -> int:
    """Insert raw network stat"""
    conn = sqlite3.connect(Config.DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO raw_stats 
            (timestamp, container_name, interface, rx_bytes, tx_bytes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (timestamp, container_name, interface, rx_bytes, tx_bytes)
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_aggregation(period_type: str, period_start: str) -> Optional[Dict]:
    """Get aggregation for a specific period"""
    conn = sqlite3.connect(Config.DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM aggregations 
            WHERE period_type = ? AND period_start = ?
            """,
            (period_type, period_start)
        )
        row = cur.fetchone()
        if row:
            return {
                "id": row[0],
                "period_type": row[1],
                "period_start": row[2],
                "period_end": row[3],
                "download_bytes": row[4],
                "upload_bytes": row[5],
                "top_containers": row[6],
                "data_completeness": row[7],
                "anomaly_score": row[8]
            }
        return None
    finally:
        conn.close()


def insert_aggregation(period_type: str, period_start: str, period_end: str,
                      download_bytes: int, upload_bytes: int, 
                      top_containers: str = "") -> int:
    """Insert or update aggregation"""
    conn = sqlite3.connect(Config.DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO aggregations 
            (period_type, period_start, period_end, download_bytes, upload_bytes, top_containers)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(period_type, period_start) DO UPDATE SET
                download_bytes = excluded.download_bytes,
                upload_bytes = excluded.upload_bytes,
                top_containers = excluded.top_containers
            """,
            (period_type, period_start, period_end, download_bytes, upload_bytes, top_containers)
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_recent_events(limit: int = 20, min_severity: str = "low", 
                     acknowledged: bool = False) -> List[Dict]:
    """Get recent events"""
    conn = sqlite3.connect(Config.DB_PATH)
    try:
        cur = conn.cursor()
        
        severity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        min_level = severity_order.get(min_severity, 0)
        
        query = """
            SELECT * FROM events 
            WHERE 1=1
        """
        params = []
        
        if not acknowledged:
            query += " AND acknowledged = 0"
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        cur.execute(query, params)
        
        events = []
        for row in cur.fetchall():
            events.append({
                "id": row[0],
                "event_id": row[1],
                "timestamp": row[2],
                "event_type": row[3],
                "severity": row[4],
                "score": row[5],
                "container_name": row[6],
                "details": row[7],
                "acknowledged": bool(row[8])
            })
        
        return events
    finally:
        conn.close()


def cleanup_old_raw_data():
    """Delete raw stats older than retention period"""
    conn = sqlite3.connect(Config.DB_PATH)
    try:
        cur = conn.cursor()
        cutoff = datetime.utcnow().timestamp() - (Config.RAW_DATA_RETENTION_HOURS * 3600)
        cur.execute(
            """
            DELETE FROM raw_stats 
            WHERE created_at < datetime(?, 'unixepoch')
            """,
            (cutoff,)
        )
        deleted = cur.rowcount
        conn.commit()
        if deleted > 0:
            print(f"✓ Cleaned up {deleted} old raw stats")
    finally:
        conn.close()
