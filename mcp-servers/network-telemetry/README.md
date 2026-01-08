# Network Telemetry MCP Server

Network monitoring and telemetry server for Jarvis.

## Features

- 📊 Network traffic monitoring (container-level)
- 📈 Time-based aggregations (hour/day/week/month)
- 🔍 Anomaly detection (coming soon)
- 📅 Daily reports

## MCP Tools

- `network_get_traffic` - Get traffic statistics
- `network_get_top_containers` - Top containers by usage
- `network_get_daily_report` - Daily summary
- `network_get_anomalies` - Recent anomalies

## Quick Start

```bash
docker-compose up -d network-telemetry
```

## Configuration

Environment variables:
- `COLLECTION_INTERVAL` - Data collection interval (default: 30s)
- `AGGREGATION_INTERVAL` - Aggregation interval (default: 300s)
- `DB_PATH` - Database path (default: /app/data/network.db)
