# Outlier API - Core Messaging & Chat

`chrome --remote-debugging-port=9222 --user-data-dir="C:\temp\chrome-debug"`

## Overview
Core API endpoints for conversations, models, and message sending in the Outlier AI playground.

**Verified by**: Sending test messages and capturing network traffic

---

## Base URL
```
https://app.outlier.ai/internal/experts/assistant/
```

---

## Authentication
- **Method**: Session-based cookies
- **Failure**: Returns 401 Unauthorized when not authenticated

---

## 1. Models

### List Available AI Models
```http
GET /models
```

**Response**: 200 OK
```json
[
  {
    "id": "gemini-2.5-pro-preview-06-05",
    "name": "Gemini 2.5 Pro"
  },
  {
    "id": "GPT-4o mini"
  },
  {
    "id": "o4-mini"
  },
  {
    "id": "claude-sonnet-4-5-20250929",
    "name": "Claude Sonnet 4.5"
  }
]
```

---

## 2. Conversations

### Create New Conversation
```http
POST /conversations
```

**Response**: 201 Created
```json
{
  "id": "690e2e0a51475b6e6569d7ab",
  "model": "gemini-2.5-pro-preview-06-05",
  "turns": []
}
```

**Notes**:
- Conversation ID: 24-character hexadecimal string
- Model can be specified in request body
- Called when sending first message

---

### Get Conversation Details
```http
GET /conversations/{conversationId}
```

**Example**:
```
GET /conversations/690e2e0a51475b6e6569d7ab
```

**Response**: 200 OK
```json
{
  "id": "690e2e0a51475b6e6569d7ab",
  "turns": [
    {
      "role": "user",
      "content": "What is 2+2?"
    },
    {
      "role": "assistant",
      "content": "2 + 2 = 4",
      "model": "gemini-2.5-pro-preview-06-05"
    }
  ]
}
```

---

### List All Conversations
```http
GET /conversations/
```

**Response**: 200 OK
- Returns array of all conversations

---

### List Conversations (Paginated)
```http
GET /conversations/paginated?page=1&pageSize=20
```

**Parameters**:
- `page`: Page number (1-based)
- `pageSize`: Results per page

**Response**: 200 OK

---

## 3. Sending Messages

### **PRIMARY ENDPOINT: Send Message with Streaming Response**
```http
POST /conversations/{conversationId}/turn-streaming
Content-Type: application/json
```

**Request Body**:
```json
{
  "content": "Your message text here",
  "model": "gemini-2.5-pro-preview-06-05"
}
```

**Response**: 200 OK  
- **Type**: Server-Sent Events (SSE) stream
- **Content-Type**: `text/event-stream`
- AI response streams in real-time as it's generated

**Example**:
```http
POST /conversations/690e2e0a51475b6e6569d7ab/turn-streaming

{
  "content": "What is 2+2?",
  "model": "gemini-2.5-pro-preview-06-05"
}
```

**Notes**:
- This is the main endpoint used for all message sending
- Response arrives incrementally via SSE
- Model must be specified in each request
- Verified with multiple test messages

---

## Typical Message Flow

When a user sends a message, the following sequence occurs:

1. **(First message only)** `POST /conversations` → Creates conversation, returns ID, must send a message after with same content
2. `POST /conversations/{id}/turn-streaming` → **Sends message, streams AI response**
3. `GET /conversations/{id}` → Refreshes conversation state
4. `GET /conversations/paginated` → Updates conversation list

---

## Response Format: Server-Sent Events

The `/turn-streaming` endpoint uses SSE for real-time streaming:

```
Content-Type: text/event-stream

data: {"type": "chunk", "content": "2"}
data: {"type": "chunk", "content": " +"}
data: {"type": "chunk", "content": " 2"}
data: {"type": "chunk", "content": " ="}
data: {"type": "chunk", "content": " 4"}
data: {"type": "done"}
```

---

## Key Technical Details

| Aspect | Details |
|--------|---------|
| **Base URL** | `https://app.outlier.ai/internal/experts/assistant/` |
| **Authentication** | Session cookies |
| **Conversation ID Format** | 24-character hex (e.g., `690e2e0a51475b6e6569d7ab`) |
| **Message Endpoint** | `POST /conversations/{id}/turn-streaming` |
| **Response Type** | Server-Sent Events (SSE) stream |
| **Required Fields** | `content` (string), `model` (string) |
