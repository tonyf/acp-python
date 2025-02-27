from acp_python.client.session import AllowAllPolicy
from acp_python.client.session import InMemorySessionStore
from acp_python.client import AcpClient


async def test_client():
    def message_handler(msg, client):
        print(f"Received message from {client.actor_id}: {msg.data}")

    client_1 = AcpClient(
        "test-1", "", InMemorySessionStore(), server_url="nats://137.66.48.8:4222"
    )
    client_2 = AcpClient(
        "test-2", "", InMemorySessionStore(), server_url="nats://137.66.48.8:4222"
    )
    await client_1.start()
    await client_2.start()

    await client_1.connect(client_2.me_as_peer("test"))
