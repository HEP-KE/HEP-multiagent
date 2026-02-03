import aiosqlite


async def recall(memory, worker_type: str) -> str:
    if not memory or not worker_type:
        return ""
    return await memory.get(worker_type)


async def learn(memory, worker_type: str, status: str, error: str, task: str = "", output: str = ""):
    if memory and worker_type and status == "failed" and error:
        lesson = f"Task: {task[:150]}\nAttempt: {output[:300]}\nFailed: {error[:150]}"
        await memory.save(worker_type, lesson)


async def recall_and_learn(memory, worker_type: str, status: str = None, error: str = None) -> str:
    """Recall past lessons. If status='failed', also saves error as new lesson."""
    if not memory or not worker_type:
        return ""
    if status == "failed" and error:
        await memory.save(worker_type, error[:350])
    return await memory.get(worker_type)


class LessonMemory:
    def __init__(self, db_path: str = "checkpoint.db"):
        self._db = db_path

    async def init(self):
        async with aiosqlite.connect(self._db) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS lessons (
                    id INTEGER PRIMARY KEY,
                    worker_type TEXT,
                    lesson TEXT
                )
            """)
            await db.commit()

    async def save(self, worker_type: str, lesson: str):
        async with aiosqlite.connect(self._db) as db:
            await db.execute("INSERT INTO lessons (worker_type, lesson) VALUES (?, ?)", (worker_type, lesson))
            await db.commit()

    async def get(self, worker_type: str, limit: int = 5) -> str:
        async with aiosqlite.connect(self._db) as db:
            cursor = await db.execute(
                "SELECT lesson FROM lessons WHERE worker_type = ? ORDER BY id DESC LIMIT ?",
                (worker_type, limit)
            )
            rows = await cursor.fetchall()
        if not rows:
            return ""
        return "# Lessons from Past Failures\n" + "\n".join(f"- {r[0]}" for r in rows)
