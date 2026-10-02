import { Placeholder } from "../../shared/Placeholder";

/** Pricing and calibration: placeholder until lane L3 builds it. Owned by L3. */
export default function Pricing() {
  return (
    <Placeholder
      title="Pricing and calibration"
      lane="L3"
      prototype="AdminCalibration and EstimateScatter"
      notes="One admin drafts, a different admin approves."
      endpoints={[
        "GET /api/admin/pricing/calibration",
        "GET /api/admin/pricing/versions",
        "POST /api/admin/pricing/versions",
        "POST /api/admin/pricing/versions/{version_id}/approve",
      ]}
    />
  );
}
