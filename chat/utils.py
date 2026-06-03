# apps/chat/services.py

from .models import Message


class ChatService:

    @staticmethod
    def create_message(
        room,
        sender,
        content
    ):
        return Message.objects.create(
            room=room,
            sender=sender,
            content=content
        )