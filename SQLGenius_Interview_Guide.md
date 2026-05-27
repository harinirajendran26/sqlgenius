# SQLGenius — Complete Interview Preparation Guide

## What is this project?

SQLGenius is a full-stack AI system that converts plain English questions into SQL queries. It has two modes:

1. **Northwind Mode** — queries a real PostgreSQL database with 13 tables and 800+ rows of business data, validates the SQL, and self-corrects errors automatically
2. **Custom Schema Mode** — paste any table definition (LeetCode, interview problems, your own DB) and get instant SQL

---

## Full System Architecture

```
User types English question
           ↓
    Frontend (index.html)
    Vanilla JS · Hosted on Vercel
           ↓
    FastAPI Backend (main.py)
    Python · Runs on localhost:8000
           ↓
    ┌──────────────────────────────┐
    │         agent.py             │
    │   LangGraph-style agent      │
    │                              │
    │  1. Schema Linking           │
    │     schema_linker.py         │
    │     Finds relevant tables    │
    │                              │
    │  2. SQL Generation           │
    │     Groq API (Llama 3.3 70B) │
    │     Writes the SQL           │
    │                              │
    │  3. Validation               │
    │     database.py              │
    │     Runs SQL on PostgreSQL   │
    │                              │
    │  4. Self-Correction          │
    │     If fail → feed error     │
    │     back to LLM → retry      │
    │     Up to 3 attempts         │
    └──────────────────────────────┘
           ↓
    PostgreSQL (Northwind DB)
    13 tables · Real business data
           ↓
    Results returned to frontend
    Rows + SQL + Plain English explanation
```

---

## Tech Stack — Detailed Explanation

### 1. PostgreSQL
**What it is:** A powerful open-source relational database. The industry standard for production databases.

**How we use it:** Loaded the Northwind dataset — a classic Microsoft sample database with 13 real tables. When a user asks a question, the generated SQL is actually executed against this real database and returns real data rows.

**Key tables in Northwind:**
- `customers` — 91 real company records
- `orders` — 830 real purchase orders
- `order_details` — line items linking orders to products
- `products` — 77 products with prices and stock
- `employees` — 9 sales staff with hierarchy
- `categories`, `suppliers`, `shippers`, `territories`, `region`

**Interview talking points:**
- PostgreSQL uses ACID transactions (Atomicity, Consistency, Isolation, Durability)
- `information_schema.columns` is a built-in metadata table we query for schema introspection
- We use `psycopg2` as the Python driver — the most popular PostgreSQL adapter

---

### 2. FastAPI
**What it is:** A modern Python web framework for building APIs. Faster than Flask, auto-generates documentation, uses Python type hints.

**How we use it:** Our backend server with 5 endpoints:

| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/` | GET | Health check — is server running? |
| `/schema` | GET | Returns all 13 table names and columns from the real DB |
| `/generate` | POST | Main endpoint — runs the full agent pipeline |
| `/generate-custom` | POST | Custom schema SQL generation via Groq |
| `/tables/{name}` | GET | Returns sample rows from any table |

**Key concepts:**
- **Pydantic models** — define the shape of request/response data. FastAPI validates automatically
- **CORS middleware** — allows the frontend (different origin) to call the backend
- **uvicorn** — the ASGI server that runs FastAPI
- **`@app.post("/generate")`** — decorator that maps a URL to a Python function

**Interview talking points:**
- FastAPI is async-first, built on Starlette
- Swagger UI auto-generated at `/docs` — interactive API testing without Postman
- Type hints with Pydantic give automatic request validation and clear error messages

---

### 3. Groq API + Llama 3.3 70B
**What it is:** Groq is an AI inference provider that runs open-source models at extremely fast speeds using custom LPU (Language Processing Unit) hardware. Llama 3.3 is Meta's best open-source large language model.

**How we use it:** We send the database schema + user's question to Llama 3.3 and ask it to return structured JSON with the SQL and explanation.

**The prompt engineering:**
```python
system_prompt = f"""You are an expert {dialect} SQL query writer.
Write ONLY the SQL query, nothing else.
No markdown, no explanation, no code fences — just raw SQL.

DATABASE SCHEMA:
{schema_text}"""
```

**Why structured JSON output:** Instead of getting free-form text back, we instruct the model to return JSON. This makes parsing reliable and prevents markdown wrapping issues.

**Interview talking points:**
- Temperature = 0.1 means low randomness — we want consistent, correct SQL not creative SQL
- We use the OpenAI-compatible API format (`/openai/v1/chat/completions`) — Groq supports this
- Free tier: ~14,400 requests/day — sufficient for portfolio and demo projects
- Model choice: Llama 3.3 70B is strong at structured output and SQL tasks

---

### 4. Schema Linking
**What it is:** Before generating SQL, we identify which of the 13 Northwind tables are actually relevant to the question. This is a core NLP/IR technique used in production Text-to-SQL systems.

**Why it matters:** Sending all 13 tables to the LLM wastes tokens, confuses the model, and reduces accuracy. If someone asks "who are the top customers?", we only need `customers`, `orders`, `order_details` — not `territories` or `region`.

**How our schema linker works (`schema_linker.py`):**

```python
# Step 1: Score each table based on question keywords
scores = {}
for table in full_schema:
    score = 0
    if table.replace("_", " ") in question_lower:
        score += 10  # Direct name match
    for keyword in TABLE_KEYWORDS.get(table, []):
        if keyword in question_lower:
            score += 5  # Keyword match
    for col_info in columns:
        if col_info["column"] in question_lower:
            score += 3  # Column name match

# Step 2: Take top scoring tables
# Step 3: Add related tables for JOINs
# Step 4: Return focused schema
```

**Interview talking points:**
- Production systems use vector embeddings (semantic similarity) for schema linking — ours uses keyword matching which is simpler but effective
- Schema linking is one of the hardest unsolved problems in Text-to-SQL research
- Our approach scores tables on: direct name match (10pts), keyword match (5pts), column name match (3pts)
- Related table expansion ensures JOIN tables are always included

---

### 5. Self-Correction Agent (LangGraph-style)
**What it is:** An AI agent that doesn't just generate SQL once — it runs the SQL against the real database, catches errors, and retries with the error message as context. This is the "agentic" behaviour.

**The loop:**
```
Generate SQL
     ↓
Run against PostgreSQL
     ↓
Success? → Return results ✅
     ↓
Failure? → Add error to conversation
     ↓
"That SQL failed with: ERROR: column u.id does not exist
 Please fix it."
     ↓
Generate SQL again (attempt 2)
     ↓
Repeat up to 3 times
```

**Why conversation history matters:** We don't just retry — we add the previous attempt and its error to the LLM's conversation. The LLM now has context about what went wrong and can fix it intelligently.

```python
messages.append({"role": "assistant", "content": sql})  # what it tried
messages.append({"role": "user", "content": f"That failed: {error}. Fix it."})
```

**Interview talking points:**
- This is a simplified LangGraph pattern — a state machine with conditional edges
- Real LangGraph uses explicit `StateGraph`, `nodes`, and `edges` — our agent implements the same logic manually
- Self-correction is a key capability that separates agents from simple LLM calls
- The error message from PostgreSQL is highly informative — "column does not exist" tells the LLM exactly what to fix

---

### 6. Frontend (Vanilla JS SPA)
**What it is:** A single HTML file that acts as a multi-page application using a custom JavaScript router.

**Key frontend patterns:**

**Router:**
```javascript
function navigate(page) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById('page-' + page).classList.add('active');
}
```
This shows/hides pages by toggling a CSS class — no page reload, instant transitions.

**API calls:**
```javascript
const res = await fetch('http://localhost:8000/generate', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({question, dialect: 'PostgreSQL'})
});
const data = await res.json();
```

**Syntax highlighting:** A custom regex function that wraps SQL keywords in `<span>` tags with colour CSS classes — no library needed.

**Interview talking points:**
- `fetch()` is the modern browser API for HTTP requests — replaces old XMLHttpRequest
- `async/await` makes asynchronous code read like synchronous code
- CSS custom properties (`--cr`, `--sa`) allow consistent theming across the app
- Canvas particle system: 55 particles with position, velocity, and opacity animation — pure `requestAnimationFrame` loop

---

### 7. Deployment (Vercel + GitHub CI/CD)
**What it is:** Vercel is a hosting platform that automatically deploys your app every time you push to GitHub.

**Our pipeline:**
```
Write code locally
       ↓
git add . && git commit && git push
       ↓
GitHub receives the push
       ↓
Vercel detects the push automatically
       ↓
Deploys in ~30 seconds
       ↓
Live at sqlgenius-self.vercel.app
```

**Interview talking points:**
- CI/CD = Continuous Integration / Continuous Deployment
- Every `git push` triggers a new deployment automatically
- Vercel serves the static HTML file as a CDN — globally fast
- The Python backend runs locally (not deployed) — in production you'd deploy on Railway or Render

---

## The Dataset — Northwind

Northwind is a classic sample database originally created by Microsoft. It represents a fictional food import/export company.

**Key relationships:**
```
customers → orders → order_details → products
                  ↓                        ↓
              employees               categories
                  ↓                        ↓
          employee_territories         suppliers
                  ↓
              territories → region
```

**Sample questions the system can answer:**
- "Who are the top 5 customers by total revenue?"
- "Which products are running low on stock?"
- "Show monthly order count for 1997"
- "Which employees handled the most orders?"
- "What is the average order value by country?"
- "Which product categories generate the most revenue?"

---

## Custom Schema Mode

**What it is:** Allows users to paste any table definition and generate SQL without a real database.

**Use cases:**
- LeetCode SQL problems
- Interview preparation
- Generating SQL for your own database design
- Academic SQL exercises

**Formats supported:**
1. `CREATE TABLE` SQL syntax
2. Plain text column descriptions
3. LeetCode-style table markdown

**Example — LeetCode Teacher problem:**
```
Paste:
Table: Teacher
Columns: teacher_id (int), subject_id (int), dept_id (int)
Primary Key: (subject_id, dept_id)

Ask:
"Count the number of unique subjects each teacher teaches"

Get:
SELECT teacher_id, COUNT(DISTINCT subject_id) AS cnt
FROM Teacher
GROUP BY teacher_id;
```

**Dialect selector:** MySQL is selected by default because LeetCode uses MySQL.

---

## Interview Questions You Must Be Ready For

**Q: What is Text-to-SQL?**
A: Text-to-SQL is the task of converting natural language questions into SQL queries. It involves understanding both the user's intent and the database schema. It's an active research area because natural language is ambiguous while SQL is precise.

**Q: What is schema linking?**
A: Schema linking is the process of identifying which database tables and columns are relevant to a given question before generating SQL. Without it, you'd send the entire database schema to the LLM, wasting tokens and reducing accuracy.

**Q: What is an AI agent vs a simple LLM call?**
A: A simple LLM call is a single request-response. An AI agent can take actions, observe results, and decide what to do next in a loop. Our agent generates SQL, validates it by running it, and retries with error context — that loop is what makes it agentic.

**Q: Why Groq instead of OpenAI?**
A: Groq is significantly faster (sub-second latency) and free. It runs open-source models like Llama 3.3. For a demo/portfolio project, the free tier is sufficient. In production, you'd evaluate based on accuracy benchmarks.

**Q: What is FastAPI and why not Flask?**
A: FastAPI is async-first, uses Python type hints for automatic validation, and auto-generates Swagger documentation. Flask is synchronous by default and requires more manual setup for validation and docs. FastAPI is generally preferred for new API projects.

**Q: How does the self-correction loop work?**
A: We maintain a conversation history array. When SQL fails, we append the failed SQL and the PostgreSQL error message to the conversation, then ask the LLM to fix it. The LLM now has context about what went wrong. We do this up to 3 times.

**Q: What are the limitations of your system?**
A: Honest answer wins points:
- Schema linking uses keyword matching, not semantic embeddings — misses synonyms
- No query execution in custom mode — can't validate correctness
- Self-correction only handles syntax errors — semantic errors (wrong logic) are harder
- No support for DDL operations (CREATE, DROP) by design
- LLM can hallucinate column names not in the schema

**Q: What would you improve next?**
A: 
- Embedding-based schema linking using sentence transformers for semantic similarity
- LangGraph proper — explicit state graph with typed state
- Evaluation set — 100 hand-labelled question→SQL pairs with execution accuracy metric
- Deploy the backend on Railway or Render for full cloud deployment

---

## Key Numbers to Memorise for Interview

| Metric | Value |
|--------|-------|
| Tables in Northwind | 13 |
| Customer records | 91 |
| Order records | 830 |
| Product records | 77 |
| Max self-correction retries | 3 |
| LLM model | Llama 3.3 70B |
| Inference provider | Groq |
| SQL dialects supported | 4 (PostgreSQL, MySQL, SQLite, BigQuery) |
| Backend port | 8000 |
| Frontend hosting | Vercel |
| Language (backend) | Python 3.12 |

---

## File-by-File Explanation

| File | Purpose |
|------|---------|
| `index.html` | Entire frontend — router, UI, API calls, animations |
| `main.py` | FastAPI server — 5 endpoints, CORS, request validation |
| `agent.py` | Self-correction agent — generate → validate → retry loop |
| `schema_linker.py` | Identifies relevant tables from question keywords |
| `database.py` | PostgreSQL connection, `run_query()`, `get_schema()` |
| `.env` | Secret keys — Groq API key, DB credentials |
| `northwind.sql` | The dataset — 13 tables + data, loaded into PostgreSQL |

---

## One-Sentence Summary for Interview

> "SQLGenius is an agentic Text-to-SQL system that uses schema linking to identify relevant tables, generates SQL with Llama 3.3 via Groq, validates it against a real 13-table Northwind PostgreSQL database, and self-corrects using error feedback — deployed on Vercel with a FastAPI backend."

---

## Good luck tomorrow. You built all of this. Own it.
