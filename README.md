# Shurly - Modern URL Shortener

A modern, full-stack URL shortener built with FastAPI and Astro.

## Tech Stack

### Backend
- **FastAPI** - Modern, fast web framework for building APIs
- **Pydantic v2** - Data validation using Python type annotations
- **SQLAlchemy 2.0** - SQL toolkit and ORM
- **uv** - Fast Python package installer and resolver
- **ruff** - Fast Python linter and formatter
- **PyMySQL** - Pure Python MySQL driver

### Frontend
- **Astro** - Modern static site builder
- **Tailwind CSS** - Utility-first CSS framework
- **TypeScript** - Type-safe JavaScript
- **Vite** - Next generation frontend tooling (bundled with Astro)

## Prerequisites

- Python 3.10 or higher
- Node.js 18 or higher
- MySQL database
- [uv](https://github.com/astral-sh/uv) (Python package installer)

## Getting Started

### 1. Clone the Repository

```bash
git clone <repository-url>
cd shurly
```

### 2. Backend Setup

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

Edit `.env` with your database credentials:

```env
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=shurly
```

#### Run the Backend

```bash
uv run uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`

- API Documentation: `http://localhost:8000/docs`
- Alternative API Docs: `http://localhost:8000/redoc`

### 3. Frontend Setup

#### Install Dependencies

```bash
cd frontend
npm install
```

#### Run the Development Server

```bash
npm run dev
```

The frontend will be available at `http://localhost:4321`

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
├── server/                 # Backend application
│   ├── app/               # API routes and endpoints
│   │   ├── code.py       # CAPTCHA generation endpoints
│   │   └── statistics.py # Statistics endpoints
│   ├── core/             # Core functionality
│   │   ├── models/       # SQLAlchemy models
│   │   │   ├── url.py   # URL model
│   │   │   └── visitor.py # Visitor tracking model
│   │   ├── __init__.py  # Database session management
│   │   └── config.py    # Application configuration
│   └── utils/           # Utility functions
│       ├── code.py      # CAPTCHA generation utilities
│       └── statistics.py # Statistics utilities
├── frontend/            # Astro frontend application
│   ├── src/
│   │   ├── layouts/    # Astro layouts
│   │   ├── pages/      # Astro pages (routes)
│   │   └── components/ # Reusable components
│   ├── public/         # Static assets
│   └── astro.config.mjs # Astro configuration
├── main.py             # FastAPI application entry point
├── pyproject.toml      # Python project configuration
├── dockerfile          # Docker configuration
└── README.md           # This file
```

## API Endpoints

- `GET /code` - Generate CAPTCHA code
- `GET /stats` - Get URL statistics
- (More endpoints to be documented)

## Docker Support

Build and run with Docker:

```bash
docker build -t shurly .
docker run -p 8000:8000 shurly
```

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

MIT
