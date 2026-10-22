"""Loopback-only TCP proxy to a private acceptance container frontend.

For development tests only. Never expose this listener on the household LAN.
"""

import argparse
import asyncio
import ipaddress


async def serve(target):
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

    server = await asyncio.start_server(connection, "127.0.0.1", 3783, limit=65536)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("container_ip")
    args = parser.parse_args()
    address = ipaddress.ip_address(args.container_ip)
    if address.version != 4 or not address.is_private or address.is_loopback:
        parser.error("Use the private Docker bridge address of the test container")
    asyncio.run(serve(str(address)))
