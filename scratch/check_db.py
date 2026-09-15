import asyncio
from app.core.database import AsyncSessionLocal
from sqlalchemy import text

async def main():
    async with AsyncSessionLocal() as session:
        res = await session.execute(text("SELECT id, status, deleted_at, title, file_name FROM knowledge"))
        for row in res.fetchall():
            print("KNOWLEDGE ROW:", row)

if __name__ == "__main__":
    asyncio.run(main())
