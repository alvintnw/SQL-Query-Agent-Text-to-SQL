"""Interactive read-only Text-to-SQL agent for the sample SQLite database."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_genai.chat_models import GoogleAPIError


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "sales.db"
MAX_ATTEMPTS = 3
LLM_RETRY_ATTEMPTS = 3
TRANSIENT_GOOGLE_ERRORS = {429, 500, 502, 503, 504}


def get_schema(connection: sqlite3.Connection) -> str:
    """Return tables, columns, types, primary keys, and foreign keys."""
    tables = connection.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()

    schema: dict[str, Any] = {}
    for (table_name,) in tables:
        columns = connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        foreign_keys = connection.execute(
            f'PRAGMA foreign_key_list("{table_name}")'
        ).fetchall()
        schema[table_name] = {
            "columns": [
                {
                    "name": column[1],
                    "type": column[2],
                    "primary_key": bool(column[5]),
                    "nullable": not bool(column[3]),
                }
                for column in columns
            ],
            "foreign_keys": [
                {"column": key[3], "references_table": key[2], "references_column": key[4]}
                for key in foreign_keys
            ],
        }
    return json.dumps(schema, indent=2)


def response_text(response: Any) -> str:
    """Normalize LangChain's string or block-list response content."""
    content = response.content
    if isinstance(content, str):
        return content
    return "\n".join(
        block.get("text", "") if isinstance(block, dict) else str(block)
        for block in content
    )


def extract_sql(text: str) -> str:
    """Extract one SQL statement and reject anything except a SELECT."""
    match = re.search(r"```(?:sql)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    sql = (match.group(1) if match else text).strip()
    sql = sql.rstrip(";").strip()
    if ";" in sql:
        raise ValueError("Hanya satu perintah SQL yang diperbolehkan.")
    if not re.match(r"^SELECT\b", sql, flags=re.IGNORECASE):
        raise ValueError("Kueri ditolak: hanya perintah SELECT yang diperbolehkan.")
    return sql


def format_table(columns: list[str], rows: list[tuple[Any, ...]]) -> str:
    """Render a compact table without adding another runtime dependency."""
    if not columns:
        return "(Tidak ada kolom hasil)"
    values = [["NULL" if value is None else str(value) for value in row] for row in rows]
    widths = [len(column) for column in columns]
    for row in values:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    def render(row: list[str]) -> str:
        return "| " + " | ".join(value.ljust(widths[i]) for i, value in enumerate(row)) + " |"

    separator = "|-" + "-|-".join("-" * width for width in widths) + "-|"
    output = [render(columns), separator]
    output.extend(render(row) for row in values)
    return "\n".join(output)


def build_agent() -> ChatGoogleGenerativeAI:
    load_dotenv(BASE_DIR / ".env")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY belum tersedia. Isi file .env terlebih dahulu.")
    return ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
        google_api_key=api_key,
        temperature=0,
    )


def invoke_llm(llm: ChatGoogleGenerativeAI, prompt: str) -> Any:
    """Retry temporary Gemini capacity and rate-limit errors."""
    for attempt in range(LLM_RETRY_ATTEMPTS):
        try:
            return llm.invoke(prompt)
        except GoogleAPIError as error:
            if error.code not in TRANSIENT_GOOGLE_ERRORS or attempt == LLM_RETRY_ATTEMPTS - 1:
                raise
            wait_seconds = 2**attempt
            print(
                f"[Status]: Gemini sedang sibuk (HTTP {error.code}). "
                f"Mencoba lagi dalam {wait_seconds} detik..."
            )
            time.sleep(wait_seconds)
    raise RuntimeError("Pemanggilan Gemini gagal setelah beberapa percobaan.")


def generate_sql(
    llm: ChatGoogleGenerativeAI,
    question: str,
    schema: str,
    previous_sql: str = "",
    error: str = "",
) -> str:
    repair_context = (
        f"SQL sebelumnya: {previous_sql}\nKesalahan SQLite: {error}\n"
        "Perbaiki SQL tersebut dan hasilkan SQL baru."
        if error
        else ""
    )
    prompt = f"""
Anda adalah generator SQL SQLite yang aman dan akurat.
Pertanyaan pengguna: {question}
Skema database:
{schema}
{repair_context}
Aturan wajib:
- Hasilkan tepat satu perintah SELECT yang valid untuk SQLite.
- Gunakan hanya tabel dan kolom yang ada pada skema.
- Jangan gunakan INSERT, UPDATE, DELETE, DROP, ALTER, PRAGMA, atau komentar.
- Jawab hanya dengan SQL, tanpa markdown dan tanpa penjelasan.
"""
    return extract_sql(response_text(invoke_llm(llm, prompt)))


def summarize_result(
    llm: ChatGoogleGenerativeAI,
    question: str,
    sql: str,
    columns: list[str],
    rows: list[tuple[Any, ...]],
) -> str:
    result_json = [dict(zip(columns, row)) for row in rows]
    prompt = f"""
Ringkas hasil query untuk tim bisnis dalam Bahasa Indonesia yang jelas dan singkat.
Pertanyaan: {question}
SQL: {sql}
Hasil JSON: {json.dumps(result_json, ensure_ascii=False, default=str)}
Sebutkan temuan utama dan angka penting jika relevan. Jangan mengarang data.
"""
    return response_text(invoke_llm(llm, prompt)).strip()


def answer_question(
    llm: ChatGoogleGenerativeAI,
    connection: sqlite3.Connection,
    question: str,
) -> None:
    schema = get_schema(connection)
    sql = ""
    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            sql = generate_sql(llm, question, schema, sql, last_error)
            print(f"[SQL Generated]: {sql}")
            cursor = connection.execute(sql)
            rows = cursor.fetchmany(100)
            columns = [description[0] for description in cursor.description or []]
            print("[Status]: Berhasil")
            print("[Final Answer]: " + summarize_result(llm, question, sql, columns, rows))
            print("\n[Tabel Hasil]:\n" + format_table(columns, rows))
            return
        except (sqlite3.Error, ValueError) as exc:
            last_error = str(exc)
            if attempt < MAX_ATTEMPTS:
                print(f"[Status]: Mencoba Perbaikan ({attempt}/{MAX_ATTEMPTS - 1}) - {last_error}")
            else:
                print(f"[Status]: Gagal setelah {MAX_ATTEMPTS} percobaan - {last_error}")
        except GoogleAPIError as exc:
            print(
                f"[Status]: Gemini tidak tersedia (HTTP {exc.code}). "
                "Coba lagi beberapa saat lagi atau gunakan model lain di GEMINI_MODEL."
            )
            return


def main() -> None:
    if not DATABASE_PATH.exists():
        print("sales.db belum ada. Jalankan: python init_db.py")
        return

    try:
        llm = build_agent()
    except RuntimeError as error:
        print(f"[Error]: {error}")
        return

    connection = sqlite3.connect(f"file:{DATABASE_PATH}?mode=ro", uri=True)
    print("SQL Query Agent siap. Ketik 'exit' atau 'quit' untuk keluar.")
    try:
        while True:
            question = input("\nPertanyaan> ").strip()
            if question.lower() in {"exit", "quit"}:
                print("Sampai jumpa.")
                break
            if question:
                answer_question(llm, connection, question)
    except KeyboardInterrupt:
        print("\nSampai jumpa.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()