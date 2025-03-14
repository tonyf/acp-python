class SessionNotFound(Exception):
    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"Session not found: {session_id}")


class SessionsUpdated(Exception):
    def __init__(self):
        super().__init__("Sessions updated")
