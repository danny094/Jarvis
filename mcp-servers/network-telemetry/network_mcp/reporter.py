# reporter.py - Query Interface for MCP Tools

import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .config import Config


class NetworkReporter:
    """
    Provides query interface for network data
    Used by MCP tools to answer questions
    """
    
    def get_traffic(self, period: str, start: str, 
                   end: Optional[str] = None) -> str:
        """
        Get traffic statistics for a time period
        Returns: Human-readable summary
        """
        conn = sqlite3.connect(Config.DB_PATH)
        
        try:
            cur = conn.cursor()
            
            # Build query based on period type
            if period in ["hour", "day", "week", "month"]:
                cur.execute(
                    """
                    SELECT 
                        SUM(download_bytes) as total_download,
                        SUM(upload_bytes) as total_upload,
                        COUNT(*) as periods
                    FROM aggregations
                    WHERE period_type = ? 
                    AND period_start >= ?
                    """,
                    (period, start)
                )
                
                row = cur.fetchone()
                
                if row and row[0]:
                    download_gb = row[0] / 1024 / 1024 / 1024
                    upload_gb = row[1] / 1024 / 1024 / 1024
                    
                    return f"Traffic ({period}): ↓ {download_gb:.2f} GB, ↑ {upload_gb:.2f} GB"
                else:
                    return f"No data available for {period} starting {start}"
        
        finally:
            conn.close()
    
    def get_top_containers(self, period: str, limit: int = 10) -> str:
        """
        Get containers ranked by network usage
        Returns: Formatted list
        """
        conn = sqlite3.connect(Config.DB_PATH)
        
        try:
            cur = conn.cursor()
            
            # Get most recent aggregation of this period
            cur.execute(
                """
                SELECT top_containers 
                FROM aggregations
                WHERE period_type = ?
                ORDER BY period_start DESC
                LIMIT 1
                """,
                (period,)
            )
            
            row = cur.fetchone()
            
            if row and row[0]:
                containers = json.loads(row[0])[:limit]
                
                result = f"Top {len(containers)} containers by traffic:\n"
                for i, c in enumerate(containers, 1):
                    dl_mb = c['download_bytes'] / 1024 / 1024
                    ul_mb = c['upload_bytes'] / 1024 / 1024
                    result += f"{i}. {c['container']}: ↓{dl_mb:.1f}MB ↑{ul_mb:.1f}MB\n"
                
                return result
            else:
                return f"No container data available for {period}"
        
        finally:
            conn.close()
    
    def get_daily_report(self, date: Optional[str] = None) -> str:
        """
        Get daily network summary
        Returns: Formatted daily report
        """
        if not date:
            # Default to yesterday
            date = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        
        conn = sqlite3.connect(Config.DB_PATH)
        
        try:
            cur = conn.cursor()
            
            # Get daily aggregation
            cur.execute(
                """
                SELECT 
                    download_bytes,
                    upload_bytes,
                    top_containers,
                    anomaly_score
                FROM aggregations
                WHERE period_type = 'day'
                AND DATE(period_start) = ?
                """,
                (date,)
            )
            
            row = cur.fetchone()
            
            if row:
                dl_gb = row[0] / 1024 / 1024 / 1024
                ul_gb = row[1] / 1024 / 1024 / 1024
                containers = json.loads(row[2]) if row[2] else []
                score = row[3]
                
                report = f"📊 Daily Report - {date}\n"
                report += f"━━━━━━━━━━━━━━━━━━━━━━\n"
                report += f"Download: {dl_gb:.2f} GB\n"
                report += f"Upload: {ul_gb:.2f} GB\n"
                
                if containers:
                    top = containers[0]
                    top_mb = top['download_bytes'] / 1024 / 1024
                    report += f"Top Container: {top['container']} ({top_mb:.1f} MB)\n"
                
                if score > 0:
                    report += f"⚠️ Anomaly Score: {score:.2f}\n"
                
                return report
            else:
                return f"No data available for {date}"
        
        finally:
            conn.close()
    
    def get_anomalies(self, since: str = "24h", 
                     min_severity: str = "medium") -> str:
        """
        Get recent anomalies
        Returns: Formatted list of events
        """
        from .database import get_recent_events
        
        # Parse time window
        hours = 24
        if since.endswith("h"):
            hours = int(since[:-1])
        elif since.endswith("d"):
            hours = int(since[:-1]) * 24
        
        events = get_recent_events(limit=20, min_severity=min_severity)
        
        if not events:
            return f"No anomalies detected in the last {since}"
        
        result = f"⚠️ Network Anomalies (last {since}):\n"
        result += f"━━━━━━━━━━━━━━━━━━━━━━\n"
        
        for event in events:
            result += f"[{event['severity'].upper()}] {event['timestamp']}\n"
            result += f"  {event['event_type']} (score: {event['score']:.2f})\n"
            if event['container_name']:
                result += f"  Container: {event['container_name']}\n"
            result += "\n"
        
        return result
