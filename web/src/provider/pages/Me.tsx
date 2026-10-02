import { Placeholder } from "../../shared/Placeholder";

/** Profile and documents: placeholder until lane L2 builds it. Owned by L2. */
export default function Me() {
  return (
    <Placeholder
      title="Profile and documents"
      lane="L2"
      prototype="MeScreen"
      endpoints={[
        "GET /api/p/profile",
        "PATCH /api/p/profile",
        "GET /api/p/documents",
        "POST /api/p/documents",
        "POST /api/files",
      ]}
    />
  );
}
