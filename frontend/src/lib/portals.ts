/**
 * Which portals an account can open.
 *
 * Both capabilities have to be worked out together, because one account can
 * hold both and `role` can only name one of them: an approved merchant who is
 * later approved as an agent stays role=MERCHANT. Anything keyed on the role
 * alone therefore hides the agent portal from exactly the people who have
 * one. The profiles are the truth; the role is only a fallback for older
 * responses that predate /auth/me returning them.
 */

export type Portals = {
  /** An approved agent — show the Agent Portal. */
  isAgent: boolean;
  /** An approved reseller — show the Partner Portal. */
  isPartner: boolean;
  /** Applied but not yet approved; the portal shows their pending status. */
  agentPending: boolean;
  partnerPending: boolean;
  isStaff: boolean;
};

export function portalsFor(me: any): Portals {
  const role = me?.role;
  const agent = me?.agent_profile;
  const merchant = me?.merchant_profile;

  return {
    isAgent: agent ? agent.status === "APPROVED" : role === "AGENT",
    isPartner: merchant ? merchant.status === "APPROVED" : role === "MERCHANT",
    agentPending: !!agent && agent.status === "PENDING",
    partnerPending: !!merchant && merchant.status === "PENDING",
    isStaff: role === "ADMIN" || role === "SUPER_ADMIN",
  };
}
