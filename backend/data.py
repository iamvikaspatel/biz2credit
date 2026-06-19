import json
import os
import re
from datetime import datetime, timezone

BORROWER_ID_RE = re.compile(r"^BOR\d{3,6}$")


def _validate_borrower_id(borrower_id: str) -> None:
    if not borrower_id or not BORROWER_ID_RE.match(borrower_id):
        raise ValueError(f"Invalid borrower ID: {borrower_id}")


def _db_path() -> str:
    return os.getenv(
        "BORROWERS_DB_PATH",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "borrowers.json"),
    )


def load_borrowers() -> list:
    path = _db_path()
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def save_borrowers(borrowers_list: list) -> None:
    path = _db_path()
    dir_name = os.path.dirname(path) or "."
    os.makedirs(dir_name, exist_ok=True)
    import tempfile

    fd, temp_path = tempfile.mkstemp(dir=dir_name, prefix="borrowers_tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            try:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                json.dump(borrowers_list, f, indent=2)
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except (ImportError, AttributeError):
                json.dump(borrowers_list, f, indent=2)
        os.replace(temp_path, path)
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise


def get_all_borrowers() -> list:
    return load_borrowers()


def get_borrower_by_id(borrower_id: str):
    _validate_borrower_id(borrower_id)
    for borrower in load_borrowers():
        if borrower.get("id") == borrower_id:
            return borrower
    return None


def add_borrower(new_borrower_dict: dict) -> dict:
    borrowers = load_borrowers()

    max_num = 0
    for borrower in borrowers:
        bid = borrower.get("id", "")
        if bid.startswith("BOR"):
            try:
                num = int(bid[3:])
                max_num = max(max_num, num)
            except ValueError:
                pass

    new_borrower_dict["id"] = f"BOR{max_num + 1:03d}"

    if not new_borrower_dict.get("ingested_timestamp"):
        new_borrower_dict["ingested_timestamp"] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    if "action_audit_log" not in new_borrower_dict:
        new_borrower_dict["action_audit_log"] = []

    borrowers.append(new_borrower_dict)
    save_borrowers(borrowers)
    return new_borrower_dict


def update_borrower(borrower_id: str, updated_dict: dict):
    _validate_borrower_id(borrower_id)
    borrowers = load_borrowers()
    for idx, borrower in enumerate(borrowers):
        if borrower.get("id") == borrower_id:
            borrowers[idx] = updated_dict
            save_borrowers(borrowers)
            return updated_dict
    return None
