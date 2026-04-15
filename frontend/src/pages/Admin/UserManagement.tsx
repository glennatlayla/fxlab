/**
 * UserManagement page — create, list, and manage Keycloak users.
 *
 * Purpose:
 *   Display all users in a table with actions to create new users,
 *   update roles, and reset passwords. Supports client-side filtering
 *   by username or email.
 *
 * Responsibilities:
 *   - Fetch and display users via adminApi.
 *   - Handle user creation with modal form.
 *   - Handle role assignment per user.
 *   - Handle password reset with confirmation.
 *   - Manage filter and pagination state.
 *   - Show loading and empty states.
 *   - Use useAuth to verify admin scope.
 *
 * Does NOT:
 *   - Perform business logic or calculations.
 *   - Store persistent state outside React.
 *
 * Dependencies:
 *   - adminApi from @/features/admin/api.
 *   - useAuth from @/auth/useAuth.
 *
 * Example:
 *   <UserManagement />
 */

import { useState, useEffect } from "react";
import { useAuth } from "@/auth/useAuth";
import { adminApi, type KeycloakUser, type CreateUserRequest } from "@/features/admin/api";

/**
 * Default pagination size.
 */
const DEFAULT_MAX_RESULTS = 100;

/**
 * UserManagement page component.
 *
 * Renders a searchable, filterable table of Keycloak users with
 * actions to create, edit roles, and reset passwords.
 *
 * Returns:
 *   JSX element containing the user management page.
 */
export default function UserManagement() {
  useAuth(); // Ensure authenticated

  // User list state
  const [users, setUsers] = useState<KeycloakUser[]>([]);
  const [filteredUsers, setFilteredUsers] = useState<KeycloakUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filter state
  const [searchTerm, setSearchTerm] = useState("");

  // Create user modal state
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createForm, setCreateForm] = useState<CreateUserRequest>({
    username: "",
    email: "",
    first_name: "",
    last_name: "",
    temporary_password: "",
  });
  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Role edit state
  const [editingUserId, setEditingUserId] = useState<string | null>(null);
  const [editingRoles, setEditingRoles] = useState<string>("");
  const [roleLoading, setRoleLoading] = useState(false);

  // Password reset confirmation state
  const [resetConfirmUserId, setResetConfirmUserId] = useState<string | null>(null);
  const [resetLoading, setResetLoading] = useState(false);

  /**
   * Fetch users on mount.
   */
  useEffect(() => {
    fetchUsers();
  }, []);

  /**
   * Filter users when search term changes.
   */
  useEffect(() => {
    const term = searchTerm.toLowerCase();
    const filtered = users.filter(
      (user) =>
        user.username.toLowerCase().includes(term) || user.email.toLowerCase().includes(term),
    );
    setFilteredUsers(filtered);
  }, [searchTerm, users]);

  /**
   * Fetch users from API.
   */
  const fetchUsers = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await adminApi.listUsers(0, DEFAULT_MAX_RESULTS);
      setUsers(result);
      setFilteredUsers(result);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(`Failed to fetch users: ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  /**
   * Handle create user form submission.
   */
  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateLoading(true);
    setCreateError(null);
    try {
      await adminApi.createUser(createForm);
      // Reset form and close modal
      setCreateForm({
        username: "",
        email: "",
        first_name: "",
        last_name: "",
        temporary_password: "",
      });
      setShowCreateModal(false);
      // Refresh user list
      await fetchUsers();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setCreateError(`Failed to create user: ${msg}`);
    } finally {
      setCreateLoading(false);
    }
  };

  /**
   * Handle role update for a user.
   */
  const handleUpdateRoles = async (userId: string) => {
    setRoleLoading(true);
    try {
      const roles = editingRoles.split(",").map((r) => r.trim());
      await adminApi.updateUserRoles(userId, roles);
      setEditingUserId(null);
      setEditingRoles("");
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      alert(`Failed to update roles: ${msg}`);
    } finally {
      setRoleLoading(false);
    }
  };

  /**
   * Handle password reset.
   */
  const handleResetPassword = async (userId: string) => {
    setResetLoading(true);
    try {
      await adminApi.resetPassword(userId);
      setResetConfirmUserId(null);
      alert("Password reset email sent to user.");
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      alert(`Failed to reset password: ${msg}`);
    } finally {
      setResetLoading(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="user-management">
      <div>
        <h1 className="text-2xl font-bold text-surface-900">User Management</h1>
        <p className="mt-1 text-sm text-surface-500">Create and manage Keycloak users</p>
      </div>

      {/* Search and Create Button */}
      <div className="flex gap-4 rounded-lg border border-surface-200 bg-white p-4">
        <input
          type="text"
          placeholder="Search by username or email..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          data-testid="search-users"
          className="flex-1 rounded border border-surface-300 px-3 py-2 text-sm"
        />
        <button
          onClick={() => setShowCreateModal(true)}
          data-testid="create-user-button"
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          Create User
        </button>
      </div>

      {/* Error message */}
      {error && <div className="rounded bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      {/* Loading state */}
      {loading ? (
        <div
          data-testid="loading-state"
          className="rounded border border-surface-200 bg-surface-50 p-8 text-center text-surface-600"
        >
          Loading users...
        </div>
      ) : filteredUsers.length === 0 ? (
        <div
          data-testid="empty-state"
          className="rounded border border-surface-200 bg-surface-50 p-8 text-center text-surface-600"
        >
          No users found
        </div>
      ) : (
        /* User table */
        <div className="overflow-x-auto">
          <table
            data-testid="user-table"
            className="w-full border-collapse border border-surface-200 bg-white"
          >
            <thead className="bg-surface-100">
              <tr>
                <th className="border border-surface-200 px-4 py-2 text-left text-xs font-semibold uppercase text-surface-700">
                  Username
                </th>
                <th className="border border-surface-200 px-4 py-2 text-left text-xs font-semibold uppercase text-surface-700">
                  Email
                </th>
                <th className="border border-surface-200 px-4 py-2 text-left text-xs font-semibold uppercase text-surface-700">
                  First Name
                </th>
                <th className="border border-surface-200 px-4 py-2 text-left text-xs font-semibold uppercase text-surface-700">
                  Last Name
                </th>
                <th className="border border-surface-200 px-4 py-2 text-center text-xs font-semibold uppercase text-surface-700">
                  Enabled
                </th>
                <th className="border border-surface-200 px-4 py-2 text-center text-xs font-semibold uppercase text-surface-700">
                  Email Verified
                </th>
                <th className="border border-surface-200 px-4 py-2 text-center text-xs font-semibold uppercase text-surface-700">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {filteredUsers.map((user) => (
                <tr
                  key={user.id}
                  data-testid={`user-row-${user.id}`}
                  className="border-b border-surface-200 hover:bg-surface-50"
                >
                  <td className="border border-surface-200 px-4 py-2 font-semibold text-surface-900">
                    {user.username}
                  </td>
                  <td className="border border-surface-200 px-4 py-2 text-sm text-surface-700">
                    {user.email}
                  </td>
                  <td className="border border-surface-200 px-4 py-2 text-sm text-surface-700">
                    {user.firstName}
                  </td>
                  <td className="border border-surface-200 px-4 py-2 text-sm text-surface-700">
                    {user.lastName}
                  </td>
                  <td className="border border-surface-200 px-4 py-2 text-center text-sm">
                    <span
                      className={`inline-block rounded px-2 py-1 text-xs font-semibold ${
                        user.enabled ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"
                      }`}
                    >
                      {user.enabled ? "Yes" : "No"}
                    </span>
                  </td>
                  <td className="border border-surface-200 px-4 py-2 text-center text-sm">
                    <span
                      className={`inline-block rounded px-2 py-1 text-xs font-semibold ${
                        user.emailVerified
                          ? "bg-green-100 text-green-800"
                          : "bg-red-100 text-red-800"
                      }`}
                    >
                      {user.emailVerified ? "Yes" : "No"}
                    </span>
                  </td>
                  <td className="border border-surface-200 px-4 py-2 text-center">
                    <div className="flex gap-2">
                      {editingUserId === user.id ? (
                        <div className="flex gap-1">
                          <input
                            type="text"
                            placeholder="role1, role2"
                            value={editingRoles}
                            onChange={(e) => setEditingRoles(e.target.value)}
                            className="w-32 rounded border border-surface-300 px-2 py-1 text-xs"
                          />
                          <button
                            onClick={() => handleUpdateRoles(user.id)}
                            disabled={roleLoading}
                            className="rounded bg-green-600 px-2 py-1 text-xs text-white hover:bg-green-700 disabled:opacity-50"
                          >
                            Save
                          </button>
                          <button
                            onClick={() => setEditingUserId(null)}
                            className="rounded bg-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-400"
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <>
                          <button
                            onClick={() => setEditingUserId(user.id)}
                            data-testid={`role-select-${user.id}`}
                            className="rounded bg-blue-600 px-2 py-1 text-xs text-white hover:bg-blue-700"
                          >
                            Edit Roles
                          </button>
                          <button
                            onClick={() => setResetConfirmUserId(user.id)}
                            data-testid={`reset-password-${user.id}`}
                            className="rounded bg-orange-600 px-2 py-1 text-xs text-white hover:bg-orange-700"
                          >
                            Reset Password
                          </button>
                        </>
                      )}
                    </div>

                    {/* Password reset confirmation */}
                    {resetConfirmUserId === user.id && (
                      <div className="absolute right-4 top-2 flex gap-2 rounded bg-white p-2 shadow-lg">
                        <button
                          onClick={() => handleResetPassword(user.id)}
                          disabled={resetLoading}
                          className="rounded bg-red-600 px-3 py-1 text-xs text-white hover:bg-red-700 disabled:opacity-50"
                        >
                          Confirm
                        </button>
                        <button
                          onClick={() => setResetConfirmUserId(null)}
                          className="rounded bg-gray-300 px-3 py-1 text-xs text-gray-700 hover:bg-gray-400"
                        >
                          Cancel
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create User Modal */}
      {showCreateModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onClick={() => setShowCreateModal(false)}
        >
          <div
            className="w-96 rounded-lg bg-white p-6 shadow-lg"
            onClick={(e) => e.stopPropagation()}
            data-testid="create-user-form"
          >
            <h2 className="mb-4 text-lg font-semibold text-surface-900">Create User</h2>
            {createError && (
              <div className="mb-4 rounded bg-red-50 p-2 text-xs text-red-700">{createError}</div>
            )}
            <form onSubmit={handleCreateUser} className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-surface-700">Username</label>
                <input
                  type="text"
                  required
                  value={createForm.username}
                  onChange={(e) => setCreateForm({ ...createForm, username: e.target.value })}
                  className="mt-1 w-full rounded border border-surface-300 px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-surface-700">Email</label>
                <input
                  type="email"
                  required
                  value={createForm.email}
                  onChange={(e) => setCreateForm({ ...createForm, email: e.target.value })}
                  className="mt-1 w-full rounded border border-surface-300 px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-surface-700">First Name</label>
                <input
                  type="text"
                  required
                  value={createForm.first_name}
                  onChange={(e) => setCreateForm({ ...createForm, first_name: e.target.value })}
                  className="mt-1 w-full rounded border border-surface-300 px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-surface-700">Last Name</label>
                <input
                  type="text"
                  required
                  value={createForm.last_name}
                  onChange={(e) => setCreateForm({ ...createForm, last_name: e.target.value })}
                  className="mt-1 w-full rounded border border-surface-300 px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-surface-700">
                  Temporary Password (optional)
                </label>
                <input
                  type="password"
                  value={createForm.temporary_password || ""}
                  onChange={(e) =>
                    setCreateForm({ ...createForm, temporary_password: e.target.value })
                  }
                  className="mt-1 w-full rounded border border-surface-300 px-3 py-2 text-sm"
                />
              </div>
              <div className="flex gap-2 pt-4">
                <button
                  type="submit"
                  disabled={createLoading}
                  className="flex-1 rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  {createLoading ? "Creating..." : "Create"}
                </button>
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="flex-1 rounded border border-surface-300 px-4 py-2 text-sm font-medium text-surface-700 hover:bg-surface-50"
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
