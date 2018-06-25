import asyncio
import logging
import random
from typing import (
    Dict,
    Iterable,
    NamedTuple,
    Tuple,
)


class Address(NamedTuple):
    transport: str
    host: str
    port: int

    def __repr__(self):
        return '<%s %s>' % (self.__class__.__name__, self)

    def __str__(self):
        return '%s:%s:%s' % (self.transport, self.host, self.port)


class MemoryTransport(asyncio.Transport):
    """
    Direct connection between a StreamWriter and StreamReader.
    """

    def __init__(self, address: Address, reader: asyncio.StreamReader) -> None:
        super().__init__()
        self._address = address
        self._reader = reader

    def get_extra_info(self, name, default=None):
        if name == 'peername':
            return (self._address.host, self._address.port)
        else:
            return super().get_extra_info(name, default)

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


def mempipe(address) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """In-memory pipe, returns a ``(reader, writer)`` pair.

    .. versionadded:: 0.1

    """

    reader = asyncio.StreamReader()

    # TODO: Calls to `writer.drain` will block until the corresponding data has
    # actually been read by the reader.  This is not how things actually behave
    # in a real networked environment as the call to `writer.drain` will return
    # once the data has been sent over the protocol, so...

    # Preliminary investigation suggests that this must be done in the
    # `Protocol` class
    transport = MemoryTransport(address, reader)
    protocol = asyncio.StreamReaderProtocol(reader)

    writer = asyncio.StreamWriter(
        transport=transport,
        protocol=protocol,
        reader=reader,
        loop=asyncio.get_event_loop(),
    )
    return reader, writer


def get_connected_readers(server_address, client_address):
    server_reader, client_writer = mempipe(server_address)
    client_reader, server_writer = mempipe(client_address)

    return (
        server_reader, server_writer,
        client_reader, client_writer,
    )


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
        return '<%s %s>' % (self.__class__.__name__, self.address)

    def close(self):
        pass

    async def wait_closed(self):
        return


class Network:
    servers: Dict[int, Server] = None
    connections: Dict[int, Address] = None

    def __init__(self, host, router):
        self.router = router
        self.host = host
        self.servers = {}
        self.connections = {}

    def get_server(self, port):
        try:
            return self.servers[port]
        except KeyError:
            raise Exception("No server running at {0}".format(port))

    def get_open_port(self):
        while True:
            port = random.randint(2**15, 2**16 - 1)
            if port in self.connections:
                continue
            elif port in self.servers:
                continue
            else:
                break
        return port

    async def start_server(self, client_connected_cb, host, port) -> Server:
        address = Address('tcp', self.host, port)
        server = Server(client_connected_cb, address, self)
        self.servers[address] = server
        return server

    async def open_connection(self, host, port) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        to_address = Address('tcp', host, port)

        if to_address in self.connections:
            raise Exception('already connected')

        from_port = self.get_open_port()
        from_address = Address('tcp', self.host, from_port)

        self.connections[from_port] = to_address

        server_reader, server_writer, client_reader, client_writer = get_connected_readers(
            server_address=to_address,
            client_address=from_address,
        )

        server = self.get_server(to_address)
        logger.info('RUNNING CB: %s', server.client_connected_cb)
        asyncio.ensure_future(server.client_connected_cb(server_reader, server_writer))
        logger.info('RAN CB')
        return client_reader, client_writer


class Router:
    networks: Dict[str, Network]

    def __init__(self):
        self.networks = {}

    def get_network(self, host):
        if host not in self.networks:
            self.networks[host] = Network(host, self)
        return self.networks[host]


router = Router()
