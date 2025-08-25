import os
import json
import socket
import threading
import multiprocessing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs
from datetime import datetime
import mimetypes
from pymongo import MongoClient

APP_PORT = int(os.environ.get("APP_PORT", "3000"))
SOCKET_PORT = int(os.environ.get("SOCKET_PORT", "5000"))
SOCKET_HOST = os.environ.get("SOCKET_HOST", "127.0.0.1")
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://mongo:27017/")
MONGO_DB = os.environ.get("MONGO_DB", "messages_db")
MONGO_COLLECTION = os.environ.get("MONGO_COLLECTION", "messages")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def read_file_bytes(path):
    with open(path, "rb") as f:
        return f.read()

def guess_type(path):
    typ, _ = mimetypes.guess_type(path)
    return typ or "application/octet-stream"

class SimpleRouter(BaseHTTPRequestHandler):
    server_version = "NoFrameworkHTTP/0.1"

    def log_message(self, fmt, *args):
        # Quiet logs (uncomment to debug)
        # super().log_message(fmt, *args)
        pass

    def _respond_file(self, filepath, status=200, content_type=None):
        try:
            data = read_file_bytes(filepath)
            self.send_response(status)
            self.send_header("Content-Type", content_type or guess_type(filepath))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self._respond_404()

    def _respond_404(self):
        error_path = os.path.join(BASE_DIR, "error.html")
        if os.path.exists(error_path):
            self._respond_file(error_path, status=404, content_type="text/html; charset=utf-8")
        else:
            self.send_error(404, "Not Found")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._respond_file(os.path.join(BASE_DIR, "index.html"), content_type="text/html; charset=utf-8")
        if self.path == "/message.html":
            return self._respond_file(os.path.join(BASE_DIR, "message.html"), content_type="text/html; charset=utf-8")
        # static assets referenced from root paths
        if self.path == "/style.css":
            return self._respond_file(os.path.join(BASE_DIR, "static", "style.css"), content_type="text/css; charset=utf-8")
        if self.path == "/logo.png":
            return self._respond_file(os.path.join(BASE_DIR, "static", "logo.png"), content_type="image/png")

        # any other route -> 404 page
        self._respond_404()

    def do_POST(self):
        if self.path != "/message":
            return self._respond_404()

        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length).decode("utf-8", errors="replace")
        form = parse_qs(body)

        username = (form.get("username", [""])[0]).strip()
        message = (form.get("message", [""])[0]).strip()

        payload = json.dumps({"username": username, "message": message}).encode("utf-8")

        # Send via TCP to socket server
        try:
            with socket.create_connection((SOCKET_HOST, SOCKET_PORT), timeout=5) as s:
                s.sendall(payload)
        except Exception as e:
            # If socket server is unavailable, still show 500 or redirect with a message.
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"Socket server error: {e}".encode("utf-8"))
            return

        # Redirect back to home after submission
        self.send_response(302)
        self.send_header("Location", "/")
        self.end_headers()

def socket_server():
    # Connect to MongoDB once per process
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB]
    col = db[MONGO_COLLECTION]

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", SOCKET_PORT))
        srv.listen(5)
        while True:
            conn, addr = srv.accept()
            threading.Thread(target=handle_client, args=(conn, col), daemon=True).start()

def handle_client(conn, col):
    with conn:
        chunks = []
        while True:
            data = conn.recv(4096)
            if not data:
                break
            chunks.append(data)
        raw = b"".join(chunks).decode("utf-8", errors="replace")
        try:
            doc_in = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            doc_in = {}

        doc = {
            "date": str(datetime.now()),
            "username": (doc_in.get("username") or "").strip(),
            "message": (doc_in.get("message") or "").strip(),
        }
        try:
            col.insert_one(doc)
        except Exception:
            # Intentionally swallow DB errors to keep server running
            pass

if __name__ == "__main__":
    # Start socket server in a separate process
    p = multiprocessing.Process(target=socket_server, daemon=True)
    p.start()

    # Start HTTP server
    server = ThreadingHTTPServer(("0.0.0.0", APP_PORT), SimpleRouter)
    print(f"HTTP server running on port {APP_PORT}")
    print(f"Socket server running on port {SOCKET_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if p.is_alive():
            p.terminate()
