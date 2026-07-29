from rest_framework import serializers
from .models import SupportQuery

class SupportQuerySerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportQuery
        fields = ['id', 'user', 'organization', 'title', 'description', 'attachment', 'created_at']
        read_only_fields = ['id', 'user', 'organization', 'created_at']

    def create(self, validated_data):
        user = self.context['request'].user
        validated_data['user'] = user
        validated_data['organization'] = getattr(user, 'organization', None)
        return super().create(validated_data)
