# Inventory Management API Documentation

This document provides a complete walkthrough of all endpoints in the new `inventory` app, including request bodies, response formats, and operational steps.

All endpoints are prefixed with: `{{BASE_URL}}/api/v1/inventory/`

---

## 1. Item Categories

Categories are used to group items together (e.g., Uniforms, Books, Stationery).

### List Categories
**GET** `/categories/`

**Response:**
```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "uuid-here",
      "branch": "branch-uuid",
      "branch_name": "Main Branch",
      "name": "Uniforms",
      "description": "School uniforms including shirts, trousers, and blazers.",
      "is_active": true,
      "created_at": "2026-06-22T10:00:00Z",
      "updated_at": "2026-06-22T10:00:00Z"
    }
  ]
}
```

### Create Category
**POST** `/categories/`

**Request Body:**
```json
{
  "branch": "branch-uuid",
  "name": "Textbooks",
  "description": "NCERT and supplementary books."
}
```

**Response:** Returns the created category object.

---

## 2. Items

Items represent the actual stock units. They belong to a category.
> **Note:** The `total_stock` field is read-only. It is automatically calculated and updated whenever a `StockTransaction` or `ItemAllocation` occurs.

### List Items
**GET** `/items/`

**Response:**
```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "item-uuid",
      "category": "category-uuid",
      "category_name": "Uniforms",
      "name": "Uniform Shirt",
      "sku": "UNI-SHT-M",
      "description": "White uniform shirt, medium size.",
      "size": "M",
      "total_stock": 50,
      "reorder_level": 10,
      "unit_price": "250.00",
      "is_active": true,
      "created_at": "2026-06-22T10:00:00Z",
      "updated_at": "2026-06-22T10:00:00Z"
    }
  ]
}
```

### Create Item
**POST** `/items/`

**Request Body:**
```json
{
  "category": "category-uuid",
  "name": "Uniform Shirt",
  "sku": "UNI-SHT-M",
  "description": "White uniform shirt.",
  "size": "M",
  "reorder_level": 10,
  "unit_price": "250.00"
}
```

---

## 3. Stock Transactions

Transactions act as a strict ledger. Whenever you purchase new stock, find damaged goods, or manually adjust inventory, you create a transaction. 
> **Important:** Creating an `ItemAllocation` automatically creates a corresponding outgoing transaction.

### Add New Stock (Purchase)
**POST** `/transactions/`

**Request Body:**
```json
{
  "item": "item-uuid",
  "transaction_type": "purchase",
  "quantity": 100,
  "unit_price": "200.00",
  "reference": "INV-10293",
  "notes": "Purchased from Vendor XYZ"
}
```
*Note: `quantity` must be positive for incoming stock. This will automatically increase the `total_stock` of the item by 100.*

---

## 4. Item Allocations (Checklist)

Allocations are used to issue an item to a specific `Student` or `Faculty`.

### Issue an Item
**POST** `/allocations/`

**Request Body (To Student):**
```json
{
  "item": "item-uuid",
  "student": "student-profile-uuid",
  "quantity": 1,
  "size": "M",
  "status": "issued",
  "notes": "Issued first set of uniforms."
}
```
*Note: This automatically decreases the `total_stock` of the item by 1.*

**Request Body (To Faculty):**
```json
{
  "item": "item-uuid",
  "faculty": "faculty-profile-uuid",
  "quantity": 1,
  "size": "L",
  "status": "issued",
  "notes": "Issued faculty blazer."
}
```

**Response:**
```json
{
  "id": "allocation-uuid",
  "item": "item-uuid",
  "item_name": "Uniform Shirt",
  "student": "student-profile-uuid",
  "student_name": "John Doe",
  "faculty": null,
  "faculty_name": null,
  "quantity": 1,
  "size": "M",
  "status": "issued",
  "status_display": "Issued",
  "issued_at": "2026-06-22T10:05:00Z",
  "issued_by": 1,
  "issued_by_name": "Admin User",
  "returned_at": null,
  "return_notes": "",
  "notes": "Issued first set of uniforms."
}
```

### Return an Issued Item
If an item is returned by a student/faculty, use this custom action to mark the allocation as returned. It automatically restores the stock quantity.

**POST** `/allocations/<allocation-uuid>/return_item/`

**Request Body:**
```json
{
  "return_notes": "Returned in good condition. Student transferred."
}
```

**Response:**
```json
{
  "status": "Item returned successfully."
}
```

---

## 5. Dynamic Forecasting

The forecasting API dynamically calculates how fast items are being consumed (based on the last 30 days of allocations) and projects the stock health for the next 30 days.

### Get Forecast
**GET** `/forecast/`

**Response:**
```json
[
  {
    "item_id": "item-uuid",
    "item_name": "Uniform Shirt",
    "sku": "UNI-SHT-M",
    "category": "Uniforms",
    "current_stock": 10,
    "reorder_level": 15,
    "last_30d_usage": 50,
    "daily_burn_rate": 1.67,
    "projected_30d_demand": 50,
    "days_until_stockout": 5,
    "status": "critical",
    "message": "Stockout expected in 5 days!"
  },
  {
    "item_id": "another-item-uuid",
    "item_name": "Math Textbook",
    "sku": "BOK-MTH-10",
    "category": "Textbooks",
    "current_stock": 200,
    "reorder_level": 20,
    "last_30d_usage": 15,
    "daily_burn_rate": 0.5,
    "projected_30d_demand": 15,
    "days_until_stockout": 400,
    "status": "healthy",
    "message": "Stock is healthy for the next 30 days."
  }
]
```

### Understanding Forecast Statuses
- **`healthy`**: Current stock is enough to cover the projected 30-day demand and stay above the reorder level.
- **`warning`**: Current stock is either currently below the reorder level, or the projected demand will cause it to drop below the reorder level within 30 days.
- **`critical`**: The stock is mathematically projected to completely run out (drop to 0 or below) within the next 30 days based on the daily burn rate.
