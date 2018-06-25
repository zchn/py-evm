import asyncio
import pytest
import logging

from eth_keys import keys

from evm.chains.ropsten import RopstenChain, ROPSTEN_GENESIS_HEADER
from evm.db.chain import ChainDB
from evm.db.header import HeaderDB
from evm.db.backends.memory import MemoryDB

from p2p.peer import (
    ETHPeer,
    PeerPool,
)
from p2p.kademlia import (
    Node,
    Address,
)
from p2p.server import Server

from auth_constants import eip8_values
from dumb_peer import DumbPeer
logger = logging.getLogger('p2p.testing.network')


NETWORK_ID = 99
SERVER_ADDRESS = Address('127.0.0.1', udp_port=30303, tcp_port=30303)
RECEIVER_PRIVKEY = keys.PrivateKey(eip8_values['receiver_private_key'])
RECEIVER_PUBKEY = RECEIVER_PRIVKEY.public_key
RECEIVER_REMOTE = Node(RECEIVER_PUBKEY, SERVER_ADDRESS)

INITIATOR_PRIVKEY = keys.PrivateKey(eip8_values['initiator_private_key'])
INITIATOR_PUBKEY = INITIATOR_PRIVKEY.public_key
INITIATOR_ADDRESS = Address('127.0.0.1', 30304)
INITIATOR_REMOTE = Node(INITIATOR_PUBKEY, INITIATOR_ADDRESS)


class MockPeerPool:
    is_full = False
    connected_nodes = {}

    def is_valid_connection_candidate(self, node):
        return True

    def __len__(self):
        return len(self.connected_nodes)


def get_server(privkey, address, peer_class):
    base_db = MemoryDB()
    headerdb = HeaderDB(base_db)
    chaindb = ChainDB(base_db)
    chaindb.persist_header(ROPSTEN_GENESIS_HEADER)
    chain = RopstenChain(base_db)
    server = Server(
        privkey,
        address.tcp_port,
        chain,
        chaindb,
        headerdb,
        base_db,
        network_id=NETWORK_ID,
        peer_class=peer_class,
        host='127.0.0.1',
    )
    return server


@pytest.fixture(autouse=True)
def router():
    from p2p.tools import network
    network.router = network.Router()
    return network.router


@pytest.fixture
async def server(router):
    server = get_server(RECEIVER_PRIVKEY, SERVER_ADDRESS, ETHPeer)
    await asyncio.wait_for(server._start_tcp_listener(), timeout=1)
    yield server
    server.cancel_token.trigger()
    await asyncio.wait_for(server._close_tcp_listener(), timeout=1)


@pytest.fixture
async def receiver_server_with_dumb_peer(router):
    server = get_server(RECEIVER_PRIVKEY, SERVER_ADDRESS, DumbPeer)
    await asyncio.wait_for(server._start_tcp_listener(), timeout=1)
    yield server
    server.cancel_token.trigger()
    await asyncio.wait_for(server._close_tcp_listener(), timeout=1)


@pytest.mark.asyncio
async def test_server_authenticates_incoming_connections(monkeypatch, server, event_loop, router):
    connected_peer = None

    async def mock_do_handshake(peer):
        logger.info('HERE!!!!: %s', peer)
        nonlocal connected_peer
        connected_peer = peer
        logger.info('HERE!!!!: %s', connected_peer)

    # Only test the authentication in this test.
    monkeypatch.setattr(server, 'do_handshake', mock_do_handshake)
    # We need this to ensure the server can check if the peer pool is full for
    # incoming connections.
    monkeypatch.setattr(server, 'peer_pool', MockPeerPool())

    network = router.get_network('127.0.0.1')

    # Send auth init message to the server.
    reader, writer = await asyncio.wait_for(
        network.open_connection(SERVER_ADDRESS.ip, SERVER_ADDRESS.tcp_port),
        timeout=1)
    writer.write(eip8_values['auth_init_ciphertext'])
    await asyncio.wait_for(writer.drain(), timeout=1)

    # Await the server replying auth ack.
    await asyncio.wait_for(
        reader.read(len(eip8_values['auth_ack_ciphertext'])),
        timeout=1)

    try:
        # We have to read through the rest of the reader to cause the
        # corresponding call to `writer.drain` on the server side to proceed to
        # the next step of the handshake.
        await asyncio.wait_for(
            reader.read(),
            timeout=0.01,
        )
    except asyncio.TimeoutError:
        pass

    # The sole connected node is our initiator.
    logger.info('PRE_ASSERT')
    assert connected_peer is not None
    logger.info('POST_ASSERT')
    assert isinstance(connected_peer, ETHPeer)
    assert connected_peer.privkey == RECEIVER_PRIVKEY


@pytest.mark.asyncio
async def test_peer_pool_connect(monkeypatch, event_loop, receiver_server_with_dumb_peer, router):
    started_peers = []

    def mock_start_peer(peer):
        nonlocal started_peers
        started_peers.append(peer)

    monkeypatch.setattr(receiver_server_with_dumb_peer, '_start_peer', mock_start_peer)
    # We need this to ensure the server can check if the peer pool is full for
    # incoming connections.
    monkeypatch.setattr(receiver_server_with_dumb_peer, 'peer_pool', MockPeerPool())

    pool = PeerPool(DumbPeer, HeaderDB(MemoryDB()), NETWORK_ID, INITIATOR_PRIVKEY, tuple())
    nodes = [RECEIVER_REMOTE]
    await pool.connect_to_nodes(nodes)
    # Give the receiver_server a chance to ack the handshake.
    await asyncio.sleep(0.1)

    assert len(started_peers) == 1
    assert len(pool.connected_nodes) == 1

    # Stop our peer to make sure its pending asyncio tasks are cancelled.
    await list(pool.connected_nodes.values())[0].cancel()
