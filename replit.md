# Ovidio Bot - WhatsApp Business Integration

## Overview

Ovidio Bot is a Flask-based WhatsApp chatbot designed for a security supplies business (Insumos de Seguridad Rosario). The bot integrates with Cianbox (an inventory/CRM system) to provide customers with product information, account balances, payment history, and automated PDF quote generation via WhatsApp.

Key capabilities:
- Customer lookup by phone number
- Product search via API and web scraping
- Account balance and payment history queries
- Automated PDF quote generation with expiration tracking
- OpenAI-powered conversational responses
- MongoDB for conversation and quote persistence

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Backend Framework
- **Flask** serves as the web framework for handling WhatsApp webhook requests
- Single-file architecture (`main.py`) contains all route handlers and business logic
- Gunicorn recommended for production deployment

### External Service Integrations

**Cianbox Integration (Dual Approach)**
- Primary: REST API integration (`services/cianbox_service.py`) with OAuth token management
- Fallback: Web scraping (`services/cianbox_scraper.py`) using session cookies and BeautifulSoup
- Handles customer data, products, balances, and payment history
- Token refresh mechanism with in-memory storage

**AI Processing**
- OpenAI API for natural language understanding and response generation
- Used to interpret customer queries and generate conversational responses

**PDF Generation**
- ReportLab library for creating professional A4 quotes/budgets
- Stored in `/tmp/presupuestos` with 15-day expiration policy
- UUID-based file naming for unique quote identification

### Data Storage
- **MongoDB** for persistent storage (conversations, quotes, customer interactions)
- Connection configured via environment variables
- In-memory token/session caching for Cianbox authentication

### File Structure
```
/
├── main.py                      # Main Flask application
├── requirements.txt             # Python dependencies
├── services/
│   ├── cianbox_service.py      # Cianbox REST API integration
│   └── cianbox_scraper.py      # Cianbox web scraping fallback
└── /tmp/presupuestos/          # Generated PDF quotes (ephemeral)
```

### Design Patterns
- **Graceful Degradation**: Services wrapped in try/except with availability flags (`CIANBOX_DISPONIBLE`, `SCRAPER_DISPONIBLE`)
- **Token Management**: In-memory token storage with expiration tracking for API authentication
- **Session Management**: Cookie-based session persistence for web scraping

## External Dependencies

### APIs & Services
| Service | Purpose | Auth Method |
|---------|---------|-------------|
| Cianbox API | Customer/product data | OAuth tokens (user/pass) |
| Cianbox Web Panel | Product scraping fallback | Session cookies |
| OpenAI | Conversational AI | API key |
| MongoDB | Data persistence | Connection string |

### Environment Variables Required
- `OPENAI_API_KEY` - OpenAI API authentication
- `CIANBOX_USER` - Cianbox panel username
- `CIANBOX_PASS` - Cianbox panel password
- MongoDB connection (likely `MONGO_URI` or similar)

### Key Python Packages
- `flask` - Web framework
- `pymongo` - MongoDB driver
- `openai` - AI integration
- `requests` - HTTP client for external APIs
- `reportlab` - PDF generation
- `beautifulsoup4` - HTML parsing for scraper
- `gunicorn` - Production WSGI server