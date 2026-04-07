import logging
import os
from typing import Optional

from .config import get_app_root


def resolve_session_directory_for_skills() -> Optional[str]:
    """
    Resolve a session directory that contains common skills locations.
    """
    app_root = str(get_app_root())
    env_session_dir = os.environ.get("COPILOT_SESSION_DIRECTORY")
    if env_session_dir:
        resolved = os.path.expanduser(env_session_dir)
        if os.path.isdir(resolved):
            return resolved

    candidate_roots = [
        app_root,
        os.path.join(app_root, ".codex"),
        os.path.join(app_root, ".claudeCode"),
        os.path.join(app_root, ".github"),
        os.path.join(app_root, ".vscode"),
    ]
    skill_dir_names = ("skills", "Skills")

    for root in candidate_roots:
        if not os.path.isdir(root):
            continue
        for name in skill_dir_names:
            skill_path = os.path.join(root, name)
            if os.path.isdir(skill_path):
                return skill_path

    return None
