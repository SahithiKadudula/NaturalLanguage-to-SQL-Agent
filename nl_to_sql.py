import sqlite3
import os
import sqlglot
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

DB_FILE = "Chinook_Sqlite.sqlite"  # change to your actual filename


def get_schema(db_file):
    """Pull table names and column info so Claude knows what it's querying."""
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]

    schema_text = ""
    for table in tables:
        cursor.execute(f"PRAGMA table_info({table});")
        columns = cursor.fetchall()
        col_list = ", ".join(f"{col[1]} ({col[2]})" for col in columns)
        schema_text += f"Table {table}: {col_list}\n"

    conn.close()
    return schema_text


def question_to_sql(question, schema_text):
    """Ask Claude to turn a plain-English question into a SQL query."""
    system_prompt = f"""You are a SQL expert. Given a database schema and a question,
write a single SQLite SELECT query that answers it.

Schema:
{schema_text}

Rules:
- Only write SELECT queries. Never write INSERT, UPDATE, DELETE, DROP, or ALTER.
- If the question explicitly asks to modify, delete, or update data, do NOT explain or
  offer an alternative. Instead respond with exactly: REFUSED: <one short reason>
- If the question is unrelated to this database and cannot be answered from this schema
  at all (e.g. general knowledge questions), do NOT explain. Instead respond with exactly:
  REFUSED: <one short reason>
- If the question is vague or subjective (e.g. "good customers", "popular tracks") but
  is still just asking to READ data from THIS database, do NOT refuse. Instead pick the
  most reasonable, common-sense interpretation (e.g. "good customers" = highest total
  spending) and write a SELECT query for it. Add a one-line SQL comment at the top of the
  query stating the assumption you made, like: -- Assuming "good customers" means highest total spending
- Otherwise, return ONLY the SQL query. No explanation outside SQL comments, no markdown
  formatting, no backticks.
- Use proper SQLite syntax.
- Never respond with plain prose explanation outside of the two REFUSED cases above. Every
  response must be either a REFUSED line or a SQL query.
"""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system=system_prompt,
        messages=[{"role": "user", "content": question}],
    )
    raw = response.content[0].text.strip()

    # Defensive cleanup: strip markdown code fences if Claude adds them anyway
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("sql"):
            raw = raw[3:].strip()

    return raw


class RefusedQuestionError(Exception):
    """Raised when Claude explicitly refuses to generate SQL for the question."""
    pass


class UnsafeSQLError(Exception):
    """Raised when generated SQL fails safety validation."""
    pass


def validate_sql(sql):
    """
    Guardrail: make sure the generated SQL is read-only before we ever execute it.
    Raises UnsafeSQLError if the query isn't a plain SELECT.
    """
    try:
        parsed = sqlglot.parse_one(sql, read="sqlite")
    except Exception as e:
        raise UnsafeSQLError(f"Could not parse generated SQL: {e}")

    # Must be a SELECT statement at the top level
    if parsed.key.lower() != "select":
        raise UnsafeSQLError(f"Blocked non-SELECT statement (type: {parsed.key}).")

    # Belt-and-suspenders: reject dangerous keywords even inside a parsed SELECT
    # (e.g. subqueries or vendor-specific extensions sqlglot might not flag)
    forbidden = ["drop", "delete", "update", "insert", "alter", "truncate", "attach", "pragma"]
    lowered = sql.lower()
    for word in forbidden:
        if word in lowered:
            raise UnsafeSQLError(f"Blocked query containing forbidden keyword: '{word}'.")

    return True


def run_query(sql, db_file, row_limit=200):
    """Execute the SQL (read-only) and return column names + rows, capped at row_limit."""
    validate_sql(sql)  # guardrail runs before anything touches the database

    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA query_only = ON;")  # extra DB-level safety net: refuses any write
    cursor = conn.cursor()
    cursor.execute(sql)
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchmany(row_limit)
    conn.close()
    return columns, rows


def explain_result(question, columns, rows):
    """Ask Claude to turn the raw result into a plain-English answer."""
    result_text = f"Columns: {columns}\nRows: {rows[:20]}"  # cap rows sent to keep it cheap

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Question: {question}\n\nQuery result:\n{result_text}\n\n"
                    "Answer the question in one or two plain sentences based on this result. "
                    "Do not use markdown formatting, headers, or bullet points \u2014 plain prose only."
                ),
            }
        ],
    )
    return response.content[0].text.strip()


if __name__ == "__main__":
    schema = get_schema(DB_FILE)

    question = "Delete all tracks by Iron Maiden"

    sql = question_to_sql(question, schema)
    print("Generated SQL:\n", sql, "\n")

    if sql.upper().startswith("REFUSED"):
        print("Claude declined to generate a query for this question:", sql)
    else:
        try:
            columns, rows = run_query(sql, DB_FILE)
            print("Raw result:\n", columns, rows, "\n")

            answer = explain_result(question, columns, rows)
            print("Answer:\n", answer)
        except UnsafeSQLError as e:
            print("Query blocked by safety guardrail:", e)