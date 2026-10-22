"""Single-instance WSGI service; HTTPS terminates at the approved host proxy."""

import os

bind = f"0.0.0.0:{int(os.environ.get('PORT', '10000'))}"
workers = 1
worker_class = "sync"
threads = 1
timeout = 30
graceful_timeout = 30
keepalive = 2
umask = 0o077
accesslog = "-"
errorlog = "-"
loglevel = "info"
capture_output = True
# Omit names, addresses, query strings, cookies, credentials and referrers.
access_log_format = '%(t)s %(m)s %(s)s %(L)s'
