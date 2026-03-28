/**
 * Permission utilities for FXLab UI
 * 
 * Maps backend roles to UI capabilities.
 * All actual authorization happens server-side; this is for UI hints only.
 */

export enum Permission {
  VIEW_STRATEGIES = 'view_strategies',
  CREATE_STRATEGY = 'create_strategy',
  EDIT_STRATEGY = 'edit_strategy',
  DELETE_STRATEGY = 'delete_strategy',
  
  VIEW_RUNS = 'view_runs',
  EXECUTE_RUN = 'execute_run',
  
  VIEW_FEEDS = 'view_feeds',
  MANAGE_FEEDS = 'manage_feeds',
  
  REQUEST_PROMOTION = 'request_promotion',
  APPROVE_PROMOTION = 'approve_promotion',
  
  VIEW_AUDIT = 'view_audit',
  EXPORT_DATA = 'export_data',
  
  MANAGE_OVERRIDES = 'manage_overrides',
  VIEW_GOVERNANCE = 'view_governance',
}

export interface Role {
  name: string;
  permissions: Permission[];
}

/**
 * Default role definitions.
 * Backend is authoritative; these are UI hints only.
 */
export const ROLES: Record<string, Role> = {
  viewer: {
    name: 'Viewer',
    permissions: [
      Permission.VIEW_STRATEGIES,
      Permission.VIEW_RUNS,
      Permission.VIEW_FEEDS,
      Permission.VIEW_AUDIT,
    ],
  },
  developer: {
    name: 'Developer',
    permissions: [
      Permission.VIEW_STRATEGIES,
      Permission.CREATE_STRATEGY,
      Permission.EDIT_STRATEGY,
      Permission.VIEW_RUNS,
      Permission.EXECUTE_RUN,
      Permission.VIEW_FEEDS,
      Permission.REQUEST_PROMOTION,
      Permission.VIEW_AUDIT,
      Permission.EXPORT_DATA,
    ],
  },
  approver: {
    name: 'Approver',
    permissions: [
      Permission.VIEW_STRATEGIES,
      Permission.VIEW_RUNS,
      Permission.VIEW_FEEDS,
      Permission.APPROVE_PROMOTION,
      Permission.VIEW_AUDIT,
      Permission.VIEW_GOVERNANCE,
    ],
  },
  admin: {
    name: 'Admin',
    permissions: Object.values(Permission),
  },
};

/**
 * Check if a role has a specific permission.
 * UI hint only - backend performs actual authorization.
 */
export function hasPermission(role: string, permission: Permission): boolean {
  const roleConfig = ROLES[role];
  if (!roleConfig) {
    return false;
  }
  return roleConfig.permissions.includes(permission);
}

/**
 * Check if a role has any of the specified permissions.
 */
export function hasAnyPermission(role: string, permissions: Permission[]): boolean {
  return permissions.some(p => hasPermission(role, p));
}

/**
 * Check if a role has all of the specified permissions.
 */
export function hasAllPermissions(role: string, permissions: Permission[]): boolean {
  return permissions.every(p => hasPermission(role, p));
}
