import asyncio
import logging
from typing import (
    Dict,
    Iterable,
    NamedTuple,
    Set,
    Tuple,
)


class MemoryTransport(asyncio.Transport):
    """Direct connection between a StreamWriter and StreamReader."""

    def __init__(self, reader: asyncio.StreamReader) -> None:
        super().__init__()
        self._reader = reader

    def write(self, data: bytes) -> None:
        self._reader.feed_data(data)

    def writelines(self, data: Iterable[bytes]) -> None:
        for line in data:
            self._reader.feed_data(line)
            self._reader.feed_data(b'\n')

    def write_eof(self) -> None:
        self._reader.feed_eof()

    def can_write_eof(self) -> bool:
        return True

    def is_closing(self) -> bool:
        return False

    def close(self) -> None:
        self.write_eof()


def mempipe(host, port) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """In-memory pipe, returns a ``(reader, writer)`` pair.

    .. versionadded:: 0.1

    """

    reader = asyncio.StreamReader()
    # TODO: attach host to memory transport
    transport = MemoryTransport(reader),

    writer = asyncio.StreamWriter(
        transport=transport,
        protocol=asyncio.StreamReaderProtocol(reader),
        reader=reader,
        loop=asyncio.get_event_loop(),
    )
    return reader, writer


def get_connected_readers(server, client):
    server_reader, client_writer = mempipe()
    client_reader, server_writer = mempipe()

    return (
        server_reader, server_writer,
        client_reader, client_writer,
    )


class Address(NamedTuple):
    transport: str
    ip: str
    port: int


logger = logging.getLogger('p2p.testing.network')


class Server:
    """
    Mock version of `asyncio.Server` object.
    """
    def __init__(self, client_connected_cb, address, network):
        self.client_connected_cb = client_connected_cb
        self.address = address
        self.network = network

    def __repr__(self):
        return '<%s %s:%s:%s>' % (self.__class__.__name__, self.address.transport, self.address.ip, self.address.port)

    def close(self):
        pass

    async def wait_closed(self):
        return


# TODO: Need a `Router` and a `Network`.  Network is aware of IP address and Router


class Network:
    servers: Dict[Address, Server] = None
    connections: Set[Address] = None

    def __init__(self, host):
        self.host
        self.servers = {}
        self.connections = set()

    def get_server(self, port):
        try:
            return self.servers[port]
        except KeyError:
            raise Exception("No server running at {0}".format(address))

    async def start_server(self, client_connected_cb, port) -> Server:
        address = Address('tcp', self.host, port)
        server = Server(client_connected_cb, address, self)
        self.servers[address] = server
        return server

    async def open_connection(self, host, port) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        to_address = Address('tcp', host, port)

        if to_address in self.connections:
            raise Exception('already connected')


        self.connections.add(to_address)

        server_reader, server_writer, client_reader, client_writer = get_connected_readers(
            from_host=self.host,
            to_address=to_address,
        )

        server = self.get_server(to_address)
        asyncio.ensure_future(server.client_connected_cb(server_reader, server_writer))
        return client_reader, client_writer


class Router:
    networks: Dict[str, Network]

    def create_network(self, host):
        if host in self.networks:
            raise Exception("network already exists")
        network = Network(host, self)
        self.networks[host] = network
        return network

    def get_network(self, host):
        try:
            return self.network[host]
        except KeyError:
            raise Exception("unknown network")


router = Router()
