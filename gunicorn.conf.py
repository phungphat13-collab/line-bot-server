# gunicorn.conf.py
import multiprocessing

# Worker settings
workers = 1
worker_class = "sync"
worker_connections = 1000
timeout = 120  # Tăng timeout lên 120s
keepalive = 5

# Memory optimization
max_requests = 1000
max_requests_jitter = 100
preload_app = False  # Đặt False để tránh memory issues

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Bind port
bind = "0.0.0.0:10000"
