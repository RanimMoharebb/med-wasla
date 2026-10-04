# MedWasla

**MedWasla** is a full-stack healthcare platform that connects patients with verified medical specialists across Egypt. Patients can discover doctors and nurses, book appointments, join live clinic queues, chat with an AI assistant, and leave reviews. Specialists manage profiles, availability, and patient flow. Administrators verify and approve specialist registrations.

The platform has three services:

| Service | Language / Framework | Purpose |
|---------|----------------------|---------|
| `backend/` | Node.js, Express 5, TypeScript | REST API, auth, business logic, MongoDB access |
| `frontend/` | React 19, TypeScript, Vite | Patient/specialist/admin web UI |
| `chatbot/` | Python, Flask | AI assistant (RAG + local LLM) used by the frontend via the backend |

---

## Demo

[Watch Med-Wasla Demo]([https://drive.google.com/file/d/1xy31gF129iYFJyo-irO9U-6rE8fI8XHU/view](https://drive.google.com/file/d/1f9fojk0umoSbk8JkUYSsosjIvX2H9p2f/view?usp=sharing))


- **Live demo video:** [HireGate Demo](https://drive.google.com/file/d/1xy31gF129iYFJyo-irO9U-6rE8fI8XHU/view)

<!-- TODO: add screenshots and/or a demo video/GIF here -->
<!-- Example:
![Home page](docs/screenshots/home.png)
![Booking flow](docs/screenshots/booking.png)

[Watch the demo video](docs/demo.mp4)
-->
<img width="1880" height="861" alt="تصميم بدون عنوان (4)" src="https://github.com/user-attachments/assets/72f4ba6e-bd59-4356-aca9-50830d9ac24d" />
<img width="1910" height="4207" alt="screencapture-med-wasla-vercel-app-services-2026-07-09-02_15_55" src="https://github.com/user-attachments/assets/6a2055ca-0e36-453b-8b8b-86631bcf5c81" />


---

## Table of Contents

- [Demo](#demo)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Environment Variables](#environment-variables)
- [Getting Started](#getting-started)
- [Database Seeding](#database-seeding)
- [API Reference](#api-reference)
- [Chatbot Service](#chatbot-service)
- [User Roles](#user-roles)
- [Testing](#testing)
- [Deployment](#deployment)
- [CI/CD](#cicd)
- [License](#license)

---

## Features

### Patients
- Register and verify account via OTP email
- Browse doctors and nurses by specialization and location
- View specialist profiles, ratings, and availability
- Book, reschedule, and cancel appointments
- Join and track position in real-time clinic queues
- Submit and update reviews for specialists
- Ask the in-app AI chatbot about symptoms/conditions or their own bookings

### Medical Specialists (Doctors & Nurses)
- Role-specific onboarding with license and certification upload
- Profile management: bio, clinic address, fees, and availability slots
- Dashboard with overview, schedule, requests, and profile tabs
- Manage and cancel appointments (including cancelling a full day)
- Queue management: advance to next patient and update status
- Admin verification workflow (pending → approved / rejected)

### Administrators
- Review pending specialist applications
- Approve or reject specialists and their certifications
- View all registered specialists

### Platform
- JWT-based authentication with role-based access control
- Email notifications (OTP, password reset, appointment reminders) and WhatsApp appointment notifications
- Cloudinary integration for profile and certificate images
- Responsive React UI with Tailwind CSS, English/Arabic i18n (i18next)
- AI chatbot backed by a local LLM (Ollama) with retrieval over a medical knowledge base

---

## Tech Stack

| Layer | Technologies |
|-------|--------------|
| **Frontend** | React 19, TypeScript, Vite, React Router 7, Tailwind CSS 4, i18next, Lucide/FontAwesome icons, React Toastify, React Markdown |
| **Backend** | Node.js, Express 5, TypeScript, Mongoose 9 |
| **Chatbot** | Python, Flask, Ollama (local LLM), sentence-transformers + FAISS (retrieval), PyTorch, pyspellchecker |
| **Database** | MongoDB (shared by backend and chatbot) |
| **Auth** | JWT, bcrypt (backend); Flask-JWT-Extended (chatbot) |
| **Storage** | Cloudinary |
| **Email / Messaging** | Nodemailer, WhatsApp Cloud API |
| **Testing** | Vitest, Supertest, MongoDB Memory Server |
| **CI** | GitHub Actions (backend, frontend, secret scanning) |

---

## Project Structure

```
med-wasla/
├── .github/workflows/
│   ├── backend-ci.yml    # Typecheck, lint, test, build (on backend/** changes)
│   ├── frontend-ci.yml   # Typecheck, lint, build (on frontend/** changes)
│   └── gitleaks.yml      # Secret scanning on every push to main and every PR
│
├── backend/
│   ├── src/
│   │   ├── app.ts                  # Express app, CORS, route mounting
│   │   ├── server.ts               # Server entry point and DB connection
│   │   │
│   │   ├── config/
│   │   │   ├── db.ts                # MongoDB connection
│   │   │   ├── cloudinary.ts        # Cloudinary SDK configuration
│   │   │   └── seed.ts              # Database seed script (doctors, nurses, patients)
│   │   │
│   │   ├── features/                # Feature modules (routes → controller → service)
│   │   │   ├── auth/                # Registration, OTP, login, logout
│   │   │   ├── patient-profile/     # Patient profile CRUD
│   │   │   ├── medicalSpecialist/   # Specialist profiles, availability, fees, certificates
│   │   │   ├── appointments/         # Booking, reschedule, cancel, reminders, WhatsApp/email notifications
│   │   │   ├── queue/               # Live clinic queue (join, leave, next patient)
│   │   │   ├── reviews/             # Patient reviews for specialists
│   │   │   ├── ai/                  # Proxies chat requests to the Python chatbot service
│   │   │   └── admin/               # Specialist approval workflow
│   │   │
│   │   ├── middleware/              # auth, upload (Multer), error handling
│   │   ├── models/                  # Mongoose schemas (user, patient, specialist, appointment, queue, review, otp, reminder)
│   │   ├── utils/                   # AppError, OTP generation, email sending
│   │   └── tests/                   # Vitest test suites (auth, queue, reviews, admin)
│   │
│   └── package.json
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx / main.tsx / index.css
│   │   ├── app/
│   │   │   ├── Layouts/             # Shared layout (navbar, footer)
│   │   │   ├── pages/               # auth/, patient/, profile/, "Doctor side/", public/, admin/, Services/, about/, contact/, Home.tsx, NotFound.tsx
│   │   │   ├── components/          # auth/, booking/, common/ (incl. ChatBot widget), patient-appointments/
│   │   │   └── context/             # AuthProvider, ChatBotProvider
│   │   ├── hooks/, locales/ (en/ar), styles/, services/api.ts, constants/, utils/
│   │
│   └── package.json
│
├── chatbot/
│   ├── app.py                # Flask entry point (POST /chat)
│   ├── chatbot_engine.py     # Pipeline: spelling/gibberish check → guards → intent routing → response
│   ├── config.py             # Env-driven config (Ollama, embeddings, Flask, MongoDB)
│   ├── core/                 # Classifier, router, Ollama client, response builders
│   ├── preprocessing/        # Sensitive-info filter, write-action guard (refuses booking/cancel/etc.)
│   ├── database/             # Direct MongoDB access (its own client, independent of the Node backend)
│   ├── data/                 # Knowledge bases: nhs_conditions.json, medwasla_knowledge.json
│   ├── models/, tests/
│   └── requirements.txt
│
├── LICENSE
└── README.md
```

---

## Prerequisites

- **Node.js** 20 or later, **npm** 9 or later
- **Python** 3.10+ (for the chatbot service)
- A **MongoDB** instance (local or [MongoDB Atlas](https://www.mongodb.com/atlas))
- **Ollama** running locally with a model pulled (e.g. `elixpo/llamamedicine`) — required for the chatbot to answer
- A **Cloudinary** account (for image uploads)
- An **SMTP email** account (for OTP and notifications)
- A **WhatsApp Cloud API** token (optional — only needed for WhatsApp appointment notifications)

---

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/<your-org>/med-wasla.git
cd med-wasla
```

### 2. Backend

```bash
cd backend
npm install
# create backend/.env — see Environment Variables above
npm run dev
```

API available at `http://localhost:5000`.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

App available at `http://localhost:5173`.

### 4. Chatbot

```bash
cd chatbot
python -m venv venv
venv\Scripts\activate        # (Windows) or: source venv/bin/activate
pip install -r requirements.txt
# create chatbot/.env — see Environment Variables above
# make sure Ollama is running and the model in OLLAMA_MODEL is pulled
python app.py
```

Chatbot available at `http://localhost:3000`. The frontend calls it indirectly through the backend's `/api/ai/chat` route, so the backend must have `CHATBOT_SERVICE_URL`/`INTERNAL_API_SECRET` configured to reach it.

---

## API Reference

All endpoints are prefixed with `/api`.

### Authentication — `/api/auth`

| Method | Endpoint | Access | Description |
|--------|----------|--------|--------------|
| POST | `/register` | Public | Register a new user |
| POST | `/verify-otp` | Public | Verify email with OTP |
| POST | `/resend-otp` | Public | Resend verification OTP |
| POST | `/login` | Public | Login and receive JWT |
| POST | `/logout` | Public | Logout |
| GET | `/me` | Private | Get current user profile |

### Patient Profile — `/api/patient`

| Method | Endpoint | Access | Description |
|--------|----------|--------|--------------|
| GET | `/profile/:userId` | Public | Get patient profile |
| PATCH | `/profile/:userId` | Public | Update patient profile |

### Specialists — `/api/specialists`

| Method | Endpoint | Access | Description |
|--------|----------|--------|--------------|
| GET | `/` | Public | List all specialists |
| GET | `/specialization/:name` | Public | Filter by specialization |
| GET | `/:id` | Public | Get specialist by ID |
| GET | `/me` | Specialist | Get own specialist profile |
| PUT | `/profile` | Specialist | Update profile |
| PUT | `/availability` | Specialist | Update availability slots |
| PUT | `/fees` | Specialist | Update consultation fees |
| POST | `/me/certificates` | Specialist | Upload a certificate |

### Appointments — `/api/appointments`

| Method | Endpoint | Access | Description |
|--------|----------|--------|--------------|
| GET | `/available-slots/:specialistId` | Public | Get open slots for a specialist |
| POST | `/` | Patient | Book an appointment |
| GET | `/my` | Patient | List own appointments |
| GET | `/specialist` | Specialist | List own appointments |
| GET | `/:id` | Patient / Specialist | Get an appointment by id |
| PATCH | `/:id/reschedule` | Patient | Reschedule an appointment |
| PATCH | `/:id/status` | Specialist | Update appointment status |
| DELETE | `/day/:date` | Specialist | Cancel all appointments for a day |
| DELETE | `/:id` | Patient / Specialist | Cancel an appointment |

### Queue — `/api/queue`

| Method | Endpoint | Access | Description |
|--------|----------|--------|--------------|
| POST | `/join` | Patient | Join a specialist's queue |
| GET | `/my-position` | Patient | Get current queue position |
| DELETE | `/leave` | Patient | Leave the queue |
| GET | `/:specialistId` | Public | View specialist queue |
| PATCH | `/next` | Specialist | Advance to next patient |
| PATCH | `/status` | Specialist | Update queue status |

### Reviews — `/api/reviews`

| Method | Endpoint | Access | Description |
|--------|----------|--------|--------------|
| POST | `/` | Patient | Create a review |
| GET | `/specialist/:id` | Public | Get specialist reviews |
| PUT | `/:id` | Patient | Update a review |
| DELETE | `/:id` | Patient / Admin | Delete a review |

### AI Chatbot — `/api/ai`

| Method | Endpoint | Access | Description |
|--------|----------|--------|--------------|
| POST | `/chat` | Public (optional auth) | Forward a message to the Python chatbot service and return its reply |

### Admin — `/api/admin`

| Method | Endpoint | Access | Description |
|--------|----------|--------|--------------|
| GET | `/specialists/pending` | Admin | List pending specialists |
| GET | `/specialists` | Admin | List all specialists |
| PATCH | `/specialists/:id/approve` | Admin | Approve a specialist |
| PATCH | `/specialists/:id/reject` | Admin | Reject a specialist |

---

## Chatbot Service

The chatbot is a separate Flask microservice, not a route inside the Node backend. A request to `POST /chat` goes through this pipeline (`chatbot/chatbot_engine.py`):

1. Spell-check / gibberish detection on the input.
2. A sensitive-information guard.
3. A **write-action guard** (`chatbot/preprocessing/write_action_guard.py`) — the chatbot explicitly refuses any request to book, cancel, reschedule, or otherwise write to the database. It only reads and answers.
4. Intent routing (`chatbot/core/router.py`, `classifier.py`) into chit-chat, general knowledge, database-lookup, or medical-RAG paths.
5. For medical questions, retrieval-augmented generation over `chatbot/data/*.json` using sentence-transformer embeddings + FAISS, answered by a local Ollama model.
6. For "database" questions (e.g. "what's my next appointment?"), it queries MongoDB directly (`chatbot/database/`) using its own PyMongo client — a second, independent connection to the same database used by the backend, not proxied through it.

The Node backend only forwards chat requests to this service (`backend/src/features/ai/`); it does not implement any chatbot logic itself.

---

## User Roles

| Role | Description |
|------|-------------|
| **patient** | Can browse specialists, book/manage appointments, join queues, and write reviews |
| **specialist** | Doctors and nurses who manage profiles, availability, appointments, and patient queues |
| **admin** | Verifies specialist registrations and moderates the platform |

Authentication uses Bearer tokens. Include the JWT in the `Authorization` header:

```
Authorization: Bearer <token>
```

---

## Testing

### Backend

```bash
cd backend
npm test        # watch mode
npm run test:run
npm run lint
npm run typecheck
```

Tests use Vitest with an in-memory MongoDB instance and cover authentication, queue operations, reviews, and admin workflows.

### Frontend

```bash
cd frontend
npm test      # Vitest
npm run lint  # ESLint
npm run build # TypeScript compile + Vite production build
```

---

## Deployment

<!-- TODO: fill in once deployed -->

| Service | Live URL | Hosted on |
|---------|----------|-----------|
| Frontend | _TODO_ | Vercel |
| Backend API | _TODO_ | Railway |
| Chatbot | _TODO_ | Hugging Face |

Notes:
- The chatbot runs on Hugging Face, which is where Ollama + the FAISS/sentence-transformers retrieval stack actually run — not on the Node backend.
- In production, set `FRONTEND_URL` (backend), `CHATBOT_SERVICE_URL`/`INTERNAL_API_SECRET` (backend → chatbot), and the frontend's API base URL (`frontend/src/services/api.ts`) to point at the deployed backend/chatbot addresses instead of `localhost`.
- The local run instructions above still apply for development — deployment doesn't replace them.

---

## CI/CD

GitHub Actions runs three workflows:

| Workflow | Trigger | Steps |
|----------|---------|-------|
| `backend-ci.yml` | Push/PR touching `backend/**` | Typecheck → ESLint → Test → Build (Node 20) |
| `frontend-ci.yml` | Push/PR touching `frontend/**` | Typecheck → ESLint → Build (Node 20; tests currently disabled in the workflow) |
| `gitleaks.yml` | Every push to `main` and every PR | Secret scanning |

There is no CI workflow for the `chatbot/` service yet.

---

## License

This project is licensed under the [MIT License](LICENSE).

Copyright (c) 2026 Aya Abdellatif
