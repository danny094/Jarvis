# tools.py - MCP Tool Definitions (Jarvis Style)

from typing import Optional, Dict
from .reporter import NetworkReporter


def register_tools(mcp):
    """Register all network telemetry MCP tools"""
    
    reporter = NetworkReporter()
    
    # --------------------------------------------------
    # network_get_traffic
    # --------------------------------------------------
    @mcp.tool
    def network_get_traffic(
        period: str,
        start: str,
        end: Optional[str] = None
    ) -> Dict:
        """
        Get traffic statistics for a time period.
        
        Args:
            period: Time bucket (hour/day/week/month)
            start: Start date (YYYY-MM-DD or ISO datetime)
            end: Optional end date
        
        Returns:
            Traffic statistics with download/upload volumes
        """
        result = reporter.get_traffic(period, start, end)
        
        return {
            "result": result,
            "structuredContent": {
                "period": period,
                "start": start,
                "end": end
            }
        }
    
    # --------------------------------------------------
    # network_get_top_containers
    # --------------------------------------------------
    @mcp.tool
    def network_get_top_containers(
        period: str,
        limit: int = 10
    ) -> Dict:
        """
        Get containers ranked by network usage.
        
        Args:
            period: Time period (day/week/month)
            limit: Number of results (default: 10)
        
        Returns:
            List of containers sorted by traffic volume
        """
        result = reporter.get_top_containers(period, limit)
        
        return {
            "result": result,
            "structuredContent": {
                "period": period,
                "limit": limit
            }
        }
    
    # --------------------------------------------------
    # network_get_daily_report
    # --------------------------------------------------
    @mcp.tool
    def network_get_daily_report(
        date: Optional[str] = None
    ) -> Dict:
        """
        Get daily network summary report.
        
        Args:
            date: Date (YYYY-MM-DD), defaults to yesterday
        
        Returns:
            Comprehensive daily network report
        """
        result = reporter.get_daily_report(date)
        
        return {
            "result": result,
            "structuredContent": {
                "date": date or "yesterday"
            }
        }
    
    # --------------------------------------------------
    # network_get_anomalies
    # --------------------------------------------------
    @mcp.tool
    def network_get_anomalies(
        since: str = "24h",
        min_severity: str = "medium"
    ) -> Dict:
        """
        Get recent network anomalies.
        
        Args:
            since: Time window (e.g., '24h', '7d')
            min_severity: Minimum severity (low/medium/high/critical)
        
        Returns:
            List of network anomalies with details
        """
        result = reporter.get_anomalies(since, min_severity)
        
        return {
            "result": result,
            "structuredContent": {
                "since": since,
                "min_severity": min_severity
            }
        }
