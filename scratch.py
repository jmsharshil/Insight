import asyncio
import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'insight.settings')
django.setup()

from chat.consumers import ChatConsumer
from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.auth import get_user_model
from chat.models import ChatRoom, Message

async def test_connect():
    User = get_user_model()
    user = await User.objects.afirst()
    if not user:
        print("No user")
        return
        
    room = await ChatRoom.objects.afirst()
    if not room:
        print("No room")
        return
        
    await room.participants.aadd(user)
    token = AccessToken.for_user(user)
    
    # Send a message to the room to make sure there's something to mark read
    # or just test it empty.
    
    consumer = ChatConsumer()
    consumer.scope = {
        "url_route": {"kwargs": {"room_id": str(room.id)}},
        "query_string": f"token={str(token)}".encode("utf-8"),
    }
    
    class MockChannelLayer:
        async def group_add(self, group, channel):
            print(f"group_add: {group}")
        async def group_send(self, group, event):
            print(f"group_send: {group}, {event['type']}")
            
    consumer.channel_layer = MockChannelLayer()
    consumer.channel_name = "test_channel"
    
    async def mock_accept():
        print("accept called")
    
    async def mock_close(code=None):
        print(f"close called: {code}")
        
    consumer.accept = mock_accept
    consumer.close = mock_close
    
    print("Testing connect...")
    try:
        await consumer.connect()
        print("Connect successful!")
    except Exception as e:
        import traceback
        traceback.print_exc()

asyncio.run(test_connect())
