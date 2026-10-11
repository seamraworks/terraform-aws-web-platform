"""Integration-only receiver: persists notifications without cloud/model clients."""
from http.server import ThreadingHTTPServer
from moderator import Database, Worker, webhook_handler

worker = Worker({'site': 'example', 'webhook_secret': 'integration-webhook',
                 'article_hosts': ['www.example.com'], 'article_path_prefix': '/journal/'},
                Database('/tmp/notifications.sqlite'), None, None, None)
ThreadingHTTPServer(('0.0.0.0', 8090), webhook_handler(worker)).serve_forever()
