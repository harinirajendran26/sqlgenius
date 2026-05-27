import psycopg2
import psycopg2.extras
import os
from dotenv import load_dotenv

# load_dotenv() reads your .env file and makes all the values
# available as environment variables in this Python session
load_dotenv()

def get_connection():
    """
    Creates and returns a connection to the PostgreSQL database.
    Think of this like opening a phone call to PostgreSQL.
    We call this every time we need to run a query.
    """
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )

def run_query(sql: str):
    """
    Runs a SQL query against the Northwind database and returns results.

    Parameters:
        sql (str): The SQL query string to execute

    Returns:
        dict with keys:
            - success (bool): Did the query run without errors?
            - rows (list): The actual data rows returned
            - columns (list): The column names
            - error (str): Error message if it failed, else None
            - row_count (int): How many rows came back
    """
    conn = None
    try:
        # Open the connection
        conn = get_connection()

        # A cursor is like a pointer — it's what actually executes queries
        # RealDictCursor means rows come back as dictionaries
        # e.g. {"customer_id": "ALFKI", "company_name": "Alfreds..."} 
        # instead of just ("ALFKI", "Alfreds...")
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Execute the SQL
        cursor.execute(sql)

        # Fetch all rows
        rows = cursor.fetchall()

        # Convert each row from RealDictRow to a plain dict
        rows = [dict(row) for row in rows]

        # Get column names from cursor description
        columns = [desc[0] for desc in cursor.description] if cursor.description else []

        return {
            "success": True,
            "rows": rows,
            "columns": columns,
            "error": None,
            "row_count": len(rows)
        }

    except Exception as e:
        # If anything goes wrong (bad SQL, missing table etc)
        # we catch the error and return it cleanly
        # This error message goes to our self-correction agent
        return {
            "success": False,
            "rows": [],
            "columns": [],
            "error": str(e),
            "row_count": 0
        }

    finally:
        # Always close the connection whether query succeeded or failed
        # Like hanging up the phone after a call
        if conn:
            conn.close()

def get_schema():
    """
    Reads the actual table and column structure directly from PostgreSQL.
    This is called 'schema introspection' — we ask the database to 
    describe itself to us, rather than hardcoding the schema.

    Returns:
        dict: {table_name: [{"column": name, "type": datatype}, ...]}
    
    Example return value:
    {
        "customers": [
            {"column": "customer_id", "type": "character"},
            {"column": "company_name", "type": "character varying"},
            ...
        ],
        "orders": [...],
        ...
    }
    """
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # information_schema is a built-in PostgreSQL schema that 
        # contains metadata about all your tables and columns
        # We query it to get every column in every table
        cursor.execute("""
            SELECT 
                table_name,
                column_name,
                data_type
            FROM 
                information_schema.columns
            WHERE 
                table_schema = 'public'
            ORDER BY 
                table_name, ordinal_position
        """)

        rows = cursor.fetchall()

        # Group columns by table name
        schema = {}
        for row in rows:
            table = row["table_name"]
            if table not in schema:
                schema[table] = []
            schema[table].append({
                "column": row["column_name"],
                "type": row["data_type"]
            })

        return schema

    except Exception as e:
        print(f"Error fetching schema: {e}")
        return {}

    finally:
        if conn:
            conn.close()