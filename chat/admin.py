from django.contrib import admin
from chat.models import *

@admin.register(ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'avatar', 'room_type', 'direct_hash', 'is_active', 'created_at',)
    search_fields = ('name',)
    list_filter = ('created_at', 'room_type', 'is_active',)
    readonly_fields = ('id','created_at', 'updated_at','direct_hash')
    ordering = ['-created_at']

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'room', 'sender', 'content', 'file_url', 'file_name', 'file_size', 'is_deleted', 'delivered_at', 'created_at',)
    list_filter = ('delivered_at', 'is_deleted', 'room', 'updated_at', 'sender', 'created_at',)
    search_fields = ('content','room__name','sender__name')
    ordering = ['-created_at']
    readonly_fields = ('id','created_at', 'updated_at','file_url','file_size')


@admin.register(MessageReadReceipt)
class MessageReadReceiptAdmin(admin.ModelAdmin):
    list_display = ('id', 'message', 'user', 'read_at',)
    list_filter = ('message', 'read_at', 'user',)
    search_fields = ('message__content','user__name')
    ordering = ['-read_at']
    readonly_fields = ('id','read_at')
