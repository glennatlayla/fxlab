/**
 * Permission utility tests.
 *
 * Verifies:
 *   - hasPermission correctly checks role→permission mapping.
 *   - hasAnyPermission and hasAllPermissions combinators.
 *   - Unknown roles return false.
 *   - Admin role has all permissions.
 *   - ROLES config matches spec (viewer, developer, approver, admin).
 */

import { describe, it, expect } from "vitest";
import {
  Permission,
  ROLES,
  hasPermission,
  hasAnyPermission,
  hasAllPermissions,
} from "./permissions";

describe("permissions", () => {
  describe("ROLES", () => {
    it("defines viewer, developer, approver, and admin roles", () => {
      expect(Object.keys(ROLES)).toEqual(
        expect.arrayContaining(["viewer", "developer", "approver", "admin"]),
      );
    });

    it("admin has all permissions", () => {
      const allPermissions = Object.values(Permission);
      for (const perm of allPermissions) {
        expect(hasPermission("admin", perm)).toBe(true);
      }
    });

    it("viewer cannot create strategies", () => {
      expect(hasPermission("viewer", Permission.CREATE_STRATEGY)).toBe(false);
    });

    it("developer can create and edit strategies", () => {
      expect(hasPermission("developer", Permission.CREATE_STRATEGY)).toBe(true);
      expect(hasPermission("developer", Permission.EDIT_STRATEGY)).toBe(true);
    });

    it("approver can approve promotions", () => {
      expect(hasPermission("approver", Permission.APPROVE_PROMOTION)).toBe(true);
    });

    it("developer cannot approve promotions", () => {
      expect(hasPermission("developer", Permission.APPROVE_PROMOTION)).toBe(false);
    });
  });

  describe("hasPermission", () => {
    it("returns false for unknown role", () => {
      expect(hasPermission("nonexistent", Permission.VIEW_STRATEGIES)).toBe(false);
    });

    it("returns true for valid role+permission combo", () => {
      expect(hasPermission("viewer", Permission.VIEW_STRATEGIES)).toBe(true);
    });
  });

  describe("hasAnyPermission", () => {
    it("returns true if role has at least one listed permission", () => {
      expect(
        hasAnyPermission("viewer", [Permission.CREATE_STRATEGY, Permission.VIEW_STRATEGIES]),
      ).toBe(true);
    });

    it("returns false if role has none of the listed permissions", () => {
      expect(
        hasAnyPermission("viewer", [Permission.CREATE_STRATEGY, Permission.DELETE_STRATEGY]),
      ).toBe(false);
    });
  });

  describe("hasAllPermissions", () => {
    it("returns true if role has all listed permissions", () => {
      expect(
        hasAllPermissions("developer", [Permission.CREATE_STRATEGY, Permission.EDIT_STRATEGY]),
      ).toBe(true);
    });

    it("returns false if role is missing any listed permission", () => {
      expect(
        hasAllPermissions("developer", [Permission.CREATE_STRATEGY, Permission.APPROVE_PROMOTION]),
      ).toBe(false);
    });
  });
});
