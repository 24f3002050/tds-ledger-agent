# Acme Appliances Ledger Agent

A Flask POST endpoint that answers ledger questions from the assignment's exported NDJSON data.

## API contract

- `GET /` — health check
- `POST /` — accepts `{"question":"..."}` and returns `{"answer": ...}`

Example:
```bash
curl -X POST https://YOUR-SERVICE.onrender.com/ \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"What was the total revenue in USD from the North region in March 2026?\"}"
```

## Run locally (Windows PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Then test:
```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/ -ContentType "application/json" -Body '{"question":"What was the total revenue in USD from the North region in March 2026?"}'
```

## Deploy to Render

1. Create a GitHub repository and upload `app.py`, `requirements.txt`, `render.yaml`, and `orders.ndjson`.
2. In Render, choose **New + → Web Service**, connect the repository, and deploy.
3. Render should use `pip install -r requirements.txt` and `gunicorn app:app`.
4. Copy the deployed HTTPS URL and submit it as the endpoint URL.

## Important

This is a first working baseline, not yet a guarantee for every possible phrasing. Test with the assignment's examples and revise the parser if the grader asks a metric or wording not currently covered. Keep the dataset private if your course rules or data policy require it.
