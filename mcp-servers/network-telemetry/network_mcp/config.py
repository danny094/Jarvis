# config.py - Network Telemetry Configuration

import os
from pathlib import Path

class Config:
    """Configuration for Network Telemetry MCP Server"""
    
    # Database
    DB_PATH = os.getenv('DB_PATH', '/app/data/network.db')
    
    # Collection Settings
    COLLECTION_INTERVAL = int(os.getenv('COLLECTION_INTERVAL', '30'))  # seconds
    AGGREGATION_INTERVAL = int(os.getenv('AGGREGATION_INTERVAL', '300'))  # 5 minutes
    
    # Data Retention
    RAW_DATA_RETENTION_HOURS = int(os.getenv('RAW_DATA_RETENTION_HOURS', '72'))
    KEEP_AGGREGATIONS_DAYS = int(os.getenv('KEEP_AGGREGATIONS_DAYS', '365'))
    
    # Docker
    DOCKER_SOCKET = os.getenv('DOCKER_SOCKET', '/var/run/docker.sock')
    
    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    
    # Baseline Learning
    BASELINE_MIN_SAMPLES = int(os.getenv('BASELINE_MIN_SAMPLES', '100'))
    BASELINE_WINDOW_DAYS = int(os.getenv('BASELINE_WINDOW_DAYS', '30'))
    
    # Anomaly Detection
    ANOMALY_THRESHOLD = float(os.getenv('ANOMALY_THRESHOLD', '0.6'))
    
    # Proc filesystem (host or container)
    PROC_NET_DEV = os.getenv('PROC_NET_DEV', '/proc/net/dev')
    
    @classmethod
    def validate(cls):
        """Validate configuration"""
        # Ensure data directory exists
        data_dir = Path(cls.DB_PATH).parent
        data_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"✓ Config validated")
        print(f"  DB Path: {cls.DB_PATH}")
        print(f"  Collection Interval: {cls.COLLECTION_INTERVAL}s")
        print(f"  Aggregation Interval: {cls.AGGREGATION_INTERVAL}s")
