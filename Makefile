# Variables
VENV = venv
PYTHON = $(VENV)/bin/python
PIP = $(VENV)/bin/pip

.PHONY: all venv-setup install dev-frontend dev-backend lint test-backend clean

# Default target
all: install

# 1. Create the virtual environment if it doesn't exist
venv-setup:
	test -d $(VENV) || python3 -m venv $(VENV)
	$(PIP) install --upgrade pip

# 2. Combined Install (Frontend + Backend)
install: venv-setup
	@echo "Installing Frontend dependencies..."
	cd frontend && npm install
	@echo "Installing Backend dependencies..."
	$(PIP) install -r backend/requirements.txt

# 3. Development Commands
dev-frontend:
	cd frontend && npm run dev

dev-backend:
	cd backend && ../$(PYTHON) -m uvicorn app.main:app --reload --port 8000

# 4. Quality Control
lint:
	cd frontend && npm run lint
	$(VENV)/bin/ruff check backend/

test-backend:
	$(VENV)/bin/pytest backend/

# 5. Clean up
clean:
	rm -rf $(VENV)
	rm -rf frontend/node_modules
	find . -type d -name "__pycache__" -exec rm -rf {} +