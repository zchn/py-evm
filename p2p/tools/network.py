import asyncio
from asyncio.base_events import Server
from typing import (
    Dict,
    NamedTuple,
    Set,
    Tuple,
)


class Address(NamedTuple):
    transport: str
    ip: str
    port: int


class MockServer(Server):
    """
    Mock `asyncio.Server` object.
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


class MockStreamWriter:
    def __init__(self, write_target):
        self._target = write_target

    def write(self, *args, **kwargs):
        self._target(*args, **kwargs)

    async def drain(self):
        pass

    def close(self):
        pass


def get_connected_readers():
    left_reader = asyncio.StreamReader()
    right_reader = asyncio.StreamReader()
    # Link the readers to mock writers.
    left_writer = MockStreamWriter(right_reader.feed_data)
    right_writer = MockStreamWriter(left_reader.feed_data)

    return (
        left_reader, left_writer,
        right_reader, right_writer,
    )


class MockNetwork:
    servers: Dict[Address, MockServer] = None
    connections: Set[Tuple[Address, Address]] = None

    def __init__(self):
        self.servers = {}
        self.connections = set()

    async def start_server(self, client_connected_cb, host=None, port=None, *, loop=None, limit=None, **kwds) -> Server:
        address = Address('tcp', host, port)
        assert host != '0.0.0.0'
        server = MockServer(client_connected_cb, address, self)
        self.servers[address] = server
        return server

    async def open_connection(self, host=None, port=None, *, loop=None, limit=None, **kwds) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        to_address = Address('tcp', host, port)

        if to_address not in self.servers:
            raise Exception('no server listening')

        server = self.servers[to_address]
        from_address = server.address

        if (to_address, from_address) in self.connections:
            raise Exception('already connected')

        self.connections.add((to_address, from_address))

        server_reader, server_writer, client_reader, client_writer = get_connected_readers()

        server.client_connected_cb(server_reader, server_writer)
        return client_reader, client_writer


mock_network = MockNetwork()
