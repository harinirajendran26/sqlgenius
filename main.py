from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from database import get_schema, run_query
from schema_linker import link_schema, format_schema_for_prompt
from agent import run_agent
from fastapi.middleware.cors import CORSMiddleware

# ── Create the FastAPI app ──────────────────────────────────────────
# FastAPI() creates your web server instance
# The title and description show up in the auto-generated docs
app = FastAPI(
    title="SQLGenius API",
    description="Agentic Text-to-SQL system with self-correction",
    version="1.0.0"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# ── CORS Middleware ─────────────────────────────────────────────────
# CORS = Cross-Origin Resource Sharing
# 
# Your frontend runs on one "origin" (e.g. file:// or vercel.app)
# Your backend runs on another (localhost:8000)
# 
# By default browsers BLOCK requests between different origins for security.
# This middleware tells the browser: "it's okay, allow requests from anywhere"
# 
# In production you'd restrict this to your actual domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # Allow all origins (frontend can call us)
    allow_credentials=True,
    allow_methods=["*"],       # Allow GET, POST, etc
    allow_headers=["*"],       # Allow any headers
)


# ── Request/Response Models ─────────────────────────────────────────
# Pydantic models define the shape of data coming in and going out.
# FastAPI uses these to automatically validate requests.
# If the frontend sends wrong data, FastAPI returns a clear error.

class GenerateRequest(BaseModel):
    """What the frontend sends when asking for SQL generation"""
    question: str           # The natural language question
    dialect: str = "PostgreSQL"  # SQL dialect (default PostgreSQL)

class RunSQLRequest(BaseModel):
    """What the frontend sends when running a raw SQL query"""
    sql: str

class CustomGenerateRequest(BaseModel):
    """What the frontend sends for custom schema generation"""
    question: str           # The natural language question
    schema_text: str        # The pasted schema (CREATE TABLE or plain text)
    dialect: str = "PostgreSQL"


# ── Endpoints ───────────────────────────────────────────────────────
# An endpoint is a URL your frontend can call.
# @app.get("/url") = responds to GET requests
# @app.post("/url") = responds to POST requests (sending data)

@app.get("/")
def root():
    """
    Health check endpoint.
    Open http://localhost:8000 in browser to confirm server is running.
    """
    return {
        "status": "running",
        "message": "SQLGenius API is live",
        "docs": "http://localhost:8000/docs"
    }


@app.get("/schema")
def get_full_schema():
    """
    Returns the complete Northwind database schema.
    The frontend calls this to show the user what tables exist.
    
    URL: GET http://localhost:8000/schema
    """
    schema = get_schema()
    if not schema:
        raise HTTPException(status_code=500, detail="Could not fetch schema from database")
    
    # Count total columns across all tables
    total_columns = sum(len(cols) for cols in schema.values())
    
    return {
        "tables": list(schema.keys()),
        "table_count": len(schema),
        "column_count": total_columns,
        "schema": schema
    }


@app.post("/link-schema")
def link_schema_endpoint(request: GenerateRequest):
    """
    Given a question, returns which tables are relevant.
    This is the schema linking step — useful for debugging
    and for showing the user which tables were used.
    
    URL: POST http://localhost:8000/link-schema
    Body: {"question": "who are the top customers?"}
    """
    result = link_schema(request.question)
    schema_text = format_schema_for_prompt(result["linked_schema"])
    
    return {
        "selected_tables": result["selected_tables"],
        "linked_schema": result["linked_schema"],
        "schema_text": schema_text
    }


@app.post("/generate")
def generate_sql(request: GenerateRequest):
    """
    THE MAIN ENDPOINT — this is what the frontend calls for SQL generation.
    
    Runs the full agent pipeline:
    1. Schema linking
    2. SQL generation
    3. Validation against real PostgreSQL
    4. Self-correction if needed
    5. Plain English explanation
    
    URL: POST http://localhost:8000/generate
    Body: {"question": "who are the top 5 customers by revenue?", "dialect": "PostgreSQL"}
    
    Returns everything the frontend needs to display results.
    """
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    
    print(f"\n{'='*60}")
    print(f"📨 New request: {request.question}")
    print(f"{'='*60}")
    
    # Run the agent — this does all the heavy lifting
    result = run_agent(
        question=request.question,
        dialect=request.dialect
    )
    
    print(f"\n📤 Returning result: success={result['success']}, attempts={result['attempts']}")
    
    return result


@app.post("/run-sql")
def execute_sql(request: RunSQLRequest):
    """
    Runs a raw SQL query directly against the database.
    Useful for letting users tweak and re-run generated queries.
    
    URL: POST http://localhost:8000/run-sql
    Body: {"sql": "SELECT * FROM customers LIMIT 5;"}
    """
    if not request.sql.strip():
        raise HTTPException(status_code=400, detail="SQL cannot be empty")
    
    result = run_query(request.sql)
    return result


@app.get("/tables/{table_name}")
def get_table_sample(table_name: str, limit: int = 5):
    """
    Returns a sample of rows from any table.
    Great for letting users preview actual data.
    
    URL: GET http://localhost:8000/tables/customers?limit=5
    """
    # Validate table name to prevent SQL injection
    schema = get_schema()
    if table_name not in schema:
        raise HTTPException(
            status_code=404,
            detail=f"Table '{table_name}' not found. Available: {list(schema.keys())}"
        )
    
    result = run_query(f"SELECT * FROM {table_name} LIMIT {limit};")
    return result


# ── Start the server ────────────────────────────────────────────────
# This block only runs when you execute: python main.py
# uvicorn is the server that actually handles HTTP requests
# reload=True means it auto-restarts when you change code
if __name__ == "__main__":
    import uvicorn
    print("\n🚀 Starting SQLGenius API...")
    print("📖 Docs: http://localhost:8000/docs")
    print("🔌 API:  http://localhost:8000")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


@app.post("/generate-custom")
def generate_custom(request: CustomGenerateRequest):
    from groq import Groq
    import os, json
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    prompt = f"""You are a SQL expert. Given this schema and question, write perfect {request.dialect} SQL.

CRITICAL RULES:
- Use the EXACT table names from the schema — do not rename or pluralise them
- Use the EXACT column names from the schema
- Write standard {request.dialect} syntax only
- If dialect is MySQL, use MySQL syntax (no INTERVAL '30 days', use INTERVAL 30 DAY etc)

SCHEMA:
{request.schema_text}

QUESTION: {request.question}

Respond ONLY with valid JSON, no markdown:
{{"sql":"the full SQL query","explanation":[{{"clause":"SELECT","explanation":"..."}},{{"clause":"FROM","explanation":"..."}},{{"clause":"GROUP BY","explanation":"..."}}]}}"""
    try:
        res = client.chat.completions.create(
            model="llama-3.3-70b-versatile", temperature=0.1, max_tokens=800,
            messages=[
                {"role":"system","content":"You are a SQL expert. Always respond with valid JSON only, no markdown, no code fences."},
                {"role":"user","content":prompt}
            ]
        )
        text = res.choices[0].message.content.replace("```json","").replace("```","").strip()
        parsed = json.loads(text)
        return {"success":True,"sql":parsed.get("sql",""),"explanation":parsed.get("explanation",[]),"attempts":1,"error":None,"selected_tables":[],"rows":[],"columns":[],"row_count":0}
    except Exception as e:
        return {"success":False,"sql":"","explanation":[],"attempts":1,"error":str(e),"selected_tables":[],"rows":[],"columns":[],"row_count":0}
