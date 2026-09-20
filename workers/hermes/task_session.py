"""Resume the native transcript, including compression continuations and tool rows."""


def open_session(root_id):
    from hermes_state import SessionDB
    db = SessionDB()
    try:
        session_id = db.get_compression_tip(root_id)
        history = []
        if db.get_session(session_id):
            history, _ = db.get_resume_conversations(session_id)
            db.reopen_session(session_id)
        return db, session_id, history
    except BaseException:
        db.close()
        raise
