"""
db.crud package — CRUD helpers grouped by domain (user, organization,
device, sessions, campaigns).

This mirrors the layout of fastapi/full-stack-fastapi-template, while
keeping backwards compatibility with existing callers that import
`from db import crud as repo`.
"""

from .user import *  # noqa: F401,F403
from .organization import *  # noqa: F401,F403
from .device import *  # noqa: F401,F403
from .session import *  # noqa: F401,F403
from .campaign import *  # noqa: F401,F403
from .mcp_session import *  # noqa: F401,F403
from .scenario_template import *  # noqa: F401,F403
from .device_group import *  # noqa: F401,F403
from .content import *  # noqa: F401,F403
from .schedule import *  # noqa: F401,F403
from .execution import *  # noqa: F401,F403

