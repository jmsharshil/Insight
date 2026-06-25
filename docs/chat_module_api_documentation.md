# Chat Module — Full Walkthrough & Realtime API Reference Guide (Updated with Targeted Messages)

> **Last Updated:** Targeted private messages for student-faculty discussions in group chats (visible only to sender + target faculty + super_admin).

> **Base URL:** `https://api.example.com/api/v1/`  
> **Auth Header:** `Authorization: Bearer <access_token>`  
> **Content-Type:** `application/json` (multipart for file uploads)  
> Responses wrapped: `{ "success": true, "data": {...}, "message": "..." }`.  
> **Realtime:** WebSocket at `/ws/chat/<room_id>/` (Django Channels consumers). Supports live message delivery, read receipts, typing indicators.

---

## Architecture & Workflow Diagram

```
Client (Web/Mobile) ── REST (rooms/messages/upload) ──► Views/Serializers
          │
          ▼
Django ORM (ChatRoom + Message + ReadReceipt) + Soft-delete (is_active/is_deleted)
          │
          ├─► **Targeted message visibility** (`target` FK): filtered in views + consumers
          │     (student ↔ specific faculty + super_admin only)
          ├─► Signals/Tasks (notifications.py, tasks.py — unread counts, push)
          │
          ▼
WebSocket Consumers (consumers.py) ──► Group broadcast (room_id) + Redis layer
          │     (with per-user privacy filter for targeted messages)
          │
          ▼
Frontend receives: new_message, message_read, user_typing, delivery_status
          │
          └─► Read receipts (MessageReadReceipt) update tick_status (sent/delivered/read)
```

**Key Features:**
- Direct rooms use deterministic `direct_hash` (sorted user UUIDs) for 1:1 uniqueness.
- **Group rooms now support targeted messages**: Students can ask questions to a *specific faculty*. These are visible **only to the sender, the target faculty, and `super_admin`** (while staying in the same group room). Normal messages remain visible to all participants.
- Group rooms support avatar, name, multiple participants.
- Messages support text + file attachments (S3 URLs).
- Soft deletes preserve history.
- Realtime via Channels + Redis (with per-user visibility filtering for targeted messages).
- Notifications for unread counts, mentions.

---

## Appendix A: System Choice Values

### A.1 Room Types (`room_type`)
| Value | Display | Use Case |
|-------|---------|----------|
| `direct` | Direct | 1-on-1 private chats (auto-created via hash) |
| `group` | Group | Multi-user channels (named, with avatar) |

### A.2 Message Status (`tick_status` property)
- `sent` — Created but not delivered.
- `delivered` — Recipient connected.
- `read` — Recipient has read receipt.

### A.3 Soft Delete Flags
- `ChatRoom.is_active` — Filters out "deleted" groups.
- `Message.is_deleted` — Hides from list but keeps in DB for audit.

---

## Data Models Summary

| Model | Purpose | Key Behaviors |
|-------|---------|---------------|
| `ChatRoom` | Container for conversations | `direct_hash` for uniqueness; M2M participants; soft-delete via `is_active` |
| `Message` | Individual chat entry | Supports `content` + `file_url`; **NEW `target` FK** for private faculty questions in groups; `tick_status` computed from receipts; soft-delete. Visibility filtering enforced in views/consumers. |
| `MessageReadReceipt` | Delivery tracking | Unique (message, user); updates status to "read" |

**Utils:** `utils.py` for room lookup, `notifications.py` for in-app/push, `tasks.py` for async unread counts.

---

## Key Workflows & Steps

### 1. Direct Chat
1. POST `/rooms/direct/` with `other_user_id` → creates or returns existing room (using `build_direct_hash()`).
2. POST message to room.
3. Realtime delivered via WS; read receipts auto-created on view.

### 2. Group Chat
1. POST `/rooms/group/` with name + participant_ids → creates room, adds participants.
2. PATCH `/rooms/<id>/update-group/` for name/avatar.
3. Members list via `/members/`.
4. Only creator or admin can delete (sets `is_active=False`).

### 2.1 Targeted Messages in Group Chats (NEW)
- **Use case**: Student wants to privately ask a question to one specific faculty *inside* an existing group chat (e.g. class/exam batch group).
- **Visibility rules** (enforced server-side in views + consumers):
  - `target=None` (default): Visible to **all participants**.
  - `target=some_faculty_id`: Visible **only to**:
    - The sender (student).
    - The target faculty (`paper_checker` / `faculty` role).
    - Any `super_admin`.
- The message stays in the **same `ChatRoom`** (no separate thread/room needed).
- Frontend can display a "Private to: Dr. X" badge.

**How to send (REST or WS):**
```json
{
  "content": "Sir, clarification needed on Q. 5 of the answer key...",
  "target_user_id": "faculty-uuid-here"
}
```

**Filtering:**
- `GET /messages/` automatically hides targeted messages you shouldn't see.
- WebSocket `new_message` events are filtered per-connection (unauthorized users never receive them).

### 3. Messaging & Files
1. GET `/rooms/<room_id>/messages/` (paginated, latest first; **respects targeted visibility**).
2. POST message with `content`, optional `target_user_id`, or file (first upload via `/upload/` to get URL).
3. WS listens for live updates, typing indicators.
4. Read receipts update on frontend open.

### 4. Notifications & Unreads
- Background tasks update unread counts per room/user.
- Push notifications on new message (if enabled).
- Mentions (@user) trigger special alerts.

**Safety:**
- Participants only see their rooms.
- File uploads validated (size/type).
- Soft deletes prevent data loss.
- WS authentication via token.

---

## Complete API Reference

### Rooms

**`GET /api/v1/chat/rooms/`**
Lists all active rooms for the authenticated user (direct + groups they participate in).

#### Response (200 OK)
```json
{
  "success": true,
  "count": 5,
  "data": [
    {
      "id": "room-uuid-001",
      "name": "Branch Managers Group",
      "room_type": "group",
      "avatar": "https://s3.../avatar.png",
      "participants_count": 8,
      "last_message": "Meeting at 3pm",
      "last_message_at": "2026-06-22T10:15:00Z",
      "unread_count": 2
    },
    {
      "id": "room-uuid-002",
      "name": "",
      "room_type": "direct",
      "other_user": {"id": "user-uuid", "name": "Priya Shah"},
      "unread_count": 0
    }
  ]
}
```

**`GET /api/v1/chat/rooms/<room_id>/`**
Detail with full participants.

**`POST /api/v1/chat/rooms/direct/`**

#### Request Body
```json
{
  "other_user_id": "user-uuid-002"
}
```

#### Response (200/201)
```json
{
  "success": true,
  "message": "Direct room ready.",
  "data": {
    "id": "room-uuid-001",
    "room_type": "direct",
    "participants": ["user-uuid-001", "user-uuid-002"]
  }
}
```

### Group Management

**`POST /api/v1/chat/rooms/group/`**

#### Request Body
```json
{
  "name": "Faculty Coordination",
  "participant_ids": ["user-uuid-002", "user-uuid-003"],
  "avatar": null
}
```

**Success:** Returns created room with ID.

**`PATCH /api/v1/chat/rooms/<room_id>/update-group/`**

#### Request Body
```json
{
  "name": "Updated Group Name",
  "avatar": "file-upload-url"
}
```

**`GET /api/v1/chat/rooms/<room_id>/members/`** — List participants.

**`DELETE /api/v1/chat/rooms/<room_id>/delete/`** — Soft deletes (sets `is_active=False`). Creator only.

### Messages

**`GET /api/v1/chat/rooms/<room_id>/messages/`**
Paginated (newest first), supports `?page=1`.

#### Response
```json
{
  "success": true,
  "count": 23,
  "data": [
    {
      "id": "msg-uuid-001",
      "sender": {"id": "user-uuid", "name": "Admin"},
      "content": "Please review the new timetable.",
      "file_url": null,
      "file_name": null,
      "created_at": "2026-06-22T10:20:00Z",
      "tick_status": "read",
      "is_deleted": false
    }
  ]
}
```

**`POST /api/v1/chat/rooms/<room_id>/messages/`**

#### Request Body
```json
{
  "content": "Hello team, any updates on the fees module?",
  "target_user_id": "optional-faculty-uuid-for-private-question",  // NEW: targeted message
  "file_url": "https://s3.../document.pdf",
  "file_name": "report.pdf",
  "file_size": 245760
}
```

**Response includes `target`** (if set):
```json
{
  "id": "msg-uuid",
  "sender": { ... },
  "target": {
    "id": "faculty-uuid",
    "full_name": "Dr. Rajesh Sharma",
    "role": "faculty"
  },
  "content": "...",
  "tick_status": "sent",
  ...
}
```

**Success:** Returns created message + broadcasts via WS (only to authorized viewers for targeted messages).

**`GET /api/v1/chat/messages/<message_id>/`** — Single message detail.

### File Upload

**`POST /api/v1/chat/upload/`** (multipart)

#### Form Data
- `file`: The file to upload (image/pdf/doc).

#### Response
```json
{
  "success": true,
  "message": "File uploaded successfully.",
  "data": {
    "file_url": "https://s3-bucket.../chat/abc123.pdf",
    "file_name": "report.pdf",
    "file_size": 245760
  }
}
```

---

## Realtime WebSocket

**Endpoint:** `ws://api.example.com/ws/chat/<room_id>/`

**Events Sent by Client:**
- `send_message` — `{content, file_url?, target_user_id?}` (**NEW**: `target_user_id` for private faculty questions in group chats)
- `typing` — `{is_typing: true}`
- `mark_read` — `{message_id}`

**Events from Server:**
- `new_message` — includes optional `target` object; **server filters delivery** so only authorized users (sender/target/super_admin) receive targeted messages.
- `message_read` (updates ticks)
- `user_typing`
- `delivery_update`

Authentication via query param `token=...` or middleware.

---

## Common Errors

- 403: Not a participant in room.
- 400: Invalid direct hash or missing content/file.
- 404: Room/Message not found (or inactive).
- WS disconnects handled with presence.

---

## Related Modules & Notes

- **Notifications:** `notifications.py` for unread counts, push (Celery tasks).
- **Exams/Results:** Perfect for **student-faculty private queries** inside batch/exam group chats (targeted messages integrate with `CheckerQuery`/`RecheckRequest` workflows).
- **Storage:** Files go to S3; URLs stored in Message.
- **Soft Delete:** All list views filter `is_active=True` / `is_deleted=False`.
- **Roles:** Leverages `super_admin`, `faculty`/`paper_checker`, `student` roles for visibility.

**WebSocket Consumers** in `consumers.py` handle auth, room joining, broadcasting.

This updated documentation brings the chat module in line with the full walkthrough style of `faculty_module_api_documentation.md`, `timetable_procedure_guide.md`, and `results_module_api_documentation.md`. Includes realtime details, soft-delete logic, and exact request/response examples from current implementation.
