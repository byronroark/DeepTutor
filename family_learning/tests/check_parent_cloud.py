"""No real credentials or Internet calls in these HTTPS-egress tests."""

import asyncio
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from parent_https_proxy import HOSTS, connect_public, handle, target


class TargetTests(unittest.TestCase):
    def test_only_exact_openai_hosts_on_https(self):
        for host in HOSTS:
            self.assertEqual(
                target(f"CONNECT {host}:443 HTTP/1.1\r\n\r\n".encode(), "172.20.0.2", "172.20.0.2"),
                host,
            )
        for authority in [
            "example.com:443",
            "auth.openai.com.evil:443",
            "auth.openai.com:80",
            "127.0.0.1:443",
            "192.168.1.138:443",
            "auth.openai.com.:443",
            "user@auth.openai.com:443",
        ]:
            with self.assertRaises(ValueError):
                target(f"CONNECT {authority} HTTP/1.1\r\n\r\n".encode(), "172.20.0.2", "172.20.0.2")

    def test_other_peers_and_plain_http_are_refused(self):
        for header, peer in [
            (b"CONNECT auth.openai.com:443 HTTP/1.1\r\n\r\n", "192.168.1.221"),
            (b"GET https://auth.openai.com/ HTTP/1.1\r\n\r\n", "172.20.0.2"),
        ]:
            with self.assertRaises(ValueError):
                target(header, peer, "172.20.0.2")


class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_dns_results_are_never_connected(self):
        for address in ["127.0.0.1", "192.168.1.138", "169.254.169.254", "::1"]:
            with (
                patch.object(
                    asyncio.get_running_loop(),
                    "getaddrinfo",
                    AsyncMock(
                        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]
                    ),
                ),
                patch("parent_https_proxy.asyncio.open_connection", AsyncMock()) as connect,
            ):
                with self.assertRaises(ValueError):
                    await connect_public("auth.openai.com")
                connect.assert_not_called()

    async def test_denied_destination_never_opens_upstream(self):
        with patch("parent_https_proxy.connect_public", AsyncMock()) as connect:
            server = await asyncio.start_server(
                lambda r, w: handle(r, w, "127.0.0.1", asyncio.Semaphore(1)), "127.0.0.1", 0
            )
            try:
                reader, writer = await asyncio.open_connection(
                    "127.0.0.1", server.sockets[0].getsockname()[1]
                )
                writer.write(b"CONNECT example.com:443 HTTP/1.1\r\n\r\n")
                await writer.drain()
                self.assertIn(b"403", await reader.read())
                writer.close()
                await writer.wait_closed()
                connect.assert_not_called()
            finally:
                server.close()
                await server.wait_closed()

    async def test_connect_relays_bytes_without_interpreting_payload(self):
        async def echo(reader, writer):
            writer.write(await reader.read(100))
            await writer.drain()
            writer.close()

        upstream = await asyncio.start_server(echo, "127.0.0.1", 0)

        async def connect(host):
            self.assertEqual(host, "auth.openai.com")
            return await asyncio.open_connection("127.0.0.1", upstream.sockets[0].getsockname()[1])

        with patch("parent_https_proxy.connect_public", connect):
            server = await asyncio.start_server(
                lambda r, w: handle(r, w, "127.0.0.1", asyncio.Semaphore(1)), "127.0.0.1", 0
            )
            try:
                reader, writer = await asyncio.open_connection(
                    "127.0.0.1", server.sockets[0].getsockname()[1]
                )
                writer.write(b"CONNECT auth.openai.com:443 HTTP/1.1\r\n\r\n")
                await writer.drain()
                self.assertIn(b"200", await reader.readuntil(b"\r\n\r\n"))
                writer.write(b"opaque-test")
                await writer.drain()
                self.assertEqual(await reader.readexactly(11), b"opaque-test")
                writer.close()
                await writer.wait_closed()
            finally:
                server.close()
                await server.wait_closed()
                upstream.close()
                await upstream.wait_closed()


if __name__ == "__main__":
    unittest.main()
