# Chat Module — Full Walkthrough & Realtime API Reference Guide

> **Last Updated:** Soft-delete everywhere, automatic unread clearing on room open (`mark_all_read` on connect), real-time unread count updates on `mark_read`/`all_read`, delivered receipts, targeted messages (M2M), visibility filtering, and bulk read receipts.

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
Django ORM (ChatRoom + Message w/ targets M2M + ReadReceipt + soft-delete)
          │
          ├─► **Visibility**: `get_visible_messages_qs()` (Count("targets") + Q filter). Super-admin bypass.
          ├─► **Unread**: `get_unread_count()` excludes messages with receipt for user.
          ├─► **Auto-clear**: `_mark_all_messages_read()` on WS connect() + bulk receipts.
          ├─► Notifications (`notify_new_message`): respects targets, runs in background.
          │
          ▼
WebSocket Consumers (`consumers.py`) ──► InMemory/Redis group broadcast
          │   • JWT + participant check + faculty-direct block (BR-011)
          │   • `_handle_mark_read()` + `_handle_mark_all_read()` → create receipt + broadcast `read_receipt`/`all_read` + `unread_update`
          │   • `connect()` auto-calls mark-all-read + delivered receipts
          │   • Privacy filter on `chat_new_message` (sender/target/super_admin only)
          │
          ▼
Frontend receives: `new_message`, `read_receipt` (with `unread_count`), `unread_update`, `all_messages_read`, `delivered_receipt`, `message_updated`, `message_deleted`, `typing`
          │
          └─► `tick_status` property on Message (read/delivered/sent based on receipts)
```

**Key Features (All Changes Incorporated):**
- **Soft-delete everywhere**: `ChatRoom.is_active`, `Message.is_deleted`. All querysets/views filter accordingly.
- **Targeted messages** (M2M `targets`): Visible only to sender + listed targets + super_admin. Normal messages (no targets) visible to all. Supports multiple targets. Filtered in views, consumers, notifications.
- Direct rooms use `direct_hash`. Group management (add/remove/delete via `is_active=False`).
- Messages support text + files (10MB validation via `FileUploadView`).
- Delivered receipts (`delivered_at`, `_mark_messages_delivered` on connect).
- `tick_status` property on Message.
- Notifications use FCM v1 (service account), background thread, respect targets.
- CHANNEL_LAYERS = InMemory (dev); WS route `ws/chat/<uuid:room_id>/`.
- `get_last_visible_message()`, `RoomListView`/`ChatRoomListSerializer` delegate to model helpers (respects visibility).

### Unread Count Mechanism (Updated)

A message is removed from a user's unread count when a `MessageReadReceipt` row exists for that `(message, user)` pair.

**How it works:**
1. `ChatRoom.get_unread_count(user)`:
   - Calls `get_visible_messages_qs(user)` (filters `is_deleted=False`, uses `Count("targets")` + `Q(num_targets=0) | sender | targets`).
   - Further filters: `~Q(read_receipts__user_id=user_id) & ~Q(sender=user)`.
   - Super-admin bypasses visibility.

2. **On `mark_read`** (`_handle_mark_read` in consumer):
   - `get_or_create` a `MessageReadReceipt`.
   - Computes new count via `_get_unread_count()`.
   - Broadcasts `read_receipt` **with `unread_count`** + dedicated `unread_update`.

3. **On room open / `mark_all_read`**:
   - `connect()` automatically calls `_mark_all_messages_read()` (bulk_create of receipts for all visible unread messages).
   - `_handle_mark_all_read` does the same for explicit frontend requests.
   - Broadcasts `all_messages_read` + `unread_update` (count usually drops to 0).

4. **Frontend impact**: Listen to `unread_update` or the `unread_count` field in `read_receipt`/`all_messages_read` to refresh sidebar badges instantly. No polling needed.

**Models involved**: `MessageReadReceipt` (unique on `(message, user)`), `Message.read_receipts` reverse relation.

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

## Data Models Summary (Updated)

| Model | Purpose | Key Behaviors |
|-------|---------|---------------|
| `ChatRoom` | Container for conversations | `direct_hash`, M2M `participants`, `is_active` (soft-delete). **New:** `get_visible_messages_qs(user)`, `get_unread_count(user)`, `get_last_visible_message(user)` (all respect targets/soft-delete). |
| `Message` | Individual chat entry | `content` + `file_url`/`file_name`/`file_size`, M2M `targets`, `is_deleted`, `delivered_at`. **New:** `tick_status` property (read/delivered/sent based on receipts). |
| `MessageReadReceipt` | Read tracking | Unique `(message, user)`; `read_at`. Bulk creation used for `mark_all_read`. |

**Core files:**
- `models.py` — visibility + unread helpers.
- `consumers.py` — auth, `_handle_mark_read`, `_handle_mark_all_read`, auto-clear on connect, privacy filters, delivered receipts.
- `views.py` / `serializers.py` — visibility on GET, PATCH/DELETE for edit/soft-delete, unread in room list.
- `notifications.py` — targeted push (FCM v1).

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

### 2.1 Targeted Messages in Group Chats (Multi-Target Support)
- **Use case**: Student wants to privately ask a question to *one or more specific faculty* inside an existing group chat (e.g. class/exam batch group). Supports multiple targets.
- **Visibility rules** (enforced server-side in `MessageListCreateView.get()`, WS `chat_new_message`, and `notify_new_message`):
  - `targets` empty (default): Visible to **all participants**.
  - `targets` populated: Visible **only to**:
    - The sender.
    - Any of the listed target user(s).
    - Any `super_admin`.
- Backward compatible; uses M2M `targets` field (no custom through model). Normal messages have empty `targets`.
- The message stays in the **same `ChatRoom`** (no separate thread/room needed).
- Frontend can display "Private to: Dr. X, Prof. Y" badge based on `message.targets` array.

**How to send (REST or WS):**
```json
{
  "content": "Sirs, clarification needed on Q. 5 of the answer key...",
  "target_user_ids": ["faculty-uuid-1", "faculty-uuid-2"]
}
```
(or single as `"target_user_ids": ["faculty-uuid-here"]` or legacy `"target_user_id": "..."` for backward compat).

**Filtering:**
- `GET /messages/` uses annotation + Q filter to hide targeted messages you shouldn't see (super_admin bypass).
- WebSocket `new_message` events filtered per-connection based on `targets` list in payload (unauthorized users never receive them).
- Push notifications similarly filtered to only relevant users + super_admins.

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
  "target_user_ids": ["optional-faculty-uuid-1", "optional-faculty-uuid-2"],  // for targeted (multi supported)
  "file_url": "https://s3.../document.pdf",
  "file_name": "report.pdf",
  "file_size": 245760
}
```

**Response includes `targets`** (array, may be empty):
```json
{
  "id": "msg-uuid",
  "sender": { ... },
  "targets": [
    {
      "id": "faculty-uuid",
      "full_name": "Dr. Rajesh Sharma",
      "role": "faculty"
    }
  ],
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

## Realtime WebSocket (Updated)

**Endpoint:** `ws://api.example.com/ws/chat/<room_id>/` (JWT via `?token=...` query param)

**Connection Flow (`connect()`):**
1. JWT auth + participant check.
2. Faculty blocked from direct rooms (BR-011).
3. Join `room_{room_id}` group.
4. `_mark_messages_delivered()` (bulk update `delivered_at`).
5. Broadcast delivered receipts.
6. `_mark_all_messages_read()` (bulk receipts for visible unread messages) → auto-clears unread count.
7. Broadcast `all_messages_read` + `unread_update` with new count.

**Events Sent by Client:**
- `send_message` — `{content, file_url?, target_user_ids?: string[] }` (multi-target support).
- `typing_start` / `typing_stop`.
- `mark_read` — `{ "type": "mark_read", "message_id": "..." }` → triggers receipt + unread count update.
- `mark_all_read` — `{ "type": "mark_all_read" }` (explicit bulk clear).
- `edit_message`, `delete_message` (soft delete).

**Events from Server:**
- `new_message` — includes `targets`; **per-user privacy filter** (sender/target/super_admin only). No echo to sender.
- `read_receipt` — now includes `"unread_count"` (updated on every `mark_read`).
- `all_messages_read` / `unread_update` — real-time badge updates (`{ "unread_count": 0, "room_id": "...", "user_id": "..." }`).
- `delivered_receipt`.
- `message_updated`, `message_deleted` (soft `is_deleted=True` + broadcast).
- `typing`.

**Outbound handlers** in consumer apply visibility filters and convert internal `chat.*` events to clean frontend payloads.

Authentication + DB helpers are `@database_sync_to_async`.

---

## Common Errors

- 403: Not a participant in room.
- 400: Invalid direct hash or missing content/file.
- 404: Room/Message not found (or inactive).
- WS disconnects handled with presence.

---

## Related Modules & Notes

- **Unread handling**: Automatic on room open (`connect()` → `_mark_all_messages_read()`). Real-time updates via `read_receipt` (with `unread_count`) and `unread_update` events on every `mark_read`.
- **Notifications:** `notifications.py` respects `target_user_ids` (only targets + super_admin, excludes sender). Uses FCM v1 with service account, runs in background.
- **Exams/Results:** Ideal for student-faculty private queries inside batch groups using targeted messages.
- **Storage:** Files validated (≤10 MB, allowed MIME types) via `FileUploadView`; URLs stored in `Message`.
- **Soft Delete:** All querysets/views filter `is_active=True` / `is_deleted=False`. Group delete sets `is_active=False`.
- **Roles:** `super_admin` bypasses visibility; faculty blocked from direct rooms (BR-011).

**WebSocket Consumers** (`consumers.py`) now fully support:
- Auto mark-all-read + delivered receipts on connect.
- Real-time unread count updates on `mark_read` / `mark_all_read`.
- Privacy filtering for targeted messages.
- Edit/delete (soft) with broadcasts.

This documentation has been updated with **all recent changes** (soft-delete, visibility helpers, unread mechanism, auto-clear on open, real-time count updates, delivered receipts, bulk operations, etc.). It follows the style of other module docs and includes exact steps for the unread flow.
