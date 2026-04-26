# Shurly - Modern URL Shortener

A modern, full-stack URL shortener with analytics and campaign management, built with FastAPI and Astro.

## Features

- **URL Shortening**: Create short, shareable links with auto-generated or custom codes
- **User Authentication**: Secure JWT-based authentication with session management
- **Campaign Management**: Create personalized URL campaigns with CSV imports
- **Analytics Dashboard**: Track clicks, geographic distribution, and user engagement
- **User Agent Detection**: Automatic browser, OS, and device type detection
- **Visitor Tracking**: Monitor URL performance with detailed visit logs

## Tech Stack

### Backend
- **FastAPI** - Modern, fast web framework for building APIs
- **Pydantic v2** - Data validation using Python type annotations
- **SQLAlchemy 2.0** - SQL toolkit and ORM
- **PostgreSQL** - Robust relational database with psycopg2-binary driver
- **python-jose** - JWT token generation and validation
- **passlib** - Secure password hashing with bcrypt
- **uv** - Fast Python package installer and resolver
- **ruff** - Fast Python linter and formatter
- **pytest** - Testing framework with 104+ passing tests

### Frontend
- **Astro** - Modern static site builder with server-side rendering
- **Tailwind CSS** - Utility-first CSS framework
- **TypeScript** - Type-safe JavaScript
- **Vite** - Next generation frontend tooling (bundled with Astro)

## Prerequisites

- Python 3.10 or higher
- Node.js 18 or higher
- PostgreSQL database (14 or higher recommended)
- [uv](https://github.com/astral-sh/uv) (Python package installer)

## Getting Started

### Quick Start with Docker (Recommended)

The fastest way to test Shurly locally:

```bash
# Start the entire stack (PostgreSQL + FastAPI)
docker compose up -d

# View logs
docker compose logs -f api

# Stop when done
docker compose down
```

- **API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Frontend**: Start separately (see Frontend Setup below)

For comprehensive testing instructions, see **[TESTING.md](TESTING.md)**.

### Manual Setup

### 1. Clone the Repository

```bash
git clone <repository-url>
cd shurly
```

### 2. Database Setup

Create a PostgreSQL database:

```bash
psql -U postgres
CREATE DATABASE shurly;
\q
```

### 3. Backend Setup

#### Install Dependencies

```bash
uv sync
```

This will create a virtual environment and install all Python dependencies.

#### Configure Environment

Create a `.env` file in the root directory:

```bash
cp .env.example .env
```

Edit `.env` with your database credentials and JWT secret:

```env
# Database Configuration (PostgreSQL)
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=your_password_here
DB_NAME=shurly

# JWT Configuration
JWT_SECRET_KEY=your-super-secret-jwt-key-change-this-in-production
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=10080

# API Configuration
API_TITLE=Shurly API
API_VERSION=0.1.0
API_DESCRIPTION=A modern URL shortener API

# CORS Configuration (comma-separated list)
CORS_ORIGINS=http://localhost:4323,http://localhost:3000
```

#### Initialize the Database

The database tables will be created automatically when you start the application. SQLAlchemy will create all necessary tables based on the models.

#### Run the Backend

```bash
uv run uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`

- API Documentation: `http://localhost:8000/docs`
- Alternative API Docs: `http://localhost:8000/redoc`

### 4. Frontend Setup

#### Install Dependencies

```bash
cd frontend
npm install
```

#### Run the Development Server

```bash
npm run dev
```

The frontend will be available at `http://localhost:4323`

## Development

### Backend Development

#### Format Code with Ruff

```bash
uv run ruff format .
```

#### Check for Linting Issues

```bash
uv run ruff check .
```

#### Auto-fix Linting Issues

```bash
uv run ruff check --fix .
```

#### Run Tests

```bash
uv run pytest
```

#### Run Tests with Coverage

```bash
uv run pytest --cov=server --cov-report=html
```

#### Run Specific Test Markers

```bash
# Unit tests only
uv run pytest -m unit

# Integration tests only
uv run pytest -m integration
```

### Frontend Development

#### Build for Production

```bash
cd frontend
npm run build
```

#### Preview Production Build

```bash
npm run preview
```

#### Type Check

```bash
npm run astro check
```

## Project Structure

```
shurly/
├── server/                    # Backend application
│   ├── app/                   # API routes and endpoints
│   │   ├── __init__.py       # Router aggregation
│   │   ├── auth.py           # Authentication endpoints (login, register)
│   │   ├── urls.py           # URL shortening endpoints (CRUD)
│   │   ├── campaigns.py      # Campaign management endpoints
│   │   ├── analytics.py      # Analytics and statistics endpoints
│   │   └── statistics.py     # Legacy statistics (deprecated)
│   ├── core/                  # Core functionality
│   │   ├── models/           # SQLAlchemy models
│   │   │   ├── user.py      # User model
│   │   │   ├── url.py       # URL model (standard, custom, campaign)
│   │   │   ├── visitor.py   # Visitor tracking model
│   │   │   └── campaign.py  # Campaign model
│   │   ├── __init__.py      # Database session management
│   │   ├── config.py        # Application configuration
│   │   └── auth.py          # Authentication utilities (JWT, passwords)
│   ├── schemas/              # Pydantic schemas
│   │   ├── auth.py          # Auth request/response schemas
│   │   ├── urls.py          # URL request/response schemas
│   │   ├── campaigns.py     # Campaign schemas
│   │   └── analytics.py     # Analytics response schemas
│   └── utils/                # Utility functions
│       ├── url.py           # URL validation and generation
│       └── user_agent.py    # User agent parsing utilities
├── frontend/                  # Astro frontend application
│   ├── src/
│   │   ├── layouts/          # Astro layouts
│   │   │   └── Layout.astro # Main layout
│   │   ├── pages/            # Astro pages (routes)
│   │   │   ├── index.astro  # Landing page
│   │   │   ├── login.astro  # Login page
│   │   │   ├── register.astro # Registration page
│   │   │   └── dashboard/   # Protected dashboard pages
│   │   │       ├── index.astro        # Dashboard home
│   │   │       ├── campaigns/         # Campaign management
│   │   │       └── urls/              # URL management
│   │   ├── components/       # Reusable components
│   │   │   ├── ProtectedRoute.astro # Auth guard
│   │   │   ├── Navbar.astro         # Navigation bar
│   │   │   └── URLCard.astro        # URL display card
│   │   └── utils/           # Frontend utilities
│   │       ├── api.ts       # API client functions
│   │       ├── auth.ts      # Auth token management
│   │       └── types.ts     # TypeScript type definitions
│   ├── public/              # Static assets
│   └── astro.config.mjs     # Astro configuration
├── tests/                    # Test suite (104+ tests)
│   ├── conftest.py          # Pytest fixtures and configuration
│   ├── test_auth.py         # Authentication tests
│   ├── test_urls.py         # URL shortening tests
│   ├── test_campaigns.py    # Campaign tests
│   ├── test_analytics.py    # Analytics tests
│   └── test_user_agent.py   # User agent parsing tests
├── main.py                   # FastAPI application entry point
├── pyproject.toml            # Python project configuration
├── dockerfile                # Docker configuration
├── .env.example              # Environment variables template
└── README.md                 # This file
```

## API Endpoints

### Authentication
- `POST /api/v1/auth/register` - Register a new user
- `POST /api/v1/auth/login` - Login and receive JWT token
- `GET /api/v1/auth/me` - Get current user information

### URL Shortening
- `POST /api/v1/urls` - Create a new shortened URL (auto-generated code)
- `POST /api/v1/urls/custom` - Create a custom shortened URL
- `GET /api/v1/urls` - List all user's URLs
- `GET /api/v1/urls/{short_code}` - Get URL details
- `DELETE /api/v1/urls/{short_code}` - Delete a URL
- `GET /{short_code}` - Redirect to original URL (tracks visit)

### Campaigns
- `POST /api/v1/campaigns` - Create a new campaign
- `GET /api/v1/campaigns` - List all user's campaigns
- `GET /api/v1/campaigns/{campaign_id}` - Get campaign details
- `POST /api/v1/campaigns/{campaign_id}/upload` - Upload CSV to generate campaign URLs
- `DELETE /api/v1/campaigns/{campaign_id}` - Delete a campaign (cascades to URLs)

### Analytics
- `GET /api/v1/analytics/overview` - Dashboard overview statistics
- `GET /api/v1/analytics/urls/{short_code}/daily` - Daily stats for a URL (last 7 days)
- `GET /api/v1/analytics/urls/{short_code}/weekly` - Weekly stats for a URL (last 8 weeks)
- `GET /api/v1/analytics/urls/{short_code}/geo` - Geographic distribution of clicks
- `GET /api/v1/analytics/campaigns/{campaign_id}/summary` - Campaign summary with top performers
- `GET /api/v1/analytics/campaigns/{campaign_id}/users` - Detailed user statistics for a campaign

## URL Types

Shurly supports three types of URLs:

1. **Standard**: Auto-generated 6-character short codes
2. **Custom**: User-defined short codes (3-20 alphanumeric characters and hyphens)
3. **Campaign**: Generated from CSV imports with personalized user data

## Testing

### Automated Tests

The project includes a comprehensive test suite with 104+ tests:

- **Unit Tests**: User agent parsing, utility functions
- **Integration Tests**: API endpoints, database operations, authentication flow

Run the full test suite:
```bash
uv run pytest
```

Tests use an in-memory SQLite database for fast execution and isolation.

### Manual Testing

For comprehensive functional and UX testing before deployment, see the complete testing guide:

📋 **[TESTING.md](TESTING.md)** - Step-by-step instructions for:
- Local setup (Docker or manual)
- Functional testing checklist (all features)
- UX testing scenarios (user journeys)
- API testing with Swagger UI
- Edge cases and error handling
- Performance testing

The testing guide includes sample data, test templates, and success criteria to ensure the application is production-ready.

## Docker Support

Build and run with Docker:

```bash
docker build -t shurly .
docker run -p 8000:8000 shurly
```

Note: Update the Docker configuration with environment variables for production deployment.

## Security Features

- **Password Hashing**: bcrypt with automatic salt generation
- **JWT Tokens**: Secure token-based authentication
- **CORS Protection**: Configurable allowed origins
- **SQL Injection Protection**: SQLAlchemy ORM with parameterized queries
- **Authorization**: User-scoped resources (users can only access their own data)
- **Campaign URL Protection**: Campaign URLs must be deleted through campaign (cascade)

## Production Deployment

For production deployment:

1. Set a strong `JWT_SECRET_KEY` (use `openssl rand -hex 32`)
2. Configure proper CORS origins
3. Set up PostgreSQL with proper user permissions
4. Use a production WSGI server (uvicorn with workers)
5. Configure HTTPS/TLS
6. Set up database backups
7. Configure logging and monitoring

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Run tests to ensure everything passes (`uv run pytest`)
4. Format your code (`uv run ruff format .`)
5. Commit your changes (`git commit -m 'Add some amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## License

MIT
