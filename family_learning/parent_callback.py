"""Forward local OAuth callbacks to the pilot frontend, never to a LAN listener.

The upstream callback handler still validates its secret state and PKCE owner.
No callback URLs or authorization codes are logged or stored by this forwarder.
"""

import argparse
import asyncio
import ipaddress

from acceptance_proxy import serve

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("container_ip")
    args = parser.parse_args()
    address = ipaddress.ip_address(args.container_ip)
    if (
        address.version != 4
        or not address.is_private
        or address.is_loopback
        or address.is_unspecified
    ):
        parser.error("Use the private pilot address")

    async def callbacks():
        await asyncio.gather(serve(str(address), 1455, True), serve(str(address), 1457, True))

    asyncio.run(callbacks())
