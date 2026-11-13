import os
import sys
import socket

# Ensure root directory is in sys.path regardless of execution directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.config import Config

def find_available_port(start_port=5000, max_attempts=20):
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start_port

if __name__ == "__main__":
    app = create_app()
    port = Config.PORT or find_available_port()
    
    banner = f"""
    ========================================================================
     BHARATSTORE - Build the Online Store (Aiven Hackathon)
     A retail chain selling through physical stores expanding across India
     Powered by Aiven: PostgreSQL | Apache Kafka | OpenSearch
    ========================================================================
     * Storefront URL:       http://localhost:{port}
     * Architecture & Pitch: http://localhost:{port}/architecture
     * Health & Aiven Check: http://localhost:{port}/api/health
     * Live Kafka Stream:    http://localhost:{port}/api/events/stream
    ========================================================================
    """
    print(banner)
    app.run(host="0.0.0.0", port=port, debug=False)
