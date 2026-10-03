import { Placeholder } from "../../shared/Placeholder";

/** Invite from a provider: placeholder until lane L1 builds it. Owned by L1. */
export default function Invite() {
  return (
    <div className="c-flow">
      <Placeholder
        title="Invite from a provider"
        lane="L1"
        prototype="InviteScreen"
        notes="The fee is paid by the provider and isn't added to the customer's price."
        endpoints={[
          "GET /api/c/invites/{token}",
          "POST /api/c/invites/{token}/accept",
        ]}
      />
    </div>
  );
}
