from database import get_schema

# These are the known relationships between tables in Northwind.
# When we select a table, we also pull in its related tables
# because a JOIN will almost certainly be needed.
# Format: "table" -> ["related_table_1", "related_table_2"]
TABLE_RELATIONSHIPS = {
    "orders":             ["customers", "employees", "shippers", "order_details"],
    "order_details":      ["orders", "products"],
    "products":           ["categories", "suppliers", "order_details"],
    "customers":          ["orders"],
    "employees":          ["orders", "employee_territories"],
    "employee_territories": ["employees", "territories"],
    "territories":        ["employee_territories", "region"],
    "categories":         ["products"],
    "suppliers":          ["products"],
    "shippers":           ["orders"],
    "region":             ["territories"],
    "customer_customer_demo": ["customers", "customer_demographics"],
    "customer_demographics":  ["customer_customer_demo"],
}

# Keywords that strongly suggest a particular table is needed.
# This helps when the user doesn't mention the table name directly.
# e.g. "show me revenue" → orders + order_details are needed
TABLE_KEYWORDS = {
    "customers":     ["customer", "customers", "client", "company", "buyer", "contact"],
    "orders":        ["order", "orders", "purchase", "sale", "sold", "revenue", "transaction"],
    "order_details": ["detail", "details", "line item", "quantity", "discount", "item"],
    "products":      ["product", "products", "item", "goods", "stock", "inventory", "price"],
    "employees":     ["employee", "employees", "staff", "worker", "sales rep", "representative"],
    "categories":    ["category", "categories", "type", "group", "kind"],
    "suppliers":     ["supplier", "suppliers", "vendor", "vendors", "source"],
    "shippers":      ["shipper", "shippers", "shipping", "ship", "freight", "carrier"],
    "territories":   ["territory", "territories", "region", "area", "zone"],
    "region":        ["region", "regions", "area", "zone"],
}

def link_schema(question: str, max_tables: int = 5) -> dict:
    """
    Given a natural language question, finds the most relevant tables
    and returns a focused schema — just the tables needed, not all 13.

    How it works:
    1. Get the full schema from the database
    2. Score each table based on keyword matches in the question
    3. Take the top scoring tables
    4. Add their related tables (for JOINs)
    5. Return just those tables' schemas

    Parameters:
        question (str): The user's natural language question
        max_tables (int): Maximum number of tables to include

    Returns:
        dict with:
            - linked_schema: {table_name: [columns]} for relevant tables only
            - selected_tables: list of table names chosen
            - full_schema: the complete schema (all tables)
    
    Example:
        question = "Who are the top 5 customers by total orders?"
        → selected_tables = ["customers", "orders"]
        → linked_schema = {"customers": [...], "orders": [...]}
    """

    # Step 1: Get the full schema from PostgreSQL
    full_schema = get_schema()
    question_lower = question.lower()

    # Step 2: Score every table
    scores = {}
    for table in full_schema:
        score = 0

        # Does the question directly mention the table name?
        if table.replace("_", " ") in question_lower:
            score += 10  # Strong signal
        if table in question_lower:
            score += 8

        # Does the question contain keywords associated with this table?
        keywords = TABLE_KEYWORDS.get(table, [])
        for keyword in keywords:
            if keyword in question_lower:
                score += 5

        # Does the question mention any column names from this table?
        columns = full_schema.get(table, [])
        for col_info in columns:
            col_name = col_info["column"].replace("_", " ")
            if col_name in question_lower:
                score += 3
            if col_info["column"] in question_lower:
                score += 3

        scores[table] = score

    # Step 3: Sort tables by score, take top ones with score > 0
    sorted_tables = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    
    # Always include tables with score > 0, up to max_tables
    selected = [t for t, s in sorted_tables if s > 0][:max_tables]

    # Step 4: If nothing matched (very vague question), 
    # fall back to the most commonly used tables
    if not selected:
        selected = ["customers", "orders", "order_details", "products"]

    # Step 5: Add related tables for likely JOINs
    # e.g. if "orders" is selected, also include "customers" and "order_details"
    related = set(selected)
    for table in selected:
        for rel_table in TABLE_RELATIONSHIPS.get(table, []):
            related.add(rel_table)
            if len(related) >= max_tables + 2:  # allow a couple extra for JOINs
                break

    final_tables = list(related)[:max_tables + 2]

    # Step 6: Build the focused schema — only the selected tables
    linked_schema = {
        table: full_schema[table]
        for table in final_tables
        if table in full_schema
    }

    return {
        "linked_schema": linked_schema,
        "selected_tables": final_tables,
        "full_schema": full_schema
    }


def format_schema_for_prompt(linked_schema: dict) -> str:
    """
    Converts the schema dictionary into a clean text format
    that the LLM can understand in its prompt.

    Example output:
        Table: customers
          - customer_id (character)
          - company_name (character varying)
          - contact_name (character varying)
          ...
        
        Table: orders
          - order_id (integer)
          - customer_id (character)
          ...
    """
    lines = []
    for table_name, columns in linked_schema.items():
        lines.append(f"Table: {table_name}")
        for col in columns:
            lines.append(f"  - {col['column']} ({col['type']})")
        lines.append("")  # blank line between tables

    return "\n".join(lines)