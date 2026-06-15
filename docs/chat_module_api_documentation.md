# Chat Module — API Documentation

The `chat` module provides internal messaging, offering both direct (1-on-1) and group chat functionality.

---

## Data Model

| Model | Purpose |
|---|---|
| `ChatRoom` | A chat channel, either direct or group. Direct rooms generate a deterministic hash. |
| `Message` | A single chat message sent within a `ChatRoom` |

---

## API Endpoints

### 1. Rooms
**`GET /api/v1/chat/rooms/`**
List all chat rooms the authenticated user is a participant of.

**`GET /api/v1/chat/rooms/<room_id>/`**
Get details of a specific chat room.

### 2. Direct Messaging
**`POST /api/v1/chat/rooms/direct/`**
Create or retrieve an existing direct (1-on-1) chat room with another user.

**Request Body:**
```json
{
  "other_user_id": "uuid-of-user"
}
```

### 3. Group Messaging
**`POST /api/v1/chat/rooms/group/`**
Create a new group chat room.

**Request Body:**
```json
{
  "name": "Branch Managers Group",
  "participant_ids": ["uuid-1", "uuid-2"]
}
```

**`PATCH /api/v1/chat/rooms/<room_id>/update-group/`**
Update group chat details (e.g., name).

**`DELETE /api/v1/chat/rooms/<room_id>/delete/`**
Delete a group chat room (usually restricted to creator).

**`GET /api/v1/chat/rooms/<room_id>/members/`**
List participants of a group chat.

### 4. Messages
**`GET /api/v1/chat/rooms/<room_id>/messages/`**
**`POST /api/v1/chat/rooms/<room_id>/messages/`**
Retrieve messages in a room, or send a new message.

**`GET /api/v1/chat/messages/<message_id>/`**
Retrieve details of a specific message.

### 5. Attachments
**`POST /api/v1/chat/upload/`**
Upload a file or image to attach to a chat message. Returns the file URL to include in the message payload.
