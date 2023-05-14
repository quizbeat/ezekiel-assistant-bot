# Health Check
import http.server
import socketserver
import threading

PORT = 8080


class HealthCheckHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()


def run_health_check_server():
    with socketserver.TCPServer(("", PORT), HealthCheckHandler) as httpd:
        print("serving at port", PORT)
        httpd.serve_forever()


def start_health_check_thread():
    thread = threading.Thread(target=run_health_check_server)
    thread.start()
