"""Loopback-only TCP proxy to a private acceptance container frontend.

For development tests only. Never expose this listener on the household LAN.
"""

import argparse
import asyncio
import errno
import ipaddress


async def serve(target, port=3783, ipv6_loopback=False, lan_address=None):
    async def connection(reader, writer):
        remote = None
        try:
            upstream, remote = await asyncio.wait_for(
                asyncio.open_connection(target, 3782), timeout=5
            )

            async def copy(source, destination):
                while chunk := await asyncio.wait_for(source.read(65536), timeout=60):
                    destination.write(chunk)
                    await destination.drain()
                if destination.can_write_eof():
                    destination.write_eof()

            await asyncio.wait_for(
                asyncio.gather(copy(reader, remote), copy(upstream, writer)), timeout=120
            )
        except (OSError, TimeoutError):
            pass
        finally:
            writer.close()
            if remote:
                remote.close()

    try:
        server = await asyncio.start_server(
            connection,
            ["127.0.0.1", lan_address]
            if lan_address
            else (["127.0.0.1", "::1"] if ipv6_loopback else "127.0.0.1"),
            port,
            limit=65536,
        )
    except OSError as error:
        if not ipv6_loopback or error.errno not in {errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL}:
            raise
        server = await asyncio.start_server(connection, "127.0.0.1", port, limit=65536)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("container_ip")
    parser.add_argument("--port", type=int, default=3783)
    parser.add_argument("--lan-address")
    args = parser.parse_args()
    if args.lan_address:
        lan = ipaddress.ip_address(args.lan_address)
        if lan.version != 4 or not lan.is_private or lan.is_loopback or lan.is_unspecified:
            parser.error("Use an explicit private IPv4 LAN address")
    address = ipaddress.ip_address(args.container_ip)
    if address.version != 4 or not address.is_private or address.is_loopback:
        parser.error("Use the private Docker bridge address of the test container")
    if not 1024 <= args.port <= 65535:
        parser.error("Use an unprivileged local port")
    asyncio.run(serve(str(address), args.port, lan_address=args.lan_address))
