# src/modal_app/main.py
import sqlite3
import sqlite_vec
from modal import asgi_app
from .common import DB_PATH, VOLUME_DIR, app, fastapi_app, volume
from openai import OpenAI
from .common import DB_PATH, VOLUME_DIR, app, fastapi_app, get_db_conn, serialize, volume, TOOLS
import os

@app.function(
    volumes={VOLUME_DIR: volume},
)
def init_db():
    """Initialize the SQLite database with a simple table."""
    volume.reload()
    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    cursor = conn.cursor()
    # Create a simple table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS discord_messages (
            id TEXT PRIMARY KEY,
            channel_id TEXT NOT NULL,
            author_id TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL
        )
    """
    )
    cursor.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_discord_messages USING vec0(
          id TEXT PRIMARY KEY,
          embedding FLOAT[1536]
        );
        """
    )
    conn.commit()
    conn.close()
    volume.commit()

@app.function(
    volumes={VOLUME_DIR: volume},
    timeout=2000
)
@asgi_app()
def fastapi_entrypoint():
    # Initialize database on startup
    init_db.remote()
    return fastapi_app

@fastapi_app.post("/items/{name}")
async def create_item(name: str):
    volume.reload()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO items (name) VALUES (?)", (name,))
    conn.commit()
    conn.close()
    volume.commit()
    return {"message": f"Added item: {name}"}

@fastapi_app.get("/items")
async def list_items():
    volume.reload()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM items")
    items = cursor.fetchall()
    conn.close()
    return {
        "items": [
            {"id": item[0], "name": item[1], "created_at": item[2]} for item in items
        ]
    }

@fastapi_app.get("/")
def read_root():
    return {"message": "Hello World"}

def similarity_search(message: str, top_k: int=15):
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    conn = get_db_conn(DB_PATH)
    cursor = conn.cursor()

    query_vec = client.embeddings.create(model="text-embedding-ada-002", input=message).data[0].embedding
    query_bytes = serialize(query_vec)

    results = cursor.execute(
        """
        SELECT
            vec_discord_messages.id,
            distance,
            discord_messages,channel_id,
            discord_messages.author_id,
            discord_messages.content,
            discord_messages.create_at
        FROM vec_discord_messages
        LEFT JOIN discord_messages USING (id)
        WHERE embedding MATCH ?
            And k = ?
        ORDER BY distance
        """,
        [query_bytes, top_k],
    ).fetchall()

    conn.close()
    return results

