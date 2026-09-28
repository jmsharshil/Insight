# Sales Module: Activity Timings & Dynamic Photo Slots

This document explains the two major updates to the Sales Module: **Multi-day Activity Timings** and **Dynamic Exhibition Photo Slots**.

---

## 1. Multi-Day Activity Timings

Previously, sales events were strictly limited to a single day. Now, activities and plans support **multi-day events** by using a `from_date` and `to_date`, along with a dedicated timing array for each specific day.

### Data Structure (`SalesDailyActivityTiming`)
When creating or viewing a multi-day activity, a new `timings` array is used. This allows the employee to specify different start and end times for each day of the event.

**Endpoints Returning This Structure:**
- `GET /api/leads/sales/activities/` (List all activities)
- `GET /api/leads/sales/activities/<activity_id>/` (View single activity)
- `POST /api/leads/sales/activities/` (Create activity)
- `PATCH /api/leads/sales/activities/<activity_id>/` (Update activity)
- *(Also returned in the `/api/leads/sales/plans/` endpoints!)*

**Example API Response / Payload:**
```json
{
    "id": "9a8b7c6d-5e4f-3210-fedc-ba0987654321",
    "name": "3-Day College Exhibition",
    "activity_date": "2026-09-28",
    "from_date": "2026-09-28",
    "to_date": "2026-09-30",
    "timings": [
        {
            "date": "2026-09-28",
            "start_time": "10:00:00",
            "end_time": "13:00:00"
        },
        {
            "date": "2026-09-29",
            "start_time": "14:00:00",
            "end_time": "17:00:00"
        },
        {
            "date": "2026-09-30",
            "start_time": "09:00:00",
            "end_time": "12:00:00"
        }
    ]
}
```

---

## 2. Dynamic Exhibition Photo Slots

When an employee attends an event/exhibition, the system now dynamically enforces photo upload limits based on the **duration** of the event for that specific day. 

### Rules
- **Slot 1** is always reserved for the `event_start_selfie`.
- **The Last Slot** is always reserved for the `event_end_selfie`.
- **The Middle Slots** are reserved for `exhibition` photos.
- **Total Slots** = Event Duration in Hours. 
  *(e.g., A 3-hour event has 3 slots: 1 start selfie, 1 exhibition photo, and 1 end selfie).*

### Uploading Photos
**Endpoint:** `POST /api/leads/sales/activities/<activity_id>/photos/`

You must pass the `photo_type` in your form-data.
Valid event photo types:
- `event_start_selfie` (Strictly 1 allowed per event)
- `event_end_selfie` (Strictly 1 allowed per event)
- `exhibition` (Dynamic limit based on event duration)

*Note: The user MUST have already checked in for the day (uploaded their daily `start_selfie`) before they are allowed to upload these event-specific photos.*

### API Response (`event_photo_slots`)
When you fetch the Sales Activity details, the API automatically calculates the required slots and maps the uploaded photos to them. This makes it incredibly easy for the frontend to render the UI and know which slots are missing.

**Endpoints Returning This Structure:**
- `GET /api/leads/sales/activities/`
- `GET /api/leads/sales/activities/<activity_id>/`

**Example Response for a 3-Hour Event:**
```json
{
    "id": "9a8b7c6d-5e4f-3210-fedc-ba0987654321",
    "name": "School Exhibition Day 1",
    "event_photo_slots": [
        {
            "slot": 1,
            "type": "event_start_selfie",
            "photo_id": "a1b2c3d4-e5f6-7890-1234-56789abcdef0",
            "photo_url": "http://localhost:8000/media/sales/activity_photos/start_selfie.jpg",
            "is_filled": true
        },
        {
            "slot": 2,
            "type": "exhibition",
            "photo_id": null,
            "photo_url": null,
            "is_filled": false
        },
        {
            "slot": 3,
            "type": "event_end_selfie",
            "photo_id": null,
            "photo_url": null,
            "is_filled": false
        }
    ]
}
```
In this example, the frontend can clearly see that the user has successfully uploaded their `event_start_selfie`, but they still need to upload 1 `exhibition` photo and their `event_end_selfie` to complete the event requirements.
