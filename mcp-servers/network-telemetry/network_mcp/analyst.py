# analyst.py - Data Aggregation & Analysis (MVP)

import asyncio
import sqlite3
from datetime import datetime, timedelta
import json
from typing import Dict, List

from .config import Config
from .database import insert_aggregation, cleanup_old_raw_data


class NetworkAnalyst:
    """
    Aggregates raw data into time buckets
    MVP: Simple hourly/daily aggregation
    """
    
    def __init__(self):
        self.running = False
    
    async def run(self):
        """Main analysis loop"""
        self.running = True
        print(f"→ Analyst started (interval: {Config.AGGREGATION_INTERVAL}s)")
        
        while self.running:
            try:
                await self.aggregate()
                cleanup_old_raw_data()
                await asyncio.sleep(Config.AGGREGATION_INTERVAL)
            except Exception as e:
                print(f"[Analyst Error] {e}")
                await asyncio.sleep(30)
    
    async def aggregate(self):
        """Run all aggregation tasks"""
        now = datetime.utcnow()
        
        # Aggregate last hour
        await self._aggregate_period("hour", now - timedelta(hours=1), now)
        
        # Aggregate last day (if it's past midnight)
        if now.hour == 0:
            yesterday = now - timedelta(days=1)
            await self._aggregate_period("day", 
                yesterday.replace(hour=0, minute=0, second=0),
                yesterday.replace(hour=23, minute=59, second=59)
            )
    
    async def _aggregate_period(self, period_type: str, 
                                start: datetime, end: datetime):
        """Aggregate data for a specific period"""
        conn = sqlite3.connect(Config.DB_PATH)
        
        try:
            cur = conn.cursor()
            
            # Query raw stats for period
            cur.execute(
                """
                SELECT 
                    container_name,
                    SUM(rx_bytes) as total_rx,
                    SUM(tx_bytes) as total_tx
                FROM raw_stats
                WHERE timestamp BETWEEN ? AND ?
                GROUP BY container_name
                ORDER BY total_rx DESC
                """,
                (start.isoformat(), end.isoformat())
            )
            
            results = cur.fetchall()
            
            if not results:
                return
            
            # Calculate totals
            total_download = sum(r[1] for r in results)
            total_upload = sum(r[2] for r in results)
            
            # Build top containers list
            top_containers = [
                {
                    "container": r[0],
                    "download_bytes": r[1],
                    "upload_bytes": r[2]
                }
                for r in results[:10]  # Top 10
            ]
            
            # Store aggregation
            insert_aggregation(
                period_type=period_type,
                period_start=start.isoformat(),
                period_end=end.isoformat(),
                download_bytes=total_download,
                upload_bytes=total_upload,
                top_containers=json.dumps(top_containers)
            )
            
            print(f"✓ Aggregated {period_type}: ↓{total_download/1024/1024:.1f}MB ↑{total_upload/1024/1024:.1f}MB")
        
        finally:
            conn.close()
    
    def stop(self):
        """Stop the analyst"""
        self.running = False
        print("→ Analyst stopped")
