"""实际 loopback HTTPS + F2 执行器，不访问抖音；证书校验保持开启。"""
import datetime
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from douyin_local.transfer import StrictF2Downloader


async def test_real_https_transfer_and_certificate(tmp_path, mp4):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]), False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / 'cert.pem', tmp_path / 'key.pem'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                         serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers)
            self.send_response(200)
            self.send_header('Content-Type', 'video/mp4')
            self.send_header('Content-Length', str(len(mp4)))
            self.end_headers()
            self.wfile.write(mp4)

        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    class LoopbackTransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.inner = httpx.AsyncHTTPTransport(verify=ssl.create_default_context(cafile=str(cert_path)))

        async def handle_async_request(self, request):
            # 测试只替换网络目的地，生产 URL 校验仍执行；真实 TCP/TLS/HTTP 未 mock。
            request.url = httpx.URL(f'https://localhost:{server.server_port}/fixture.mp4')
            return await self.inner.handle_async_request(request)

        async def aclose(self):
            await self.inner.aclose()
    try:
        client = httpx.AsyncClient(transport=LoopbackTransport(), trust_env=False)
        async with StrictF2Downloader('real-browser-UA', client) as downloader:
            await downloader.download_verified(['https://v.douyinvod.com/fixture.mp4'], tmp_path / 'result.mp4')
        assert (tmp_path / 'result.mp4').read_bytes() == mp4
        assert len(seen) == 1
        assert seen[0].get('Cookie') is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
