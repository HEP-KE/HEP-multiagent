from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


class SQLiteCheckpoint:
    def __init__(self, db_path: str = "checkpoint.db"):
        self._db_path = db_path

    def checkpointer(self):
        return AsyncSqliteSaver.from_conn_string(self._db_path)

    async def get_state(self, saver, thread_id: str) -> dict | None:
        config = {"configurable": {"thread_id": thread_id}}
        checkpoint = await saver.aget(config)
        return checkpoint.get("channel_values") if checkpoint else None
