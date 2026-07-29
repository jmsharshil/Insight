from rest_framework import serializers
from .models import SupportQuery, SupportQueryMessage

class SupportQueryMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportQueryMessage
        fields = ['id', 'sender', 'message', 'attachment', 'is_resolution', 'created_at']
        read_only_fields = ['id', 'sender', 'is_resolution', 'created_at']


class SupportQuerySerializer(serializers.ModelSerializer):
    messages = SupportQueryMessageSerializer(many=True, read_only=True)

    class Meta:
        model = SupportQuery
        fields = ['id', 'user', 'organization', 'assigned_to', 'title', 'description', 'attachment', 'status', 'created_at', 'messages']
        read_only_fields = ['id', 'user', 'organization', 'assigned_to', 'status', 'created_at']

    def create(self, validated_data):
        user = self.context['request'].user
        validated_data['user'] = user
        validated_data['organization'] = getattr(user, 'organization', None)
        return super().create(validated_data)
