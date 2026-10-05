from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from api.schemas.account import AccountOut
from api.schemas.content import ContentItemOut


class AdminOwnerOut(BaseModel):
    user_id: str
    email: str
    name: str
    role: str
    is_active: bool = True
    mustChangePassword: bool = False
    created_at: Optional[datetime] = None


class AdminWorkspaceAdminOut(BaseModel):
    user_id: str
    email: str
    name: str
    role: str = "admin"
    is_active: bool = True
    created_at: Optional[datetime] = None
    joined_at: Optional[datetime] = None


class AdminWorkspaceAccessMemberOut(BaseModel):
    id: str
    userId: str
    email: str
    name: str
    role: str
    created_at: datetime
    workspaceId: str
    workspaceName: str


class AdminWorkspaceAccessAdminOut(AdminWorkspaceAdminOut):
    workspaceId: str
    workspaceName: str


class AdminWorkspaceAccessOut(BaseModel):
    members: list[AdminWorkspaceAccessMemberOut] = Field(default_factory=list)
    admins: list[AdminWorkspaceAccessAdminOut] = Field(default_factory=list)


class AdminUserWorkspaceOut(BaseModel):
    id: str
    businessName: str
    status: str
    joined_at: Optional[datetime] = None


class AdminUserOut(BaseModel):
    user_id: str
    email: str
    name: str
    platformRole: str
    is_active: bool = True
    adminWorkspaceCount: int = 0
    adminWorkspaces: list[AdminUserWorkspaceOut] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class AdminUserListOut(BaseModel):
    items: list[AdminUserOut]
    total: int
    offset: int
    limit: int


class AdminUserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    password: Optional[str] = Field(default=None, max_length=255)
    workspaceIds: list[str] = Field(default_factory=list, max_length=200)


class AdminUserCreated(AdminUserOut):
    temporaryPassword: Optional[str] = None


class AdminUserPasswordResetOut(BaseModel):
    admin: AdminUserOut
    temporaryPassword: str


class AdminUserWorkspaceBulkUpdate(BaseModel):
    workspaceIds: list[str] = Field(min_length=1, max_length=200)


class AdminUserWorkspaceBulkResult(BaseModel):
    workspaceId: str
    workspaceName: Optional[str] = None
    status: str
    reason: Optional[str] = None


class AdminUserWorkspaceBulkOut(BaseModel):
    admin: AdminUserOut
    assigned: list[AdminUserWorkspaceBulkResult] = Field(default_factory=list)
    removed: list[AdminUserWorkspaceBulkResult] = Field(default_factory=list)
    skipped: list[AdminUserWorkspaceBulkResult] = Field(default_factory=list)


class AdminUserUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    is_active: Optional[bool] = None


class AdminWorkspaceAdminAssign(BaseModel):
    userId: str = Field(min_length=1)


class AdminWorkspaceOut(BaseModel):
    id: str
    businessName: str
    description: str = ""
    businessEmail: Optional[str] = None
    businessLogo: Optional[str] = None
    slug: Optional[str] = None
    status: str
    plan: str
    kind: str = "tenant"
    owner: Optional[AdminOwnerOut] = None
    workspaceAdmins: list[AdminWorkspaceAdminOut] = Field(default_factory=list)
    agentCount: int = 0
    deviceCount: int = 0
    memberCount: int = 0
    adminCount: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None


class AdminWorkspaceListOut(BaseModel):
    items: list[AdminWorkspaceOut]
    total: int
    offset: int
    limit: int


class AdminAssignableWorkspaceOut(BaseModel):
    id: str
    businessName: str
    status: str


class AdminAssignableWorkspaceListOut(BaseModel):
    items: list[AdminAssignableWorkspaceOut]
    total: int
    offset: int
    limit: int


class AdminWorkspaceCreate(BaseModel):
    businessName: str = Field(min_length=1, max_length=255)
    kind: Optional[str] = Field(default=None, max_length=20)
    description: Optional[str] = Field(default=None, max_length=2000)
    businessEmail: Optional[str] = Field(default=None, max_length=255)
    businessLogo: Optional[str] = Field(default=None, max_length=255)
    ownerUserId: Optional[str] = None
    ownerEmail: Optional[str] = Field(default=None, max_length=255)
    ownerName: Optional[str] = Field(default=None, max_length=255)
    ownerPassword: Optional[str] = Field(default=None, max_length=255)
    adminUserIds: list[str] = Field(default_factory=list)


class AdminWorkspaceCreated(AdminWorkspaceOut):
    temporaryPassword: Optional[str] = None


class AdminWorkspaceUpdate(BaseModel):
    businessName: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    businessEmail: Optional[str] = Field(default=None, max_length=255)
    businessLogo: Optional[str] = Field(default=None, max_length=255)
    status: Optional[str] = Field(default=None, max_length=20)
    plan: Optional[str] = Field(default=None, max_length=20)
    kind: Optional[str] = Field(default=None, max_length=20)


class AdminWorkspaceTransferOwner(BaseModel):
    userId: str = Field(min_length=1)


class AdminOwnerPasswordReset(BaseModel):
    password: Optional[str] = Field(default=None, max_length=255)


class AdminOwnerPasswordResetOut(BaseModel):
    owner: AdminOwnerOut
    temporaryPassword: str


class AdminOwnerUpdate(BaseModel):
    is_active: Optional[bool] = None
    mustChangePassword: Optional[bool] = None


class AdminAgentTokenCreate(BaseModel):
    workspaceId: str = Field(min_length=1)
    name: str = Field(default="", max_length=255)
    ownerUserId: Optional[str] = None


class AdminAgentTokenOut(BaseModel):
    id: str
    workspaceId: str
    workspaceName: Optional[str] = None
    user_id: str
    name: str
    prefix: str
    status: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None


class AdminAgentTokenCreated(AdminAgentTokenOut):
    token: str


class AdminWorkspaceDependenciesOut(BaseModel):
    agents: int = 0
    devices: int = 0
    members: int = 0


class AdminWorkspaceMetricOut(BaseModel):
    workspaceId: str
    workspaceName: Optional[str] = None
    count: int = 0


class AdminAccountOut(AccountOut):
    workspaceId: str
    workspaceName: Optional[str] = None


class AdminAccountListOut(BaseModel):
    items: list[AdminAccountOut]
    total: int
    offset: int
    limit: int
    byWorkspace: list[AdminWorkspaceMetricOut] = Field(default_factory=list)


class AdminContentItemOut(ContentItemOut):
    workspaceId: str
    workspaceName: Optional[str] = None


class AdminContentListOut(BaseModel):
    items: list[AdminContentItemOut]
    total: int
    offset: int
    limit: int
    byWorkspace: list[AdminWorkspaceMetricOut] = Field(default_factory=list)


class AdminDashboardSummaryOut(BaseModel):
    totalWorkspaces: int = 0
    activeWorkspaces: int = 0
    suspendedWorkspaces: int = 0
    archivedWorkspaces: int = 0
    totalAgents: int = 0
    onlineAgents: int = 0
    offlineAgents: int = 0
    staleAgents: int = 0
    totalDevices: int = 0
    assignedDevices: int = 0
    unassignedDevices: int = 0
    devicesByWorkspace: list[dict] = Field(default_factory=list)
    agentsByWorkspace: list[dict] = Field(default_factory=list)


class AdminAgentOut(BaseModel):
    relay_id: str
    workspaceId: str
    workspaceName: Optional[str] = None
    # "pool" | "tenant". Only a pool agent's phones may be handed to another
    # workspace, so the console needs this before it offers the button.
    workspaceKind: str = "tenant"
    user_id: Optional[str] = None
    enrollment_token_id: Optional[str] = None
    name: str = ""
    hostname: str = ""
    ip: str = ""
    version: str = ""
    serials: list[str] = Field(default_factory=list)
    status: str = "unknown"
    health: str = "offline"
    # Fact, not intent: is the control stream open right now? Enabling an agent
    # only sets intent — it is not in effect until the agent itself returns.
    connected: bool = False
    deviceCount: int = 0
    connected_at: Optional[datetime] = None
    last_heartbeat_at: Optional[datetime] = None
    disconnected_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class AdminAgentListOut(BaseModel):
    items: list[AdminAgentOut]
    total: int
    offset: int
    limit: int


class AdminAgentPhoneOut(BaseModel):
    serial: str
    deviceId: Optional[str] = None
    registered: bool = False
    name: str = ""
    brand: str = ""
    model: str = ""
    status: str = "ready"
    state: str = "unknown"
    last_seen: Optional[datetime] = None
    managedByWorkspaceId: Optional[str] = None
    managedByWorkspaceName: Optional[str] = None
    assignedWorkspaceId: Optional[str] = None
    assignedWorkspaceName: Optional[str] = None
    # `org_id` doubles as "in stock" and "handed out" — it equals the managing
    # workspace in both cases. True means the phone is still in the stock of the
    # workspace that owns it.
    pooled: bool = True


class AdminAgentPhoneListOut(BaseModel):
    items: list[AdminAgentPhoneOut]
    total: int
    offset: int = 0
    limit: int = 100


class AdminAgentPhoneAssign(BaseModel):
    targetWorkspaceId: str = Field(min_length=1)
    serials: list[str] = Field(min_length=1)


class AdminAgentPhoneAssignOut(BaseModel):
    items: list[AdminAgentPhoneOut]
    total: int


class AdminAgentPhoneUnassign(BaseModel):
    serials: list[str] = Field(min_length=1)


class AdminAgentUpdate(BaseModel):
    # hostname belongs to the agent (diagnostic); the admin owns `name`.
    name: Optional[str] = Field(default=None, max_length=255)
    status: Optional[str] = Field(default=None, max_length=16)
    workspaceId: Optional[str] = None


class AdminDeviceOut(BaseModel):
    id: str
    serial: str
    device_serial: str = ""
    name: str = ""
    workspaceId: str
    workspaceName: Optional[str] = None
    managedByWorkspaceId: Optional[str] = None
    managedByWorkspaceName: Optional[str] = None
    user_id: Optional[str] = None
    brand: str = ""
    model: str = ""
    android_version: str = ""
    adb_serial: Optional[str] = None
    relay_serial: Optional[str] = None
    adb_ip: Optional[str] = None
    adb_port: int = 5555
    status: str = "paired"
    state: str = "unknown"
    assigned: bool = False
    # Only phones managed by a pool workspace are the admin's to move.
    transferable: bool = True
    # True means the phone still sits in the stock of the workspace that owns
    # it; false means it has been allocated out to another workspace.
    pooled: bool = True
    last_seen: Optional[datetime] = None
    paired_at: Optional[datetime] = None
    unpaired_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AdminDeviceListOut(BaseModel):
    items: list[AdminDeviceOut]
    total: int
    offset: int
    limit: int


class AdminDeviceTransfer(BaseModel):
    workspaceId: Optional[str] = None
    userId: Optional[str] = None
