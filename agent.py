import os
import json
from groq import Groq
from dotenv import load_dotenv
from database import run_query
from schema_linker import link_schema, format_schema_for_prompt

load_dotenv()

# Initialize the Groq client
# This is like creating a phone connection to the Groq AI service
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Maximum number of times the agent will try to fix a broken query
# before giving up. 3 is a good balance between thoroughness and speed.
MAX_RETRIES = 3

def call_llm(messages: list) -> str:
    """
    Sends a conversation to Groq and gets back a response.
    
    Parameters:
        messages: A list of message dicts like:
            [
                {"role": "system", "content": "You are a SQL expert..."},
                {"role": "user", "content": "Show top customers..."},
                {"role": "assistant", "content": "SELECT ..."},  # previous attempt
                {"role": "user", "content": "That failed with error: ..."}  # correction
            ]
    
    Returns:
        str: The LLM's response text
    """
    response = client.chat.completions.create(
        model="llama3-70b-8192",
        temperature=0.1,  # Low temperature = more consistent, less creative
        max_tokens=1000,
        messages=messages
    )
    return response.choices[0].message.content


def extract_sql(text: str) -> str:
    """
    Pulls the SQL query out of the LLM's response.
    
    The LLM sometimes wraps SQL in markdown code blocks like:
        ```sql
        SELECT * FROM customers;
        ```
    
    This function strips all that and returns just the raw SQL.
    """
    # Remove markdown code fences
    text = text.strip()
    
    if "```sql" in text:
        text = text.split("```sql")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    
    return text.strip()


def generate_explanation(sql: str, question: str, dialect: str = "PostgreSQL") -> list:
    """
    Takes a working SQL query and generates a plain English
    clause-by-clause explanation of what it does.
    
    Returns a list of {"clause": "SELECT", "explanation": "..."} dicts
    """
    prompt = f"""You have this SQL query that answers the question: "{question}"

SQL:
{sql}

Break down this SQL into its main clauses and explain each one in plain English.
A non-technical person should understand each explanation.

Respond ONLY with valid JSON — no markdown, no preamble:
[
  {{"clause": "SELECT", "explanation": "what this selects and why"}},
  {{"clause": "FROM", "explanation": "which table and why"}},
  {{"clause": "JOIN", "explanation": "how and why tables are joined"}},
  {{"clause": "WHERE", "explanation": "what filter is applied"}},
  {{"clause": "GROUP BY", "explanation": "how results are grouped"}},
  {{"clause": "ORDER BY", "explanation": "how results are sorted"}},
  {{"clause": "LIMIT", "explanation": "why results are limited"}}
]

Only include clauses that actually appear in the SQL above."""

    messages = [
        {"role": "system", "content": "You are a SQL educator. Always respond with valid JSON only."},
        {"role": "user", "content": prompt}
    ]

    try:
        response = call_llm(messages)
        clean = response.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except Exception:
        return [{"clause": "Query", "explanation": "SQL generated successfully."}]


def run_agent(question: str, dialect: str = "PostgreSQL") -> dict:
    """
    The main self-correction agent. This is the heart of the system.
    
    How it works:
    ─────────────────────────────────────────────
    Step 1: Schema Linking
        Find which tables are relevant to this question
    
    Step 2: Generate SQL
        Ask Groq to write SQL based on the linked schema
    
    Step 3: Validate
        Actually run the SQL against PostgreSQL
    
    Step 4: Check result
        ✅ Success → Return results + explanation
        ❌ Failure → Add error to conversation, go to Step 2
    
    Step 5: Repeat up to MAX_RETRIES times
    
    This loop is what makes it an "agent" rather than just an LLM call.
    ─────────────────────────────────────────────
    
    Parameters:
        question (str): Natural language question from the user
        dialect (str): SQL dialect (PostgreSQL, MySQL etc) — we use PostgreSQL

    Returns:
        dict with:
            - success (bool)
            - sql (str): The final SQL query
            - rows (list): Actual data from the database
            - columns (list): Column names
            - row_count (int): Number of rows
            - explanation (list): Plain English breakdown
            - attempts (int): How many tries it took
            - error (str): Error if completely failed
            - selected_tables (list): Which tables were used
    """

    # ── Step 1: Schema Linking ──────────────────────────────────────
    print(f"\n🔍 Schema linking for: '{question}'")
    link_result = link_schema(question)
    linked_schema = link_result["linked_schema"]
    selected_tables = link_result["selected_tables"]
    schema_text = format_schema_for_prompt(linked_schema)
    print(f"   Selected tables: {selected_tables}")

    # ── Step 2: Build the initial conversation ───────────────────────
    # This is the system prompt — it tells the LLM who it is and what to do
    system_prompt = f"""You are an expert {dialect} SQL query writer.
You will be given a database schema and a natural language question.
Write a {dialect} SQL query that correctly answers the question.

IMPORTANT RULES:
- Write ONLY the SQL query, nothing else
- No markdown, no explanation, no code fences — just raw SQL
- Use proper {dialect} syntax
- Always use table aliases for clarity (e.g. c for customers, o for orders)
- End the query with a semicolon

DATABASE SCHEMA:
{schema_text}"""

    # The conversation history — starts with just the user's question
    # As we retry, we add the previous attempt and its error to this list
    # This gives the LLM context to fix its mistakes
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": f"Write a SQL query to answer: {question}"}
    ]

    # Track attempts for the resume bullet point metric
    attempts = 0
    last_error = None
    last_sql = None

    # ── Steps 3-5: Generate → Validate → Retry loop ─────────────────
    for attempt in range(MAX_RETRIES):
        attempts += 1
        print(f"\n🤖 Attempt {attempts}/{MAX_RETRIES}: Generating SQL...")

        try:
            # Call the LLM
            raw_response = call_llm(messages)
            sql = extract_sql(raw_response)
            last_sql = sql
            print(f"   Generated SQL:\n   {sql[:100]}...")

        except Exception as e:
            last_error = f"LLM call failed: {str(e)}"
            print(f"   ❌ LLM error: {last_error}")
            break

        # ── Step 3: Validate — actually run the SQL ──────────────────
        print(f"   🔄 Validating against PostgreSQL...")
        result = run_query(sql)

        if result["success"]:
            # ✅ Query worked!
            print(f"   ✅ Success! {result['row_count']} rows returned in {attempts} attempt(s)")

            # Generate the plain English explanation
            explanation = generate_explanation(sql, question, dialect)

            return {
                "success":         True,
                "sql":             sql,
                "rows":            result["rows"],
                "columns":         result["columns"],
                "row_count":       result["row_count"],
                "explanation":     explanation,
                "attempts":        attempts,
                "error":           None,
                "selected_tables": selected_tables
            }

        else:
            # ❌ Query failed — add the error to the conversation
            # so the LLM knows what went wrong and can fix it
            last_error = result["error"]
            print(f"   ❌ SQL Error: {last_error}")

            if attempt < MAX_RETRIES - 1:
                print(f"   🔁 Retrying with error context...")

                # Add the failed attempt + error to conversation history
                # This is the self-correction mechanism
                messages.append({
                    "role": "assistant",
                    "content": sql  # what it tried
                })
                messages.append({
                    "role": "user",
                    "content": f"""That SQL query failed with this error:
ERROR: {last_error}

Please fix the SQL query. Common issues to check:
- Column names must match the schema exactly
- Table names must match the schema exactly  
- JOIN conditions must reference correct foreign keys
- Aggregate functions need GROUP BY
- Write ONLY the corrected SQL, nothing else."""
                })

    # ── All retries exhausted ────────────────────────────────────────
    print(f"\n💀 All {MAX_RETRIES} attempts failed. Last error: {last_error}")

    return {
        "success":         False,
        "sql":             last_sql or "",
        "rows":            [],
        "columns":         [],
        "row_count":       0,
        "explanation":     [],
        "attempts":        attempts,
        "error":           last_error,
        "selected_tables": selected_tables
    }