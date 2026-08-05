# Centralized Authentication Service (ExamSimula)

A robust, centralized Identity Provider (IdP) for the ExamSimula platform. This service handles user authentication, session management, and Role-Based Access Control (RBAC) across different domain portals (Student Portal, Teacher Portal, Admin Dashboard).

## Features
- **Google OAuth 2.0 Integration**: Secure Single Sign-On (SSO) login flow using Google.
- **Stateful Session Management**: Instead of stateless JWTs, opaque session tokens are stored in the database, allowing for instant session revocation and secure logouts.
- **Role-Based Access Control (RBAC)**: Strict permission enforcement for `STUDENT`, `TEACHER`, and `ADMIN` roles.
- **FastAPI & SQLAlchemy**: High-performance async Python backend with an SQLite/PostgreSQL database connector.
- **Auto-Provisioning**: Automated database table creation on startup via lifespan events.

---

## Setup & Installation

### 1. Requirements
- Python 3.10+
- Database (SQLite locally, PostgreSQL in production)
- Google Cloud Console API Credentials (Client ID & Secret)

### 2. Environment Variables
Create a `.env` file in the root directory (alongside `main.py`) with the following variables:
```env
PROJECT_NAME="Centralized Authentication Service"
API_V1_STR="/api/v1"
DATABASE_URL="sqlite+aiosqlite:////path/to/your/db.sqlite"
GOOGLE_CLIENT_ID="your-google-client-id.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET="your-google-client-secret"
ACCESS_TOKEN_EXPIRE_MINUTES=1440
```

### 3. Run the Service
Ensure your virtual environment is activated, install requirements, and start Uvicorn:
```bash
pip install -r requirements.txt
uvicorn app.main:app --port 5001 --reload
```
*Note: We run on port `5001` to avoid macOS AirPlay conflicts on port `5000`.*

---

## API Reference

All endpoints are prefixed with `/api/v1/auth`.

### 1. Google OAuth Flow

#### `GET /google/login`
Initializes the Google OAuth flow. Redirects the user to the Google Sign-in page.
- **Query Parameters**:
  - `role` (Required): The role the user is logging in as (e.g., `STUDENT`, `TEACHER`, `ADMIN`).
  - `exam_code` (Optional): An exam code context (e.g., `JEE`).
- **Permissions**: Public

#### `GET /google/callback`
The callback URL triggered by Google after successful authentication.
- **Behavior**:
  - Automatically registers new `STUDENT` users.
  - Rejects new users attempting to register as `TEACHER` or `ADMIN` (403 Forbidden).
  - Rejects existing `STUDENT` users attempting to log in as `TEACHER` or `ADMIN` (403 Forbidden).
  - Issues a stateful `session_token` upon success.

---

### 2. User & Session Management

#### `GET /me`
Retrieves the profile data of the currently authenticated user.
- **Headers**: `Authorization: Bearer <session_token>`
- **Returns**: User details including `id`, `email`, `role`, and `exam_code`.

#### `POST /logout`
Logs the user out by securely deleting their active session token from the database.
- **Headers**: `Authorization: Bearer <session_token>`
- **Returns**: `{"message": "Successfully logged out"}`

---

### 3. Administrator Actions
*The following endpoints strictly require the calling user to hold the `ADMIN` role.*

#### `POST /register-staff`
Pre-provisions a `TEACHER` or `ADMIN` account in the database.
- **Headers**: `Authorization: Bearer <admin_session_token>`
- **Body**:
  ```json
  {
    "email": "teacher@example.com",
    "name": "Jane Teacher",
    "role": "TEACHER",
    "exam_code": "JEE"
  }
  ```

#### `PUT /users/{user_id}/role`
Promotes, demotes, or modifies the role/exam code of an existing user.
- **Headers**: `Authorization: Bearer <admin_session_token>`
- **Path Parameter**: `user_id` (The UUID of the target user)
- **Body**:
  ```json
  {
    "role": "ADMIN",
    "exam_code": "NEET"
  }
  ```
