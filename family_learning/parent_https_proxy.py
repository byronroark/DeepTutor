"""Optional parent HTTPS egress: fixed OpenAI hosts, private bridge peer only.

CONNECT tunnels preserve end-to-end TLS. No URLs, headers, tokens or payloads
are logged or stored. Learner API confinement and Python isolation stay separate.
"""

import argparse
import asyncio
import ipaddress
import socket

HOSTS = frozenset({"auth.openai.com", "chatgpt.com", "api.openai.com"})


def target(header, peer, allowed_peer):
    if peer != allowed_peer:
        raise ValueError("Peer refused")
    method, authority, version = header.decode("ascii").split("\r\n", 1)[0].split(" ")
    if (
        method != "CONNECT"
        or version != "HTTP/1.1"
        or authority not in {host + ":443" for host in HOSTS}
    ):
        raise ValueError("Target refused")
    return authority[:-4]


async def connect_public(host):
    results = await asyncio.wait_for(
        asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM), 5
    )
    if not results or any(not ipaddress.ip_address(row[4][0]).is_global for row in results):
        raise ValueError("Non-public destination refused")
    for family, _, _, _, address in results:
        try:
            return await asyncio.wait_for(
                asyncio.open_connection(address[0], 443, family=family), 5
            )
        except OSError:
            continue
    raise OSError("Destination unavailable")


async def handle(reader, writer, allowed_peer, slots):
    remote = None
    try:
        peer = writer.get_extra_info("peername")
        if not peer or peer[0] != allowed_peer or slots.locked():
            raise ValueError("Peer or capacity refused")
        async with slots:
            header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            if len(header) > 8192:
                raise ValueError("Header too large")
            host = target(header, peer[0], allowed_peer)
            upstream, remote = await connect_public(host)
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()

            async def copy(source, destination):
                while chunk := await asyncio.wait_for(source.read(65536), 90):
                    destination.write(chunk)
                    await destination.drain()
                if destination.can_write_eof():
                    destination.write_eof()

            await asyncio.wait_for(
                asyncio.gather(copy(reader, remote), copy(upstream, writer)), 600
            )
    except (
        OSError,
        ValueError,
        UnicodeError,
        TimeoutError,
        asyncio.IncompleteReadError,
        asyncio.LimitOverrunError,
    ):
        if remote is None:
            writer.write(
                b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            )
    finally:
        writer.close()
        if remote:
            remote.close()


async def serve(bind, peer, port):
    slots = asyncio.Semaphore(8)
    server = await asyncio.start_server(
        lambda r, w: handle(r, w, peer, slots), bind, port, limit=8192
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", required=True)
    parser.add_argument("--peer", required=True)
    parser.add_argument("--port", type=int, default=3786)
    args = parser.parse_args()
    for address in (args.bind, args.peer):
        ip = ipaddress.ip_address(address)
        if ip.version != 4 or not ip.is_private or ip.is_loopback or ip.is_unspecified:
            parser.error("Use the private Docker bridge and app addresses")
    if args.bind == args.peer or not 1024 <= args.port <= 65535:
        parser.error("Use distinct bridge/app addresses and an unprivileged port")
    asyncio.run(serve(args.bind, args.peer, args.port))
